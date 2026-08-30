# GPI Hub Migration Control

This branch is the migration control plane for the dedicated GPI Hub VM move.

## Safety model

- Source `QualityProjectManagement` remains the rollback checkpoint.
- No source stop/restart/deallocate unless explicitly authorized for a later final cutover window.
- No Production BC/SharePoint writes are enabled by migration tooling.
- No DNS or public-IP cutover is performed by the repo runner unless a later explicitly authorized phase says so.
- The existing dirty `DocSync-Zetadocs` worktree is never reset or checked out by the bootstrap.
- Migration tooling runs from a separate worktree: `C:\Users\ChadDillerud\Documents\DocSync-GPIHub-Migration`.

## Operating model

The repository determines the current phase through `state.json`.

`Invoke-GPIHubMigration.ps1` self-updates the dedicated migration worktree from the `migration/gpi-hub-dedicated-vm` branch, reloads itself, then executes the repo-defined mode.

Modes:

- `monitor-v99`: monitor the currently executing V99 first-pass transfer without interrupting it.
- `run-script`: execute the phase script named in `state.json`.
- `hold`: show the hold reason and make no changes.

This lets future migration fixes and phases be committed directly to GitHub. The operator uses the same runner instead of downloading a new PowerShell file for every revision.

## One-time bootstrap

Run `Bootstrap-GPIHubMigration.ps1` once. It fetches this control branch, creates the separate migration worktree, and starts the repo runner. It does not change the application worktree.

After bootstrap, the stable entry point is:

`C:\Users\ChadDillerud\Documents\DocSync-GPIHub-Migration\tools\gpi-hub-migration\Invoke-GPIHubMigration.ps1`

## Current phase

V99 first-pass migration is in progress outside the repo runner. The current repository mode is monitoring only. Do not launch a second V99 while the existing transfer is active.

After V99 is proven successful, update `state.json` and commit the V100 phase script. The same local runner will fetch and execute it.
