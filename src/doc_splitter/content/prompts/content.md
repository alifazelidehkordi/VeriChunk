# Content Analysis — Host Agent Instructions

Read the **entire chunk** below. Produce a precise conceptual description — not a generic label.

## Rules

1. Read the full chunk content before writing anything.
2. Use `section_headings` and `provisional_topic` from the context as your primary title source.
3. `topic_*` must be a **short section title** (like a chapter/session name), never a copied sentence from the body.
4. `study_focus_*` must be **1–2 educational lines** listing key concepts, mechanisms, tests, or algorithms to master.
5. Output both Persian (`topic_fa`, `study_focus_fa`) and English (`topic_en`, `study_focus_en`).
6. Judge coherence: is this chunk a cohesive unit? Does the cut feel logical vs neighbors?
7. Use `confident` or `needs_review` with a short reason.

## Field definitions

| Field | Purpose | Length |
|---|---|---|
| `topic_*` | Short session/section title (from headings, not body text) | ≤ 14 words, no trailing period |
| `study_focus_*` | What to learn in this session — concepts, mechanisms, applications | 1–2 lines, comma-separated key points |

**Bad topic:** `HeFH is the most frequent genetic disease, HoFH is rarer and it is really dangerous.`
**Good topic:** `Familial Hypercholesterolemia and Lipid Risk`
**Good study_focus:** `DLCN criteria, LDLR/PCSK9, sdLDL, Lp(a), residual cardiovascular risk after statins.`

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