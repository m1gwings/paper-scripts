# Default project instructions

Edit `AGENTS.paper.md`, `AGENTS.poster.md`, or `AGENTS.slides.md` in this folder.
The next `paper create` copies the chosen file to the new project's `AGENTS.md`.
The files are the defaults: there is no second embedded copy to edit and no
build step. Commit your edits to preserve them on GitHub.

You can change the title, editing guidance, verification rules, and other
project-specific sections independently for each project type.

Keep these three pairs of marker comments, with one begin and one end per block:

- `managed-notifications`
- `managed-feature-cleanup`
- `managed-tasking`

These blocks carry the shared lifecycle contracts. Editing their contents also
updates that block in existing projects the next time `paper init` runs there.
Do not remove, rename, duplicate, nest, or cross their begin/end comments.
Malformed templates are rejected before initialization writes any files.

Existing custom instructions outside those blocks survive upgrades. Changing a
default does not silently rewrite existing projects. A missing `AGENTS.md` is
restored from the selected default; an explicit type selection can replace an
untouched current or previously installed template. Previously installed
copies are recognized only when their manifest hashes still match. A customized
`AGENTS.md` is preserved even during a type switch.

Each project vendors its own copies under `.paper/runtime/templates/` for repair
and reproducibility. Edit the defaults here in paper-scripts for future projects,
not a project's vendored copies. To upgrade an existing project, run `paper init`
with the updated paper-scripts installation, then review and commit the changes.
