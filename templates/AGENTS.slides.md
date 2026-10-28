# Scientific slides instructions

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
- Prefer explicit algebraic derivations and compact inequality chains. For repeated calculations, cite the analogous argument and give the needed result.

## Slides LaTeX and verification (Beamer + TikZ)

### One canvas for a complex slide

- Author slides in LaTeX Beamer. Inspect the existing theme, aspect ratio, frame title/footer, macros, and build workflow before editing. Simple layouts may use ordinary Beamer and LaTeX constructs.
- Implement each non-trivial layout as ONE full-slide TikZ picture that owns its text, equations, figures, and annotations. Do not assemble complex layouts from nested boxes/minipages or fragile manual spacing and visual nudges.

### Geometry, anchors, and bounds

- Treat the slide as a precise coordinate system. Derive `slideW` and `slideH` from `\paperwidth` and `\paperheight`; name safe-area margins, centers, object widths/heights, gaps, and row/column boundaries. Use one origin and unit system. Account explicitly for any frame title, footline, or theme padding.
- Solve placements before drawing. For two equal columns in usable width `W`, side margin `p`, and gap `g`, encode `w=(W-2p-g)/2`, `leftX=p+w/2`, and `rightX=p+w+g+w/2`; derive row centers and alignment lines similarly. Choose design dimensions deliberately, then compute constrained positions instead of nudging them.
- Default major TikZ nodes to `anchor=center` at derived centers, with `inner sep=0pt, outer sep=0pt`. Use another anchor only for a concrete geometric reason, and include any intentional padding in the equations. Use semantic coordinate and node names; separate Geometry / Content / Debug sections.
- Allocate text and figures within named cells and check their actual bounds. If content changes or overflows, revise the cells or content; do not hide overflow with a fixed canvas or add unexplained offsets.
- For a plain frame, anchor the full-slide picture at `current page.south west` with `remember picture,overlay`. The Beamer page itself has fixed dimensions; do not let nodes, labels, or guides alter the frame layout. For a frame with theme chrome, derive the usable region inside the page rather than assuming the whole page is available.

### Reusable layout guides

- Define one preamble-wide boolean, for example `\newif\ifslidesdebug` with `\slidesdebugfalse` by default; use `\slidesdebugtrue` to inspect every complex slide. Reuse an existing equivalent flag if the project has one.
- Under `\ifslidesdebug ... \fi`, draw guides from the SAME named geometry and nodes as the content: slide bounds, safe-area/margin lines, horizontal and vertical centers, relevant grid/alignment lines, named reference coordinates, and useful object bounding boxes and anchors.
- Draw guides in a bounding-box-neutral TikZ overlay/scope. Show both allocated cells and actual node bounds, using `(name.north west)` to `(name.south east)` and `(name.center)` for rectangular nodes. Toggling the flag must remove every guide in normal mode without changing the canvas size, content placement, or surrounding Beamer layout.

Minimal two-column plain-frame pattern (requires TikZ; adapt the named safe area to the theme). Enable `\slidesdebugtrue` in the preamble when inspecting layout, then restore `\slidesdebugfalse`:

```latex
% Preamble, after loading TikZ:
\newif\ifslidesdebug
\slidesdebugfalse

% In the document:
\begin{frame}[plain]
\begin{tikzpicture}[remember picture,overlay,x=1pt,y=1pt,
  every node/.style={anchor=center,inner sep=0pt,outer sep=0pt}]
  % Geometry: one page coordinate system, origin at its lower-left corner.
  \pgfmathsetmacro{\slideW}{\the\paperwidth}
  \pgfmathsetmacro{\slideH}{\the\paperheight}
  \pgfmathsetmacro{\marginX}{0.08*\slideW}
  \pgfmathsetmacro{\marginY}{0.12*\slideH}
  \pgfmathsetmacro{\gap}{0.04*\slideW}
  \pgfmathsetmacro{\colW}{(\slideW-2*\marginX-\gap)/2}
  \pgfmathsetmacro{\leftX}{\marginX+\colW/2}
  \pgfmathsetmacro{\rightX}{\leftX+\colW+\gap}
  \pgfmathsetmacro{\centerX}{\slideW/2}
  \pgfmathsetmacro{\centerY}{\slideH/2}
  \begin{scope}[shift={(current page.south west)}]
    % Content: centers follow the solved geometry.
    \node[text width=\colW pt,align=center] (left)
      at (\leftX,\centerY) {Left content};
    \node[text width=\colW pt,align=center] (right)
      at (\rightX,\centerY) {Right content};
    % Debug: derives from the same dimensions and nodes; changes no geometry.
    \ifslidesdebug
      \draw[red,thin] (0,0) rectangle (\slideW,\slideH);
      \draw[orange,dotted] (\marginX,\marginY) rectangle
        (\slideW-\marginX,\slideH-\marginY);
      \draw[red,dashed] (\centerX,0) -- (\centerX,\slideH)
        (0,\centerY) -- (\slideW,\centerY);
      \foreach \name in {left,right} {
        \draw[magenta,thin] (\name.north west) rectangle (\name.south east);
        \fill[magenta] (\name.center) circle[radius=1pt];
      }
    \fi
  \end{scope}
\end{tikzpicture}
\end{frame}
```

### Overlays and verification

- If using Beamer overlays or animations, keep the TikZ canvas, named coordinates, and reserved dimensions stable across all overlay states. Reveal content without shifting other objects or removing reference nodes needed by the guides; check every state for overlap and clipping.
- Compile with the project's build command and visually inspect every rendered overlay after non-trivial layout changes. Inspect debug guides against actual objects, then turn debug off, recompile, and inspect the final PDF. Record the build command and any verification limits.
- Preserve mathematical meaning, notation, macros, labels, and references; summarize content changes separately from layout changes.

<!-- paper-scripts:begin managed-drafting -->
## Local PDF workflow

- After source edits, follow `.paper/WORKFLOW.md#local-pdf-workflow` for the
  required build, ignored output directory, and reuse of the existing watcher.
  Report compilation failures; a viewer may still show an older PDF.

## Scientific writing and notation

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
