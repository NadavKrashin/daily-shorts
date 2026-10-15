---
name: image_generation
version: 1.0.0
purpose: Agent F - wrap a scene prompt with brand style + continuity for image models
---
## system
(Not sent to an LLM - this template is rendered into the provider prompt.)

## user
{{ scene_prompt }}. Style: premium stylised 3D illustration, miniature diorama feel, soft global
illumination, gentle ambient occlusion, clean background, bright controlled palette ({{ palette }}), high
contrast focal subject, generous negative space at the top and bottom third for captions, vertical 9:16
composition. {% for o in objects %}{{ o.id }}: {{ o.reference_prompt }} (colour {{ o.canonical_color }}). {% endfor %}
Avoid: {{ negative }}, text, letters, logos, watermarks, real brands, real people, photorealistic faces.
