# Dispatch discipline

How to write a subagent prompt so the round does not cost four times what it
should. The rules are short; the arithmetic behind them is here because the
rules look arbitrary without it.

## The cost model, measured

Three real subagents from 2026-09-09, read from the `usage` fields of their
transcripts:

| agent | calls | total context | entry -> final | second half |
|---|---:|---:|---:|---:|
| F34a (build the site table) | 79 | 8,627,995 | 66,734 -> 152,051 | 61% |
| F35 (falsify the DD claim) | 116 | 15,886,184 | 67,789 -> 203,829 | 63% |
| F42 (replay a known-wrong card) | 82 | 7,903,794 | 65,989 -> 119,668 | 56% |

The bill is not the number of calls. **Every tool result stays in context and is
re-sent on every later call**, so the cost is an integral:

    total ≈ N × (entry + final) / 2

Two independent variables: the number of calls **N**, and how fast the context
**grows**. Both matter more than anything inside a single call.

Consequences, computed against F35's real numbers:

| change | arithmetic | effect |
|---|---|---|
| halve the calls (batch into one script per hypothesis) | 58 × (68 + 204)/2 = 7.9M | **−50%** |
| split one long agent into two phases, each starting fresh | growth-dominated cost ≈ c·N²/2, so k phases divide by k | **−50%** |
| halve the growth (aggregate, do not dump) | 116 × (68 + 136)/2 = 11.8M | **−26%** |
| move a 20k-token read from call 10 to call 90 | rides 90 calls (1.8M) vs 10 (200k) | **9× on that result** |
| trim the fixed prefix | 67.8k × 116 = 7.9M is entry alone — **half the bill** | −13% |

The fourth row is the one nobody guesses: it reduces no work at all, only the
order. Reading something early is nine times more expensive than reading the
same thing late.

## Rules for the dispatcher

1. **One hypothesis, one script.** If the task needs more than a handful of
   probes, have the subagent write a script, run it once, and commit it. This
   project already works that way for verification (`measure_*.sh`,
   `evidence_*.sh`, `dd_sites.sh`) but exploration is still done with 20-40
   interactive greps, which is where the money goes. A committed script is also
   the only form of this work that the next round can reuse.
2. **Give exact paths, and line numbers when you have them.** `cards.tsv` holds
   each card's criterion and negative control. A subagent told to "explore the
   tree" spends 10-20 calls discovering what the prompt could have stated in one
   line — and those calls are the expensive early ones.
3. **Split by phase, not by hope.** Two 58-call agents cost half of one
   116-call agent for the same work. Split where the artifacts change:
   measure in one, decide in another.
4. **Say what NOT to read.** Name the big artifacts that must be aggregated
   rather than printed. Our verification products are 400KB-900KB; one of them
   in context is worse than ten greps.
5. **Demand a strict return format.** Already contract law, and it protects the
   parent rather than the child, so state it anyway.

## Rules for the subagent (put these in the prompt)

- **Never print a tool output you only need a number from.** Pipe through
  `wc -l`, `grep -c`, `awk`, or a small python aggregation, and print the number
  and the names. F35 reported `2 of 4328 leaves` — that is the shape to copy.
- **Bound every read.** `sed -n 'a,bp'` with a real range; `tail` for the end of
  a file. `Read` does not take a negative offset — asking for `offset=-8` reads
  from the top and can drop 25k tokens of log into context, where it is then
  re-sent on every later call. (Measured today, in the main loop, by me.)
- **Reuse artifacts, never regenerate them.** `out_pm/` is already built.
  Regenerating costs a build and produces megabytes of output.
- **Do the largest reads last.** Establish what you need with cheap probes
  first; pull the big thing in only when you are about to use it.
- **Do not fetch tool schemas you will not call.** Once fetched, a schema rides
  along in every subsequent call.
- **Do not compress-and-store intermediate results through a tool.** At our
  context size one extra call is ~10-13k input-equivalent, which is more than
  the compression saves. Aggregate in-process instead.
