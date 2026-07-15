# Product

## Register

product

## Users

RogueRecall is used by Benchmark Operators working locally to configure Target Systems, execute Evaluation Runs, inspect evidence, compare compatible results, and export audit-quality records. Legal, policy, and safety stakeholders consume the resulting evidence but do not operate the benchmark directly.

## Product Purpose

RogueRecall measures whether deployed language-model systems reproduce protected text when given indirect prompts. It succeeds when an operator can produce traceable, repeatable evidence, distinguish Text Leaks from Source Identification, and understand Grading Coverage and errors without mistaking ungraded observations for safe outcomes.

## Brand Personality

Precise, forensic, quietly authoritative. The interface should feel composed under scrutiny: technically exact without becoming cold, theatrical, or intimidating.

## Anti-references

- Generic SaaS dashboards built from interchangeable rounded cards and decorative metrics.
- Gamified scoreboards, rankings, winner language, or celebratory treatment of benchmark outcomes.
- “Hacker terminal” theatrics that confuse evidence work with cyberpunk decoration.
- Safety dashboards that hide errors, qualifiers, or provenance behind a simplified pass/fail score.

## Design Principles

- Keep evidence one step away: summaries must lead directly to the Run Record facts that support them.
- Pair every rate with its denominator and Grading Coverage so missing grades cannot read as safety.
- Make system boundaries legible: the Python engine writes; immutable Run Records preserve evidence; the local dashboard reads and compares.
- Prefer calm precision over spectacle; use emphasis only to communicate operational risk or evidentiary meaning.
- Name domain concepts exactly and never collapse Text Leak, Source Identification, refusal, truncation, or errors into one outcome.

## Accessibility & Inclusion

Meet WCAG 2.2 AA. Outcomes must never depend on color alone. All workflows must support keyboard operation, visible focus, readable contrast, and reduced-motion preferences. Dense evidence views should remain understandable under zoom and on narrow screens without hiding outcome meaning.
