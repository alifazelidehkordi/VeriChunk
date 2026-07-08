# Content Analysis — Host Agent Instructions

Read the **entire chunk** below. Produce a precise conceptual description — not a generic label.

## Rules

1. Describe what arguments, concepts, and examples are actually covered.
2. If multiple related subtopics appear in one chunk, mention all of them.
3. Output both Persian (`topic_fa`, `study_focus_fa`) and English (`topic_en`, `study_focus_en`).
4. Judge coherence: is this chunk a cohesive unit? Does the cut feel logical vs neighbors?
5. Use `confident` or `needs_review` with a short reason.

## Field definitions

| Field | Purpose | Length |
|---|---|---|
| `topic_*` | Short session title / label (what this chunk is about) | 1 sentence |
| `study_focus_*` | Educational study focus — what to learn, apply, or review | 1–2 lines |

`study_focus` must be **practical and educational**: key concepts, mechanisms, algorithms, comparisons, examples, or clinical/lab applications the learner should master. Do not repeat the topic verbatim.

## Response format (JSON)

```json
{
  "topic_fa": "عنوان کوتاه جلسه به فارسی",
  "topic_en": "Short session title in English",
  "study_focus_fa": "۱ تا ۲ خط توضیح آموزشی: مفاهیم، مکانیسم‌ها، الگوریتم‌ها یا کاربردهایی که باید در این جلسه یاد گرفته شوند.",
  "study_focus_en": "1-2 line educational focus: concepts, mechanisms, algorithms, or applications to master in this session.",
  "coherence": "confident",
  "reason": "Brief justification for coherence assessment"
}
```