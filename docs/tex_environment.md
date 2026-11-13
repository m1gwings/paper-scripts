# Matching Overleaf builds

Paper Scripts can restore a frozen native TeX installation and enforce a captured
Overleaf compilation baseline. The declaration is portable project data in
`.paper/tex_environment.json`; it contains version information and archive hashes,
not downloaded logs, private paths, credentials or PDF files.

## Enroll a project

In Overleaf, confirm the compiler, TeX Live release and main document. Recompile
from scratch and download the **full compilation log** and resulting PDF from
**Logs and output files**. Use source revisions identical to the local checkout.
Overleaf's Git export does not contain these settings; Paper Scripts does not
claim to discover or update them through Git.

```sh
paper tex capture --log /path/to/overleaf.log --main main.tex
paper tex install
paper build
paper tex compare-pdf output/main.pdf /path/to/overleaf.pdf
```

The supplied default recipe targets the verified pdfLaTeX / TeX Live 2025
combination: packages frozen at 2025-06-15, pdfTeX 1.40.27 from 2025-03-09.
It installs `scheme-full` to support different document classes, languages and
fonts: allow **several GB** and a substantial initial download. This is a candidate
environment, not a guarantee for every Overleaf image labelled 2025. Capture
rejects incompatible engine banners, and builds reject declared version drift.
A failed match requires a reviewed recipe matching that project's actual log.
Existing projects without a declaration retain their current build behavior;
`paper tex status` explicitly reports their parity as unverified.

For a smaller or different frozen installation, supply `--recipe recipe.json`.
The existing stopped-ranking project's `tools/texlive.json` is accepted directly
(the old embedded baseline is ignored in favor of the supplied log). To add
packages, edit the portable recipe's `packages` array and rerun installation;
its new identity gets a separate cache directory. No rolling package updates run.
Do not replace the baseline simply to silence a mismatch. Capture refuses to
replace an existing manifest; deliberate upgrades require reviewing its diff.

## Build and CI behavior

`paper build`, `paper build --watch` and `paper view` select the manifest's main
file, compiler and isolated TeX user trees. They check the full log's engine,
LaTeX kernel and all dated class/package declarations before publishing the PDF.
Missing or different declarations fail the build and preserve the last good
preview. Explicit alternative roots are checked against the same baseline, so a
root with different packages needs its own reviewed project declaration.
Watch mode notices manifest changes. Missing installations fail with a restoration
instruction; there is no silent system-TeX fallback or download during editing.

The managed preview workflow restores the same recipe when the declaration is
present. The preview worker uses its compiler/main file and checks versions before
uploading. As before, CI disables project rc files and shell escape and receives
no publication credentials. Projects needing custom rc rules must account for
that existing restriction. Upgrade project runtimes and generated CI using
`paper init --workflow-only`; custom workflows are preserved and need equivalent
explicit installation/check steps. The shared `paper` command works immediately.

```sh
paper tex status
paper tex check output/.latex/main.log
paper tex compare-pdf output/main.pdf /path/to/overleaf.pdf --dpi 144
```

PDF comparison uses Poppler to rasterize every page with the same renderer,
compares all raster bytes and detects missing pages. Equality is at the selected
resolution (default 144 dpi), not proof of identical PDF objects or behavior at
all zoom levels. Metadata and timestamps are excluded. Matching declared versions
also does not prove identical package/font bytes; the PDF comparison is an
independent output check. New figures or prose naturally require a fresh matching
Overleaf build before comparing.

## Restoration and dependencies

Linux x86_64, Python 3.12+, Perl, curl, tar and xz are required for native restore.
PDF comparison requires Poppler's `pdftoppm`. Install Paper Scripts normally with
`./install.sh`; project runtime upgrades include the installer and default recipe.
No Docker daemon, root installation or global PATH modification is required.
Toolchains are cached under `$XDG_DATA_HOME/paper/texlive/<recipe-hash>` (default
`~/.local/share`). A completed matching installation is reused without downloading
again. `PAPER_TEXLIVE_ROOT` can explicitly select an existing installation for
verification or testing; its actual compiler/package versions remain checked.
Installation serializes concurrent restorations and checks installer/catalogue
SHA-256 values; TeX Live checks package archives. Incomplete trees are preserved
for inspection rather than automatically deleted.

Recipes include `repository`, `installer_sha256`, `catalogue_sha256`, `packages`
and `engine_version` (first line of the engine executable's `--version`). Optional
`engine_repository` and `engine_catalogue_sha256` pin an older engine binary.
`engine_command` defaults to `pdftex`; custom verified recipes can select `xetex`
or `luahbtex`, paired with `--compiler xelatex` or `--compiler lualatex` at capture.
Only the supplied pdfTeX recipe has been validated against the existing paper;
other engines/releases require independently verified recipes. There is no claim
that a full recipe for another Overleaf release can be inferred from a log alone.

Overleaf documents [compiler and release selection](https://docs.overleaf.com/getting-started/recompiling-your-project/selecting-a-tex-live-version-and-latex-compiler)
and its [TeX Live release policy](https://docs.overleaf.com/troubleshooting-and-support/tex-live).
