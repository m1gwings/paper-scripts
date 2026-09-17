# paper-scripts: local and cloud paper workflow

This README is the self-contained architecture and operating reference. It can
be pasted into a new chat to explain the tools, command semantics, trust boundary,
and recovery rules. It describes the implementation; a particular paper gains
cloud support only after its generated workflows are installed on GitHub's default
branch and its protected CI environments are configured.

## Purpose and architecture

Use the same `paper` commands on your laptop and in a cloud coding environment.
Keep unfinished work on feature branches. Review a private PDF from your phone,
then explicitly request publication to Overleaf. The laptop does not need to
remain online for cloud work. No pull request is required for the paper lifecycle.

```text
                           Phone
                    review PDF / give instructions
                              |
                  cloud coding environment
                  paper start / commit / backup
                              |
                              v
Laptop <------------------- GitHub ----------------------+
  |                    base + feature branches           |
  | paper start/sync         |                           |
  |                          +--> unprivileged preview   |
  |                          |    -> private PDF artifact|
  |                          |    -> phone notification |
  |                          |                           |
  |                    paper publish (cloud)             |
  |                          |                           |
  |                    privileged GitHub Actions         |
  |                    fresh sync -> rebase -> publish   |
  |                          |                           |
  +-- paper publish (local) -+---------------------------+
                             |
                             v
                          Overleaf
                    collaborative paper
```

- **Overleaf** is the collaborative publication target.
- **GitHub** holds the base mirror, isolated feature branches, CI workflows, and
  temporary private PDF artifacts. A GitHub backup is not Overleaf publication.
- **The laptop** is another client, not a required gateway for cloud publication.
- **The cloud coding environment** gets GitHub access, never the Overleaf token.
- **GitHub Actions** performs privileged sync/publication using trusted scripts
  and a dedicated Overleaf token held in a protected environment.
- **Pushover** is an optional notification adapter. It can be replaced by an HTTPS
  webhook or disabled without changing the Git workflow.
- Nothing in the protocol depends on a particular OpenAI account. A replacement
  coding account needs its own GitHub access and environment setup.

## Repository and installation layout

The tooling repository is `m1gwings/paper-scripts`. A complete checkout normally
lives in `~/.local/bin`, with `paper`, `paper-init`, `install.sh`, `lib/`,
`templates/`, and `tests/`. Keep the helpers and templates beside the scripts;
copying only the `paper` file is no longer a complete installation.

A paper repository contains:

```text
main.tex, content/, appendix/, ...       manuscript and existing project files
AGENTS.md                              project-specific instructions
notes/                                 research knowledge
tasks/                                 resumable work records
.paper/config.json                     non-secret project settings
.paper/manifest.json                   generated-file ownership hashes/version
.paper/WORKFLOW.md                      lifecycle instructions for coding agents
.paper/runtime/                        pinned copy of paper and its helpers
.github/workflows/paper-preview.yml     unprivileged build on branch pushes
.github/workflows/paper-notify.yml      trusted notification after a preview
.github/workflows/paper-publish.yml     trusted sync/publication on request
```

The runtime is vendored into each paper so CI does not download a moving version
of `paper-scripts` at execution time. Updating the central scripts does not silently
upgrade every paper: run `paper init` and review its changes in each project.

Local paper repositories use `github` and `overleaf` remotes. A cloud checkout
needs `github`; its Overleaf access goes through CI. A normal GitHub clone starts
with an `origin` remote: rename that to `github` once during environment setup.

`<base>` is the actual collaborative branch, detected from Overleaf's cached
HEAD/tracking refs locally and configured explicitly for cloud/CI. It is **not
hard-coded to master**: it may be `main`, `master`, or another valid branch name.
The generated workflows must be on GitHub's default branch. The publisher uses
the configured base branch; the trusted workflow source is always the default
branch. For the CMABs with RUM Feedback pilot, both are `main`.

## Command semantics

| Command | Meaning and side effects |
| --- | --- |
| `paper start NAME` | Require a clean, attached working tree and no Git operation in progress; synchronize the collaborative base; create/switch to NAME; back it up on GitHub. Never publish to Overleaf. |
| `paper commit "message"` | Stage all changes and create a local checkpoint. Push nowhere. Review files before committing; never stage credentials. |
| `paper backup` | Push the current committed branch to GitHub using a normal push. Require a clean working tree. Refuse divergence instead of overwriting remote work. Overleaf is untouched. |
| `paper sync` | Run from the base branch with a clean working tree. Reconcile GitHub and Overleaf into the local base. Local execution writes no remote; cloud execution asks CI to refresh the GitHub mirror first. |
| `paper publish` | Require explicit user publication authorization, committed work, and no Git operation in progress. Reconcile fresh state, integrate the feature, back up on GitHub, and publish to Overleaf. Local and cloud execution are detailed below. |
| `paper init` | Inside an existing Git repository, create research/task files and install or upgrade generated infrastructure. Preserve custom files/configuration. No remote creation, commit, or push. |
| `paper-init OVERLEAF_ID OWNER/REPO [DIRECTORY]` | Create the two-remote project from Overleaf and a new private GitHub repository, then invoke `paper init`. Default directory: `paper`. For an existing directory, verify both remote identities before upgrading; never repoint them. |
| `paper configure-ci [--environments-only]` | Create/verify default-branch-only environments and configure the paper's Overleaf publication credential. Requires GitHub administration access. |
| `paper configure-notifications [--device NAME] OWNER/REPO [OWNER/REPO ...]` | Prompt once and install or rotate notification credentials across all selected papers' protected GitHub environments. |
| `paper notify --title TITLE --message MESSAGE [--url HTTPS_URL]` | Dispatch the trusted GitHub Actions notification workflow; provider secrets never enter the calling environment. |
| `paper notify-test` | Dispatch a simple notification test through GitHub Actions. |
| `paper status` / `paper doctor` | Inspect repository state, remotes, tracking, tools, and cached divergence. Remote divergence is only as fresh as the last fetch. |
| `paper build [ROOT.tex]` / `paper clean [ROOT.tex]` | Build or clean with local latexmk; default `main.tex`. Local build behavior is separate from the restricted CI preview build. |
| `paper open` | Open the repository in VS Code. |
| `paper abort` | Confirm the current non-base branch name, then delete it locally and from GitHub. Never modify Overleaf or the base. |
| `paper clear-experiments` | Confirm `DELETE EXPERIMENTS`, then delete all non-base branches locally and on GitHub. Use cautiously: this includes any non-base branch in that repository. |
| `paper gitignore` | Create the standard LaTeX ignore file only if absent. |
| `paper task status [--all]` / `paper task delete ID ...` | Inspect task records or move selected records into recoverable trash after confirmation. No commits or pushes. |
| `paper help` / `paper examples` | Show command help or sample workflows. |

A synchronization conflict stops `start` before a feature is created. If the
initial feature backup fails after branch creation, the local feature remains
recoverable; inspect status and retry the backup after resolving the cause.

## Shared synchronization and publication invariants

`start`, `sync`, and local/CI `publish` use **one shared synchronization function**:

1. Fetch both GitHub and Overleaf before changing the local base.
2. Capture the exact GitHub base SHA for the later publication lease.
3. Rebase the local base onto the fetched GitHub base, including remote work.
4. Rebase that result onto the fetched Overleaf base, preserving linear history.
5. Stop on conflicts; do not choose a side or discard changes automatically.

Local publication from a feature then reconciles the freshly fetched feature
backup, rebases onto the synchronized base, backs up the feature, fast-forwards
the local base, backs up the base, and pushes it to Overleaf. Publication from the
base performs the same fresh synchronization and the two base pushes. Successful
publication leaves the checkout on the base; feature branches are retained.

The safety rules are:

- `commit` is local, `backup` writes GitHub only, and `publish` makes work collaborative.
- Starting a feature does not publish it. Publication synchronizes again because
  collaborators may edit while the feature is being developed.
- Overleaf is **never force-pushed** by these commands.
- A GitHub history rewrite required by rebasing uses an **explicit lease** tied to
  the SHA captured before reconciliation. An editor's background fetch cannot
  silently refresh that lease. A concurrent remote change causes rejection.
- Dirty worktrees and existing merges/rebases stop synchronization/publication.
- Destructive experiment deletion requires an exact typed confirmation.
- A failed build, conflict, timeout, or rejected push is never reported as a
  successful publication. Notification delivery does not determine write success.
- Generated PDFs are never committed by preview generation. They expire as artifacts.
- Credentials never belong in commits, `.paper/config.json`, Git URLs, logs, or chat.

**The two remote writes are not atomic.** GitHub may update before an Overleaf
push fails. Inspect the failure; rerunning publication refreshes both remotes and
reconciles again. Do not “fix” a race with an unconditional force push. A feature
backup may also succeed before a later publication step fails.

## Local versus cloud execution

`PAPER_EXECUTION=local|cloud|auto` overrides local Git configuration
`paper.execution`. Automatic mode chooses local when an Overleaf remote exists
and cloud otherwise. Explicit `PAPER_EXECUTION=cloud` is recommended in disposable
coding environments. A failed local login/network operation never silently turns
into a cloud publication.

Cloud `start`/`sync` request a privileged CI synchronization and wait. CI reads
Overleaf and refreshes the GitHub mirror; the client then fetches and updates its
base. This closes the stale-GitHub gap without giving Overleaf credentials to the
coding environment.

Cloud `publish` backs up the committed branch, captures its exact SHA, and sends
`operation`, `branch`, `sha`, and a unique request ID to `paper-publish.yml` on the
**default branch** using `gh`. It waits for the matching workflow run, not merely
for dispatch acceptance. CI checks that the branch still matches the requested
SHA after fetching. Changed branches are refused and must be reviewed again.
After success, the client refreshes its base and retained feature reference.

One concurrency group serializes CI sync/publication. Running publication is not
cancelled automatically, but GitHub may replace a pending run; the client reports
that cancellation as a failure. A client timeout does not cancel the job: inspect
Actions before retrying. Automatic duplicate publication is deliberately avoided.

Cloud prerequisites: Git, Python 3, `gh`, the complete scripts installation (or
vendored runtime), and GitHub access for Contents write plus Actions read/write.
Connecting a chat app does not by itself establish those CLI permissions. Never
provision the cloud coding environment with Overleaf or Pushover credentials.

## CI trust boundary

The preview build has read-only repository permissions, no publication/notification
secrets, and no persisted checkout credential. It runs pdfLaTeX through
`latexmk -norc -no-shell-escape`; project `.latexmkrc` is ignored. The Ubuntu TeX
package set supports ordinary pdfLaTeX manuscripts; other engines/packages need
an explicit workflow change.

The privileged publisher checks out the workflow's immutable default-branch SHA
and executes that trusted vendored runtime. It fetches paper content into a
separate disposable repository with hooks and global Git configuration disabled.
It does not compile LaTeX, run feature scripts, or load executable project config.
It rejects changes to `.paper/` or `.github/` relative to the trusted revision
before publishing. Infrastructure upgrades use the owner-controlled local path.
The Overleaf token is passed through a host-restricted Askpass helper, not a URL.

Secrets are stored in **GitHub environments**, not repository-level secrets or
agent environments:

| Environment | Allowed branch | Secrets | Variables |
| --- | --- | --- | --- |
| `paper-publish` | GitHub default branch only | `OVERLEAF_TOKEN`; provider credentials when enabled | `PAPER_NOTIFY_PROVIDER`, optional `PAPER_PUSHOVER_DEVICE` |
| `paper-notify` | GitHub default branch only | Provider credentials only; no Overleaf token | `PAPER_NOTIFY_PROVIDER`, optional `PAPER_PUSHOVER_DEVICE` |

Pushover credentials are `PAPER_PUSHOVER_USER_KEY` and `PAPER_PUSHOVER_APP_TOKEN`.
Webhook credentials/endpoint use `PAPER_NOTIFY_WEBHOOK_URL`.

The separate preview-notification workflow runs from the default branch after
`Paper preview` completes. It reads GitHub run/artifact metadata and never executes
feature source or downloads artifact contents. A manual run of `Paper preview
notification` on the default branch sends a test message using the saved secrets.
Publication sends a result notification after its write steps; notification failure
cannot turn a successful publication into a failed write.

Environment restrictions are not a substitute for protecting trusted source.
Anyone able to modify the default branch or environment rules administers this
boundary. Restrict cloud access to trusted infrastructure accordingly. Private
repository environments require a GitHub plan supporting them (Pro/Team/Enterprise,
including eligible Education benefits). Setup stops if unsupported; it does not
fall back to exposing the Overleaf token through repository secrets.

## Pushover and phone delivery

The Pushover application (for example **Papers**) identifies the sender. Its app
token and your **User Key** are different credentials. The User Key selects your
account; it connects delivery to the devices registered under that account.

1. Install Pushover on the phone and sign in to the account whose User Key was
   entered during setup. Allow notifications in the phone's system settings.
2. Verify the phone is registered/enabled in that Pushover account. No separate
   subscription to the Papers application or phone-specific token is needed.
3. Leave `pushover_device` empty to send to all active account devices, or set it
   to the exact registered name, such as `migwings-A25`, to request that device.
4. Run `paper configure-ci` in each paper after changing its non-secret settings.
5. Run `paper configure-notifications --device DEVICE OWNER/REPO ...` once to
   install or rotate the Pushover credentials across every listed paper.
6. After activating the workflows on the default branch, run `paper notify-test`
   from any configured paper for a phone test.

Pushover may fall back to all active devices if a requested device is invalid or
has been disabled. Device selection is routing, not a credential/access boundary.
The app's own message settings and phone notification permissions control sound
and alerts. The registered device name is non-secret.

Local and cloud callers use the same `paper notify` command. It dispatches the
trusted default-branch GitHub Actions workflow and waits for the exact run. The
workflow reads the configured provider/device and credentials from the protected
`paper-notify` environment. Notification secrets are never copied into a local or
Codex agent environment.

Adapters are `none` (default), `pushover`, and `webhook`. Webhooks receive JSON
`{title,message,url}` over HTTPS. Delivery has a 20-second timeout, rejects redirects,
and does not print provider response bodies or credential-bearing URLs.

PDF notifications link to private GitHub artifacts. Sign in to GitHub to download
`paper.pdf` directly, without ZIP extraction. Artifacts are retained for 14 days;
this is not permanent/public PDF hosting. Phone viewing depends on the browser.
There is no built-in credit-reset monitor or general coding-agent completion
listener; callers invoke `paper notify` explicitly.

## Installation, configuration, and safe upgrades

For a new tooling installation, when `~/.local/bin` is not already a checkout:

```bash
git clone https://github.com/m1gwings/paper-scripts.git ~/.local/bin
~/.local/bin/install.sh
```

For an existing installation, inspect its status and fast-forward from the tooling
repository's `main`. Preserve local modifications and unrelated files; never use
`reset --hard`, replace the directory, or remove an existing checkout just to
upgrade. `install.sh` checks command availability and can add `~/.local/bin` to
PATH; it does not install system packages. Reload the shell if PATH changed.

Requirements: Bash and Git; Python 3.9+ for initialization, task commands,
notifications, and cloud support; `gh` for setup/cloud requests; `latexmk` and TeX
for local builds. VS Code is optional. Basic local Git lifecycle operations remain
Bash/Git operations.

Inside each existing paper, run `paper init` and review this non-secret config:

```json
{
  "version": 2,
  "base_branch": "main",
  "overleaf_project_id": "YOUR_PROJECT_ID",
  "root_tex": "main.tex",
  "notify_provider": "pushover",
  "pushover_device": "migwings-A25"
}
```

The base and project ID are inferred from existing Overleaf refs/URL when available.
Missing information must be configured before cloud use. `root_tex` controls the CI
preview entry point; local `paper build` still takes its own optional argument.

`paper init` records generated hashes in `.paper/manifest.json`. Repeated runs
repair missing files and update known unedited generated files. Custom configuration
fields, hand-written `AGENTS.md`, research notes, and task records are preserved.
Edited/unmanaged workflow collisions, symlinked output paths, and newer unsupported
schema versions stop the upgrade for review. Never hand-edit the manifest to
bypass a collision. The schema version covers the format; hashes also detect
runtime/template changes between releases with the same schema version.
Untouched generated agent instructions can be upgraded; custom instructions remain
user-owned. Add a reference to `.paper/WORKFLOW.md` to an existing custom AGENTS file.

After review, commit the generated files to the paper's default branch, protect
the trusted paths, and run `paper configure-ci` from a private terminal. Setup
verifies branch restrictions before any hidden credential prompt. Use a dedicated
Overleaf Git token for CI; keep the laptop's credential separate. Configure
notifications for all papers in one batch with `paper configure-notifications`.
Overleaf uses username `git` and the Git token as password. Tokens expire and must
be rotated; never use your university/SSO password or paste a token into a chat.

For a new paper, use `paper-init OVERLEAF_ID OWNER/REPO DIRECTORY`, then review the
newly generated configuration and complete the same protected CI setup. Initial
repository creation is distinct from publishing later manuscript edits.

## Research notes, tasks, and agent instructions

Keep reusable research knowledge in `notes/`, and execution checkpoints in
`tasks/NNN_short_name/task.md`; link each record from `tasks/index.md`. Each record
has one status (`queued`, `active`, `paused`, `blocked`, or `done`), steps, verification,
and a next concrete action. `paper task status` reports declared metadata, not
proof correctness. A checkpoint supports later resumption; it does not automatically
restart a task after a quota limit or interruption.

Task deletion requires the displayed folder names and moves records into a
batch under `tasks/.trash/`, with the original index preserved. Restore selected
folders and index rows manually; do not overwrite newer queue changes. Task
commands do not modify manuscript/research files or commit anything.

Coding agents should inspect project instructions and preserve existing work,
use `paper` for repository lifecycle operations, and publish only on explicit user
authorization. Raw Git is reserved for initial setup, tooling maintenance, and
conflict recovery. Do not automatically resolve mathematical or textual conflicts.

## Typical work and recovery

```bash
paper start lemma-fix
# edit and verify
paper commit "Clarify the lemma"
paper backup
# review the preview; then explicitly authorize publication
paper publish
# later, on another checkout's base branch
paper sync
```

For a rebase conflict, inspect `git status`, resolve only understood conflicts,
then `git add` the resolved files and `git rebase --continue`. To abandon that
rebase, use `git rebase --abort`, then inspect `paper status`. Earlier successful
steps may already have updated a local base or GitHub backup. Never assume a
multi-step command was rolled back entirely. A failed cloud job leaves the local
feature available; inspect its Actions run before retrying.

## Tests and verification limits

```bash
python3 -m unittest discover -s tests -v
bash -n paper paper-init install.sh
```

Tests use real temporary Git repositories for local/CI synchronization, races,
conflicts, and preservation, plus simulated cloud dispatch/notifications and a
local TeX smoke test when installed. GitHub's tooling CI runs these checks. Live
phone receipt, actual Overleaf writes, account permissions, and mobile PDF viewing
require an end-to-end test for the configured paper; passing unit tests alone does
not establish them.

The CMAB pilot has passed a hosted build and direct PDF artifact upload. This
fact does not imply that its privileged publication has been run. Consult the
paper's current workflow checkpoint and Actions results for rollout status.

Official references: [Pushover API](https://pushover.net/api),
[GitHub environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[GitHub workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows),
[Overleaf Git tokens](https://www.overleaf.com/learn/how-to/Git_integration_authentication_tokens).
