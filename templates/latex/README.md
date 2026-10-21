# Shared LaTeX package and starter sources

Edit papermacros.sty here for future projects. It is the only maintained shared
macro package, used by all three starter types. Keep research-specific notation
and algorithm names in each project's projectmacros.tex.

Each project vendors a pinned package and starter templates. Ordinary paper init
upgrades untouched shared packages using manifest hashes, preserves edited
packages, and never regenerates existing document sources. paper init --force
explicitly reinstalls the selected starter and backs up differing starter files.
Existing legacy projects are not automatically migrated.

## Package options

    \usepackage[profile=paper,review=visible,theorems=external]{papermacros}

| Option | Values and default |
| --- | --- |
| profile | paper (default), slides, poster |
| review | visible (default), applied, reverted |
| theorems | external (default), standard (explicit opt-in) |
| algorithms | false (default), true to load algorithm and algpseudocode helpers |
| labels | true (default), false to hide short author/type labels |

External means that the project or venue owns theorem environments. The generic
paper starter explicitly opts into standard theorem helpers, then defines its
numbered remark and proofsketch in projectmacros.tex. Change that local remark
declaration to an unnumbered one if the venue requires it. Beamer profiles use
Beamer's environments. No margin dimensions, venue files, or page geometry are
changed by the shared package. No caption or enumitem policy is imposed.

Generic mathematics includes \Reals and \Reals[0] (a lower bound), delimiters
such as \norm, \norm*, and \norm[\big], probability/expectation/distribution
operators, and abbreviations. \wp means "with probability". \vec retains its
standard vector accent; use \vecop for the vectorization operator. \st retains
soul's strikeout; use \sucht for "such that". Paper-specific classes, utilities,
regret notation, and algorithm names are intentionally absent.

## Revision API

| Operation | Command |
| --- | --- |
| Addition | \AgentsIns{new} |
| Inline deletion | \AgentsDel{old} |
| Replacement | \AgentsDel{old}\AgentsIns{new} |
| Stacked mathematical replacement | \AgentsReplaceMath{old}{new}, inside math mode |
| Explanatory review box | \Agents{comment} |
| Outer note, inline in presentations | \AgentsOut{comment} |

The same operations are defined for CM, MM, AMM, DA, GG, and Rebuttal.
To add an author, put this in projectmacros.tex:

    \DeclarePaperAuthor{AB}{Author Name}{AB}{0072B2}

The four arguments are command prefix, name, short label, and HTML color.
Public insertion commands end in Ins. There are no Inline or Codex aliases.

\CommentsVisible displays proposed changes and comments. \CommentsApplied
shows insertions and suppresses deletions. \CommentsReverted does the converse.
These switches change rendering only: author review is required to accept or
reject changes permanently in the source. Color is paired with short labels
such as AG+ and AG- by default; deletions always use strikeout.
The dark, Okabe--Ito-derived palette is designed for white backgrounds and
tested for at least 4.5:1 text contrast on white. Labels preserve attribution
when colors are hard to distinguish or output is printed in grayscale. No
finite palette guarantees distinguishability for every color-vision condition.

Revision commands also support section headings and captions through auxiliary-file
round trips. PDF bookmarks use the proposed text in visible/applied mode and the
original text in reverted mode, without review colors or labels.

Use inline deletion for plain text, citations/references, and short math.
For displays or whole proofs, strike safe prose spans and individual math
expressions/alignment cells with \AgentsDel (brace a leading alignment cell as
{\AgentsDel{old}} so TeX enters math mode before expanding it). Keep display
delimiters and environment boundaries outside wrappers. Use the existing review-mode
conditionals to suppress deleted environments in applied mode and restore them
in reverted mode. Do not define or use a separate block-deletion mechanism;
keep old and new labels unique.
Do not put preambles, environment boundaries, verbatim, or arbitrary file edits
inside revision macros. Avoid nesting wrappers. Presentation blocks must fit
their frames; split long revisions. Structural edits should remain valid
LaTeX and be described precisely in the task checkpoint and change report.

The package is not a drop-in replacement for old mymacros files: it deliberately
removes paper-specific definitions and obsolete names. Migration requires
explicitly replacing those dependencies and renaming existing source uses.
