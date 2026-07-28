#!/usr/bin/env python3
"""
ether_hook.py -- Claude Code hook: the first working seed of the shared LTM.

Diary refs: F13 (deposit = firing), F14 (manifests are reconstructions),
F15 (provenance ladder: readout > declaration > testimony > reconstruction
in authority; the reverse in mechanistic honesty).

Registered for TWO hook events (dispatch on hook_event_name):

  UserPromptSubmit -- detects granular user memory verbs and records them
                      at their provenance rung, then injects a confirmation
                      into Claude's context:
        /remember <text>   declaration / pin         (w=5)
        /declare  <text>   declaration / ruling      (w=8)
        /assume   <text>   declaration / assumption  (w=4, defeasible)
        /note     <text>   testimony   / note        (w=2)
        /retract  <text>   declaration / retraction  (supersede, never delete)
        /park     <text>   declaration / parked      (seen and set aside)
      Both "/verb text" and "verb: text" forms are accepted, as is the
      "ETHER-COMMAND verb:" marker emitted by the companion slash commands.

  Stop -- extracts the last atomic interaction (last real user prompt +
          assistant reply) from the transcript, runs the encoder pass
          ETHER_ENCODES times (default 2) to produce reconstruction
          manifests, logs their agreement (the F14 consistency
          experiment, running continuously), and deposits the keys.

Storage (under $CLAUDE_PROJECT_DIR/.claude/ether/ by default):
  manifests.jsonl  -- append-only log of every entry, with provenance
  ltm_sketch.json  -- persisted counting sketch (F12 semantics:
                      deposits increment fully; queries would reinforce
                      fractionally, gated min>0 -- amplify, never create)
  error.log        -- failures (the hook itself never blocks the session)

Env:
  ANTHROPIC_API_KEY  required for real encoding (else falls back to dry run)
  ETHER_MODEL        default "claude-haiku-4-5"
  ETHER_ENCODES      default "2" (2 => consistency experiment on every stop)
  ETHER_DIR          override storage dir
  ETHER_DRY_RUN=1    force keyword-fallback encoder (no API call)

Fail-safe: every path exits 0. A memory that can wedge the organism is
worse than no memory.
"""

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ether_store import (EtherStore, ether_dir, keys_of,  # noqa: E402
                         load_aliases, resolve)

# --------------------------------------------------------------------------
# user memory verbs -> (provenance, kind, default weight, defeasible)
# --------------------------------------------------------------------------
VERBS = {
    "remember": ("declaration", "pin",        5.0, False),
    "declare":  ("declaration", "ruling",     8.0, False),
    "assume":   ("declaration", "assumption", 4.0, True),
    "note":     ("testimony",   "note",       2.0, True),
    "retract":  ("declaration", "retraction", 8.0, False),
    "park":     ("declaration", "parked",     6.0, False),
    # Agent-authored content extracted from an external artifact.
    # NOT a declaration -- the agent is not the principal -- but above
    # ordinary reconstruction because it has an anchor you can re-check.
    "extract":  ("extraction",  "source-fact", 3.0, True),
}
# /query is a READ verb: no provenance rung, handled separately.
ALL_COMMANDS = list(VERBS) + ["query"]
VERB_RE = re.compile(
    r"^\s*(?:ETHER-COMMAND\s+)?/?(%s)\b[:\s]\s*(.+)$" % "|".join(ALL_COMMANDS),
    re.IGNORECASE | re.DOTALL,
)

STOPWORDS = set("""a an and are as at be but by for from has have i if in is
it its me my of on or our so that the their this to was we what when which
with you your""".split())

def log_error(base, err):
    try:
        with open(os.path.join(base, "error.log"), "a") as f:
            f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), err))
    except OSError:
        pass


def append(store, record):
    """Append to the log of record. Keys are flattened into the
    event_keys index so retrieval is a lookup, not a scan."""
    return store.append(record, keys=keys_of(record))


def canon(key):
    return re.sub(r"\s+", " ", key.strip().lower())


def naive_keys(text, top=8):
    """Dry-run fallback encoder: frequency of non-stopword tokens."""
    counts = {}
    for tok in re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", text.lower()):
        if tok not in STOPWORDS:
            counts[tok] = counts.get(tok, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:top]
    return [{"key": k, "w": float(w)} for k, w in ranked]


# --------------------------------------------------------------------------
# transcript parsing (Stop event)
# --------------------------------------------------------------------------
def text_of(content):
    if isinstance(content, str):
        return content
    parts = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
    return "\n".join(parts)


def last_exchange(transcript_path, max_chars=6000):
    """Return (user_text, assistant_text) for the final atomic interaction."""
    turns = []
    with open(os.path.expanduser(transcript_path)) as f:
        for line in f:
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("type") not in ("user", "assistant"):
                continue
            msg = obj.get("message", {})
            content = msg.get("content")
            # skip tool_result-only "user" entries: not a human prompt
            if obj["type"] == "user" and isinstance(content, list):
                if all(isinstance(b, dict) and b.get("type") == "tool_result"
                       for b in content):
                    continue
            txt = text_of(content)
            if txt.strip():
                turns.append((obj["type"], txt))
    last_user = None
    for i in range(len(turns) - 1, -1, -1):
        if turns[i][0] == "user":
            last_user = i
            break
    if last_user is None:
        return None, None
    user_text = turns[last_user][1]
    assistant_text = "\n".join(t for r, t in turns[last_user + 1:]
                               if r == "assistant")
    return user_text[:max_chars], assistant_text[:max_chars]


# --------------------------------------------------------------------------
# encoder pass (reconstruction manifests)
# --------------------------------------------------------------------------
ENCODER_SYSTEM = """You are the deposit-manifest encoder of a long-term \
memory system. Given one atomic interaction (user message + assistant \
reply), emit ONLY a JSON object, no markdown fences, no commentary:
{"episode_gist": "<one sentence>",
 "entity_keys": [{"key": "<canonical-noun-phrase>", "w": <0.1-8>}, ...],
 "pair_keys": [{"key": "<keyA x keyB>", "w": <0.1-8>}, ...],
 "novelty": ["<anything new to this project>", ...]}
Weights reflect attentional centrality: mentioned-in-passing ~0.1-0.5, \
discussed ~1-3, the actual focus of joint work ~4-8. 4-10 entity keys, \
0-4 pair keys. Canonicalize keys: lowercase, singular, hyphenated."""


def call_encoder(user_text, assistant_text):
    body = json.dumps({
        "model": os.environ.get("ETHER_MODEL", "claude-haiku-4-5"),
        "max_tokens": 1000,
        "system": ENCODER_SYSTEM,
        "messages": [{"role": "user", "content":
                      "USER MESSAGE:\n%s\n\nASSISTANT REPLY:\n%s"
                      % (user_text, assistant_text)}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"content-type": "application/json",
                 "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read())
    text = "".join(b.get("text", "") for b in data.get("content", [])
                   if b.get("type") == "text")
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(),
                  flags=re.MULTILINE).strip()
    return json.loads(text)


def call_encoder_cli(user_text, assistant_text):
    """Encoder via headless Claude Code (`claude -p`): inherits whatever
    auth the user's Claude Code already has (corporate OAuth, Bedrock,
    Vertex) -- no ANTHROPIC_API_KEY needed. `--bare` skips hook/MCP
    auto-discovery so this inner call cannot re-fire our own hooks;
    ETHER_INNER guards the same on versions predating --bare."""
    prompt = (ENCODER_SYSTEM + "\n\nUSER MESSAGE:\n%s\n\nASSISTANT REPLY:\n%s"
              % (user_text, assistant_text))
    env = dict(os.environ, ETHER_INNER="1")
    cmd = ["claude", "-p", "--output-format", "json",
           "--model", os.environ.get("ETHER_MODEL", "haiku"),
           "--max-turns", "1"]
    if os.environ.get("ETHER_NO_BARE") != "1":
        cmd.insert(2, "--bare")
    try:
        out = subprocess.run(cmd, input=prompt, env=env, timeout=50,
                             capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError:
        if os.environ.get("ETHER_NO_BARE") != "1":
            # older CLI without --bare: retry once without it
            os.environ["ETHER_NO_BARE"] = "1"
            return call_encoder_cli(user_text, assistant_text)
        raise
    result = json.loads(out.stdout).get("result", "")
    result = re.sub(r"^```(?:json)?|```$", "", result.strip(),
                    flags=re.MULTILINE).strip()
    manifest = json.loads(result)
    manifest["encoder"] = "claude-cli"
    return manifest


def encode(user_text, assistant_text):
    """Priority: forced dry-run > direct API (individual key) >
    headless Claude Code (corporate auth) > keyword fallback."""
    if os.environ.get("ETHER_DRY_RUN") != "1":
        if os.environ.get("ANTHROPIC_API_KEY"):
            return call_encoder(user_text, assistant_text)
        if shutil.which("claude"):
            return call_encoder_cli(user_text, assistant_text)
    return {"episode_gist": "dry-run keyword fallback",
            "entity_keys": naive_keys(user_text + " " + assistant_text),
            "pair_keys": [], "novelty": [],
            "encoder": "naive-fallback"}


def consistency(m1, m2):
    """The F14 experiment: how stable are reconstructions?"""
    k1 = {canon(e["key"]): e["w"] for e in m1.get("entity_keys", [])}
    k2 = {canon(e["key"]): e["w"] for e in m2.get("entity_keys", [])}
    shared = set(k1) & set(k2)
    union = set(k1) | set(k2)
    jac = len(shared) / len(union) if union else 1.0
    wdiff = ([abs(k1[k] - k2[k]) for k in shared] or [0.0])
    return {"jaccard": round(jac, 3),
            "shared": sorted(shared),
            "only_first": sorted(set(k1) - shared),
            "only_second": sorted(set(k2) - shared),
            "mean_weight_diff_on_shared": round(sum(wdiff) / len(wdiff), 2)}


# --------------------------------------------------------------------------
# event handlers
# --------------------------------------------------------------------------
def handle_query(store, base, payload, text):
    """Read path. Two tiers (F12: the sketch says how loud, the log says
    what and why), reinforcement gated on min>0, and the query itself
    logged -- query traffic is the behavioural record that lets stale
    declarations be challenged (F15)."""
    aliases = load_aliases(base)
    qkeys = [resolve(e["key"], aliases)[0]
             for e in naive_keys(text, top=6)]
    sk = store.load_sketch()
    fam = {k: round(sk.familiarity(k, reinforce=0.25), 2) for k in qkeys}
    store.save_sketch(sk)

    top = []
    for r in store.find_by_keys(qkeys, limit=5):     # indexed, not a scan
        if r.get("type") == "user_manifest":
            top.append("[%s/%s w=%s%s] %s"
                       % (r["provenance"], r["kind"], r["weight"],
                          " DEFEASIBLE" if r.get("defeasible") else "",
                          r.get("text", "")))
        elif r.get("type") == "reconstruction_manifest":
            m0 = (r.get("manifests") or [{}])[0]
            top.append("[reconstruction] %s"
                       % m0.get("episode_gist", ""))

    eid = append(store, {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                         "session_id": payload.get("session_id"),
                         "type": "query", "author": "user",
                         "provenance": "readout", "text": text,
                         "keys": qkeys, "familiarity": fam})

    # The receipt is a verifiable token: an answer that cites it came
    # from this store, and an answer that cannot cite it did not (F21).
    ctx = ["[LTM QUERY] receipt #%d -- \"%s\"" % (eid, text),
           "Familiarity (min-estimate; reinforced 0.25x on read): "
           + ", ".join("%s=%s" % kv for kv in fam.items())]
    if top:
        ctx.append("Matching memories in the ETHER store "
                   "(declaration > testimony > extraction > "
                   "reconstruction):")
        ctx.extend("  - " + t for t in top)
        ctx.append("")
        ctx.append("ANSWERING RULES -- provenance rules, not style "
                   "preferences. This is a memory read-out, not a "
                   "question to answer helpfully:")
        ctx.append("1. Report ONLY what is listed above. The listed "
                   "memories are the entire permissible content of "
                   "your reply.")
        ctx.append("2. Add NOTHING of your own: no background "
                   "knowledge, no inference, no interpretation, no "
                   "elaboration, no content from project memory files, "
                   "CLAUDE.md, the transcript, or uploaded documents. "
                   "If it is not in the list above, it does not go in "
                   "the reply.")
        ctx.append("3. Cite receipt #%d so the user can verify the "
                   "answer came from the ETHER store." % eid)
        ctx.append("4. Reproduce each memory's rung and weight exactly "
                   "as bracketed above. Never invent or upgrade a "
                   "rung.")
        ctx.append("5. If the listed memories do not actually address "
                   "the question, say that plainly -- do not fill the "
                   "gap. The user asked what memory holds, not what "
                   "you know.")
    else:
        ctx.append("")
        ctx.append("THE ETHER STORE HAS NOTHING ON THIS. Familiarity "
                   "~0 means definitely never recorded -- the sketch "
                   "has no false negatives.")
        ctx.append("ANSWERING RULES -- this is a memory read-out:")
        ctx.append("1. Reply that the ETHER store returned no match, "
                   "citing receipt #%d. That is the complete answer."
                   % eid)
        ctx.append("2. STOP THERE. Do not answer the question from "
                   "project memory files, CLAUDE.md, the transcript, "
                   "uploaded documents, or your own knowledge. Do not "
                   "offer a substitute answer, a guess, or a summary "
                   "of what you think the user meant. An empty memory "
                   "is a real and useful result; filling it in "
                   "destroys the signal.")
        ctx.append("3. You may offer to search elsewhere, but only as "
                   "an offer, and only after reporting the empty "
                   "result.")
        ctx.append("4. A nonzero familiarity with no listed match "
                   "means the bell rings with nothing behind it "
                   "(collision or aliasing) -- report that as such.")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": "\n".join(ctx)}}))


def handle_prompt(store, base, payload):
    m = VERB_RE.match(payload.get("prompt", ""))
    if not m:
        return                                   # ordinary prompt
    verb, text = m.group(1).lower(), m.group(2).strip()
    # Slash-command expansion appends acknowledgement scaffolding after
    # a blank line; the declaration is the first paragraph only.
    text = text.split("\n\n")[0].strip()
    if verb == "query":
        handle_query(store, base, payload, text)
        return
    provenance, kind, weight, defeasible = VERBS[verb]
    aliases = load_aliases(base)
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "session_id": payload.get("session_id"),
             "type": "user_manifest", "author": "user", "verb": verb,
             "provenance": provenance, "kind": kind, "weight": weight,
             "defeasible": defeasible, "text": text,
             "entity_keys": [{"key": resolve(e["key"], aliases)[0],
                              "w": e["w"]}
                             for e in naive_keys(text, top=5)]}
    append(store, entry)
    sk = store.load_sketch()
    for e in entry["entity_keys"]:
        sk.deposit(e["key"], weight)             # user rank sets weight
    store.save_sketch(sk)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext":
            '[LTM] Recorded %s (%s/%s, w=%s%s): "%s". Acknowledge '
            "briefly; honor it for the rest of the session."
            % (verb, provenance, kind, weight,
               ", defeasible" if defeasible else "", text)}}))


def handle_stop(store, base, payload):
    """CAPTURE ONLY -- no model calls in the hook path, ever (F16).
    Fast weak trace now; real encoding happens offline in batch via
    ether_consolidate.py (the sleep job)."""
    user_text, assistant_text = last_exchange(payload["transcript_path"])
    if not user_text or VERB_RE.match(user_text):
        return                       # verb turns recorded at higher rank
    capture_id = hashlib.sha256(
        ((payload.get("session_id") or "") + "\x00" + user_text[:2000]
         + "\x00" + assistant_text[:2000]).encode()).hexdigest()[:16]
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    aliases = load_aliases(base)
    keys = [{"key": resolve(e["key"], aliases)[0], "w": e["w"]}
            for e in naive_keys(user_text + " " + assistant_text)]
    if not store.add_capture({"capture_id": capture_id, "ts": ts,
                              "session_id": payload.get("session_id"),
                              "user_text": user_text,
                              "assistant_text": assistant_text,
                              "naive_keys": keys}):
        return                       # already captured: idempotent
    # The weak deposit is logged too, or the sketch stops being a pure
    # function of the log (F19; caught by --rebuild).
    append(store, {"ts": ts, "session_id": payload.get("session_id"),
                   "capture_id": capture_id, "type": "capture",
                   "author": "system", "provenance": "readout",
                   "note": "fast weak trace; superseded but not erased "
                           "by consolidation (F16)",
                   "weight_factor": 0.5, "naive_keys": keys})
    sk = store.load_sketch()
    for e in keys:                               # weak hippocampal trace
        sk.deposit(e["key"], 0.5 * e["w"])
    store.save_sketch(sk)


def main():
    if os.environ.get("ETHER_INNER") == "1":
        sys.exit(0)  # we are inside our own encoder call: do nothing
    payload = json.load(sys.stdin)
    base = ether_dir(payload)
    try:
        event = payload.get("hook_event_name")
        with EtherStore(base) as store:
            if event == "UserPromptSubmit":
                handle_prompt(store, base, payload)
            elif event == "Stop":
                handle_stop(store, base, payload)
    except Exception as err:                 # noqa: BLE001  fail-safe
        log_error(base, repr(err))
    sys.exit(0)


if __name__ == "__main__":
    main()
