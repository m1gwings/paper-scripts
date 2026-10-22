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
- Do not modify conference, journal, or presentation style files.
- Do not add LaTeX packages unless necessary.

- After changing LaTeX, compile using the project's build workflow and fix errors caused by the edits. Record the command, result, and any unresolved verification limitation.
- Summarize mathematical changes separately from typographical changes.

<!-- paper-scripts:begin managed-drafting -->
## Scientific writing

- Define technical terms before using them unless they are widely familiar—for example, to a second-year STEM undergraduate.
- Prefer simple phrasing unless greater complexity is necessary for precision.
- When a concept already has an established symbol, use that symbol rather than repeatedly describing it in elaborate words. Where helpful, pair a brief verbal explanation with the mathematical notation.

## Mathematical notation

- Keep notation expressive and dependencies explicit. Do not introduce a new symbol merely to abbreviate a short expression; reserve shorthand for expressions so long that writing them in full materially harms readability. For example, keep `\xi_{j,t}^{(p)} O_{j,t}^{(p)}` explicit rather than defining `X_t` solely to shorten it. Never suppress indices, parameters, arguments, or other dependencies (including `j` and `p` in this example) without the user's explicit authorization; any authorized shorthand must retain all dependencies unless their omission is separately authorized.

- Avoid notation clashes: check existing definitions before introducing a symbol, and do not use the same notation for distinct objects in the same context. When a subscript, superscript, or similar annotation contains multiple indices, parameters, or labels, separate them with commas, e.g. `X_{i,j}` and `X^{(p,q)}` rather than concatenating the entries.

## Draft revisions and review

- Unless the user explicitly asks otherwise, track manuscript edits using the collaboration API actually loaded by the project. The paper-scripts starter loads `papermacros.sty`: use `\AgentsIns{new}`, `\AgentsDel{old}`, and `\AgentsDel{old}\AgentsIns{new}` for replacements. Use `\Agents[MODEL NAME]{comment}` for an explanatory review box and `\AgentsOut[MODEL NAME]{comment}` for an outer note (inline on slides/posters).
- Model attribution is required for new Agents comments: supply your actual model name in the optional argument, e.g. `\Agents[GPT-6 Astra]{Check this assumption.}`. Apply the same rule to `\AgentsOut`. The name replaces “Agent” in the rendered title; the AG cue remains. Use only identity supplied by the execution environment; never guess a model or version. If it is unavailable, use `\Agents[Model unavailable]{...}` and state that limitation in the task checkpoint. Keep existing comments unchanged. First verify that the loaded macro supports this optional argument; legacy project macros and their review policies still take precedence.
- Use only strikethrough deletion commands: `\AgentsDel{old}` in the shared package or the loaded project's `\CodexDel{old}` and related author commands. Do not use or define a separate block-deletion mechanism. Split deleted paragraphs into safe prose spans; keep display delimiters and environment boundaries outside wrappers, striking individual math expressions or alignment cells. Preserve applied/reverted semantics with the existing review-mode conditionals when entire environments must disappear. Use `\AgentsReplaceMath{old}{new}` inside math mode for stacked replacements; its old expression is struck through. In Beamer frames, keep revisions within the frame.
- Never wrap a whole file, preamble, package definition, environment boundary, verbatim material, or other syntactically incompatible change in an inline revision command. Keep labels unique across visible old/new material. Record structural/non-LaTeX changes precisely in the task checkpoint and change report.
- Preserve existing author/reviewer markup; use the appropriate author commands only when attributing that person's changes. Do not nest revision wrappers or silently relabel someone else's work as agent work. The shared API uses `Ins` as the primary insertion name; do not introduce `AuthorInline` or `Codex...` aliases.
- `\CommentsVisible` shows revisions, `\CommentsApplied` renders insertions and hides deletions, and `\CommentsReverted` hides insertions and restores deletions. Rendering a clean PDF does not accept/reject changes in source. Preserve the project's selected mode unless the task requests another; use visible mode for draft review. Permanently accepting/rejecting changes requires user authorization.
- Existing projects may still load older `\AgentIns`, `\AgentDel`, `\CodexIns`, `\CodexDel`, or other collaboration macros. Inspect their definitions; use the loaded API until an explicit migration is requested. Never insert undefined commands or silently migrate tracking. Preserve project-specific reviewer/author colors. If no tracking API exists, report that limitation instead of silently adding one.
- “Finalize the Agent edits”, “finalize the Codex edits”, “finalize the Claude edits”, and equivalent requests mean permanently accepting the relevant reviewed revisions in the source. The agent/model name does not change these semantics.
- In the authorized scope, delete each `\AgentsDel{old}` command together with its entire contents; replace each `\AgentsIns{new}` with `new`, removing only the surrounding insertion command/braces. Apply the same rule to equivalent legacy `Del`/`Ins`/`Inline` commands. For `\AgentsReplaceMath{old}{new}`, discard `old` and retain `new`. Preserve nested LaTeX structure, unrelated author/reviewer markup, and comments outside the agreed scope. Merely selecting `\CommentsApplied` or recoloring revisions does not finalize their source.
- “Finalize all edits” normally refers to all edits discussed so far in the current review context. It does not automatically authorize accepting every tracked revision throughout the manuscript. Use the conversation and task checkpoints to identify the reviewed passages; absence of evidence that a passage was reviewed is not approval. If the intended passages or review/acceptance scope are uncertain, ask the user before permanently removing or unwrapping any ambiguous markup. Manuscript-wide acceptance requires clear evidence of that broader scope.
- After edits, compile and check the affected document. When changing shared review macros, validate visible/applied/reverted output including citations, references, math, and environment edits. Keep paper-specific notation in `projectmacros.tex`; theorem and remark numbering belongs to the project or venue setup. Never modify a venue style file to accommodate the shared package.
<!-- paper-scripts:end managed-drafting -->

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
