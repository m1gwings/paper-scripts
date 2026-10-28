# Theoretical paper instructions

## Project and editing

<!-- paper-scripts:begin managed-feature-cleanup -->
- Before repository lifecycle operations, follow `.paper/WORKFLOW.md` for
  publication authorization, reconciliation, and merged-branch cleanup.
- During an ongoing sequence of small document edits, apply and verify each change
  promptly, but batch commits and remote synchronization every few edits, when we
  stop working, or when Cristiano asks for a checkpoint/publication. Do not treat
  each brief response in that sequence as a requirement to commit and publish.
  This exception applies only to document editing, not tool or infrastructure changes.
<!-- paper-scripts:end managed-feature-cleanup -->
- Inspect the existing layout, notation, macros, and build instructions before editing.
- Keep research knowledge (derivations, conjectures, examples, reusable proof audits) in `notes/`. Keep task management, checkpoints, and revision-specific verification in `tasks/`; link between them instead of duplicating content.
- Preserve pre-existing user edits. Make the smallest change sufficient for correctness; avoid unrelated stylistic changes.
- Preserve the proof strategy unless asked to redesign it. Do not silently strengthen assumptions or claims.
- Check index ranges, stopping times, conditioning, constants, and parameter regimes explicitly. Distinguish conjectural, conditional, and proved claims.
- Show the first derivation and the steps that explain the probabilistic or structural argument. When computations are analogous to an earlier calculation, state the needed result and cite the precise equation, proof step, or lemma instead of repeating the derivation (for example, "By computations analogous to ..."). Specify any changed assumptions, indices, or parameters needed to justify the analogy; retain genuinely new reasoning.

## LaTeX and verification

- Preserve existing notation, macros, labels, and references; do not expand custom macros or change labels without a structural need.
- Use semantic label prefixes and `snake_case` identifiers, such as `eq:stopped_regret` or `lem:time_stopped_kl`; do not use spaces or hyphens in labels.
- Introduce multiline displays with appropriate punctuation (normally a colon) and end them with punctuation fitting the surrounding sentence.
- In a `cases` block, do not punctuate the individual branches; place punctuation only after the complete `cases` expression.
- For integration with respect to the Lebesgue measure, write `\mathrm{d}\lambda(x)` rather than `\mathrm{d}x`.
- Prefer compact multiline derivations rather than one equality per line.
- In set-builder notation, use `\text{ s.t. }` rather than a colon.
- Do not modify conference, journal, or presentation style files.
- Do not add LaTeX packages unless necessary.

- Record the build command/result and unresolved limitations; follow the PDF workflow below.
- Summarize mathematical changes separately from typographical changes.

<!-- paper-scripts:begin managed-drafting -->
## Local PDF workflow

- After source edits, follow `.paper/WORKFLOW.md#local-pdf-workflow` for the
  required build, ignored output directory, and reuse of the existing watcher.
  Report compilation failures; a viewer may still show an older PDF.

## Scientific writing and notation

- Avoid semicolons in prose unless they clearly express the connection better than a full stop or conjunction.
- Define unfamiliar technical terms before use (aim at a second-year STEM reader),
  prefer simple precise prose, and use established symbols where appropriate.
- Preserve expressive notation and every index/parameter/argument. Introduce
  shorthand only for materially long expressions, never merely to shorten
  `\xi_{j,t}^{(p)} O_{j,t}^{(p)}`. Omitting dependencies requires explicit user
  authorization separate from authorization for shorthand itself.
- Avoid notation clashes. Separate multiple indices/labels with commas:
  `X_{i,j}`, `X^{(p,q)}`. Use "implies" and "if and only if" in prose,
  including pseudocode, rather than `\implies`, `\iff`, or similar symbols.
  Inside formulas, prefer the abbreviation `\text{ iff }`, on the same line
  as the preceding equation when it fits.

## Draft revisions and review

- Unless asked otherwise, track all manuscript edits with the collaboration API
  actually loaded. Inspect definitions; preserve legacy commands and project
  colors until an authorized migration. Report a missing API instead of adding
  undefined commands. The starter loads `papermacros.sty`:
  `\AgentsIns{new}`, `\AgentsDel{old}`, and `\AgentsDel{old}\AgentsIns{new}`.
  Do not introduce `AuthorInline` or `Codex...` aliases.
- For explanatory comments use `\Agents[MODEL NAME]{comment}` or
  `\AgentsOut[MODEL NAME]{comment}` (outer note; inline on slides/posters).
  Verify optional-argument support first. Attribute new comments to the actual
  environment-supplied model; if unavailable use `Model unavailable` and record
  the limitation. Preserve existing comments and other authors' attribution.
- Deletions must be struck through using the loaded `Del` command; no separate
  block-deletion mechanism. In math use `\AgentsReplaceMath{old}{new}` for stacked
  replacements. Keep display delimiters/environment boundaries outside wrappers;
  strike safe prose spans or individual math/alignment cells. Preserve applied/
  reverted semantics for disappearing environments; keep Beamer edits in-frame.
- Never wrap whole files, preambles, packages, environment boundaries, verbatim,
  or other incompatible syntax, nest wrappers, duplicate labels, or relabel others'
  work. Record exact structural/non-LaTeX changes in checkpoint/report.
- `\CommentsVisible` shows revisions; `\CommentsApplied` hides deletions and
  `\CommentsReverted` restores them and hides insertions. Preserve the project's
  selected mode; draft review uses visible mode. A clean rendering does not accept
  revisions. Permanent acceptance/rejection requires user authorization.
- "Finalize the Agent/Codex/Claude edits" means accept the reviewed revisions in
  source, regardless of agent name. In the authorized scope, delete each
  `\AgentsDel{old}` with its entire contents; unwrap `\AgentsIns{new}`, removing only the surrounding insertion command/braces.
  For `\AgentsReplaceMath{old}{new}`, keep only `new`; apply equivalent semantics
  to legacy `Del`/`Ins`/`Inline` commands. Preserve nested LaTeX, unrelated markup,
  and comments outside scope; switching mode or color is not finalization.
- "Finalize all edits" covers the current review context, not automatically the
  whole manuscript: absence of evidence that a passage was reviewed is not approval.
  If scope is uncertain, ask the user before permanently removing ambiguous markup.
  Manuscript-wide acceptance needs clear evidence of that scope.
- Keep paper notation in `projectmacros.tex`, theorem/remark numbering in the
  project/venue setup; never alter venue styles for collaboration macros.
  Shared macro changes require visible/applied/reverted verification including
  citations, references, math, and environments, in addition to the normal build.
<!-- paper-scripts:end managed-drafting -->

<!-- paper-scripts:begin managed-notifications -->
## Notifications and cloud execution

- Before sending notifications or operating in Codex Cloud, read
  `.paper/WORKFLOW.md#notifications-and-cloud-execution`.
<!-- paper-scripts:end managed-notifications -->

<!-- paper-scripts:begin managed-tasking -->
## Tasks and resumption

- Substantial work requires a task checkpoint in `tasks/NNN_short_name/task.md`
  and `tasks/index.md`; follow `.paper/WORKFLOW.md#tasks-and-resumption`.
  Tiny corrections and discussion need no checkpoint; no-changes excludes bookkeeping.

## Token use and delegation

- Default to one agent and targeted reads/checks. Follow the task/delegation
  procedure in `.paper/WORKFLOW.md#token-use-and-delegation`.
<!-- paper-scripts:end managed-tasking -->
