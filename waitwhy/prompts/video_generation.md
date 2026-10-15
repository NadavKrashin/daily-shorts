---
name: video_generation
version: 1.0.0
purpose: Agent F - wrap a scene prompt for text/image-to-video models
---
## system
(Not sent to an LLM - rendered into the provider prompt.)

## user
{{ scene_prompt }}. Camera: {{ camera }}. Motion: {{ motion }}. {{ seconds }} seconds, smooth and continuous,
no cuts. Style: premium stylised 3D miniature world, soft lighting, palette {{ palette }}, vertical 9:16.
Continuity: {{ continuity }}. Avoid: {{ negative }}, text, logos, watermarks, real people, flicker,
morphing objects, objects appearing or disappearing.
