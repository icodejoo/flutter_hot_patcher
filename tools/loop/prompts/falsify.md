# Falsification pass

A standing adversarial review, run by a **fresh** agent before a card is closed.

## Why this exists

This project's verification is a self-check that the worker runs (`verify_all.sh`).
Every comparable unattended system separates the two roles — gh-aw applies writes
in a trusted job the agent cannot reach, looper has review/fix agents, ralph's
`/goal` uses an evaluator. We did not, and it cost:

- the phase was declared complete **twice** and retracted twice (E3's "0 gaps";
  `bfa898d`'s `PHASE COMPLETE`)
- **seven instrument defects**, each one a criterion that could not fail, or one
  that failed in the wrong direction
- 2026-09-09: a single adversarial pass (F35) overturned "DD dispatch theirs 92 /
  ours 0" — a gap that had blocked 18 matrix cells and driven three rounds of work.
  It cost one dispatch.

The asymmetry that makes this cheap: **withdrawing a claim is always safe, making
one must justify itself.** So this pass only ever has to look for reasons to
withdraw.

## How to run it

Dispatch a fresh agent (no shared context) with the block below, filling in the
four placeholders. Do **not** ask the agent that did the work.

Its success criterion is **finding a flaw**, not confirming the result. An agent
that reports "looks correct" has not done the job unless it also names the test
that could still overturn the claim.

### Which model

**2026-09-24, operator instruction: every subagent dispatch uses Opus. No
Haiku, no Sonnet, no task-shape exception below.** The table and the
reasoning under it are kept as the record of why Sonnet/Haiku were ever
considered acceptable for some shapes of pass; they no longer govern the
choice. If this is ever revisited, change this line, not the table.

~~Default to Opus or Sonnet. Haiku only for a single, fully specified,
purely mechanical dispatch~~ — "run this command, report its exit code and the
diff" — where there is nothing left to judge.

This is not a guess about capability; both have run passes here and the record
compares them directly.

Where Haiku earned its place: it found the defect in F60's denominator
(`diff_units.sh` reading a binary artifact as UTF-8, so UNITS said 12 where
`cmp -l` says 23,733 — off by 1977x). Mechanical, checkable, real.

Where it did not: across the passes it ran, four returned a verdict the
dispatcher had to reject on inspection — attacks restated from the card rather
than executed (F49 pass 1, "attacks 3/4/6 are restatements"), three of five
mandatory items skipped while still reporting SURVIVES (F49 pass 3), a verdict
reached by circular reasoning (F42 pass 3: this card was FALSIFIED before,
therefore it is FALSIFIED now), and a verdict that missed the evidence in
`wip.log` contradicting it (F41 pass 1).

The counter-example that decided it, both on 2026-09-10 and on the same card:
Haiku's pass on F60 (32 tool calls) found the wrong denominator. Opus's pass on
F60's *fix* (**18** tool calls) found that the check **could not fail at all** —
`evidence_compute_dd_table_residual.sh` and `structural_evidence_check.sh` both
compute the denominator by calling `diff_units.sh`, so the two sides are equal
by construction. It proved it by injecting 500 heterogeneous bytes into a
fixture and watching the check still print `UNEXPLAINED 0, rc=0`. It then found
the same defect reaches **seven other already-closed binary flags**
(`print_field_table_link_info_to`: UNITS=6 against 100,273 measured).

Note the cost, because the intuition runs the wrong way: the Opus pass used
**fewer** tool calls than the Haiku one, 18 against 32. Under this loop's
measured cost model the spend is roughly `N x (entry + exit) / 2` — quadratic
in call count — so a stronger model that converges earlier is not the expensive
option. And a pass is short anyway (25-43 calls) next to an implementation
dispatch (79-116), so the model price delta on passes is a small share of the
total, while a wrong verdict costs a retracted closure. That has happened twice
and cost days each time.

**So:** ask what the dispatch has to decide.

| the pass has to... | model |
|---|---|
| run commands and compare numbers, nothing to judge | Haiku |
| attack a claim, its evidence, and its controls | Sonnet |
| ask whether the criterion *can fail at all*; the last pass before a card closes; anything that moves the `phase_gate` pin | Opus |

Two things that matter more than this choice, both on the record:

- **One mandatory item per dispatch.** Of six passes on F49, five skipped the
  same required item; the sixth was narrowed to a single question and found a
  real escape within minutes. A mandatory item bundled with six other attacks
  gets squeezed out no matter which model runs it.
- **Never the agent that wrote the thing.** Including — especially — when what
  is being reviewed is a *fix* it just made.

State the model in the verdict line. `dispatch_stats.tsv` records it per round,
but the verdict is where a later reader will look.

---

## Prompt block (copy from here)

You are running a **falsification pass** on a claim another agent just made in the
flutter_hot_patcher / Shorebird dart-sdk reproduction project. You have no prior
context and you are not here to reproduce the work.

**Your job is to break the claim.** Confirming it is the less useful outcome and
must not be your goal. If you cannot break it, you must name the specific test
that could still overturn it — "it looks right" is not an acceptable answer.

CLAIM: <one sentence, as the card states it>
CRITERION THE CARD SET: <the pass condition its author wrote down>
EVIDENCE OFFERED: <commits, scripts, numbers, artifact paths>
WHERE TO LOOK: <trees, files, out_* dirs>

Work through all seven attacks below. Report each by number, with the command you
ran and its output. Each one is here because it has already produced a false
result in this repository at least once.

1. **Could the criterion have failed at all?**
   Read the check, not its output. Look for: a verdict written as a constant
   (a hardcoded `structural`), a threshold that the measured value cannot cross,
   a comparison of two empty things (`cmp` answered "identical" for two files that
   did not exist and turned three cells green), a set difference that is empty by
   definition, a grep whose pattern also matches the text of the check itself.
   Then: perturb the input and confirm the check goes red. If it cannot go red,
   the claim is unsupported no matter how good the number looks.

2. **Are both sides comparable?**
   Same build mode on both sides? (`R(...)` flags are compile-time constants in
   PRODUCT and are not registered at all, which once manufactured a +209 entry
   surplus and blocked ten cells.) Same-age binaries? (`analyze_snapshot` lives
   only in ReleaseARM64; the Product half is not in the default ninja target, and
   stale binaries have produced both false greens and false reds here.) Were the
   two oracle inputs perhaps the same file? (`cmp` them: `base.ct` and `patch.ct`
   were byte-identical, so an entire check only ever exercised the identity case.)

3. **Does the named cause explain the whole difference, or a slice of it?**
   Demand the denominator. The same locus (`Thread+0x678`) was used to close three
   batches of cells; the weakest instance explained **0 of 3656** differing objects
   and still passed, because the gate only asked whether the offset existed. A
   cause row needs a residual row: print `EXAMINED <n>` where n is computed by the
   harness from both products — never by the claimant — and `UNEXPLAINED 0`.
   One component per evidence row; a single row cannot cover two mechanisms.

4. **Does the detection pattern match anything else in our own tree?**
   The largest "gap" in this project's history was a mislabel: the pattern
   `asr x16,x16,#1; ldr x30,[x26,x16]; blr` was read as DD dispatch, but our own
   `EmitIndirectStaticCall` emits those exact six instructions, and the 92 sites
   were lazily-linked native calls. Before trusting a counter, ask what else it
   hits — especially another code path in our own source that emits the same shape.
   The decisive evidence is *which single instruction differs*, not which pattern
   matched.

5. **Is anything the card cites stale?**
   Every "missing / gap / we emit 0 / blocked / dead code" assertion needs a
   measured date and a commit. Check them: `git merge-base --is-ancestor <sha> HEAD`,
   `grep -n <symbol> <file>` and look at the exit code, `ls` the actual path.
   Two cards (F5 and F34b) cited the same hardcoded literal that had been deleted
   eight days and 27 commits earlier. A disassembly address is not freshness
   evidence — it only proves somebody looked once.
   Never grep a path you have not confirmed exists: "zero references" was once
   concluded from grepping `runtime/vm/stub_code_compiler_arm64.cc`, whose real
   path is `runtime/vm/compiler/stub_code_compiler_arm64.cc`. Empty output and
   "genuinely absent" look identical; a timed-out grep also returns empty.

6. **Was the negative control real?**
   It must have been applied, compiled, and observed in the same pass:
   a build that failed can "go red" on the previous stale binary with identical
   numbers; a patch that did not apply looks the same as a test that failed;
   a perturbation can be semantically an identity transform (changing a backfill
   `cursor+1` to `0` left four tests green because the two rules are equivalent).
   Ask: did the perturbed build return 0 from ninja, and did the perturbation
   actually change the meaning of that line?

7. **Was the question swapped for an easier one?**
   Five times here, an answer went green because the problem changed underneath
   it: ours-vs-theirs became "two tools on the same .so"; a residual script
   measured a set that is empty by definition; a histogram cited for two rounds
   turned out not to reproduce at all. Compare the criterion actually run against
   the question the card asked.

Report in exactly this format, nothing else — no logs, no code, no long analysis:

```
VERDICT: [SURVIVES|FALSIFIED|PARTIAL]
ATTACK RESULTS: 1..7, one line each: number, what you ran, what it showed
FLAW: <if FALSIFIED or PARTIAL: the specific defect, and the command that shows it>
STILL OPEN: <if SURVIVES: the specific test that could yet overturn this>
COST OF BEING WRONG: <one line: what downstream work rests on this claim>
```

## After the verdict — what the dispatcher does with it

A verdict is not the end of the round. The loop is: do it, review it, fix what
the review found, review again, and only then close.

- **SURVIVES** — close the card, and copy the reviewer's `STILL OPEN` line into
  memo.md verbatim. It is the part most likely to matter later.
- **PARTIAL / FALSIFIED** — **do not close.** Fix each finding in the same round
  if it can be fixed there, then run the pass again. The context that just did
  the work knows the most about it; the next round has to rebuild that from
  memo.md, and rebuilding is how a quota interruption turns into a loop that
  burns the same hours. Only when a fix is large enough to need its own
  criterion and negative control does it become a new card instead.
- **Either way**, the verdict goes into memo.md on a line naming the card. The
  end-of-round gate looks for exactly that, and a verdict recorded without its
  card id does not count.

⚠️ **A fix does not inherit the review of the thing it fixed.** On 2026-09-09 a
pass over eight cards took four of them down — one was silently losing
snapshots — and all four were fixed the same day. Those four fixes have not
been reviewed. They are new `built` work, not `closed` work. This is the
sentence most likely to be skipped.

## Validating this template

A falsification prompt that never falsifies anything is decoration. Test it by
replay: hand it a card whose conclusion is **known to have been wrong**, with only
the evidence available at the time, and check that the fresh agent reports the
flaw. Known-wrong cards suitable for replay:

- **F14** — attributed a 4-object surplus to Shorebird's private inlining, with
  named functions and disassembly from both sides. Real cause: our Release build
  versus their product build. Attack 2 should catch it.
- **F18 (first round)** — closed `disassemble` on locus `Thread+0x678`, which
  explains 0 of the 9922 differing objects. Attack 3 should catch it.
- **F24** — four residual rows all printing `UNEXPLAINED 0`, one of which measured
  "functions with the same self_hash but a different size", a set that is empty by
  construction. Attack 1 should catch it.

If a replay does not produce the flaw, fix the template, not the record.
