# Boundary Detection — Host Agent Instructions

You are choosing a **conceptual split point** in a document. Do NOT pick the next heading by default. Read the content and decide where the current topic/discussion truly ends and a new independent topic begins.

## Rules

1. You may ONLY choose from the provided `safe_candidates` list (element IDs).
2. Never cut mid-paragraph, mid-table, or mid-list.
3. Target chunk size is roughly 5–10 pages, but **concept completeness overrides page count**.
4. If the current concept is not complete within the window, respond with `action: "extend"` and explain why.
5. Provide a short `reason` for auditability (stored in manifest.json).

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
  "reason": "The pathophysiology discussion continues through the case studies without a natural break yet."
}
```