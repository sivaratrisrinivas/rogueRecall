# Operator workflow prototype

Throwaway UI prototype for the Wayfinder ticket **Prototype the local operator workflow**.

It tests three structurally different dashboard hierarchies on one route:

- `?variant=A` — operation-first control room
- `?variant=B` — evidence-first ledger
- `?variant=C` — comparison-first analysis canvas

Run it from the repository root:

```bash
python3 -m http.server 4173 -d prototypes/operator-workflow
```

Then open <http://localhost:4173/?variant=A>. Use the floating switcher or the left/right arrow keys to move between variants.

This is intentionally dependency-free, read-only, and disposable. It simulates the Python engine → immutable Run Record → local dashboard boundary; it does not implement V1.
