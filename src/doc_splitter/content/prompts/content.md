# Content Analysis — Host Agent Instructions

Read the **entire chunk** below. Produce a precise conceptual description — not a generic label.

## Rules

1. Describe what arguments, concepts, and examples are actually covered.
2. If multiple related subtopics appear in one chunk, mention all of them.
3. Output both Persian (`topic_fa`) and English (`topic_en`).
4. Judge coherence: is this chunk a cohesive unit? Does the cut feel logical vs neighbors?
5. Use `confident` or `needs_review` with a short reason.

## Response format (JSON)

```json
{
  "topic_fa": "توضیح دقیق مفهومی به فارسی",
  "topic_en": "Precise conceptual description in English",
  "coherence": "confident",
  "reason": "Brief justification for coherence assessment"
}
```