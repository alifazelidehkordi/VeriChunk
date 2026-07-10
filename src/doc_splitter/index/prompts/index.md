# Study Index — Host Agent Instructions

You are writing the final study indexes. Python has only prepared verified
source data; you must author the Markdown content yourself.

## Before you write — REQUIRED

**You MUST read every chunk file before the index commit will be accepted.**
The `chunks_unread` field below lists exactly which chunk IDs you have NOT yet
read via `get_chunk`. The `commit-index` tool rejects submissions until all
chunks appear in `chunks_read`.

1. Call `get_chunk_analysis_context` for every unread chunk ID. This reads and
   records the full chunk for the index gate.
2. Verify that the `topic_*` and `study_focus_*` fields match the actual content.
3. If the study_focus is wrong or template-like, correct it in the index.

## Rules

1. Write three complete standalone Markdown files:
   - Persian: `study-index-fa.md`
   - English: `study-index-en.md`
   - Document map: `study-map.md`
2. Do not use generic placeholder study focus text.
3. Use every chunk exactly once in each index.
4. Link every session title to its chunk `file`.
5. Use the agent-selected `topic_*` and `study_focus_*` fields as the starting
   point, but correct them if they don't match the actual chunk content.
6. Mention page ranges and estimated study time.
7. All chunks in this context have already passed boundary/coherence review as
   `confident`; do not invent or hide review issues.
8. Keep Persian and English files separate; do not make one bilingual file.
9. **Do NOT use templated study focus** like "Study X: core definitions, mechanisms,
   clinical applications". Every session's study focus must be unique.
10. **Do NOT auto-generate or template the content.** Write each line yourself.
11. **Do NOT list section_headings as study focus.** Write actual educational content.

## Required structure for the Persian and English indexes

- H1 title with the source document name.
- Overview with total sessions, page coverage, and estimated study time.
- Session table with session number, linked title, pages, time, and study focus.
- Optional chapter/group sections when the chunk topics naturally group together.

## Required structure for `study-map.md`

This is a document-level learning map. It must be useful for any subject, not
only medicine, and must use these exact headings:

- H1 title naming the source document.
- `## Topic Map`: group recurring or related themes, link the supporting
  sessions, and explain the relationship. Use a table when it improves scanability.
- `## Suggested Study Order`: a ranked, dependency-aware order for studying the
  themes. Explain each priority briefly. Include numeric frequency only when you
  actually counted it from the chunks; never invent a score.
- `## Session Directory`: link every chunk exactly once with pages, time, and a
  concise focus.

The map should resemble a useful revision overview: it surfaces recurring
themes and a practical order of study, while the bilingual indexes remain the
complete session-by-session references.

Return the three Markdown bodies, then commit them with `commit-index`.
