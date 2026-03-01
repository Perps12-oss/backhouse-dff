# Architecture refactor v6 — Core boundaries & golden rule

## Current problem: cross-layer coupling

```
UI → workers → core → history → UI (via imports)
```

Tight coupling across layers makes changes risky and blocks clean domain logic.

---

## Target architecture (layered)

```
UI
  ↓
Application / Controllers
  ↓
Domain (pure logic)
  ↓
Infrastructure (filesystem, cache, hashing)
```

- **UI** — Views and user input only; no direct imports of workers/core/history.
- **Application / Controllers** — Orchestration, use cases; call into domain and infrastructure via interfaces.
- **Domain** — Pure business logic (what is a duplicate, what is a group); no I/O, no UI.
- **Infrastructure** — Filesystem, hash cache, discovery, hashing; implements interfaces defined by application/domain.

---

## Migration strategy (no big-bang)

1. **Old pipeline still runs** — Leave existing flow working.
2. **New pipeline added** — Implement new flow behind interfaces (e.g. new scanner/use-case layer).
3. **Controller switches to new** — Controllers call the new pipeline instead of the old.
4. **Old pipeline deleted** — Remove legacy code once the new path is default and verified.

Main stays runnable at every step.

---

## Golden rule for large refactors

- **`main` = always runnable.** No broken builds, no half-migrated features on main.
- **Refactor branch is allowed to be broken.** Work and experiment on `refactor/architecture-v6`; merge to main only when the app runs and tests pass with the new structure.

---

## Branch

- **Branch:** `refactor/architecture-v6`
- **Base:** `main` (synced before creating/resetting this branch).
- **Stashed work:** Any WIP that was on this branch before the sync is in stash (`refactor WIP before main sync`). Re-apply with `git stash pop` when you want to continue from that state.
