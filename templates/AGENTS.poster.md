# Scientific poster instructions

## Project and editing

- Follow `.paper/WORKFLOW.md` for repository lifecycle operations. Publication requires user authorization, which may already be standing; do not ask again when it covers the work.
<!-- paper-scripts:begin managed-feature-cleanup -->
- After a feature branch has been published, do not leave it pending: verify that every listed non-base branch has been integrated, then run `paper clear-feature-branches` to remove published feature branches locally and from GitHub.
<!-- paper-scripts:end managed-feature-cleanup -->
- Inspect the existing layout, notation, macros, and build instructions before editing.
- Keep research knowledge (derivations, conjectures, examples, reusable proof audits) in `notes/`. Keep task management, checkpoints, and revision-specific verification in `tasks/`; link between them instead of duplicating content.
- Preserve pre-existing user edits. Make the smallest change sufficient for correctness; avoid unrelated stylistic changes.
- Preserve the proof strategy unless asked to redesign it. Do not silently strengthen assumptions or claims.
- Check index ranges, stopping times, conditioning, constants, and parameter regimes explicitly. Distinguish conjectural, conditional, and proved claims.
- Prefer explicit algebraic derivations and compact inequality chains. For repeated calculations, cite the analogous argument and give the needed result.

## Poster LaTeX and verification (beamerposter + TikZ)

### One canvas per complex block

- Use the existing beamerposter theme and build workflow. Inspect its block body dimensions and padding before editing; distinguish the body canvas from the title and page/column gutters.
- Any block with a nontrivial internal layout MUST use ONE fixed-size TikZ picture/canvas that owns the full internal layout: text, equations, figures, and annotations. Simple vertical text blocks may remain ordinary LaTeX.
- Do not construct complex blocks with ad-hoc nested minipages, `\hspace`, `\vspace`, `\quad`, negative spacing, repeated manual nudges, or independent pictures positioned by surrounding glue. Text wrapping or an aligned equation inside a node is content, not a second layout system.

### Geometry

- Define explicit named canvas width and height variables (`boxW`, `boxH`) and relevant gaps, padding, row/column sizes, and boundaries. Use one consistent unit system and coordinate origin throughout a block.
- Solve the layout equations exactly before placing content. For two equal columns filling width `W` with gap `g`, encode `w=(W-g)/2`, `leftX=w/2`, and `rightX=w+g+w/2`. Derive `centerX=W/2`, `centerY=H/2`, row centers, object centers, and reference lines similarly. With padding `p`, solve `2p+2w+g=W` instead.
- Design choices such as the canvas height or gap may be chosen explicitly; positions constrained by those choices must be computed, not guessed. Avoid unexplained magic-number positional tweaks whenever geometry determines the position.
- Separate source sections for Geometry / Content / Debug overlay. Change named dimensions and re-solve the constraints rather than accumulating x/y shifts.
- Size or measure major objects, including multiline text heights and figure dimensions, so they fit their allocated cells. If content overflows, revise the dimensions or content; a fixed bounding box must not hide an overflow problem.

### Anchors and padding

- Default every major node/object to `anchor=center`, placed at its derived center coordinate. Use another anchor only for a concrete geometric reason, such as baseline or deliberate boundary alignment, and explain that reason in the source. Do not casually mix coordinate conventions.
- Default major layout nodes to `inner sep=0pt, outer sep=0pt`. Remove accidental block-body padding/margins from the canvas wrapper using the theme's appropriate mechanism. If padding is intentional, name it and include it in the equations; do not silently add it outside the canvas.
- Set an explicit fixed bounding box, e.g. `\path[use as bounding box] (0,0) rectangle (\boxW,\boxH);`, before placing objects. Keep subsequent content and debug paths inside an `overlay` scope (or an equivalent bounding-box-neutral mechanism) so incidental paths cannot change the box size. Do not put the entire picture in `overlay` mode: it must reserve the declared canvas space in the block.

### Global debug mode

- Define `\newif\ifposterdebug` once in the poster preamble and default to `\posterdebugfalse`. Use `\posterdebugtrue` to enable diagnostics globally; every complex block must honor that same conditional. Reuse an equivalent existing project flag if present.
- Under `\ifposterdebug ... \fi`, draw the canvas wireframe, `centerX`/`centerY` axes, row/column boundaries, relevant alignment/reference lines, major object bounding boxes, and center points/anchors. Add coordinate labels when useful. Derive every debug mark from the SAME variables and named nodes as the content.
- Draw diagnostics in an `overlay` scope; all debug labels and marks must be excluded from bounding-box calculations. Do not conditionally change dimensions, anchors, content, padding, or surrounding spacing. Debug on/off MUST have identical production geometry, reserved width/height/depth, and object positions.
- For rectangular layout nodes, draw bounding boxes from `(name.north west)` to `(name.south east)` and centers from `(name.center)`. For other shapes or transformed graphics, use their actual measured extents and relevant anchors. Include both allocated cell boundaries and actual object bounds so overflow and unequal margins are visible.

Minimal two-column body pattern (requires TikZ; define the global conditional in the preamble). The example uses numerical point coordinates, a chosen height ratio and gap, and one row. Adapt the Geometry section to the actual block; extend the overlay for additional rows and objects.

```latex
\begin{tikzpicture}[x=1pt,y=1pt,
  every node/.style={rectangle,anchor=center,inner sep=0pt,outer sep=0pt}]
  % Geometry: \linewidth is the usable block-body width, in TeX points.
  \pgfmathsetmacro{\boxW}{\the\linewidth}
  \pgfmathsetmacro{\boxH}{0.55*\boxW}
  \pgfmathsetmacro{\gap}{0.04*\boxW}
  \pgfmathsetmacro{\colW}{(\boxW-\gap)/2}
  \pgfmathsetmacro{\centerX}{\boxW/2}
  \pgfmathsetmacro{\centerY}{\boxH/2}
  \pgfmathsetmacro{\leftX}{\colW/2}
  \pgfmathsetmacro{\rightStart}{\colW+\gap}
  \pgfmathsetmacro{\rightX}{\rightStart+\colW/2}
  \path[use as bounding box] (0,0) rectangle (\boxW,\boxH);
  \begin{scope}[overlay]
    % Content: center coordinates follow the solved geometry.
    \node[text width=\colW pt,align=center] (left)
      at (\leftX,\centerY) {Left content};
    \node[text width=\colW pt,align=center] (right)
      at (\rightX,\centerY) {Right content};
    % Debug overlay: never contributes to the picture's bounding box.
    \ifposterdebug
      \draw[red,thin] (0,0) rectangle (\boxW,\boxH);
      \draw[red,dashed] (\centerX,0) -- (\centerX,\boxH)
        (0,\centerY) -- (\boxW,\centerY);
      \draw[blue,dotted] (\colW,0) -- (\colW,\boxH)
        (\rightStart,0) -- (\rightStart,\boxH);
      \foreach \name in {left,right} {
        \draw[magenta,thin] (\name.north west) rectangle (\name.south east);
        \fill[magenta] (\name.center) circle[radius=1pt];
      }
    \fi
  \end{scope}
\end{tikzpicture}
```

The [TikZ bounding-box](https://tikz.dev/tikz-actions#sec-15.8) and
[overlay documentation](https://tikz.dev/tikz-shapes#sec-17.13) describe the
bounding-box controls used in this pattern.

### Visual verification

- Preserve existing notation, macros, labels, references, and mathematical meaning. Do not replace custom macros with expanded LaTeX or add packages without need.
- After changing LaTeX, compile using the project's build workflow and fix errors caused by the edits. After EVERY nontrivial layout change, render and visually inspect the PDF at whole-poster scale and at readable block scale; successful compilation alone is insufficient.
- Check centering, alignment, balance, readable type sizes, margins, overlap, clipping, and overflow. When useful, compile with debug enabled and inspect the wireframes/reference lines against the actual objects. Compare debug on/off to confirm unchanged geometry.
- Turn debug OFF and recompile/inspect the production PDF before delivery or authorized publication. Record the build command, visual checks, and any unresolved verification limitation; do not claim visual verification when no renderer/viewer was available.
- Summarize mathematical/content changes separately from layout/typographical changes.

<!-- paper-scripts:begin managed-drafting -->
## Local PDF workflow

- After source edits run `paper build [ROOT.tex]` (default `main.tex`) and fix
  introduced errors before completion. PDF/auxiliaries belong in ignored `output/`.
  `paper build --watch [ROOT.tex]` rebuilds on saves; `paper view [ROOT.tex]` opens
  an external viewer. Reuse watchers and avoid overlapping one-shot builds.
  Report failures: the viewer may still show older output.

## Scientific writing and notation

- Define unfamiliar technical terms before use (aim at a second-year STEM reader),
  prefer simple precise prose, and use established symbols where appropriate.
- Preserve expressive notation and every index/parameter/argument. Introduce
  shorthand only for materially long expressions, never merely to shorten
  `\xi_{j,t}^{(p)} O_{j,t}^{(p)}`. Omitting dependencies requires explicit user
  authorization separate from authorization for shorthand itself.
- Avoid notation clashes. Separate multiple indices/labels with commas:
  `X_{i,j}`, `X^{(p,q)}`. Spell out logical connections in proofs: "implies",
  "if and only if", etc., rather than `\implies`, `\iff`, or similar symbols.

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
## Codex Cloud GitHub access

- Local Codex clients and other local agents use existing authentication; this
  section applies only in Codex Cloud. There, expect `GH_TOKEN` to be configured as a secret environment variable.
  Check presence only; `gh` reads it automatically. If absent and GitHub is needed,
  ask the user to configure it in the Cloud environment: their token is available in their Google Drive.
  Never request it in chat or print, log, commit, or embed credentials in URLs/arguments.

## Notifications

- Send notifications only when the user or an explicitly invoked workflow authorizes
  them. Use `paper notify --title "TITLE" --message "MESSAGE" [--url "HTTPS_URL"]`;
  it dispatches trusted GitHub Actions. Never call providers/webhooks directly or
  inspect their protected credentials. Discord is the default delivery provider.
- For PDF handoffs use the completed GitHub preview's HTTPS artifact URL; local
  PDFs stay ignored and are not notification URLs. There is no arbitrary PDF-upload
  command. Use the project's output convention (`output/`); report unavailable
  preview links rather than inventing them.
<!-- paper-scripts:end managed-notifications -->

<!-- paper-scripts:begin managed-tasking -->
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
<!-- paper-scripts:end managed-tasking -->
