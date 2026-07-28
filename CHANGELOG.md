# Changelog

## 0.1.1

- Hooks locate the interpreter via `scripts/run-python.sh` instead of
  assuming `python`; hook PATH can differ from the Bash tool's.
- Store resolution no longer uses hook-only environment
  (`$CLAUDE_PLUGIN_DATA`, `CLAUDE_PLUGIN_OPTION_*` as a default): a
  `SessionStart` hook persists the plugin setting into
  `~/.claude/ether-ltm/ether.config.json`, which every process reads.
  Without this the hook and the CLI opened different databases.
- Default store moved to `~/.claude/ether-ltm/store`.
- Doctor is plugin-aware: checks the plugin's own commands and
  hooks.json, and accepts the `memory-ltm` skill in place of
  CLAUDE.md rules.

## 0.1.0

First packaged release. Consolidates work previously installed by hand.

- Store location resolved at runtime (`$ETHER_DIR` → plugin
  `store_path` → `ether.config.json` → `$CLAUDE_PLUGIN_DATA` →
  project) instead of patched into source, so upgrades cannot move the
  database.
- Slash commands invoke `ether_record.py` directly. They must never
  return to the `ETHER-COMMAND` marker form: slash commands route
  through the skill loader and bypass `UserPromptSubmit`.
- `extraction` provenance rung for agent-recorded source facts, with a
  required `--source` anchor; declaration verbs refused for agent
  writes.
- Verified writes: nothing is reported until read back from the
  database; non-zero exit on failure.
- Query receipts and strict read-out rules; no result — match or empty
  — may be reported without a run.
- Standing provenance rules shipped as a skill (a plugin's CLAUDE.md is
  not loaded into context).
- `/memory-status` doctor: checks each layer independently and proves
  retrieval with a live read.
