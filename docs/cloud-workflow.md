# Local and cloud paper workflow

The same commands now work on the laptop and on a cloud checkout:

```text
paper start NAME  → synchronize both remotes, create and back up an isolated branch
paper commit MSG  → local checkpoint
paper backup      → back up committed work to GitHub, trigger a PDF preview
paper publish     → reconcile and publish locally, or wait for privileged CI
paper sync        → refresh the local base after remote work
```

No PR is needed for paper work. Feature branches remain after publication.
`sync` still requires the base branch, and all synchronization/publication
requires a clean worktree and no operation already in progress.

## What changed in synchronization

`start`, `sync`, and local/CI `publish` share one implementation: fetch GitHub
and Overleaf, rebase the local base onto GitHub, then rebase onto Overleaf.
This includes cloud-published work and retains Overleaf's linear-history model.
A conflict stops the command for review; a failed start never creates its feature.
Local sync/start update no remote base. Cloud sync/start ask CI to refresh the
GitHub mirror first; Overleaf is not modified by synchronization.

Publication can rewrite GitHub history after a rebase. Every such push uses
an explicit lease captured before reconciliation. Even an editor's background
fetch cannot make the lease accept a later remote writer. Overleaf is pushed
without force. Backup now uses a normal push: it refuses divergent remote work
instead of potentially discarding it after a background fetch.

GitHub and Overleaf cannot be updated atomically. If GitHub succeeds and the
Overleaf push fails (including a collaborator racing publication), the command
fails and reports Git's error. Review it and retry `paper publish`: the shared
sync reconciles both remotes again. Do not force-push Overleaf.

## One-time setup for an existing paper

1. Install this version of the complete `paper-scripts` checkout (the `lib/` and
   `templates/` directories must stay beside `paper`). Python 3 is now required
   for initialization, notifications, and cloud commands. Pure local Git lifecycle
   operations retain their Bash/Git implementation.
2. Run `paper init` inside the paper repository. Review `.paper/config.json`:

   ```json
   {
     "version": 1,
     "base_branch": "main",
     "overleaf_project_id": "YOUR_PROJECT_ID",
     "root_tex": "main.tex",
     "notify_provider": "pushover"
   }
   ```

   Use the actual Overleaf base branch (`main`, `master`, or another name).
   Initialization infers it from existing Overleaf tracking refs when available.
   Configuration contains identifiers and preferences only, never credentials.
   Existing custom `AGENTS.md` is preserved: add a reference to
   `.paper/WORKFLOW.md` to its workflow section.
3. Run `paper configure-ci` from a private terminal. This creates `paper-publish`
   and `paper-notify` GitHub environments and restricts them to the default
   branch before asking for secrets. Paste the dedicated Overleaf Git token,
   Pushover User Key, and application token into its hidden prompts. Values go
   directly to `gh secret set` over stdin; they never enter the repository.
   Enter at a prompt preserves an already installed secret. This command needs
   repository administration access. Existing weaker/broader environment rules
   are rejected rather than silently altered.
4. Review and commit the generated infrastructure to the **default branch**.
   The privileged workflow refuses dispatches to other branches. Protect this
   branch from unreviewed changes to `.github/` and `.paper/`.
5. Run `paper start preview-test`, make a harmless approved change, commit it,
   and `paper backup`. Open Actions → Paper preview and verify the PDF and phone
   notification. Then explicitly request `paper publish`. Check Overleaf and
   finish by running `paper sync` on another checkout.

For a new project, `paper-init OVERLEAF_ID OWNER/REPO DIRECTORY` preserves its
original repository-creation interface and also invokes `paper init`. Running
it against an existing directory verifies both remote identities before upgrading;
it never repoints a repository or creates a replacement GitHub repository.

GitHub **Pro/Team/Enterprise (including eligible Education benefits)** is needed
for protected environments in private repositories. If your plan does not support
them, setup stops. Do not fall back to repository-level Overleaf secrets: feature
branch workflows could read them. A separate trusted publisher repository is an
alternative architecture, not implemented here.

## Cloud client setup

Install Git, Python 3, GitHub CLI, and this complete scripts checkout. Configure
a remote named `github` pointing to the paper repository (a normal GitHub clone
calls it `origin`; rename it once during environment setup). Authenticate `gh`
with repository access sufficient for Contents write and Actions read/write.
The connected chat integration by itself does not guarantee those CLI permissions.
Do not give the cloud environment the Overleaf token or notification credentials.

Set `PAPER_EXECUTION=cloud` in the environment, or run
`git config paper.execution cloud` once in that checkout. In automatic mode,
checkouts with an Overleaf remote use local execution; checkouts without one use
cloud execution. Explicit cloud mode is recommended for disposable environments.
A local authentication/network failure never silently becomes a cloud publication.

`paper start` asks CI to synchronize Overleaf into GitHub, waits, then branches
from the refreshed base. `paper publish` backs up the committed branch and sends
its exact SHA to the default-branch workflow. It waits for that uniquely identified
run, fails on cancellation/conflicts/stale SHA, and refreshes the local base only
after success. A timeout means the job may still be running; inspect the printed
run link or the Actions list before retrying.

The workflow serializes sync/publication with a shared concurrency group. GitHub
may replace a pending run when newer work arrives; the waiting client reports
cancellation rather than claiming success. It does not retry a cancelled publish
automatically. Local writers are still protected by Git leases and Overleaf's
non-fast-forward rejection.

## Preview and notifications

The unprivileged push workflow compiles with `latexmk -norc -no-shell-escape` and
uploads `paper-preview`, retained for 14 days. The first version uses private
GitHub artifacts: sign in to download the ZIP containing `paper.pdf`. It is not
a public, persistent PDF host or an inline mobile viewer. PDFs are not committed.
Custom `.latexmkrc` is deliberately ignored in CI. The provided Ubuntu package
set supports ordinary pdfLaTeX papers; adjust the trusted workflow for projects
requiring a different engine or additional packages.

Notification delivery is independent of builds and publication: a notification
failure never changes a successful publication into a failed write. Preview
notifications run in a separate default-branch workflow with protected environment
secrets; they never execute feature source or download artifacts. Publication
notifications run after the writer and include its result and run link.

```bash
# Set these privately in your shell/password-manager integration:
# PAPER_NOTIFY_PROVIDER=pushover
# PAPER_PUSHOVER_USER_KEY=...
# PAPER_PUSHOVER_APP_TOKEN=...
paper notify-test
paper notify --title "Paper ready" --message "Please review the preview" --url "https://..."
```

Providers: `none` (default), `pushover`, and `webhook`. Webhooks receive JSON
`{title,message,url}` at `PAPER_NOTIFY_WEBHOOK_URL` (HTTPS only). Requests have a
20-second timeout, do not follow redirects, and do not log provider response
bodies or URLs. Pushover uses its documented messages API. No reset-window monitor
or automatic Codex-completion detector is included; callers explicitly notify.

## Trust boundary and upgrades

CI checks out the workflow's immutable default-branch SHA with no persisted GitHub
credential. It runs the vendored trusted scripts, fetches content into a disposable
repository with hooks/global configuration disabled, and never compiles there.
The Overleaf token is scoped to that job and passed via a host-restricted Askpass
helper. It is never embedded in a remote URL. The requested branch must still
match its reviewed SHA after fetching; any changes to `.paper/` or `.github/`
relative to the trusted revision are rejected before publication. Upgrade those
files through the owner-controlled local path.

Anyone able to change the trusted default branch or its environment rules is
an administrator of this boundary. Restrict cloud access accordingly. In
particular, do not let unreviewed agent changes replace the privileged workflows.
Use environment secrets, not repository secrets, for the Overleaf token and
notification credentials. Rotate the dedicated Overleaf token before expiration.

`paper init` records generated file hashes in `.paper/manifest.json`. Repeated
runs add missing files, replace only known unedited generated files, preserve
custom configuration and research records, and refuse edited/unmanaged workflow
collisions, symlinked output paths, and newer infrastructure versions. The schema
version describes the manifest/config format; hashes also detect template changes
between releases with the same schema. Interrupted installs can be rerun.

## Verification

```bash
python3 -m unittest discover -s tests -v
bash -n paper paper-init install.sh
```

Tests use temporary real Git remotes for reconciliation and CI publication,
mocked notification/API boundaries, and a real local TeX build when available.
Live GitHub runner behavior, environment policies, phone delivery, and actual
Overleaf publication still require the pilot test; unit tests do not claim those.

References: [GitHub environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows),
[Pushover API](https://pushover.net/api),
[Overleaf Git tokens](https://www.overleaf.com/learn/how-to/Git_integration_authentication_tokens).
