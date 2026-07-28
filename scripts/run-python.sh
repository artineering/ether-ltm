#!/usr/bin/env bash
# Locate a Python interpreter and exec it. Hooks run under bash with a
# PATH that may lack `python` even when the Bash tool has it, so probe
# rather than assume. Exits 0 when none is found: a memory hook must
# never block a session.
for p in python3 python py python3.exe python.exe; do
  if command -v "$p" >/dev/null 2>&1; then exec "$p" "$@"; fi
done
echo "ether: no python interpreter found on PATH" >&2
exit 0
