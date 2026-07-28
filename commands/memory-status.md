---
description: Diagnose and inspect the ETHER LTM (doctor + snapshot)
---
Use the Bash tool to run:

    python "${CLAUDE_PLUGIN_ROOT}/scripts/ether_doctor.py" .

Report its output verbatim, including which problems it lists and the
store path it resolved. If it passes, optionally follow with:

    python "${CLAUDE_PLUGIN_ROOT}/scripts/ether_inspect.py"

Do not interpret beyond what the tools printed. If the doctor reports
the store is empty, say so plainly -- an empty store is a real state,
not a problem to explain away.
