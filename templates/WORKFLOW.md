# Paper lifecycle

Use paper start NAME before isolated work, paper commit for local checkpoints,
paper backup for GitHub backup, and paper publish only with user publication
authorization (including existing standing authorization). Use paper sync from the base branch when returning to a machine.
After publishing feature work, verify that the remaining non-base branches are
integrated, then remove them with paper clear-feature-branches. Use paper commands
for lifecycle operations; raw Git is reserved for resolving conflicts or repairing
the implementation. Never commit credentials.

Normal publication preserves both histories with ordinary pushes. If required,
Overleaf receives a snapshot of the verified files, so equal files may have
different commit IDs; repeated publication of equal files is a no-op there.

When supported by the pinned runtime, use paper align-history
[--from github|overleaf] [--dry-run] from the clean base
for explicit commit-history alignment. Default preserves both histories. An explicit
--from selects ancestry only, after file reconciliation, and archives the originals
locally and on GitHub before any exact-lease replacement. Destinations may reject
replacement; there is no snapshot fallback. This command is local-only.

## Local PDF workflow

`paper build [ROOT.tex]` writes `output/ROOT.pdf` (`main.tex` by default).
After source edits, build and fix introduced errors before reporting completion.
Reuse `paper build --watch [ROOT.tex]` for rebuilds after saved edits; avoid
overlapping builds. `paper view [ROOT.tex]` builds and opens the external viewer.
Keep PDFs and auxiliary files in ignored `output/`. Report failures: the viewer
may still show an older PDF. Documentation-only changes need no manuscript build.

## Notifications and cloud execution

### GitHub access

- Local Codex clients and other local agents use existing authentication; this
  section applies only in Codex Cloud. There, expect `GH_TOKEN` to be configured as a secret environment variable.
  Check presence only; `gh` reads it automatically. If absent and GitHub is needed,
  ask the user to configure it in the Cloud environment: their token is available in their Google Drive.
  Never request it in chat or print, log, commit, or embed credentials in URLs/arguments.

### Notifications

- Send notifications only when the user or an explicitly invoked workflow authorizes
  them. Use `paper notify --title "TITLE" --message "MESSAGE" [--url "HTTPS_URL"]`;
  it dispatches trusted GitHub Actions. Never call providers/webhooks directly or
  inspect their protected credentials. Discord is the default delivery provider.
- For PDF handoffs use the completed GitHub preview's HTTPS artifact URL; local
  PDFs stay ignored and are not notification URLs. There is no arbitrary PDF-upload
  command. Use the project's output convention (`output/`); report unavailable
  preview links rather than inventing them.

## Tasks and resumption

- Before substantial edits, sustained proof work, or meaningful verification,
  create/resume `tasks/NNN_short_name/task.md` from `tasks/template.md` and link it
  in `tasks/index.md`. Reuse it for related follow-ups. Tiny corrections, questions,
  and discussion need no record; a no-changes instruction also prohibits bookkeeping.
- Keep folders stable and exactly one `Status: ...` line before the first subsection:
  queued, active, paused, blocked, or done. Keep the index consistent. Queued ideas
  and saved checkpoints do not authorize or automatically resume execution.
- Resume from the index and relevant current checkpoint, then inspect the tree;
  consult older material only as needed. Reconcile discrepancies rather than restart.
- Save substantive milestones and a final checkpoint with established results,
  decisions, unresolved obligations, affected files, verification, and next action.
  Replace stale text; link proofs/logs instead of duplicating them. Separate proved
  results from manuscript integration; mark done only when scope/checks are complete.

## Token use and delegation

- Default to one agent and targeted reads/checks. Delegate only bounded independent
  work whose expected benefit justifies its cost, never routine bookkeeping.
  The main agent owns checkpoints, integration, and compilation; assign disjoint
  editor ownership (prefer read-only audits) and record scope, dependencies, results,
  and remaining obligations in the task.
