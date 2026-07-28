#!/usr/bin/env python3
"""
ether_consolidate.py -- the sleep job (diary F16).

Offline batch consolidation for the ETHER LTM. Run this OUTSIDE any
Claude session -- manually, or on a timer (cron/systemd). It is never
hook-spawned, so encoder recursion is impossible by construction.

  python3 .claude/hooks/ether_consolidate.py            # consolidate
  python3 .claude/hooks/ether_consolidate.py --age 0.5  # + aging pass
  python3 .claude/hooks/ether_consolidate.py --stats    # experiment read-out

What it does:
  1. Drains .claude/ether/pending.jsonl (captures enqueued by the Stop
     hook -- fast weak traces awaiting refinement).
  2. For each capture, runs the encoder ETHER_ENCODES times (default 2:
     the reconstruction-consistency experiment), appends a
     reconstruction_manifest record, deposits refined keys at full
     weight (the weak 0.5x capture deposit was the fast trace; replay
     strengthening is phenomenologically correct, not double-counting).
  3. Optionally ages the sketch (--age FACTOR): weak traces vanish
     first, the frequent and salient persist.
Processed captures are removed from pending.jsonl atomically; failures
stay queued for the next run.

Encoder auth (same chain as the hook): ANTHROPIC_API_KEY -> direct API;
`claude -p --bare` -> corporate/OAuth; ETHER_DRY_RUN=1 -> naive keys.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ether_hook import consistency, encode  # noqa: E402
from ether_store import (EtherStore, Sketch, ether_dir,  # noqa: E402
                         keys_of, load_aliases, migrate_jsonl, resolve)


def log_error(base, err):
    try:
        with open(os.path.join(base, "error.log"), "a") as f:
            f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), err))
    except OSError:
        pass


BATCH_CAP = int(os.environ.get("ETHER_BATCH_CAP", "50"))
def consolidate(store, base):
    captures = store.pending_captures(limit=BATCH_CAP)
    if not captures:
        print("nothing pending.")
        return
    n_enc = max(1, int(os.environ.get("ETHER_ENCODES", "2")))
    sk = store.load_sketch()
    aliases = load_aliases(base)
    done = failed = 0

    for cap in captures:
        try:
            manifests = [encode(cap["user_text"], cap["assistant_text"])
                         for _ in range(n_enc)]
            record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                      "session_id": cap.get("session_id"),
                      "capture_id": cap["capture_id"],
                      "captured_at": cap.get("ts"),
                      "type": "reconstruction_manifest", "author": "agent",
                      "provenance": "reconstruction",
                      "note": "self-report; reconstruction, not readout "
                              "(F14); consolidated offline (F16)",
                      "manifests": manifests}
            if n_enc >= 2:
                record["consistency"] = consistency(manifests[0],
                                                    manifests[1])
            resolutions = []
            for e in manifests[0].get("entity_keys", []):
                canonical, superseded = resolve(e["key"], aliases)
                if canonical != e["key"]:
                    resolutions.append({"surface": e["key"],
                                        "canonical": canonical,
                                        "superseded_name": superseded})
                e["key"] = canonical          # store canonical in the log
                sk.deposit(canonical, float(e.get("w", 1.0)))
            if resolutions:
                record["canonicalization"] = resolutions
            gist = manifests[0].get("episode_gist")
            if gist:
                sk.deposit(gist, 1.0)
            store.append(record, keys=keys_of(record))
            store.mark_consolidated(cap["capture_id"])
            done += 1
        except Exception as err:  # noqa: BLE001 -- stays queued, move on
            failed += 1
            log_error(base, "consolidate %s: %r"
                      % (cap.get("capture_id"), err))
    store.save_sketch(sk)
    print("consolidated %d capture(s); %d failed (kept queued)."
          % (done, failed))


def age(store, factor):
    sk = store.load_sketch()
    sk.age(factor)
    store.save_sketch(sk)
    store.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                  "type": "aging", "author": "system",
                  "provenance": "readout", "factor": factor})
    print("aged sketch by %.2f: weak traces fade first, the salient "
          "persist." % factor)


def rebuild(store, base):
    """The sketch is a FUNCTION OF THE LOG (F19), not a precious mutable
    blob. Replays every event in insertion order onto a fresh sketch."""
    store.reset_sketch()
    sk = Sketch()
    aliases = load_aliases(base)
    counts = {}
    for r in store.iter_events():
        kind = r.get("type")
        if kind == "capture":
            wf = float(r.get("weight_factor", 0.5))
            for e in r.get("naive_keys", []):
                sk.deposit(resolve(e["key"], aliases)[0],
                           wf * float(e.get("w", 1.0)))
        elif kind == "user_manifest":
            w = float(r.get("weight", 1.0))
            for e in r.get("entity_keys", []):
                sk.deposit(resolve(e["key"], aliases)[0], w)
        elif kind == "reconstruction_manifest":
            m0 = (r.get("manifests") or [{}])[0]
            for e in m0.get("entity_keys", []):
                sk.deposit(resolve(e["key"], aliases)[0],
                           float(e.get("w", 1.0)))
            if m0.get("episode_gist"):
                sk.deposit(m0["episode_gist"], 1.0)
        elif kind == "query":
            for k in r.get("keys", []):
                sk.familiarity(resolve(k, aliases)[0], reinforce=0.25)
        elif kind == "aging":
            sk.age(float(r.get("factor", 1.0)))
        else:
            continue
        counts[kind] = counts.get(kind, 0) + 1
    store.save_sketch(sk)
    print("rebuilt sketch from log: %s"
          % (", ".join("%s=%d" % kv for kv in sorted(counts.items()))
             or "(empty log)"))


def stats(store):
    js = [r["consistency"] for r in
          store.iter_events(types=["reconstruction_manifest"])
          if r.get("consistency")]
    print("store: %s" % json.dumps(store.stats()))
    if not js:
        print("no consistency records yet.")
        return
    print("reconstruction-stability experiment (F14 -> verdict F17):")
    print("  n=%d  mean jaccard=%.3f  mean weight diff on shared=%.2f"
          % (len(js), sum(c["jaccard"] for c in js) / len(js),
             sum(c["mean_weight_diff_on_shared"] for c in js) / len(js)))


def main():
    ap = argparse.ArgumentParser(description="ETHER offline consolidation")
    ap.add_argument("--age", type=float, metavar="FACTOR",
                    help="after consolidating, multiply all counters "
                         "by FACTOR (e.g. 0.5)")
    ap.add_argument("--stats", action="store_true",
                    help="print experiment read-out and exit")
    ap.add_argument("--aliases", action="store_true",
                    help="show the loaded alias table and exit")
    ap.add_argument("--reindex", action="store_true",
                    help="rebuild the event_keys index from event "
                         "payloads with canonicalization (run once "
                         "after upgrading)")
    ap.add_argument("--rebuild", action="store_true",
                    help="rebuild the sketch from manifests.jsonl alone "
                         "and exit (the sketch is a function of the log)")
    ap.add_argument("--dir", help="override ether dir")
    ap.add_argument("--migrate", action="store_true",
                    help="import a legacy manifests.jsonl into ether.db")
    args = ap.parse_args()

    if args.dir:
        os.environ["ETHER_DIR"] = args.dir
    base = ether_dir({"cwd": os.getcwd()})

    if args.migrate:
        migrate_jsonl(base)
        return
    with EtherStore(base) as store:
        if args.reindex:
            rows, n = store.reindex_keys()
            print("reindexed %d event(s), %d key row(s) -- index now "
                  "agrees with the sketch on key identity." % (rows, n))
            return
        if args.rebuild:
            rebuild(store, base)
            return
        if args.stats:
            stats(store)
            return
        if args.aliases:
            table = load_aliases(base)
            if not table:
                print("no alias table found.")
                return
            canon_keys = sorted({c for c, _ in table.values()})
            print("%d surface forms -> %d canonical concepts"
                  % (len(table), len(canon_keys)))
            for ck in canon_keys:
                forms = sorted(s for s, (c, sup) in table.items()
                               if c == ck and not sup and s != ck)
                dead = sorted(s for s, (c, sup) in table.items()
                              if c == ck and sup)
                line = "  %-22s <- %s" % (ck, ", ".join(forms) or "(none)")
                if dead:
                    line += "   [superseded: %s]" % ", ".join(dead)
                print(line)
            return
        consolidate(store, base)
        if args.age:
            age(store, args.age)


if __name__ == "__main__":
    main()
