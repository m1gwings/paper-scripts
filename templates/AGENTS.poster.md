# Scientific poster instructions

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
