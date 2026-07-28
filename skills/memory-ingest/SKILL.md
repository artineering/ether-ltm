---
name: memory-ingest
description: "Use when reading an external document (md, txt, pdf, notebook, or anything the Read tool supports) and capturing its facts into the ETHER long-term memory. Invoke for `/ingest`, or any request to 'read this file into memory', 'extract facts from', 'summarise into LTM', or 'ingest this PDF'. Governs the draft → confirm → batch → audit workflow with per-line source anchors."
---

# ETHER memory — ingest workflow

Documents get read into the memory at the **extraction** rung: agent
authorship, external source, source anchor required. Not declaration —
you are reporting what a document said, not stipulating a fact on the
principal's authority. See [[memory-ltm]] for the rung ladder and the
one rule that governs everything here: a write is not recorded until it
has been read back.

## Inputs

Anything the harness's Read tool can open:

- Markdown, plain text, source code — read whole.
- PDFs — read whole if ≤10 pages; otherwise iterate through ranges via
  the `pages` parameter (`"1-10"`, `"11-20"`, …). Do not "sample" a
  long document by reading only the first few pages and inferring the
  rest; that is a reconstruction dressed as an extraction.
- Notebooks — the Read tool returns cells and outputs together.

If a file type is not supported by the Read tool, say so and stop. Do
not fetch, transcribe, or paraphrase from a source you cannot open.

## The four steps

### 1. Read

Open the file. If it is long, plan the passes (page ranges, sections)
before writing anything.

### 2. Draft

Produce a JSON-lines block of candidate facts. One object per line:

```json
{"text": "cognitive load is measured by NASA-TLX plus dwell time", "source": "study.pdf p.4"}
{"text": "the dwell threshold used in the pilot was 400ms", "source": "study.pdf p.5"}
```

- `text` — the fact, in your own words, one claim per line. No pronouns
  that only resolve inside the source. No summaries that lump several
  claims together — a batch of narrow facts is more useful than one
  fat sentence.
- `source` — the anchor. Use `<file p.N>` for paginated documents,
  `<file §heading>` for markdown/notebook sections, `<file:line>` for
  code, `<file>` alone only when the document is short and single-piece.
  Every line needs one; the extraction rung is defined by the anchor.
- `verb` — omit. `batch` defaults to `extract`, which is correct here.
  Never emit `remember`, `declare`, or `assume` from a document; those
  are declaration-rung and require the principal.

Present the full draft to the user and **stop**. Do not run the batch
yet.

### 3. Confirm

Wait for the user's go-ahead. They may edit the draft, drop lines,
tighten wording, or change source anchors. Apply their edits verbatim.

Do not proceed on ambiguity ("looks fine", "sure, whatever") — ask what
they want changed if anything.

### 4. Batch and audit

Write the confirmed lines to a temporary `.jsonl` file, then run:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/ether_record.py" batch \
    --source "<file>" --session ingest-<slug> < facts.jsonl
python "${CLAUDE_PLUGIN_ROOT}/scripts/ether_record.py" audit \
    --session ingest-<slug>
```

Notes:
- `--session ingest-<slug>` groups the writes so `audit` can read them
  back. Use a slug that identifies the document, e.g.
  `ingest-nasa-tlx-2026-07-28`.
- The top-level `--source` is a fallback; per-line `source` in the JSON
  wins when present. Prefer per-line anchors — they carry page numbers.
- Report the `audit` output verbatim. That read-back is the only
  evidence the writes landed. If `batch` printed `FAILED` for any line
  or exited non-zero, say the ingest partially or wholly FAILED and
  quote the failing lines. Never round a partial failure up to success.

## What not to do

- Do not write from memory of a document. If you closed the file
  between draft and batch, re-read the relevant page — the anchor must
  point at content you can still see.
- Do not silently truncate a long document. If you only read the first
  N pages, say so and offer to continue; the memory will otherwise
  falsely suggest the document has been ingested fully.
- Do not invent anchors. If you cannot cite a specific page or heading,
  the claim is not extraction-grade — either read more carefully or
  drop the line.
- Do not use `remember`/`declare`/`assume`. If a document says
  something the user should stipulate, tell them and let them run
  `/declare` themselves.
- Do not summarise. Small, atomic facts survive future conflicts;
  compound sentences do not.

## When something looks wrong

Run `/memory-status`. If the audit disagrees with what `batch` printed,
trust the audit — it is a live read of the database. Report what it
showed and stop.

## Reflection Gate

Before marking an ingest task complete, open `docs/insights.md` (create
if missing) and append a row:

| Date | Skill | Worked Well | Unexpected | Do Differently |
|------|-------|-------------|------------|----------------|
| YYYY-MM-DD | memory-ingest | _answer_ | _answer_ | _answer_ |
