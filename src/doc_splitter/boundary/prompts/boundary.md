# Boundary Detection — Host Agent Instructions

Choose a **conceptual split point**. Topic continuity is more important than
hitting an exact page count, but a real topic change always wins over size.

## Priority order

1. Confirmed topic change or change of learning objective.
2. Natural completion of the current argument, lesson, example set, or unit.
3. Structurally safe cut.
4. Preferred chunk size.
5. Visual headings.

A heading is evidence, not an automatic split. A topic can also change without a
heading.

## Rules

1. Choose only from `safe_candidates` and never cut inside an element.
2. When `required_topic_boundary` is present, cut at that exact element. It is
   backed by independent review and cannot be crossed or overridden.
3. The preferred maximum is 12 pages. Page 13 is a soft completion allowance.
4. Extending from 12 to 13 requires a specific semantic reason.
5. Every extension beyond page 13 requires at least two independent reviewer IDs
   and at least two cited element IDs proving that the same topic continues.
6. The window grows one page at a time. Do not jump directly to the hard limit.
7. Twenty pages is an absolute cap. At that point choose the best safe candidate;
   the system records a `forced_size_split` and links the continuation.
8. Never extend across a confirmed topic change.
9. Reasons must describe the actual conceptual relationship. Generic reasons,
   word-count formulas, and `auto-cut` language are rejected.

## Cut response

```json
{
  "action": "cut",
  "element_id": "el-042",
  "reason": "The current mechanism and its examples conclude here; the next paragraph begins a separate learning objective."
}
```

## Extension to page 13

```json
{
  "action": "extend",
  "allow_oversize": true,
  "reason": "The same derivation continues into its concluding example on the next page."
}
```

## Extension beyond page 13

```json
{
  "action": "extend",
  "allow_oversize": true,
  "reason": "Both reviewers confirm that the argument remains one continuous derivation.",
  "continuity_evidence": ["el-118", "el-121"],
  "continuity_reviewers": ["reviewer-a", "reviewer-b"]
}
```
