# ETHER LTM — a Claude Code plugin

A long-term memory with provenance discipline built in: append-only
event log, counting-sketch familiarity, verified writes, and strict
read-outs. Derived from a phenomenology-first study of human memory —
tiered forgetting, residues that never fully vanish, familiarity that
can say *how loudly* something rings but never *why*.

Pure stdlib Python plus SQLite. No third-party packages.

## Install

```bash
# from the directory containing ether-ltm/
claude plugin marketplace add ./ether-ltm
claude plugin install ether-ltm@ether-ltm-local

# or, for a session without installing:
claude --plugin-dir ./ether-ltm
```

Validate before installing:

```bash
claude plugin validate ./ether-ltm
```

## Configure the store location

At enable time Claude Code prompts for **Memory store location**. It is
optional, and the resolution order is:

| Priority | Source | Use |
|---|---|---|
| 1 | `$ETHER_DIR` | one-off override |
| 2 | `CLAUDE_PLUGIN_OPTION_STORE_PATH` | the plugin setting, **visible to hooks only** |
| 3 | `ether.config.json` | how everything else finds it — project `.claude/`, project root, `~/.claude/ether-ltm/`, `~/.claude/` |
| 4 | `~/.claude/ether-ltm/store` | default; stable across upgrades |
| 5 | `<project>/.claude/ether` | fallback when there is no home directory |

Leave the setting empty for a per-machine store. Set an absolute path
(e.g. `I:\ether`) to share one memory across every project.

**Why the config file matters.** Claude Code exports `userConfig`
values and `$CLAUDE_PLUGIN_DATA` to *hook processes only* — a Bash tool
call cannot see them. Resolving against them directly would make the
hook and the CLI open different databases, each looking empty from the
other's vantage. So a `SessionStart` hook persists the setting into
`~/.claude/ether-ltm/ether.config.json`, and every process reads that.
You can also write that file by hand and skip the plugin setting
entirely.

Nothing is patched into the source, so upgrades cannot silently move
your database.

`/memory-status` always prints which of the five it resolved from — a
store in an unexpected place is otherwise indistinguishable from an
empty one.

## Commands

| Command | Rung | w | Meaning |
|---|---|---|---|
| `/remember` | declaration/pin | 5 | pin a fact |
| `/declare` | declaration/ruling | 8 | stipulation; wins conflicts |
| `/assume` | declaration/assumption | 4 | defeasible working assumption |
| `/note` | testimony/note | 2 | your own first-person report |
| `/retract` | declaration/retraction | 8 | supersede — never deletes |
| `/park` | declaration/parked | 6 | seen and set aside |
| `/extract` | extraction/source-fact | 3 | agent-recorded, source anchor required |
| `/ingest` | extraction (batch) | 3 | read a file (md, pdf, notebook); draft → confirm → batch → audit |
| `/query` | *(read)* | — | strict read-out with a receipt |
| `/memory-status` | *(read)* | — | doctor + snapshot |

## How it behaves

**Capture is cheap and dumb.** The `Stop` hook makes no model calls: it
dedupes the exchange, queues it, and lays a weak trace. Inline encoding
loops, and brains don't consolidate inline either.

**Consolidation is offline.** Run it from a plain shell, never inside a
Claude session:

```bash
python "$CLAUDE_PLUGIN_ROOT/scripts/ether_consolidate.py"            # encode
python "$CLAUDE_PLUGIN_ROOT/scripts/ether_consolidate.py" --age 0.9  # decay
python "$CLAUDE_PLUGIN_ROOT/scripts/ether_consolidate.py" --stats    # experiment
```

Only this step calls a model — via `ANTHROPIC_API_KEY`, else
`claude -p --bare` (inheriting a corporate seat), else a keyword
encoder.

**Nothing is deleted.** `events` is insert-only, enforced by SQLite
triggers. Retraction supersedes; both versions stay visible.

**The sketch is disposable.** It is a fold over the log and can be
rebuilt at any time:

```bash
python "$CLAUDE_PLUGIN_ROOT/scripts/ether_consolidate.py" --reindex
python "$CLAUDE_PLUGIN_ROOT/scripts/ether_consolidate.py" --rebuild
```

## Try it before trusting it

```bash
python "$CLAUDE_PLUGIN_ROOT/scripts/ether_seed.py" --dir /tmp/ltm-trial
python "$CLAUDE_PLUGIN_ROOT/scripts/ether_inspect.py" --dir /tmp/ltm-trial
python "$CLAUDE_PLUGIN_ROOT/scripts/ether_inspect.py" --dir /tmp/ltm-trial --key quaternion
```

A scripted three-week project history in a throwaway store: frequency
versus salience, canonicalization across surface forms, supersession,
and honest misses. Offline and deterministic.

## Interpreter

Hooks run through `scripts/run-python.sh`, which probes `python3`,
`python`, and `py` in turn and exits cleanly if none is found — hooks
run under a bash whose PATH can differ from the Bash tool's, so the
interpreter is located rather than assumed. No configuration needed.

## Safety

Hooks run shell commands on your machine. This plugin's hooks execute
only the bundled `scripts/ether_hook.py`, make no network calls, and
write only to the resolved store directory. The consolidation job is
the sole component that contacts a model, and it never runs
automatically — you invoke it.
