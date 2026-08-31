cat > README.md <<'EOF'
# scripts

Personal Linux command-line utilities.

The repository is intended to be cloned directly into:

```bash
~/.local/bin
```

so that its executable files are automatically available on `PATH`.

## Installation

On a new machine:

```bash
git clone git@github.com:YOUR_USERNAME/scripts.git ~/.local/bin
~/.local/bin/install.sh
source ~/.bashrc
```

Replace `YOUR_USERNAME` with the appropriate GitHub username.

No passwords, authentication tokens, API keys, or other secrets should
ever be committed to this repository.

---

# Paper workflow

Two commands implement the paper-writing workflow:

```bash
paper
paper-init
```

The architecture is:

```text
                    collaborators
                         |
                         v
                    Overleaf
                         |
                         | overleaf/master
                         v
                   local repository
                     /         \
                    /           \
             local branches    GitHub
                              private mirror
```

## Repository assumptions

Paper repositories have two remotes:

```text
overleaf    -> Overleaf
github      -> private GitHub repository
```

The collaborative branch is:

```text
master
```

The intended roles are:

```text
overleaf/master
    Collaborative/published version of the paper.

github/master
    Private mirror/backup of master.

github/<feature>
    Experimental work.
```

GitHub is treated as a personal mirror and experimental-branch store.

Overleaf is treated as the collaborative publication target.

---

# Mental model

There are three important operations.

## Commit

```bash
paper commit "message"
```

Creates a **local Git checkpoint**.

Nothing is pushed anywhere.

## Backup

```bash
paper backup
```

Pushes the current committed branch to **GitHub**.

Overleaf is untouched.

## Publish

```bash
paper publish
```

Integrates the current work into `master` when necessary, backs it up to
GitHub, and sends `master` to **Overleaf**.

This is the normal operation that makes collaborators see your changes.

---

# Everyday commands

## See where you are

```bash
paper status
```

Shows:

- current branch;
- working tree;
- local branches;
- remotes;
- cached divergence from GitHub and Overleaf.

If you return to a project after a long time, start here.

## Get collaborators' latest changes

While on `master`:

```bash
paper sync
```

This updates local `master` from Overleaf.

## Make a local checkpoint

```bash
paper commit "Fix lower bound argument"
```

## Back up without publishing

```bash
paper backup
```

This changes GitHub only.

## Start an experiment

```bash
paper start case3-rewrite
```

This:

1. updates `master` from Overleaf;
2. creates `case3-rewrite`;
3. creates its backup branch on GitHub.

Overleaf remains untouched.

## Publish

```bash
paper publish
```

From `master`, it publishes `master`.

From a feature branch, it:

1. updates `master` from Overleaf;
2. rebases the feature branch onto current master;
3. backs up the feature branch;
4. fast-forwards master;
5. backs up master;
6. pushes master to Overleaf.

## Abandon the current experiment

```bash
paper abort
```

This permanently deletes the current non-master branch locally and from
GitHub.

It asks you to type the exact branch name.

It never modifies Overleaf.

## Delete all experiments

```bash
paper clear-experiments
```

This deletes every non-master branch locally and on GitHub.

It requires the exact confirmation:

```text
DELETE EXPERIMENTS
```

It never modifies Overleaf or master.

---

# Examples

The easiest way to remember the intended workflows is:

```bash
paper examples
```

The complete command reference is:

```bash
paper help
```

---

# Typical small change

```bash
paper sync
paper open

# edit...

paper commit "Clarify Lemma 7"

# perhaps more work...

paper commit "Fix proof notation"

paper publish
```

---

# Typical large experiment

```bash
paper start new-lower-bound

# work...

paper commit "First construction"
paper backup

# more work...

paper commit "Complete information-theoretic argument"
paper backup
```

If successful:

```bash
paper publish
```

If unsuccessful:

```bash
paper abort
```

---

# Creating a new paper

Suppose the Overleaf project ID is:

```text
abc123def456
```

and the desired private GitHub repository is:

```text
bandits-with-logic
```

Run from the directory that should contain the paper:

```bash
paper-init abc123def456 bandits-with-logic
```

By default this creates:

```text
./paper
```

You may specify another local directory:

```bash
paper-init abc123def456 bandits-with-logic manuscript
```

You may specify an organization:

```bash
paper-init abc123def456 my-organization/bandits-with-logic paper
```

Run:

```bash
paper-init --help
```

for details.

---

# Overleaf authentication

Overleaf Git authentication is separate from university SSO.

When cloning or pulling, Git may ask:

```text
Username:
Password:
```

The username is:

```text
git
```

The password is your **Overleaf Git authentication token**, not your
university/SSO password.

Never save that token in this repository.

---

# Conflicts

A Git conflict during:

```bash
paper sync
```

or:

```bash
paper publish
```

is not automatically resolved.

Inspect the situation:

```bash
git status
```

Resolve the conflicting files manually, then:

```bash
git add <resolved-files>
git rebase --continue
```

Repeat if necessary.

To abandon the rebase:

```bash
git rebase --abort
```

Then:

```bash
paper status
```

Do not blindly use destructive commands such as:

```bash
git reset --hard
git clean -fd
```

unless you know exactly what would be deleted.

---

# Diagnostics

Inside a paper repository:

```bash
paper doctor
```

checks:

- remotes;
- `master` tracking;
- default push remote;
- Git;
- GitHub CLI;
- GitHub authentication;
- `latexmk`;
- VS Code;
- cached remote divergence.

---

# LaTeX helpers

Compile the default `main.tex`:

```bash
paper build
```

Or specify a root file:

```bash
paper build aistats.tex
```

Clean:

```bash
paper clean
```

Open VS Code:

```bash
paper open
```

---

# Safety invariants

The workflow is deliberately designed so that:

- `paper commit` pushes nowhere;
- `paper backup` pushes only to GitHub;
- `paper abort` never touches Overleaf;
- `paper clear-experiments` never touches Overleaf;
- `paper publish` requires a clean working tree;
- destructive branch deletion requires explicit confirmation;
- GitHub is the private mirror/experimental area;
- Overleaf is the collaborative publication target.

If unsure:

```bash
paper status
paper help
paper examples
```
EOF
