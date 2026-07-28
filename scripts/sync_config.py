#!/usr/bin/env python3
"""Persist plugin-only environment into a config file every process can
read.

CLAUDE_PLUGIN_OPTION_* and CLAUDE_PLUGIN_DATA are exported to hook
processes only -- not to Bash tool calls. Relying on them directly
would make the hook and the CLI resolve DIFFERENT databases, each of
which looks empty from the other's vantage. This runs on SessionStart
(a hook, so it can see them) and writes ~/.claude/ether-ltm/
ether.config.json, which every later process reads.
"""
import json
import os
import sys

HOME_DIR = os.path.join(os.path.expanduser("~"), ".claude", "ether-ltm")


def main():
    try:
        sys.stdin.read()
    except Exception:  # noqa: BLE001
        pass
    store = os.environ.get("CLAUDE_PLUGIN_OPTION_STORE_PATH")
    model = os.environ.get("CLAUDE_PLUGIN_OPTION_ENCODER_MODEL")
    os.makedirs(HOME_DIR, exist_ok=True)
    path = os.path.join(HOME_DIR, "ether.config.json")
    cfg = {}
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        pass
    changed = False
    if store and cfg.get("store_path") != store:
        cfg["store_path"] = store
        changed = True
    if model and cfg.get("encoder_model") != model:
        cfg["encoder_model"] = model
        changed = True
    cfg.setdefault("store_path", os.path.join(HOME_DIR, "store"))
    if changed or not os.path.exists(path):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, path)
    sys.exit(0)


if __name__ == "__main__":
    main()
