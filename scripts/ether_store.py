#!/usr/bin/env python3
"""
ether_store.py -- SQLite storage for the LTM (diary F19).

Replaces the flat manifests.jsonl / ltm_sketch.json pair with a single
ether.db. Rationale: /query full-scanned the log on every read, there
were no indexes, hook and consolidator could interleave appends, and
nothing enforced the append-only discipline.

Design invariants, enforced by the schema itself:
  * events is INSERT-ONLY -- DELETE and UPDATE raise at the DB level
    (F11: never hard-delete; F19: the log is the source of truth).
  * event_keys is a flattened index of every deposited key, so
    retrieval is an indexed lookup rather than a scan.
  * captures is transient work state (the queue), not the log.
  * sketch is DISPOSABLE -- a materialized fold over the log,
    recomputable at any time by ether_consolidate.py --rebuild.

The diary stays markdown; it is a human document, not a store.
"""

import array
import hashlib
import json
import math
import os
import sqlite3
import time

# ---------------------------------------------------------------------
# Store location. Resolved at runtime, never patched into this file --
# a patched constant is silently reset by the next upgrade.
#
#   1. $ETHER_DIR                        explicit override, wins always
#   2. $CLAUDE_PLUGIN_OPTION_STORE_PATH  plugin userConfig, set via
#                                        /plugin config at enable time
#   3. ether.config.json                 {"store_path": "..."} looked up
#                                        beside this file, in the project
#                                        .claude/, and in ~/.claude/
#   4. ~/.claude/ether-ltm/store         stable default, survives updates
#   5. <project>/.claude/ether           fallback when no home dir
#
# $CLAUDE_PLUGIN_DATA is deliberately NOT in this chain: it is visible
# only to hook processes, so using it would split the hook and the CLI
# across two databases.
# ---------------------------------------------------------------------
CONFIG_NAME = "ether.config.json"

DB_NAME = "ether.db"
ALIAS_FILE = "concept_aliases.json"
_ALIAS_CACHE = {}

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          TEXT NOT NULL,
  type        TEXT NOT NULL,
  author      TEXT,
  provenance  TEXT,
  session_id  TEXT,
  capture_id  TEXT,
  payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_type    ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_ts      ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_capture ON events(capture_id);

CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT,
  'events are append-only: never hard-delete (F11); retract instead');
END;
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT,
  'events are append-only: amend with a new event, never overwrite');
END;

CREATE TABLE IF NOT EXISTS event_keys (
  event_id INTEGER NOT NULL REFERENCES events(id),
  key      TEXT NOT NULL,
  weight   REAL NOT NULL,
  role     TEXT
);
CREATE INDEX IF NOT EXISTS idx_event_keys_key ON event_keys(key);

CREATE TABLE IF NOT EXISTS captures (
  capture_id      TEXT PRIMARY KEY,
  ts              TEXT,
  session_id      TEXT,
  user_text       TEXT,
  assistant_text  TEXT,
  naive_keys      TEXT,
  consolidated_at TEXT
);

CREATE TABLE IF NOT EXISTS sketch (
  id       INTEGER PRIMARY KEY CHECK (id = 1),
  m        INTEGER NOT NULL,
  k        INTEGER NOT NULL,
  n        INTEGER NOT NULL,
  counters BLOB NOT NULL
);
"""


# --------------------------------------------------------------------
# alias table (shared by hook and consolidator so both canonicalize
# identically -- otherwise sketch != f(log); see F19 bug 2)
# --------------------------------------------------------------------
def load_aliases(base):
    if base in _ALIAS_CACHE:
        return _ALIAS_CACHE[base]
    spec = None
    for path in (os.path.join(base, ALIAS_FILE),
                 os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              ALIAS_FILE)):
        try:
            with open(path) as f:
                spec = json.load(f)
            break
        except (OSError, ValueError):
            continue
    table = {}
    if spec:
        for key, entry in spec.get("canonical", {}).items():
            table[key.lower()] = (key, False)
            table[entry.get("label", "").lower()] = (key, False)
            for a in entry.get("aliases", []):
                table[a.lower()] = (key, False)
            for s in entry.get("superseded_names", []):
                table[s.lower()] = (key, True)
        table.pop("", None)
    _ALIAS_CACHE[base] = table
    return table


def resolve(key, table):
    """Under-merge by default: unknown keys stay themselves rather than
    being guessed into a neighbour (splitting is recoverable;
    over-merging fuses two histories and is not)."""
    hit = table.get(key.strip().lower())
    return hit if hit else (key, False)


# --------------------------------------------------------------------
# the counting sketch -- a materialized fold, never the source of truth
# --------------------------------------------------------------------
class Sketch:
    M, K = 16384, 7

    def __init__(self, m=None, k=None, n=0, counters=None):
        self.m = m or self.M
        self.k = k or self.K
        self.n = n
        self.counters = counters if counters is not None \
            else array.array("d", [0.0]) * self.m

    def _idx(self, key):
        dg = hashlib.sha256(key.strip().lower().encode()).digest()
        h1 = int.from_bytes(dg[:8], "big")
        h2 = int.from_bytes(dg[8:16], "big") | 1
        return [(h1 + i * h2) % self.m for i in range(self.k)]

    def deposit(self, key, w=1.0):
        for i in self._idx(key):
            self.counters[i] = min(65535.0, self.counters[i] + w)
        self.n += 1

    def familiarity(self, key, reinforce=0.25):
        """min over k counters: collisions only inflate, so min is the
        honest estimate. Reinforcement is gated on min>0 -- queries
        amplify, never create (F12)."""
        idx = self._idx(key)
        score = min(self.counters[i] for i in idx)
        if reinforce and score > 0:
            for i in idx:
                self.counters[i] = min(65535.0, self.counters[i] + reinforce)
        return score

    def age(self, factor):
        for i in range(self.m):
            self.counters[i] *= factor

    def theoretical_fp_rate(self):
        if not self.n:
            return 0.0
        return (1 - math.exp(-self.k * self.n / self.m)) ** self.k


# --------------------------------------------------------------------
# the store
# --------------------------------------------------------------------
class EtherStore:
    def __init__(self, base):
        self.base = base
        os.makedirs(base, exist_ok=True)
        self.path = os.path.join(base, DB_NAME)
        self.db = sqlite3.connect(self.path, timeout=10.0)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()
        # Index and sketch must agree on key identity, or a key
        # deposited as "lidar extrinsic calibration" is unfindable under
        # the canonical form it was actually counted under.
        self.aliases = load_aliases(base)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.db.commit()
        self.close()

    # ---- the log (insert-only) ----
    def append(self, record, keys=None):
        """keys: iterable of (key, weight, role) flattened for indexed
        retrieval. The payload keeps the full record verbatim."""
        cur = self.db.execute(
            "INSERT INTO events (ts, type, author, provenance, "
            "session_id, capture_id, payload) VALUES (?,?,?,?,?,?,?)",
            (record.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%S"),
             record.get("type", "unknown"), record.get("author"),
             record.get("provenance"), record.get("session_id"),
             record.get("capture_id"),
             json.dumps(record, ensure_ascii=False)))
        eid = cur.lastrowid
        if keys:
            self.db.executemany(
                "INSERT INTO event_keys (event_id, key, weight, role) "
                "VALUES (?,?,?,?)",
                [(eid, resolve(k, self.aliases)[0], float(w), role)
                 for k, w, role in keys])
        self.db.commit()
        return eid

    def iter_events(self, types=None):
        """Chronological replay order (id is insertion order, which is
        the true causal order -- safer than ts, which has 1s
        granularity)."""
        if types:
            q = ("SELECT payload FROM events WHERE type IN (%s) ORDER BY id"
                 % ",".join("?" * len(types)))
            rows = self.db.execute(q, tuple(types))
        else:
            rows = self.db.execute("SELECT payload FROM events ORDER BY id")
        for r in rows:
            yield json.loads(r["payload"])

    def find_by_keys(self, keys, limit=8):
        """Indexed retrieval: events touching any of these keys, ranked
        by provenance then accumulated weight. Replaces the old
        full-file scan."""
        if not keys:
            return []
        rows = self.db.execute(
            "SELECT e.payload, e.type, e.provenance, "
            "       COUNT(*) AS hits, SUM(k.weight) AS w "
            "FROM event_keys k JOIN events e ON e.id = k.event_id "
            "WHERE k.key IN (%s) "
            "GROUP BY e.id "
            "ORDER BY CASE e.provenance WHEN 'declaration' THEN 4 "
            "         WHEN 'testimony' THEN 3 "
            "         WHEN 'extraction' THEN 2 ELSE 1 END DESC, "
            "         hits DESC, w DESC LIMIT ?"
            % ",".join("?" * len(keys)), tuple(keys) + (limit,))
        return [json.loads(r["payload"]) for r in rows]

    # ---- capture queue (transient work state) ----
    def add_capture(self, capture):
        """Idempotent: repeated Stop firings for one exchange dedupe."""
        cur = self.db.execute(
            "INSERT OR IGNORE INTO captures (capture_id, ts, session_id, "
            "user_text, assistant_text, naive_keys) VALUES (?,?,?,?,?,?)",
            (capture["capture_id"], capture["ts"],
             capture.get("session_id"), capture["user_text"],
             capture["assistant_text"],
             json.dumps(capture.get("naive_keys", []))))
        self.db.commit()
        return cur.rowcount > 0          # False => already captured

    def pending_captures(self, limit=50):
        rows = self.db.execute(
            "SELECT * FROM captures WHERE consolidated_at IS NULL "
            "ORDER BY ts LIMIT ?", (limit,))
        out = []
        for r in rows:
            d = dict(r)
            d["naive_keys"] = json.loads(d["naive_keys"] or "[]")
            out.append(d)
        return out

    def mark_consolidated(self, capture_id):
        self.db.execute(
            "UPDATE captures SET consolidated_at = ? WHERE capture_id = ?",
            (time.strftime("%Y-%m-%dT%H:%M:%S"), capture_id))
        self.db.commit()

    # ---- sketch (disposable materialized view) ----
    def load_sketch(self):
        row = self.db.execute("SELECT * FROM sketch WHERE id = 1").fetchone()
        if not row:
            return Sketch()
        counters = array.array("d")
        counters.frombytes(row["counters"])
        return Sketch(row["m"], row["k"], row["n"], counters)

    def save_sketch(self, sk):
        self.db.execute(
            "INSERT INTO sketch (id, m, k, n, counters) VALUES (1,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET m=?, k=?, n=?, counters=?",
            (sk.m, sk.k, sk.n, sk.counters.tobytes(),
             sk.m, sk.k, sk.n, sk.counters.tobytes()))
        self.db.commit()

    def reset_sketch(self):
        self.db.execute("DELETE FROM sketch")
        self.db.commit()
        return Sketch()

    def reindex_keys(self):
        """Rebuild event_keys from event payloads, canonicalizing as we
        go. Needed once after upgrading to canonicalize-on-write:
        rows written before the upgrade hold raw surface forms, so a
        key counted under 'lidar-calibration' is unfindable via the
        index entry 'lidar extrinsic calibration'. Touches only the
        derived index -- events themselves are never modified."""
        self.db.execute("DELETE FROM event_keys")
        n = rows = 0
        for r in self.db.execute("SELECT id, payload FROM events "
                                 "ORDER BY id"):
            rec = json.loads(r["payload"])
            ks = keys_of(rec)
            if not ks:
                continue
            self.db.executemany(
                "INSERT INTO event_keys (event_id, key, weight, role) "
                "VALUES (?,?,?,?)",
                [(r["id"], resolve(k, self.aliases)[0], float(w), role)
                 for k, w, role in ks])
            n += len(ks)
            rows += 1
        self.db.commit()
        return rows, n

    def stats(self):
        c = self.db.execute(
            "SELECT type, COUNT(*) n FROM events GROUP BY type").fetchall()
        pend = self.db.execute(
            "SELECT COUNT(*) n FROM captures WHERE consolidated_at IS NULL"
        ).fetchone()["n"]
        return {"events": {r["type"]: r["n"] for r in c}, "pending": pend}


def _config_store_path():
    """Look for ether.config.json beside this file, in the project's
    .claude/, and in ~/.claude/. First hit wins."""
    here = os.path.dirname(os.path.abspath(__file__))
    project = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    home = os.path.expanduser("~")
    for d in (os.path.join(project, ".claude"), project,
              os.path.join(home, ".claude", "ether-ltm"),
              os.path.join(home, ".claude"),
              here, os.path.join(here, "..")):
        p = os.path.join(d, CONFIG_NAME)
        try:
            with open(p, encoding="utf-8") as f:
                val = json.load(f).get("store_path")
            if val:
                return os.path.expanduser(os.path.expandvars(val))
        except (OSError, ValueError):
            continue
    return None


def resolve_store_dir(payload=None):
    """Return (path, source) so tooling can report WHERE it looked -- a
    store in an unexpected place is indistinguishable from an empty
    one, which is the failure mode this project keeps rediscovering.

    Note on plugin environment: CLAUDE_PLUGIN_OPTION_* and
    CLAUDE_PLUGIN_DATA are exported to HOOK PROCESSES ONLY, not to Bash
    tool calls. Resolving against them directly would let the hook and
    the CLI open different databases. So the plugin's SessionStart hook
    persists them into ether.config.json, and everything else reads
    that file.
    """
    env = os.environ.get("ETHER_DIR")
    if env:
        return os.path.expanduser(env), "$ETHER_DIR"
    opt = os.environ.get("CLAUDE_PLUGIN_OPTION_STORE_PATH")
    if opt:
        return os.path.expanduser(opt), "plugin config (hook env)"
    cfg = _config_store_path()
    if cfg:
        return cfg, CONFIG_NAME
    home = os.path.expanduser("~")
    if home and home != "~":
        return (os.path.join(home, ".claude", "ether-ltm", "store"),
                "~/.claude/ether-ltm (default)")
    root = (os.environ.get("CLAUDE_PROJECT_DIR")
            or (payload or {}).get("cwd") or ".")
    return os.path.join(root, ".claude", "ether"), "project default"


def ether_dir(payload=None):
    base, _ = resolve_store_dir(payload)
    os.makedirs(base, exist_ok=True)
    return base


def migrate_jsonl(base):
    """One-shot import of a legacy manifests.jsonl into ether.db."""
    src = os.path.join(base, "manifests.jsonl")
    if not os.path.exists(src):
        print("no manifests.jsonl to migrate.")
        return 0
    n = 0
    with EtherStore(base) as store:
        with open(src) as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                store.append(rec, keys=keys_of(rec))
                n += 1
    os.replace(src, src + ".migrated")
    print("migrated %d records into %s (source renamed .migrated)"
          % (n, DB_NAME))
    return n


def keys_of(record):
    """Flatten a record's deposited keys for the event_keys index."""
    t = record.get("type")
    out = []
    if t == "capture":
        wf = float(record.get("weight_factor", 0.5))
        out = [(e["key"], wf * float(e.get("w", 1.0)), "naive")
               for e in record.get("naive_keys", [])]
    elif t == "user_manifest":
        w = float(record.get("weight", 1.0))
        out = [(e["key"], w, "entity")
               for e in record.get("entity_keys", [])]
    elif t == "reconstruction_manifest":
        m0 = (record.get("manifests") or [{}])[0]
        out = [(e["key"], float(e.get("w", 1.0)), "entity")
               for e in m0.get("entity_keys", [])]
        if m0.get("episode_gist"):
            out.append((m0["episode_gist"], 1.0, "gist"))
    elif t == "query":
        out = [(k, 0.0, "query") for k in record.get("keys", [])]
    return out


if __name__ == "__main__":
    import sys
    base = ether_dir({"cwd": os.getcwd()})
    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        migrate_jsonl(base)
    else:
        with EtherStore(base) as s:
            print(json.dumps(s.stats(), indent=2))
