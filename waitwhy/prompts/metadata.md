---
name: metadata
version: 1.0.0
purpose: Publishing metadata for YouTube, Instagram, TikTok, Facebook
---
## system
Write platform metadata for an educational short from "{{ brand }}". No misleading clickbait: titles must
be answered by the video. Max 5 hashtags, relevant only. A short, non-pushy call to action is optional.
YouTube title <= 70 characters. Set disclosure flags honestly: ai_generated_visuals if any AI-generated
imagery is used; realistic_synthetic_media only if it depicts realistic people/places/events that could be
mistaken for real footage; paid_promotion if sponsored.

## user
Title: {{ title }}
Script: {{ script }}
Uses AI-generated imagery: {{ uses_ai }}
Sponsored: {{ sponsored }}
Key sources (for the YouTube description "Sources" section):
{% for s in sources %}- {{ s.title }} - {{ s.url }}
{% endfor %}
