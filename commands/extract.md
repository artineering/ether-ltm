---
description: Record a fact from a source document (extraction rung, w=3)
---
For agent-authored content taken from an external artifact:

    python "${CLAUDE_PLUGIN_ROOT}/scripts/ether_record.py" extract --source "<file p.N>" "$ARGUMENTS"

The --source anchor is required -- it is what makes this rung more
reliable than reconstruction. Report the printed event id.

For many facts at once, write JSON lines and use:

    python "${CLAUDE_PLUGIN_ROOT}/scripts/ether_record.py" batch --source "<file>" --session <name> < facts.jsonl
    python "${CLAUDE_PLUGIN_ROOT}/scripts/ether_record.py" audit --session <name>

Run the audit and report its output: that read-back is the only
evidence the batch landed.
