---
description: Read the ETHER LTM (strict read-out -- store contents only)
---
Use the Bash tool to run exactly this, and nothing else:

    python "${CLAUDE_PLUGIN_ROOT}/scripts/ether_record.py" query "$ARGUMENTS"

Then follow the ANSWERING RULES that command prints. In summary:

* You may not report ANY result -- match or empty -- unless you ran the
  command above in this turn and saw its output. If you did not run it,
  say "I did not run the query"; never turn a failure to run into a
  claim about what memory holds.
* Report ONLY what the command returned. Its output is the entire
  permissible content of your reply.
* Add NOTHING of your own: no background knowledge, no inference, no
  interpretation, no elaboration, and no content from project memory
  files, MEMORY.md, CLAUDE.md, the transcript, or uploaded documents.
* Cite the printed `receipt #N`.
* Reproduce each memory's rung and weight exactly as shown. Never
  invent or upgrade a rung. Files that are NOT in the ETHER store have
  NO rung -- never describe them as declarations.
* If it reports no match, say the store returned no match, cite the
  receipt, and STOP. An empty memory is a real result; filling it in
  destroys the signal. You may offer to look elsewhere, but only as an
  offer, after reporting the empty result.
