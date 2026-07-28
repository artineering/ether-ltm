#!/usr/bin/env python3
"""
ether_inspect.py -- read-only snapshot of the LTM store.

  python3 ether_inspect.py                  # full snapshot
  python3 ether_inspect.py --concepts 30    # top concepts by familiarity
  python3 ether_inspect.py --recent 10      # last N events
  python3 ether_inspect.py --key ether-tier # everything about one key
  python3 ether_inspect.py --sql "SELECT ..."  # raw read-only query

STRICTLY READ-ONLY. In particular, familiarity is sampled with
reinforce=0: inspecting memory must not strengthen it, or the act of
looking would inflate exactly what it reports (cf. F18's silent-read
constraint on the encoding snapshot).

Note on enumeration: the sketch is content-free and CANNOT be listed --
it only answers questions about keys you already hold. The key names
below come from the event_keys index, i.e. from the log. The log knows
what was deposited; the ether only knows how loudly it rings.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ether_store import EtherStore, ether_dir  # noqa: E402


def hr(title):
    print("\n" + title)
    print("-" * len(title))


def summary(store):
    hr("store")
    size = os.path.getsize(store.path) / 1024.0
    print("  %s  (%.1f KiB)" % (store.path, size))
    row = store.db.execute(
        "SELECT MIN(ts) a, MAX(ts) b, COUNT(*) n FROM events").fetchone()
    print("  %d events   %s .. %s" % (row["n"], row["a"] or "-",
                                      row["b"] or "-"))
    for r in store.db.execute(
            "SELECT type, COUNT(*) n FROM events GROUP BY type "
            "ORDER BY n DESC"):
        print("    %-26s %d" % (r["type"], r["n"]))
    p = store.db.execute(
        "SELECT COUNT(*) t, SUM(consolidated_at IS NULL) pend "
        "FROM captures").fetchone()
    print("  captures: %d total, %d pending consolidation"
          % (p["t"] or 0, p["pend"] or 0))
    sk = store.load_sketch()
    nz = sum(1 for c in sk.counters if c > 0)
    print("  sketch:   m=%d k=%d deposits=%d  cells used=%d (%.1f%%)  "
          "est. fp=%.2f%%"
          % (sk.m, sk.k, sk.n, nz, 100.0 * nz / sk.m,
             100 * sk.theoretical_fp_rate()))


def declarations(store):
    hr("user memory (declarations & testimony, newest first)")
    rows = store.db.execute(
        "SELECT payload FROM events WHERE type='user_manifest' "
        "ORDER BY id DESC LIMIT 25").fetchall()
    if not rows:
        print("  (none)")
        return
    for r in rows:
        d = json.loads(r["payload"])
        print("  %s  %-9s %-11s w=%-4s%s %s"
              % (d["ts"][:16], d["verb"], d["kind"], d["weight"],
                 " DEFEAS" if d.get("defeasible") else "       ",
                 d["text"][:70]))


def concepts(store, limit):
    hr("top concepts by familiarity (keys from the log, scores from "
       "the sketch)")
    keys = [r["key"] for r in store.db.execute(
        "SELECT key, COUNT(*) n FROM event_keys WHERE role != 'query' "
        "GROUP BY key ORDER BY n DESC LIMIT 400")]
    sk = store.load_sketch()
    scored = sorted(((sk.familiarity(k, reinforce=0), k) for k in keys),
                    reverse=True)[:limit]
    if not scored:
        print("  (none)")
        return
    for score, k in scored:
        n = store.db.execute(
            "SELECT COUNT(DISTINCT event_id) n FROM event_keys "
            "WHERE key = ?", (k,)).fetchone()["n"]
        print("  %8.2f  %-34s  in %d event(s)" % (score, k[:34], n))


def episodes(store, limit):
    hr("recent episode gists")
    rows = store.db.execute(
        "SELECT payload FROM events WHERE type='reconstruction_manifest' "
        "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    if not rows:
        print("  (none yet -- run ether_consolidate.py)")
        return
    for r in rows:
        d = json.loads(r["payload"])
        m0 = (d.get("manifests") or [{}])[0]
        cons = d.get("consistency", {})
        print("  %s  jaccard=%-5s %s"
              % (d["ts"][:16], cons.get("jaccard", "-"),
                 (m0.get("episode_gist") or "")[:70]))


def key_detail(store, key):
    hr("key: %s" % key)
    sk = store.load_sketch()
    print("  familiarity (silent read): %.2f" % sk.familiarity(key,
                                                               reinforce=0))
    rows = store.db.execute(
        "SELECT e.ts, e.type, e.provenance, SUM(k.weight) weight, "
        "       COUNT(*) forms, e.payload "
        "FROM event_keys k JOIN events e ON e.id=k.event_id "
        "WHERE k.key = ? GROUP BY e.id ORDER BY e.id DESC LIMIT 20",
        (key,)).fetchall()
    if not rows:
        print("  no log entries. If familiarity is >0, the bell rings "
              "with nothing behind it (collision or aliasing).")
        return
    print("  %d log entrie(s):" % len(rows))
    for r in rows:
        d = json.loads(r["payload"])
        text = d.get("text") or (
            (d.get("manifests") or [{}])[0].get("episode_gist")) or ""
        forms = ("x%d forms " % r["forms"]) if r["forms"] > 1 else ""
        print("    %s  %-24s %-14s w=%-5s %s%s"
              % (r["ts"][:16], r["type"], r["provenance"] or "-",
                 round(r["weight"], 2), forms, text[:40]))


def experiment(store):
    hr("reconstruction-stability experiment (F14 -> F17)")
    js = [json.loads(r["payload"]).get("consistency") for r in
          store.db.execute("SELECT payload FROM events WHERE "
                           "type='reconstruction_manifest'")]
    js = [c for c in js if c]
    if not js:
        print("  no paired encodes yet (needs ETHER_ENCODES>=2)")
        return
    print("  n=%d  mean jaccard=%.3f  mean weight diff=%.2f"
          % (len(js), sum(c["jaccard"] for c in js) / len(js),
             sum(c["mean_weight_diff_on_shared"] for c in js) / len(js)))
    worst = min(js, key=lambda c: c["jaccard"])
    print("  least stable encode: jaccard=%.2f  disagreed on: %s"
          % (worst["jaccard"],
             ", ".join((worst["only_first"] + worst["only_second"])[:6])
             or "(none)"))


def main():
    ap = argparse.ArgumentParser(description="read-only LTM snapshot")
    ap.add_argument("--dir")
    ap.add_argument("--concepts", type=int, default=15)
    ap.add_argument("--recent", type=int, default=5)
    ap.add_argument("--key")
    ap.add_argument("--sql", help="raw read-only SQL")
    args = ap.parse_args()
    if args.dir:
        os.environ["ETHER_DIR"] = args.dir
    base = ether_dir({"cwd": os.getcwd()})

    with EtherStore(base) as store:
        if args.sql:
            low = args.sql.strip().lower()
            if not low.startswith(("select", "with", "pragma", "explain")):
                sys.exit("read-only: SELECT / WITH / PRAGMA only")
            for row in store.db.execute(args.sql):
                print(" | ".join(str(v)[:60] for v in tuple(row)))
            return
        if args.key:
            key_detail(store, args.key)
            return
        summary(store)
        declarations(store)
        concepts(store, args.concepts)
        episodes(store, args.recent)
        experiment(store)


if __name__ == "__main__":
    main()
