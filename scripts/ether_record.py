#!/usr/bin/env python3
"""
ether_record.py -- the agent's door into the LTM (diary F20).

The UserPromptSubmit hook only fires on prompts a HUMAN types. An
assistant invoking /remember expands the slash command locally; the
hook never sees it. F15 specified two writers but only one door was
built, so agent-initiated writes silently did nothing -- and worse, the
agent reported success it had never verified.

This tool closes that gap with one rule: **a write is not reported
until it has been read back from the database.** Confirmation is a
readout (row id + stored text from a fresh SELECT), never the caller's
expectation. Exit code is non-zero if verification fails, so an agent
cannot claim "recorded" over a failure.

Usage:
  # agent extracting from a source document (extraction rung, w=3)
  python3 ether_record.py extract --source "study.pdf p4" \\
      "cognitive load is measured by NASA-TLX plus dwell time"

  # bulk ingestion: one JSON object per line on stdin
  python3 ether_record.py batch --source "study.pdf" < facts.jsonl

  # read back what a session wrote -- verification after the fact
  python3 ether_record.py audit --session ingest-2026-07-28

  # query (prints what the hook would inject)
  python3 ether_record.py query "gestalt cues"

Provenance note: agents should use `extract` (with --source) or `note`.
`remember`/`declare` are DECLARATION rung -- the principal's authority.
An agent writing there puts its reading of a document above the user's
own testimony in every future conflict. The tool warns when an agent
reaches for a declaration verb without --i-am-the-principal.
"""

import argparse
import contextlib
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ether_hook import VERBS, handle_prompt  # noqa: E402
from ether_store import EtherStore, ether_dir  # noqa: E402

DECLARATION_VERBS = {v for v, spec in VERBS.items()
                     if spec[0] == "declaration"}


def _write(store, base, verb, text, source, session):
    """Record one memory, then VERIFY by reading it back."""
    before = store.db.execute(
        "SELECT COALESCE(MAX(id), 0) m FROM events").fetchone()["m"]
    payload = {"hook_event_name": "UserPromptSubmit",
               "session_id": session,
               "prompt": "/%s %s" % (verb, text)}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        handle_prompt(store, base, payload)

    row = store.db.execute(
        "SELECT id, ts, type, provenance, payload FROM events "
        "WHERE id > ? ORDER BY id DESC LIMIT 1", (before,)).fetchone()
    if row is None:
        return None, buf.getvalue()
    stored = json.loads(row["payload"])
    if source:                       # attach the anchor as its own event
        store.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                      "session_id": session, "type": "source_ref",
                      "author": "agent", "provenance": "readout",
                      "refers_to_event": row["id"], "source": source})
    return {"id": row["id"], "ts": row["ts"],
            "provenance": row["provenance"],
            "stored_text": stored.get("text", ""),
            "keys": [e["key"] for e in stored.get("entity_keys", [])],
            "source": source}, buf.getvalue()


def cmd_single(store, base, args, verb, text):
    rec, hook_out = _write(store, base, verb, text, args.source,
                           args.session)
    if verb == "query":
        try:
            print(json.loads(hook_out)["hookSpecificOutput"]
                  ["additionalContext"])
            return 0
        except (ValueError, KeyError):
            print("query produced no context")
            return 1
    if rec is None:
        print("FAILED: nothing was written to %s" % store.path,
              file=sys.stderr)
        return 1
    print("verified write  event #%d  %s  %s"
          % (rec["id"], rec["provenance"],
             ("[src: %s]" % rec["source"]) if rec["source"] else ""))
    print("  stored: %s" % rec["stored_text"][:100])
    print("  keys:   %s" % ", ".join(rec["keys"]))
    return 0


def cmd_batch(store, base, args):
    """One JSON object per line: {"verb": "...", "text": "...",
    "source": "..."} -- source optional per line, falls back to
    --source. Reports per-line verification and a final tally."""
    ok = failed = 0
    ids = []
    for lineno, line in enumerate(sys.stdin, 1):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            print("line %d: not JSON -- skipped" % lineno, file=sys.stderr)
            failed += 1
            continue
        verb = item.get("verb", args.default_verb)
        text = (item.get("text") or "").strip()
        if not text or verb not in VERBS:
            print("line %d: missing text or bad verb %r" % (lineno, verb),
                  file=sys.stderr)
            failed += 1
            continue
        if verb in DECLARATION_VERBS and not args.i_am_the_principal:
            print("line %d: %r is DECLARATION rung -- refused for agent "
                  "writes (use 'extract' or 'note')" % (lineno, verb),
                  file=sys.stderr)
            failed += 1
            continue
        rec, _ = _write(store, base, verb, text,
                        item.get("source") or args.source, args.session)
        if rec is None:
            print("line %d: FAILED" % lineno, file=sys.stderr)
            failed += 1
        else:
            ok += 1
            ids.append(rec["id"])
            print("  #%-4d %-10s %s" % (rec["id"], verb, text[:70]))
    print("\nverified %d write(s), %d failure(s) -> %s"
          % (ok, failed, store.path))
    if ids:
        print("event ids %d..%d -- re-check with: "
              "ether_record.py audit --session %s"
              % (min(ids), max(ids), args.session))
    return 1 if failed else 0


def cmd_audit(store, args):
    """Read back what a session actually wrote. This is the honest
    answer to 'did it record?' -- it comes from the database."""
    rows = store.db.execute(
        "SELECT id, ts, type, provenance, payload FROM events "
        "WHERE session_id = ? AND type != 'source_ref' ORDER BY id",
        (args.session,)).fetchall()
    if not rows:
        print("NOTHING recorded for session %r in %s"
              % (args.session, store.path))
        return 1
    srcs = {}
    for r in store.db.execute(
            "SELECT payload FROM events WHERE type='source_ref'"):
        d = json.loads(r["payload"])
        srcs[d.get("refers_to_event")] = d.get("source")
    print("%d event(s) for session %r:" % (len(rows), args.session))
    for r in rows:
        d = json.loads(r["payload"])
        text = d.get("text", "")
        src = srcs.get(r["id"])
        print("  #%-4d %-16s %-13s %s%s"
              % (r["id"], r["ts"][:16], r["provenance"] or "-",
                 text[:60], (" [src: %s]" % src) if src else ""))
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="agent-facing LTM recorder with verified writes")
    ap.add_argument("verb", choices=list(VERBS) + ["query", "batch",
                                                   "audit"])
    ap.add_argument("text", nargs="*")
    ap.add_argument("--source", help="external anchor for extraction "
                                     "rung, e.g. 'study.pdf p4'")
    ap.add_argument("--session", default=os.environ.get(
        "ETHER_SESSION_ID", "cli-%s" % time.strftime("%Y%m%d-%H%M%S")))
    ap.add_argument("--default-verb", default="extract",
                    help="verb for batch lines that omit one")
    ap.add_argument("--dir")
    ap.add_argument("--i-am-the-principal", action="store_true",
                    help="required to write at declaration rung")
    args, extra = ap.parse_known_args()
    # Text may appear after the flags; argparse can't always place a
    # nargs="*" positional in that case. Recover it rather than failing
    # a write on a formatting technicality.
    bad = [x for x in extra if x.startswith("--")]
    if bad:
        ap.error("unrecognized arguments: %s" % " ".join(bad))
    args.text = list(args.text) + extra

    if args.dir:
        os.environ["ETHER_DIR"] = args.dir
    base = ether_dir({"cwd": os.getcwd()})

    if args.verb in DECLARATION_VERBS and not args.i_am_the_principal:
        print("refusing: %r writes at DECLARATION rung -- the "
              "principal's authority (F15).\nIf you are the agent, use "
              "'extract --source ...' (extraction rung) or 'note'.\n"
              "If you are the user, pass --i-am-the-principal."
              % args.verb, file=sys.stderr)
        return 2

    with EtherStore(base) as store:
        if args.verb == "audit":
            return cmd_audit(store, args)
        if args.verb == "batch":
            return cmd_batch(store, base, args)
        text = " ".join(args.text).strip() or sys.stdin.read().strip()
        if not text:
            print("no text provided", file=sys.stderr)
            return 2
        if args.verb == "extract" and not args.source:
            print("extract requires --source (the anchor is what makes "
                  "this rung better than reconstruction)", file=sys.stderr)
            return 2
        return cmd_single(store, base, args, args.verb, text)


if __name__ == "__main__":
    sys.exit(main())
