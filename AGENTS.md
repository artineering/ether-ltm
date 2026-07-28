# ether-ltm

## Working Directory

When authoring or modifying anything in this repo, invoke agents from the project root. Tools detect the repo type via `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` in the working directory.

## Repo Layout

This repo is a single-plugin marketplace: the plugin manifest and marketplace manifest both live at the root, and the marketplace's one plugin entry points back at `./`.

- `.claude-plugin/plugin.json` — plugin metadata (`ether-ltm`)
- `.claude-plugin/marketplace.json` — local marketplace registering this plugin
- `commands/*.md` — slash commands (`/remember`, `/declare`, `/assume`, `/note`, `/retract`, `/park`, `/extract`, `/ingest`, `/query`, `/memory-status`)
- `hooks/hooks.json` — `SessionStart`, `UserPromptSubmit`, `Stop` hooks
- `scripts/*.py` — Python entry points invoked by hooks, commands, and offline consolidation
- `scripts/run-python.sh` — interpreter locator used by hooks
- `skills/memory-ltm/SKILL.md` — provenance rules the agent must consult before recording, recalling, or reporting on memory
- `skills/memory-ingest/SKILL.md` — draft/confirm/batch/audit workflow for reading external documents into the LTM at the extraction rung

## Authoring

Do not create or modify skills manually. Use `skill-workshop` for the full authoring workflow.

Do not restructure the plugin, marketplace, or skill layout manually. Use `skill-packaging` for structural changes.

## Provenance Discipline

Any change that touches recording, recalling, or reporting on memory MUST be consistent with `skills/memory-ltm/SKILL.md`. That skill is the authority for what counts as "the memory", what a rung means, and how writes and reads must be reported.

## Agent Agnostic

Skills in this repo must work across Claude Code, Amp, Gemini CLI, and Codex. No agent-specific language or assumptions.
