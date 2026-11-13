# Automatic Overleaf build synchronization

`paper create` enrolls a project automatically: it retrieves the selected compiler,
TeX Live image and main document over HTTP, downloads the cloud log/PDF/source,
restores the native toolchain, and builds the matching source in a disposable
local directory. It compares declared engine/kernel/package versions and every
rendered page at 72 dpi. Current Editor buffers are never used for this check.
No manual log download, recipe editing, agent, MCP call or GUI automation is part
of the routine workflow. Website creation itself is a separate operation.

`paper sync` and `paper publish` refresh this verification. `paper build --watch`
schedules background refreshes at most every five minutes; one-shot builds also
schedule a refresh when due. Network access, installation and comparison stay off
the typing/navigation path. Cloud refresh never publishes local draft edits.

## Status and failure behavior

Reader shows a dismissible amber **Overleaf verification** notice, with a small
status control retained after dismissal. Editor's build status includes
**Overleaf ⚠**, and its Build panel explains the warning. CLI builds print it too.
Local compilation and the last good PDF remain available when HTTP capture fails.
Missing/locked cookies, expired authentication, network/rate-limit errors,
interface changes, unavailable restoration profiles and stale verification have
separate diagnostic codes. A failed refresh does not overwrite the last verified
environment or claim current parity. A genuine compiler error remains a build
failure, separate from a verification warning.

Portable compiler settings and frozen recipes live in `.paper/tex_environment.json`.
Runtime status, downloaded artifacts and the verification log live in ignored
`output/.overleaf/`. ZIP timestamps do not cause redundant verification; source
contents determine the proof identity. The selected main file is reflected in
`.paper/config.json`, so Reader/Editor agree with the build command.

Local draft changes can add/remove packages; builds compare versions of shared
package declarations and always check the engine/kernel. The stricter complete
package/class comparison and pixel comparison run against the exact cloud source.
Pixel equality is at the recorded resolution; PDF metadata/timestamps and PDF
object byte identity are not compared.

## Standalone connector and repair

The machine provides a `workspace-overleaf` HTTP connector. Paper Scripts invokes
its command interface; it has no dependency on an AI provider or browser driver.
`PAPER_OVERLEAF_HELPER` can select a compatible executable elsewhere. Authentication
stays in local browser storage/keyring; no cookies or session values belong in
project files, logs, command arguments, Git or agent messages.

Optional inspection/recovery commands:

```sh
paper tex status
paper tex sync
paper tex sync --fresh
workspace-overleaf diagnose --project PROJECT_ID
paper tex check output/.latex/main.log
paper tex compare-pdf output/main.pdf /path/to/reference.pdf
```

The connector's `http_contract.json` owns routes, CSRF metadata/header names and
required response fields. Unexpected redirects, HTTP errors, schema changes and
invalid artifacts fail explicitly. Its sanitized diagnose output identifies the
failing route/field without printing credentials. Repair requires one targeted
browser/network inspection, updating that adapter and rerunning its contract tests;
routine captures continue as HTTP calls. See the connector's README for the exact
repair procedure. Credentials are never recovered by an agentic repair.

## Restoration and supported environments

The included profiles cover the observed Overleaf `texlive-full:2025.1` and
`texlive-full:2026.1` environments, with frozen repositories and checked installer/
catalogue hashes. The 2025 profile pins the original pdfTeX binary independently
of its newer packages. The 2026 profile resolves additional packages from actual
log input paths and its immutable catalogue, including generated bitmap fonts.
Frozen environments share a cache across projects; adding packages expands the
same frozen tree rather than installing another copy. Both pdfLaTeX and XeLaTeX
are verified against the projects that use them. Other compilers can use suitable
verified profiles; unknown images produce a warning instead of silently choosing
a different annual release.

Native restoration needs Linux x86_64, Python 3.12+, Perl, curl, tar and xz.
Poppler's `pdftoppm` is required for output verification. `./install.sh` installs
Paper Scripts command links. `paper init --workflow-only` deploys the shared runtime
conservatively to existing projects; custom Actions workflows are preserved and
must use the same installer/build declaration. The managed preview worker uses
the selected compiler, root and Overleaf job name (`output`), then checks versions.
CI has no browser cookies or publication credentials in the build worker.

The shared profiles install the packages identified from actual Overleaf logs,
rather than an entire TeX distribution. Both are expanded automatically when a log
requires another package; subsequent projects reuse the same frozen cache. Cache roots live below `$XDG_DATA_HOME/paper/texlive/`
(default `~/.local/share`). `PAPER_TEXLIVE_ROOT` is an explicit testing override.
No global PATH change, Docker daemon or root TeX installation is needed.
`PAPER_OVERLEAF_AUTO=0` disables background scheduling for isolated/test builds.

Sources: Overleaf's public server routes/compile-cache implementation and
[compiler selection](https://docs.overleaf.com/getting-started/recompiling-your-project/selecting-a-tex-live-version-and-latex-compiler),
[generated outputs](https://docs.overleaf.com/navigating-in-the-editor/generated-files),
[system LatexMk configuration](https://docs.overleaf.com/managing-projects-and-files/the-latexmkrc-file).
