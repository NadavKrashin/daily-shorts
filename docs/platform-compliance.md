# Platform, copyright & safety compliance

## Hard rules enforced in code
| Rule | Where |
|---|---|
| Publication needs an approved `publication` approval (supervised mode: always human) | `publishing/service.py::schedule_video`, `publish` |
| Live publishing refuses versions with non-commercial or mock assets | `VideoVersion.manifest.publishable`, QC `rights_cleared`, `no_mock_content` |
| Private/draft uploads are never reported as publications | `PublishOutcome.is_public`; video only reaches PUBLISHED with ≥ 1 public post |
| No duplicate posts | unique `(video, platform)`, idempotency keys, `uploading` re-entry guard |
| Nothing deletes or unpublishes live content | no such code path exists |
| Unaudited TikTok client never attempts public posting | `TikTokAdapter` defaults to manual handoff |
| AI disclosure | metadata guard forces `ai_generated_visuals` when any generated asset is used; YouTube `containsSyntheticMedia` for realistic synthetic media; TikTok `is_aigc` |
| Paid promotion disclosure | sponsored videos force `paid_promotion` (TikTok `brand_content_toggle`) and always require human approval |
| Simulations labelled | every simulation scene carries a visible "SIMULATION" tag. Never presented as footage of the real experiment |
| No voice cloning without authorisation | ElevenLabs voice must be a licensed library/designed voice (owner choice) |
| Music & SFX | procedurally generated in-house (owned); no third-party music |
| Sponsorship outreach | drafts only; `outreach_sending_enabled: false`; per-draft approval |
| Rate limits | per-type concurrency, provider retry-after honoured, quota errors back off 1 h |

## Research notes (official docs, 2026-10-15)
* YouTube `videos.insert`: unverified API projects created after 2020-07-28 upload as private until audited;
  `status.containsSyntheticMedia` is supported on insert/update.
  https://developers.google.com/youtube/v3/docs/videos/insert
* Instagram content publishing (Reels via `media_type=REELS`, container status, `media_publish`, 100 posts/24 h, public video URL):
  https://developers.facebook.com/docs/instagram-platform/content-publishing
* Facebook Reels Publishing API (start/upload/finish, 3–90 s, 30 reels/24 h): https://developers.facebook.com/docs/video-api/guides/reels-publishing
* TikTok Content Posting API (unaudited clients limited to private viewing; audit required):
  https://developers.tiktok.com/doc/content-posting-api-get-started
* Higgsfield API (commercial use of outputs permitted; outputs retained ≥ 7 days): https://higgsfield.ai/blog/higgsfield-api

These policies change. Re-check them before switching any platform to live mode, and at least quarterly.
