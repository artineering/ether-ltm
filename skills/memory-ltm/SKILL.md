---
name: memory-ltm
description: Provenance rules for the ETHER long-term memory. Consult this whenever recording, recalling, or reporting on memory — including any time you are about to say something was remembered, stored, pinned, or that memory holds nothing. Also use before answering from MEMORY.md or project memory files, since those are NOT the ETHER store.
---

# ETHER memory — provenance rules

These rules exist because of five recorded incidents in which the
memory reported things that had not happened: writes that never landed,
answers sourced from elsewhere and labelled as remembered, provenance
rungs invented wholesale, and empty results asserted without a lookup.
Each was caused by reporting rather than checking.

**The one-line version:** every claim about memory must be sourced from
memory — including claims about having written to it, and including
claims that it is empty.

## What counts as "the memory"

The ETHER LTM is **only** the SQLite store reached through
`scripts/ether_record.py` or the plugin's hook.

These are **NOT** the ETHER LTM. Content from them must never be
presented as remembered:

- `MEMORY.md` and project memory markdown
- `CLAUDE.md`, rules files, and other instructions
- the current transcript
- uploaded or read documents
- your own knowledge or inference

Such content is often useful. Offer it — but label it as coming from
somewhere other than the ETHER store.

## Never invent provenance

The ladder, ascending in authority:

| Rung | Who | Nature |
|---|---|---|
| `readout` | machine | mechanical signal; corroborates, doesn't compete |
| `reconstruction` | agent | self-reported activation; confabulation-prone |
| `extraction` | agent | from an external artifact; **source anchor required**, defeasible |
| `testimony` | user | first-person report; privileged, defeasible |
| `declaration` | user | performative stipulation; wins conflicts |

- Report a memory's rung **exactly** as the store printed it.
- Content not in the store has **no rung**. Never call a markdown file,
  a document, or an inference a "declaration."
- Never upgrade a rung. An `extraction` is not a `declaration`.

## Reads

- Use `/query`. Report **only** what it printed; its output is the
  entire permissible content of the reply.
- Cite the printed `receipt #N`. **An answer with no receipt did not
  come from the ETHER store** and must say so. This applies to empty
  answers too: "no match (receipt #N)" is a result; "no match" without
  a receipt is a guess.
- You may not report any result — match or empty — without having run
  the command in this turn. If you did not run it, say exactly that.
- If the store returns nothing, say so and stop. An empty memory is a
  real and useful result; filling it in destroys the signal. Offering
  to look elsewhere is allowed only afterwards, and only as an offer.
- A broken read path and an empty store look identical from outside.
  Never conflate them.

## Writes

- The `UserPromptSubmit` hook fires **only on prompts a human types**.
  Slash commands route through the skill loader and bypass it, so
  "invoking `/remember`" yourself records nothing. Always go through
  `scripts/ether_record.py`.
- Agents write at `extraction` (with `--source`) or `note`.
  Declaration-rung verbs are the principal's authority and are refused
  without `--i-am-the-principal`.
- **A write is not recorded until it has been read back.** Report only
  the event id the tool printed. If the command failed or exited
  non-zero, say the write FAILED. Never acknowledge a write you did not
  see confirmed.
- After bulk ingestion run `ether_record.py audit --session <name>` and
  report its output.

## Nothing is ever deleted

The `events` table is insert-only, enforced by database triggers.
Corrections supersede via `/retract`; both versions stay visible. Never
propose deleting memory — propose retracting it.

## When something looks wrong

Run `/memory-status` (the doctor). It checks each layer independently
and proves the read path with a live query and receipt. Report what it
printed rather than diagnosing from intuition.
