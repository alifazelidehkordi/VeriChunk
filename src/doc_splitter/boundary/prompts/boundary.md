# Boundary Detection — Host Agent Instructions

You are choosing a **conceptual split point** in a document. Do NOT pick the next heading by default. Read the content and decide where the current topic/discussion truly ends and a new independent topic begins.

This is an agent decision. The tool only supplies safe candidates; it does not
decide the conceptual boundary for you.

## Rules

1. You may ONLY choose from the provided `safe_candidates` list (element IDs).
2. Never cut mid-paragraph, mid-table, or mid-list.
3. Target chunk size is roughly 5–10 pages, but **concept completeness overrides page count**.
4. If the current concept is not complete within the window, respond with `action: "extend"` and explain why.
5. Provide a short `reason` for auditability (stored in manifest.json).
6. **NEVER use generic or auto-generated reasons.** "auto-cut ~6000 words" is forbidden. Write a real conceptual reason explaining where the topic ends and why this cut is logical.
7. The `reason` field must be your own writing — not copied from the parser, not auto-generated, not a word-count formula.

## Response format (JSON)

```json
{
  "action": "cut",
  "element_id": "el-042",
  "reason": "Examples 1-3 are part of one argument; the next independent topic starts after the summary paragraph."
}
```

Or to extend the window:

```json
{
  "action": "extend",
  "reason": "The current argument continues through the examples without a natural break yet."
}
```
