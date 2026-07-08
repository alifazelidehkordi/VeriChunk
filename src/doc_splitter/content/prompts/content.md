# Content Analysis — Host Agent Instructions

Read the **entire chunk** below. Produce a precise conceptual description — not a generic label and not a copied parser heading.

## Rules

1. Read the full chunk content before writing anything.
2. Treat `section_headings` and `provisional_topic` as parser hints only. They can be wrong, over-specific, missing, or split across pages.
3. Choose `topic_*` from your understanding of the whole chunk. Do not blindly copy the first heading, the longest heading, or `provisional_topic`.
4. `topic_*` must be a **short session title**, never a copied body sentence.
5. `topic_en` is also used as the final chunk filename slug. Choose it carefully; it must describe the whole chunk, not just the first heading.
6. `study_focus_*` must be **1–2 educational lines** listing what a learner should master in this specific chunk.
7. Output both Persian (`topic_fa`, `study_focus_fa`) and English (`topic_en`, `study_focus_en`).
8. Judge coherence and boundary quality: is this chunk a cohesive unit, and does the cut feel logical vs neighbors?
9. Use `confident` or `needs_review` with a short reason.
10. **NEVER use auto-generated reasons.** "auto from section_headings" is forbidden. "auto populated from headings" is forbidden. The `reason` field must be your own conceptual judgment.
11. **NEVER copy `section_headings` verbatim as `study_focus_*`.** Write actual educational content: concepts, procedures, definitions, arguments, caveats.

## Field definitions

| Field | Purpose | Length |
|---|---|---|
| `topic_*` | Short agent-authored session title based on the whole chunk | ≤ 14 words, no trailing period |
| `study_focus_*` | What to learn in this session — concepts, procedures, arguments, definitions, examples, caveats | 1–2 lines |

**Bad topic:** `This chapter explains several ideas and then gives examples.`
**Bad topic:** blindly copying a noisy parser heading that covers only the first page.
**Good topic:** `Recursive Tree Traversal`
**Good study_focus:** `Call stack behavior, base cases, preorder/inorder/postorder traversal, and common off-by-one mistakes.`

## Response format (JSON)

```json
{
  "topic_fa": "عنوان کوتاه بخش به فارسی",
  "topic_en": "Short section title in English",
  "study_focus_fa": "۱ تا ۲ خط: مفاهیم و کاربردهای آموزشی کلیدی این جلسه.",
  "study_focus_en": "1-2 lines: key educational concepts and applications for this session.",
  "coherence": "confident",
  "reason": "Brief justification for coherence assessment"
}
```
