# Production Branch Policy

## Current production source

The Azure VM deployment at `/data/apps/gpi-hub` runs from:

```text
gemini-model-fix-clean
```

This branch is the current production integration branch and is tracked by:

```text
origin/gemini-model-fix-clean
```

Do not switch the production worktree to `main`.

## Why `main` must not be merged or rebased directly

`main` and `gemini-model-fix-clean` have deeply diverged histories. As of July 25, 2026:

- `gemini-model-fix-clean` is 2,631 commits ahead of `main`.
- `gemini-model-fix-clean` is 1,064 commits behind `main`.
- Their merge base is `7c92af128bd01e6fa8c180013227e52617f5cc02`.

A normal merge or rebase would therefore be a large reconstruction effort and must not be used as a routine deployment step.

## Release workflow

1. Create feature branches from `gemini-model-fix-clean`.
2. Develop and test changes on the feature branch.
3. Merge or fast-forward the tested feature branch into `gemini-model-fix-clean`.
4. Pull `origin/gemini-model-fix-clean` on the Azure VM.
5. Rebuild or restart only the affected containers.
6. Run:

```bash
./scripts/live_production_smoke_test.sh
```

7. Require all checks to pass before considering the deployment complete.

## Production safety rules

- Never run `git pull origin main` from `/data/apps/gpi-hub`.
- Never run `git reset --hard origin/main` in production.
- Never rebase the production branch onto `main`.
- Do not commit `backend/.env`, secrets, uploaded documents, generated reports, backups, or recovery artifacts.
- Stage files explicitly. Avoid `git add .` on the production VM.
- Before every deployment, confirm:

```bash
git branch --show-current
git status --short
git log -1 --oneline
```

The expected branch is `gemini-model-fix-clean`.

## Current validation

The production read-only smoke test currently validates:

- API health
- migration compatibility routes
- Business Central company access
- inbox metrics
- inbox statistics
- posting-pattern badge count

All six checks returned HTTP 200 after the Business Central environment correction.

## Longer-term cleanup

`main` should not be declared the production branch until a deliberate reconciliation project is completed. That project should inventory unique code on both branches, identify the intended canonical architecture, migrate production-only functionality into a clean branch, validate it in a non-production environment, and perform an explicit cutover.
