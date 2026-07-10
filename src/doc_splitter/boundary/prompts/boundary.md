# Boundary Detection — Host Agent Instructions

You are choosing a **conceptual split point** in a document. Do NOT pick the next heading by default. Read the content and decide where the current topic/discussion truly ends and a new independent topic begins.

This is an agent decision. The tool only supplies safe candidates; it does not
decide the conceptual boundary for you.

## Rules

1. You may ONLY choose from the provided `safe_candidates` list (element IDs).
2. Never cut mid-paragraph, mid-table, or mid-list.
3. The configured `max_pages` is enforced for normal decisions. Prefer a smaller
   coherent unit over a broad chapter grouping.
4. If no safe boundary exists within the limit, respond with `action: "extend"`,
   set `allow_oversize: true`, and explain why this specific concept cannot be
   split. This is an exception, not the normal workflow.
5. Provide a short `reason` for auditability (stored in manifest.json).
6. **NEVER use generic or auto-generated reasons.** "auto-cut ~6000 words" is forbidden. Write a real conceptual reason explaining where the topic ends and why this cut is logical.
7. The `reason` field must be your own writing — not copied from the parser, not auto-generated, not a word-count formula.
8. A `required_topic_boundary` is backed by independent review votes. Cut at or
   before it. Crossing it requires `allow_topic_merge: true` and a reason that
   explains why the reviewers were wrong about the topic change.

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
  "allow_oversize": true,
  "reason": "The current argument continues through the examples without a natural break yet."
}
```
