"""Claude (Anthropic API) provider.

* Structured outputs via ``output_config.format`` (JSON schema derived from the Pydantic model), then
  re-validated with Pydantic - the schema is a contract, not a suggestion.
* Research uses the server-side ``web_search`` tool so every source URL comes from an actual search
  result, never from model memory. A second call structures the memo into a FactSheet.
* Server-side refusal fallbacks are enabled for Opus/Sonnet; refusals are surfaced, never ignored.
"""
from __future__ import annotations

import copy
import json
import logging
from typing import Any

import anthropic

from waitwhy.errors import AuthError, PermanentError, PolicyError, TransientError
from waitwhy.providers.base import LLMResult, ResearchResult, SearchHit
from waitwhy.providers.pricing import llm_cost

log = logging.getLogger("waitwhy.llm.anthropic")

_UNSUPPORTED = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength",
                "pattern", "default", "minItems", "maxItems", "multipleOf", "format", "title"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def strict_schema(model_cls) -> dict:
    """Pydantic JSON schema -> strict structured-output schema (refs inlined, all fields required,
    additionalProperties false, unsupported numeric/string constraints stripped; Pydantic re-validates)."""
    schema = model_cls.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            out = {k: resolve(v) for k, v in node.items() if k not in _UNSUPPORTED}
            if out.get("type") == "object" or "properties" in out:
                out["type"] = "object"
                out.setdefault("properties", {})
                out["required"] = list(out["properties"].keys())
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [resolve(x) for x in node]
        return node

    return resolve(schema)


class AnthropicLLM:
    name = "anthropic"

    def __init__(self, api_key: str):
        if not api_key:
            raise AuthError("ANTHROPIC_API_KEY is not set")
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=600)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _extras(model: str) -> dict:
        if model.startswith(("claude-opus", "claude-sonnet", "claude-fable")):
            return {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        return {"betas": []}

    def _call(self, **kwargs):
        try:
            with self.client.beta.messages.stream(**kwargs) as stream:
                return stream.get_final_message()
        except anthropic.RateLimitError as e:
            retry_after = None
            try:
                retry_after = float(e.response.headers.get("retry-after", "0")) or None
            except Exception:  # noqa: BLE001
                pass
            raise TransientError(f"anthropic rate limited: {e}", retry_after_s=retry_after) from e
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            raise AuthError(f"anthropic auth failed: {e}") from e
        except anthropic.BadRequestError as e:
            raise PermanentError(f"anthropic rejected request: {e}") from e
        except (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.InternalServerError) as e:
            raise TransientError(f"anthropic unavailable: {e}") from e
        except anthropic.APIStatusError as e:
            if e.status_code >= 500 or e.status_code == 529:
                raise TransientError(f"anthropic {e.status_code}: {e}") from e
            raise PermanentError(f"anthropic {e.status_code}: {e}") from e

    @staticmethod
    def _check_stop(msg) -> None:
        if msg.stop_reason == "refusal":
            details = getattr(msg, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise PolicyError(f"model declined the request (category={category})")
        if msg.stop_reason == "max_tokens":
            raise PermanentError("model output truncated at max_tokens; raise the limit for this task")

    # ------------------------------------------------------------------ API
    def structured(self, *, task, system, prompt, schema, model, effort="medium", max_tokens=16000, context=None,
                   images=None):
        content: list[dict] | str = prompt
        if images:  # multimodal review: sampled frames as base64 JPEG blocks before the text
            import base64
            content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.b64encode(open(p, "rb").read()).decode()}}
                       for p in images] + [{"type": "text", "text": prompt}]
        msg = self._call(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": strict_schema(schema)}},
            **self._extras(model),
        )
        self._check_stop(msg)
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        try:
            parsed = schema.model_validate(json.loads(text))
        except Exception as e:  # noqa: BLE001
            raise TransientError(f"structured output failed validation for {task}: {e}") from e
        u = msg.usage
        return LLMResult(parsed=parsed, model=msg.model, input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                         cost_usd=llm_cost(model, u.input_tokens, u.output_tokens), raw_text=text)

    def research(self, *, system, prompt, model, effort="high", max_searches=8, context=None):
        messages: list[dict] = [{"role": "user", "content": prompt}]
        hits: dict[str, SearchHit] = {}
        memo_parts: list[str] = []
        tin = tout = searches = 0
        for _ in range(4):  # handle pause_turn continuations of the server-side tool loop
            msg = self._call(
                model=model, max_tokens=32000, system=system, messages=messages,
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches}],
                output_config={"effort": effort}, **self._extras(model),
            )
            u = msg.usage
            tin += u.input_tokens
            tout += u.output_tokens
            stu = getattr(u, "server_tool_use", None)
            searches += getattr(stu, "web_search_requests", 0) or 0
            for block in msg.content:
                btype = getattr(block, "type", "")
                if btype == "web_search_tool_result":
                    content = block.content
                    if isinstance(content, list):  # error results are a single object, not a list
                        for r in content:
                            url = getattr(r, "url", None)
                            if url:
                                hits[url] = SearchHit(url=url, title=getattr(r, "title", "") or url,
                                                      page_age=getattr(r, "page_age", None))
                elif btype == "text":
                    memo_parts.append(block.text)
            if msg.stop_reason == "pause_turn":
                messages = [messages[0], {"role": "assistant", "content": msg.content}]
                continue
            self._check_stop(msg)
            break
        return ResearchResult(memo="\n".join(memo_parts), hits=list(hits.values()), model=model,
                              input_tokens=tin, output_tokens=tout, searches=searches,
                              cost_usd=llm_cost(model, tin, tout, searches))
