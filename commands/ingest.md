---
description: Read an external document and capture its facts as extraction-rung memories (draft, confirm, batch, audit)
---
Ingest the file at `$ARGUMENTS` into the ETHER LTM as extraction-rung
facts.

Consult the `memory-ingest` skill for the full workflow. In short:

1.  Read the file with the Read tool (md, txt, pdf, notebook — whatever
    the harness supports). For PDFs longer than ten pages, iterate
    through page ranges via the `pages` param rather than reading blind.
2.  Draft candidate facts as JSON lines: one object per line with
    `text` and a per-line `source` anchor of the form `<file p.N>` or
    `<file §heading>`. Present the draft and STOP.
3.  On the user's go-ahead, run the batch write with a fresh session:

        python "${CLAUDE_PLUGIN_ROOT}/scripts/ether_record.py" batch \\
            --source "$ARGUMENTS" --session ingest-<slug> < facts.jsonl

    then

        python "${CLAUDE_PLUGIN_ROOT}/scripts/ether_record.py" audit \\
            --session ingest-<slug>

    Report the audit's output verbatim. A write is not recorded until
    that read-back confirms it.

Do not skip the draft step. Do not use declaration-rung verbs — the
principal's authority is not yours to spend from a document.
