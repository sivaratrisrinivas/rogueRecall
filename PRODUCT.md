# Product

## Purpose

RogueRecall gives a Benchmark Operator one narrow local workflow: configure Target Systems, run the fixed Benchmark Corpus, and inspect one denominator-explicit `results.json` artifact. It measures observable protected-text reproduction after indirect prompts.

## Product invariant

The same RogueRecall version, fixed cases, deterministic grading rules, and generation settings are used for every configured Target System. Results show Text Leaks, Grading Coverage, and errors without rankings, winners, or an implication that ungraded observations are safe.

## Interface

`roguerecall benchmark --manifest <targets.json> --results <new-results.json>` is the sole product workflow. The result artifact is self-contained, never overwritten, and atomically updated during execution.
