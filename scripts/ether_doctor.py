#!/usr/bin/env python3
"""
ether_doctor.py -- check the whole install, end to end.

  python3 .claude/hooks/ether_doctor.py [project_dir]

Answers the question "why didn't /query return anything?" without
guesswork. Checks each layer independently, because the failures in
F20-F23 were all a silent layer, and a silent layer looks exactly like
an empty memory from the outside:

  1. hook scripts present and at the expected revision
  2. slash-command files call the CLI (not the dead marker form)
  3. hook registered in settings.json
  4. standing provenance rules present in CLAUDE.md
  5. store reachable, and what is in it
  6. LIVE end-to-end query: runs a real read and prints its receipt

Exit code is non-zero if anything is broken, so it can gate a session.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

OK, BAD, WARN = "  [ok]   ", "  [FAIL] ", "  [warn] "
problems = []


def fail(msg, fix):
    problems.append((msg, fix))
    print(BAD + msg)


def check_scripts():
    print("\n1. hook scripts")
    need = ["ether_store.py", "ether_hook.py", "ether_consolidate.py",
            "ether_record.py", "ether_inspect.py"]
    for f in need:
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            print(OK + f)
        else:
            fail("%s missing from %s" % (f, HERE),
                 "copy it from the consolidated bundle")
    hook = os.path.join(HERE, "ether_hook.py")
    if os.path.exists(hook):
        src = open(hook, encoding="utf-8", errors="replace").read()
        if '"extract":' in src:
            print(OK + "ether_hook.py has the extraction rung")
        else:
            fail("ether_hook.py predates the extraction rung",
                 "update from the bundle")
        if "receipt #" in src:
            print(OK + "ether_hook.py emits query receipts")
        else:
            fail("ether_hook.py does not emit receipts",
                 "update from the bundle")


def check_commands(root):
    print("\n2. slash-command files")
    proot = plugin_root()
    d = os.path.join(proot, "commands") if proot \
        else os.path.join(root, ".claude", "commands")
    if not os.path.isdir(d):
        print(WARN + "no .claude/commands -- use the colon form "
                     "(`query: ...`), which reaches the hook directly")
        return
    stale = live = 0
    for name in sorted(os.listdir(d)):
        if not name.endswith(".md"):
            continue
        body = open(os.path.join(d, name), encoding="utf-8",
                    errors="replace").read()
        if "ETHER-COMMAND" in body:
            stale += 1
            print(BAD + "%s uses the dead ETHER-COMMAND marker" % name)
        elif "ether_record.py" in body:
            live += 1
            print(OK + "%s calls ether_record.py" % name)
    if stale:
        fail("%d command file(s) rely on the UserPromptSubmit hook, "
             "which slash commands BYPASS -- they silently do nothing"
             % stale,
             "rm .claude/commands/*.md && bash install_ether_commands.sh")
    elif not live:
        print(WARN + "no ether command files found")


def check_settings(root):
    print("\n3. hook registration")
    proot = plugin_root()
    if proot:
        hp = os.path.join(proot, "hooks", "hooks.json")
        try:
            cfg = json.load(open(hp, encoding="utf-8"))
        except (OSError, ValueError) as e:
            fail("plugin hooks.json unreadable: %s" % e, "reinstall")
            return
        for ev in ("SessionStart", "UserPromptSubmit", "Stop"):
            if ev in cfg.get("hooks", {}):
                print(OK + "%s registered (plugin)" % ev)
            else:
                fail("%s missing from plugin hooks.json" % ev,
                     "reinstall the plugin")
        launcher = os.path.join(proot, "scripts", "run-python.sh")
        if os.path.exists(launcher):
            print(OK + "interpreter launcher present")
        else:
            fail("run-python.sh missing", "reinstall the plugin")
        return
    p = os.path.join(root, ".claude", "settings.json")
    if not os.path.exists(p):
        print(WARN + "no .claude/settings.json (fine if you only use "
                     "the slash commands / CLI)")
        return
    try:
        cfg = json.load(open(p, encoding="utf-8"))
    except ValueError as e:
        fail("settings.json is not valid JSON: %s" % e, "fix the syntax")
        return
    hooks = json.dumps(cfg.get("hooks", {}))
    for ev in ("UserPromptSubmit", "Stop"):
        if ev in hooks and "ether_hook" in hooks:
            print(OK + "%s registered" % ev)
        else:
            print(WARN + "%s not registered for ether_hook.py" % ev)


def plugin_root():
    """HERE is <plugin>/scripts when installed as a plugin."""
    parent = os.path.dirname(HERE)
    if os.path.isdir(os.path.join(parent, ".claude-plugin")):
        return parent
    return None


def check_claude_md(root):
    print("\n4. standing provenance rules")
    proot = plugin_root()
    if proot:
        skill = os.path.join(proot, "skills", "memory-ltm", "SKILL.md")
        if os.path.exists(skill):
            print(OK + "shipped as the memory-ltm skill (plugin "
                       "install; a plugin CLAUDE.md is not loaded)")
            return
        fail("plugin install is missing skills/memory-ltm/SKILL.md",
             "reinstall the plugin -- the rules are what stop the agent "
             "answering from other memory files")
        return
    found = False
    for name in ("CLAUDE.md", "ETHER-CLAUDE-md-rules.md"):
        p = os.path.join(root, name)
        if os.path.exists(p):
            body = open(p, encoding="utf-8", errors="replace").read()
            if "ETHER" in body and "receipt" in body:
                print(OK + "%s carries the standing rules" % name)
                found = True
    if not found:
        fail("no standing provenance rules in CLAUDE.md",
             "paste ETHER-CLAUDE-md-rules.md into CLAUDE.md")


def check_store():
    print("\n5. store")
    try:
        from ether_store import EtherStore, ether_dir, resolve_store_dir
    except ImportError as e:
        fail("cannot import ether_store: %s" % e, "check the scripts dir")
        return None
    base, source = resolve_store_dir({"cwd": os.getcwd()})
    ether_dir()
    print(OK + "store dir: %s" % base)
    print("         (resolved from: %s)" % source)
    if not os.path.isdir(base):
        fail("store directory does not exist", "it is created on first "
             "write; check DEFAULT_STORE points where you expect")
        return None
    try:
        store = EtherStore(base)
    except Exception as e:  # noqa: BLE001
        fail("cannot open the database: %r" % e, "check permissions")
        return None
    st = store.stats()
    total = sum(st["events"].values())
    print(OK + "%d event(s): %s" % (total, st["events"] or "(empty)"))
    if not total:
        print(WARN + "the store is empty -- queries returning nothing "
                     "would be CORRECT")
    n = store.db.execute("SELECT COUNT(DISTINCT key) n "
                         "FROM event_keys").fetchone()["n"]
    print(OK + "%d distinct key(s) in the retrieval index" % n)
    if total and not n:
        fail("events exist but the key index is empty -- retrieval "
             "cannot match anything",
             "python ether_consolidate.py --reindex")
    return store


def live_query(store):
    print("\n6. live end-to-end read")
    if store is None:
        print(BAD + "skipped (no store)")
        return
    row = store.db.execute(
        "SELECT key FROM event_keys WHERE role != 'query' "
        "GROUP BY key ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
    if row is None:
        print(WARN + "nothing deposited yet; cannot prove retrieval")
        return
    probe = row["key"]
    import io
    import contextlib
    from ether_hook import handle_query
    from ether_store import ether_dir
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        handle_query(store, ether_dir({"cwd": os.getcwd()}),
                     {"session_id": "doctor"}, probe)
    try:
        ctx = json.loads(buf.getvalue())["hookSpecificOutput"][
            "additionalContext"]
    except (ValueError, KeyError):
        fail("the query path produced no injection", "check ether_hook.py")
        return
    receipt = re.search(r"receipt #(\d+)", ctx)
    matched = "Matching memories" in ctx
    print(OK + "queried the most-deposited key: %r" % probe)
    print(OK + "receipt #%s issued" % (receipt.group(1) if receipt
                                       else "MISSING"))
    if matched:
        print(OK + "retrieval returned matches -- the read path works "
                   "end to end")
        print("\n  --- what a working /query looks like ---")
        for line in ctx.splitlines()[:5]:
            print("  " + line)
    else:
        fail("retrieval returned NO matches for a key that is in the "
             "index (%r) -- retrieval is broken, not empty" % probe,
             "python ether_consolidate.py --reindex")


def main():
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    print("ether doctor -- project root: %s" % root)
    check_scripts()
    check_commands(root)
    check_settings(root)
    check_claude_md(root)
    store = check_store()
    live_query(store)
    if store:
        store.close()
    print("\n" + "=" * 62)
    if problems:
        print("%d problem(s) found:\n" % len(problems))
        for msg, fix in problems:
            print("  * %s\n      fix: %s" % (msg, fix))
        return 1
    print("all checks passed. If /query still reports nothing, the "
          "agent is not running the command -- ask it to show the\n"
          "receipt, which only a real run can produce.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
