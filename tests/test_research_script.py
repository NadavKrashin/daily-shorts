import json

from waitwhy.agents import research, trends, writer
from waitwhy.schemas import FactSheet, ScriptDraft, TopicCandidate, TopicScores
from waitwhy.settings import ROOT

SEED = ROOT / "seeds" / "why-traffic-jams-appear-out-of-nowhere"


def fs():
    return FactSheet.model_validate(json.loads((SEED / "factcheck.json").read_text()))


def test_seeded_fact_sheet_passes_with_retrieved_urls():
    hits = {h["url"] for h in json.loads((SEED / "research.json").read_text())["hits"]}
    status, issues = research.validate(fs(), hits, [])
    assert status == "verified", issues


def test_source_not_returned_by_search_is_removed_and_blocks():
    sheet = fs()
    status, issues = research.validate(sheet, {"https://only-this.example"}, [])
    assert status == "needs_research"
    assert any("not returned by search" in i for i in issues)


def test_claim_with_single_weak_source_is_downgraded():
    sheet = fs()
    sheet.sources[5].source_type = "secondary"
    sheet.claims[0].source_ids = ["S6"]          # only the press release
    status, issues = research.validate(sheet, None, [])
    assert sheet.claims[0].status == "partially_verified"
    assert status == "needs_research"


def test_high_risk_topic_requires_human():
    status, _ = research.validate(fs(), None, ["medical"])
    assert status == "needs_human"


def test_script_checks_catch_problems(cfg):
    draft = ScriptDraft.model_validate(json.loads((SEED / "script.json").read_text()))
    assert writer.check_script(draft, fs(), cfg) == []
    draft.segments[0].text = "Did you know traffic is weird?"
    draft.segments[2].claim_ids = ["C99"]
    problems = writer.check_script(draft, fs(), cfg)
    assert any("banned phrase" in p for p in problems)
    assert any("unverified/unknown claims" in p for p in problems)


def test_numbers_must_cite_claims(cfg):
    draft = ScriptDraft.model_validate(json.loads((SEED / "script.json").read_text()))
    draft.segments[3].claim_ids = []
    assert any("numeric statement" in p for p in writer.check_script(draft, fs(), cfg))


def test_topic_scoring_and_near_duplicate_detection(session, cfg):
    sc = TopicScores(hook_strength=80, visual_potential=80, audience_curiosity=80, scientific_clarity=80, evergreen=80,
                     originality=80, feasibility=80)
    a = trends.add_candidate(session, cfg, TopicCandidate(title="Why Traffic Jams Appear Out of Nowhere",
                             category="x", angle="a", summary="s", keywords=["traffic", "jams", "phantom"],
                             risk_flags=[], scores=sc, reasoning="r"))
    assert a.status == "evaluated" and a.score_total == 80.0
    b = trends.add_candidate(session, cfg, TopicCandidate(title="Phantom traffic jams explained", category="x",
                             angle="a", summary="s", keywords=["traffic", "jam"], risk_flags=[], scores=sc,
                             reasoning="r"))
    assert b.status == "duplicate" and b.duplicate_of_id == a.id
    c = trends.add_candidate(session, cfg, TopicCandidate(title="How vaccines train immunity", category="x",
                             angle="a", summary="s", keywords=["vaccine"], risk_flags=["medical"], scores=sc,
                             reasoning="r"))
    assert c.requires_human_review


def test_seed_backlog_has_at_least_30_topics(session, cfg):
    assert trends.seed_backlog(session, cfg) >= 30
