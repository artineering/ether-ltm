---
description: Record a working assumption (declaration/assumption, w=4, defeasible)
---
Use the Bash tool to run exactly this, and nothing else:

    python "${CLAUDE_PLUGIN_ROOT}/scripts/ether_record.py" assume --i-am-the-principal "$ARGUMENTS"

Then report only what that command printed. It verifies the write by
reading it back from the database and prints the event id; that printed
confirmation is the only evidence a write happened. If the command
fails or exits non-zero, say the write FAILED -- never report success
you did not see in its output.

Treat as true, but flag any contradicting evidence.
