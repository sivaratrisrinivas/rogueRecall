# Domain Docs

This repository uses a single-context domain-document layout.

## Before exploring, read these

- `CONTEXT.md` at the repository root.
- Relevant architectural decision records under `docs/adr/`.

If these files do not exist, proceed silently. Do not flag their absence or suggest creating them upfront. The domain-modeling workflows create them lazily when terminology or architectural decisions are resolved.

## File structure

```text
/
├── CONTEXT.md
├── docs/adr/
└── src/
```

## Use the glossary’s vocabulary

When output names a domain concept—in an issue title, refactor proposal, hypothesis, or test name—use the term defined in `CONTEXT.md`. Do not drift to synonyms the glossary explicitly avoids.

If a needed concept is absent, reconsider whether the term belongs to the project or note the gap for domain modeling.

## Flag ADR conflicts

If proposed work contradicts an existing ADR, surface the conflict explicitly instead of silently overriding the decision.
