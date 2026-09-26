# Theoretical paper instructions

## Project and editing

- Follow `.paper/WORKFLOW.md` for repository lifecycle operations. Use `paper start`, `paper backup`, `paper sync`, and `paper publish`; publish only when explicitly authorized.
<!-- paper-scripts:begin managed-feature-cleanup -->
- After a feature branch has been published, do not leave it pending: verify that every listed non-base branch has been integrated, then run `paper clear-feature-branches` to remove published feature branches locally and from GitHub.
<!-- paper-scripts:end managed-feature-cleanup -->
- Inspect the existing layout, notation, macros, and build instructions before editing.
- Keep research knowledge (derivations, conjectures, examples, reusable proof audits) in `notes/`. Keep task management, checkpoints, and revision-specific verification in `tasks/`; link between them instead of duplicating content.
- Preserve pre-existing user edits. Make the smallest change sufficient for correctness; avoid unrelated stylistic changes.
- Preserve the proof strategy unless asked to redesign it. Do not silently strengthen assumptions or claims.
- Check index ranges, stopping times, conditioning, constants, and parameter regimes explicitly. Distinguish conjectural, conditional, and proved claims.
- Prefer explicit algebraic derivations and compact inequality chains. For repeated calculations, cite the analogous argument and give the needed result.

## LaTeX and verification

- Preserve existing notation and macros whenever possible.
- Do not replace custom macros with expanded LaTeX.
- Preserve labels and references unless a structural change requires otherwise.
- Use semantic label prefixes and `snake_case` identifiers, such as `eq:stopped_regret` or `lem:time_stopped_kl`; do not use spaces or hyphens in labels.
- Introduce every multiline displayed equation with grammatically appropriate punctuation, normally a colon.
- End every multiline displayed equation with punctuation appropriate to the surrounding sentence.
- In a `cases` block, do not punctuate the individual branches; place punctuation only after the complete `cases` expression.
- For integration with respect to the Lebesgue measure, write `\mathrm{d}\lambda(x)` rather than `\mathrm{d}x`.
- Prefer compact multiline derivations rather than one equality per line.
- In set-builder notation, use `\text{ s.t. }` rather than a colon.
- Do not modify the AISTATS style files.
- Do not add LaTeX packages unless necessary.

- After changing LaTeX, compile using the project's build workflow and fix errors caused by the edits. Record the command, result, and any unresolved verification limitation.
- Summarize mathematical changes separately from typographical changes.

<!-- paper-scripts:begin managed-notifications -->
## Codex Cloud GitHub access

- This section applies only when running in Codex Cloud. Local Codex clients and other local agents should continue to use the machine's existing GitHub authentication and must not require `GH_TOKEN` solely because of this section.
- In Codex Cloud, expect `GH_TOKEN` to be configured as a secret environment variable for authenticated access to the user's GitHub repositories. Check only whether it is set, for example with `test -n "${GH_TOKEN:-}"`; never print or otherwise reveal its value. The GitHub CLI reads `GH_TOKEN` automatically, so do not pass the token on the command line or embed it in a Git remote URL.
- If `GH_TOKEN` is unset or empty and GitHub access is needed, stop before the authenticated operation and ask the user to configure it in the Codex Cloud environment. Remind the user that their token is available in their Google Drive; do not ask them to paste it into chat.
- Treat `GH_TOKEN` as a credential: never echo, log, commit, store in repository files, or expose it through shell tracing or diagnostic output.

## Notifications

- You may proactively notify the user about a useful completed result, a material blocker, or a requested milestone. If the user says "At the end send me a notification with ...", treat that as authorization to do so.
- Use only `paper notify --title "TITLE" --message "MESSAGE" [--url "HTTPS_URL"]`. It always dispatches the trusted GitHub Actions notification workflow; do not call Discord, Pushover, a webhook, or the internal adapter directly.
- Discord is the default delivery provider, but the command is provider-neutral. It works locally and in cloud environments with authenticated GitHub access. The Discord webhook stays in the protected `paper-notify` GitHub environment; never inspect, request, print, add, or commit it or any other provider credential.
- A local path is not a notification URL. For a requested PDF handoff, generate `output/pdf/NAME.pdf` when that is this repository's output convention, and do not commit it. The current supported PDF-link mechanism is the private GitHub Actions preview artifact: after the normal preview workflow has completed, it produces `paper.pdf` and its trusted notifier uses a URL of the form `https://github.com/OWNER/REPOSITORY/actions/runs/RUN_ID/artifacts/ARTIFACT_ID`. For a custom notification, pass an already available HTTPS artifact URL with `--url`; there is no `paper` command that uploads an arbitrary `output/pdf/` file or converts its local path into a link.

Example, once the preview artifact URL is available:

```bash
paper notify --title "Paper update" --message "Revised PDF is ready." \
  --url "https://github.com/OWNER/REPOSITORY/actions/runs/RUN_ID/artifacts/ARTIFACT_ID"
```
<!-- paper-scripts:end managed-notifications -->

<!-- paper-scripts:begin managed-tasking -->
## Tasks and resumption

- Before substantial execution work, create or resume `tasks/NNN_short_name/task.md` using `tasks/template.md`, and link it in `tasks/index.md`. Reuse the task for related follow-ups. Substantial work includes multi-step edits, sustained proof work, or meaningful verification.
- Simple questions, tiny corrections, and discussion-only requests need no task record. Explicit instructions to make no changes also prohibit bookkeeping edits.
- Keep task folders stable. Put exactly one plain status line (e.g. `Status: active`) before the first subsection. Allowed statuses: queued, active, paused, blocked, done. Keep the index consistent with the task record. A queued idea does not authorize execution.
- When resuming, read the index and the relevant task's current checkpoint first, then inspect the working tree. Read older material only as needed; reconcile discrepancies rather than restarting completed work.
- Update the current checkpoint after substantive results and before stopping or handing off work. Record established results, unresolved obligations, decisions, affected files, verification, and the next concrete action. Save enough to resume in a fresh session without the chat.
- Keep records concise: replace stale checkpoint text, retain only useful decision history, and mark superseded arguments clearly. Link to proofs and logs instead of copying them. Add supporting files only when necessary.
- Mark a proof proved only when its obligations are satisfied; distinguish proof completion from manuscript integration and verification. Mark the task done only when its scope and required checks are complete.
- Task files preserve progress across interruptions; they do not automatically restart execution. Save milestones during work rather than relying only on an end-of-session handoff.

## Token use and delegation

- Default to one agent. Use targeted searches and reads; avoid repeatedly loading entire notes, histories, or logs. Run checks appropriate to the change and repeat them only when new evidence warrants it.
- Delegate bounded independent work to subagents only when the expected time or quality benefit justifies the additional token cost. Do not spawn agents for routine bookkeeping or small edits.
- The main agent owns the task checkpoint, integration, and compilation. Give parallel editors disjoint file ownership; prefer read-only assignments for independent audits. Record each assignment's scope, dependencies, results, and remaining obligations in the task.
<!-- paper-scripts:end managed-tasking -->
