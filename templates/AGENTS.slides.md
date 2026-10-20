# Scientific slides instructions

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
## Draft revisions and review

- Unless the user explicitly asks otherwise, track manuscript edits using the collaboration API actually loaded by the project. The paper-scripts starter loads `papermacros.sty`: use `\AgentIns{new}`, `\AgentDel{old}`, and `\AgentDel{old}\AgentIns{new}` for replacements. Use `\Agent[MODEL NAME]{comment}` for an explanatory review box and `\AgentOut[MODEL NAME]{comment}` for an outer note (inline on slides/posters).
- Model attribution is required for new Agent comments: supply your actual model name in the optional argument, e.g. `\Agent[GPT-6 Astra]{Check this assumption.}`. Apply the same rule to `\AgentOut`. The name replaces “Agent” in the rendered title; the AG cue remains. Use only identity supplied by the execution environment; never guess a model or version. If it is unavailable, use `\Agent[Model unavailable]{...}` and state that limitation in the task checkpoint. Keep existing comments unchanged. First verify that the loaded macro supports this optional argument; legacy project macros and their review policies still take precedence.
- Use `\AgentDelBlock{...}` for deleted paragraphs, proofs, displays, or environments that cannot safely go inside an inline strikeout. Use `\AgentReplaceMath{old}{new}` inside math mode for a displayed replacement that stacks the two versions. These commands support all three review modes. In Beamer frames, split large blocks to fit the frame; frames are not automatically paginated.
- Never wrap a whole file, preamble, package definition, environment boundary, verbatim material, or other syntactically incompatible change in an inline revision command. Keep labels unique across visible old/new material. Record structural/non-LaTeX changes precisely in the task checkpoint and change report.
- Preserve existing author/reviewer markup; use the appropriate author commands only when attributing that person's changes. Do not nest revision wrappers or silently relabel someone else's work as agent work. The shared API uses `Ins` as the primary insertion name; do not introduce `AuthorInline` or `Codex...` aliases.
- `\CommentsVisible` shows revisions, `\CommentsApplied` renders insertions and hides deletions, and `\CommentsReverted` hides insertions and restores deletions. Rendering a clean PDF does not accept/reject changes in source. Preserve the project's selected mode unless the task requests another; use visible mode for draft review. Permanently accepting/rejecting changes requires user authorization.
- Existing projects may load older `\CodexIns`, `\CodexDel`, or other collaboration macros. Inspect their loaded definitions and follow their project-specific review/rebuttal policy. Do not insert undefined Agent commands, import a second macro package, rename old commands, or migrate old markup implicitly. If no tracking API exists, report that limitation instead of silently adding one.
- After edits, compile and check the affected document. When changing shared review macros, validate visible/applied/reverted output including citations, references, math, and block edits. Keep paper-specific notation in `projectmacros.tex`; theorem and remark numbering belongs to the project or venue setup. Never modify a venue style file to accommodate the shared package.
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
