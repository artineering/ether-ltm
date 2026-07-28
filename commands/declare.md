---
description: Record a constitutive ruling (declaration/ruling, w=8; wins conflicts)
---
Use the Bash tool to run exactly this, and nothing else:

    python "${CLAUDE_PLUGIN_ROOT}/scripts/ether_record.py" declare --i-am-the-principal "$ARGUMENTS"

Then report only what that command printed. It verifies the write by
reading it back from the database and prints the event id; that printed
confirmation is the only evidence a write happened. If the command
fails or exits non-zero, say the write FAILED -- never report success
you did not see in its output.

Treat it as authoritative for the rest of the session.
