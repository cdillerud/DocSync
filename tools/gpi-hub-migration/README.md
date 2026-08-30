# GPI Hub Migration Control

This branch is the migration control plane for the dedicated GPI Hub VM move.

## Safety model

- Source `QualityProjectManagement` remains the rollback checkpoint.
- No source stop/restart/deallocate unless explicitly authorized for a later final cutover window.
- No Production BC/SharePoint writes are enabled by migration tooling.
- No DNS or public-IP cutover is performed by the repo runner unless a later explicitly authorized phase says so.
- The existing dirty `DocSync-Zetadocs` working tree is never reset, checked out, archived, or cleaned by the controller.
- The local controller is a plain folder at `C:\Users\ChadDillerud\Documents\DocSync-GPIHub-Migration`.
- The controller does not use a Git worktree, Git index, checkout, reset, sparse checkout, tree traversal, or `git archive`.

## Operating model

The repository determines the current phase through `state.json`.

`control-files.txt` is the authoritative manifest of repo-controlled migration files. Bootstrap and self-update fetch each listed file individually with `git show <ref>:<path>`. This avoids the invalid Windows path elsewhere in the DocSync repository.

`Invoke-GPIHubMigration.ps1` fetches the migration branch, refreshes only the explicitly listed control files, reloads itself, then executes the repo-defined mode.

Modes:

- `monitor-v99`: monitor the currently executing V99 first-pass transfer without interrupting it.
- `run-script`: execute the phase script named in `state.json`.
- `hold`: show the hold reason and make no changes.

Future migration fixes and phases are committed directly to GitHub and added to `control-files.txt`. The operator uses the same Desktop launcher instead of downloading a new PowerShell file for every revision.

## One-time bootstrap

Run `Bootstrap-GPIHubMigration.ps1` once. It fetches this control branch, reads `control-files.txt`, materializes only those explicit files into the plain control folder, and starts the repo runner. It does not change the application working tree.

After bootstrap, the stable entry point is:

`C:\Users\ChadDillerud\Documents\DocSync-GPIHub-Migration\tools\gpi-hub-migration\Invoke-GPIHubMigration.ps1`

The Desktop launcher is `GPI Hub Migration.cmd`.

## Current phase

V99 first-pass migration is in progress outside the repo runner. The current repository mode is monitoring only. Do not launch a second V99 while the existing transfer is active.

After V99 is proven successful, update `state.json`, commit the V100 phase script, and add that phase script to `control-files.txt`. The same local runner will fetch and execute it.
