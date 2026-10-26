"""Explicit, local-only history alignment; quick publication remains independent."""
import argparse
import fcntl
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid


class AlignmentError(RuntimeError):
    pass


def git(root, *args, input=None, check=True):
    result = subprocess.run(['git', '-C', str(root), *args], input=input,
                            text=True, capture_output=True)
    if check and result.returncode:
        raise AlignmentError(result.stderr.strip() or result.stdout.strip() or 'Git command failed.')
    return result.stdout.strip() if check else result


def oid(root, ref):
    return git(root, 'rev-parse', '--verify', ref)


def ancestor(root, older, newer):
    result = git(root, 'merge-base', '--is-ancestor', older, newer, check=False)
    if result.returncode not in (0, 1):
        raise AlignmentError(result.stderr.strip())
    return result.returncode == 0


def tree(root, commit):
    return oid(root, commit + '^{tree}')


def require_unchanged(root, base, original):
    if git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD') != base:
        raise AlignmentError('Run align-history from the base branch; the branch may have changed while aligning.')
    if oid(root, 'HEAD') != original or git(root, 'status', '--porcelain'):
        raise AlignmentError('Local work changed. It has been preserved; commit it and retry.')
    for name in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply'):
        if Path(git(root, 'rev-parse', '--path-format=absolute', '--git-path', name)).exists():
            raise AlignmentError('A Git operation is in progress; finish or abort it before aligning.')


def content_base(root, base, source, overleaf):
    refs = []
    for suffix in ('source', 'overleaf'):
        result = git(root, 'rev-parse', '--verify', f'refs/paper-sync/{base}/{suffix}', check=False)
        refs.append(result.stdout.strip() if result.returncode == 0 else '')
    if not all(refs):
        exported = git(root, 'log', '-1', '--format=%H%n%B', '--grep=^Paper-source: ', overleaf).splitlines()
        refs = [next((line[14:] for line in exported if line.startswith('Paper-source: ')), ''),
                exported[0] if exported else '']
    if all(refs):
        # Ignore stale or missing synchronization records, as normal sync does.
        exists = git(root, 'cat-file', '-e', refs[0] + '^{commit}', check=False)
        if (exists.returncode == 0 and ancestor(root, refs[0], source)
                and ancestor(root, refs[1], overleaf) and tree(root, refs[0]) == tree(root, refs[1])):
            return refs
    return None


def commit_tree(root, contents, parents, message):
    args = ['commit-tree', contents]
    for parent in dict.fromkeys(parents):
        args += ['-p', parent]
    return git(root, *args, input=message + '\n')


def reconcile(root, base, original, github, overleaf):
    """Resolve in a disposable worktree, leaving the user's index/buffers alone."""
    with tempfile.TemporaryDirectory(prefix='paper-align-') as temporary:
        work = Path(temporary) / 'worktree'
        git(root, '-c', 'core.hooksPath=/dev/null', 'worktree', 'add', '--detach', str(work), original)
        try:
            def merge(commit):
                result = git(work, '-c', 'core.hooksPath=/dev/null', '-c', 'merge.autoStash=false',
                             'merge', '--no-edit', commit, check=False)
                if result.returncode:
                    raise AlignmentError('Content reconciliation failed:\n' + result.stdout + result.stderr +
                                         '\nYour checkout is unchanged. Run paper sync, resolve and commit, then retry.')
            merge(github)
            source = oid(work, 'HEAD')
            if tree(root, source) != tree(root, overleaf):
                known = content_base(root, base, source, overleaf)
                if known:
                    previous_source, previous_overleaf = known
                    if previous_overleaf != overleaf:
                        imported = commit_tree(root, tree(root, overleaf), [previous_source, overleaf],
                                               'Import Overleaf changes since last synchronization')
                        merge(imported)
                else:
                    merge(overleaf)
            reconciled = oid(work, 'HEAD')
            if not ancestor(root, overleaf, reconciled):
                reconciled = commit_tree(root, tree(root, reconciled), [reconciled, overleaf],
                                         'Align GitHub and Overleaf histories')
            return reconciled
        finally:
            # This worktree contains only our synthetic merge attempt, never user buffers.
            git(root, 'worktree', 'remove', '--force', str(work))


def remote_tip(root, remote, base):
    lines = git(root, 'ls-remote', '--heads', remote, f'refs/heads/{base}').splitlines()
    if len(lines) != 1:
        raise AlignmentError(f'{remote}/{base} is missing or ambiguous.')
    return lines[0].split()[0]


def align(root, base, preferred=None, dry_run=False):
    original = oid(root, 'HEAD')
    require_unchanged(root, base, original)
    tips = {}
    for remote in ('github', 'overleaf'):
        git(root, 'fetch', '--no-tags', remote,
            f'+refs/heads/{base}:refs/remotes/{remote}/{base}')
        tips[remote] = oid(root, f'refs/remotes/{remote}/{base}')
    candidate = reconcile(root, base, original, tips['github'], tips['overleaf'])
    if preferred:
        selected = tips[preferred]
        candidate = selected if tree(root, selected) == tree(root, candidate) else commit_tree(
            root, tree(root, candidate), [selected], f'Align reconciled files on {preferred} history')
    print('History: ' + (f'retain {preferred}' if preferred else 'preserve both'), flush=True)
    print(f'Target commit: {candidate}', flush=True)
    for remote, previous in tips.items():
        method = 'already aligned' if previous == candidate else (
            'fast-forward' if ancestor(root, previous, candidate) else 'replace with an explicit lease')
        print(f'  {remote}/{base}: {method}', flush=True)
    require_unchanged(root, base, original)
    if dry_run:
        print('Dry run: branches, worktree and remotes unchanged (remote refs fetched).')
        return
    if original == candidate and all(tip == candidate for tip in tips.values()):
        if any(remote_tip(root, remote, base) != candidate for remote in tips):
            raise AlignmentError('A remote changed during alignment. Fetch and retry.')
        print('Files and history already aligned.')
        return

    # Tags survive feature-branch cleanup and preserve the complete original DAGs.
    prefix = 'paper-history-backup/' + uuid.uuid4().hex
    archives = dict(local=original, **tips, reconciled=candidate)
    for label, commit in archives.items():
        git(root, 'update-ref', f'refs/tags/{prefix}/{label}', commit, '0' * len(commit))
    git(root, 'push', '--atomic', 'github', *[f'refs/tags/{prefix}/{label}' for label in archives])
    print(f'Original histories archived locally and on GitHub: {prefix}/*', flush=True)
    require_unchanged(root, base, original)
    # Try Overleaf first: if its bridge rejects this history, GitHub's base is untouched.
    for remote in ('overleaf', 'github'):
        previous = tips[remote]
        if remote_tip(root, remote, base) != previous:
            raise AlignmentError(f'{remote}/{base} changed. Earlier writes may have succeeded; rerun alignment.')
        if previous == candidate:
            continue
        options = []
        if not ancestor(root, previous, candidate):
            if not preferred:
                raise AlignmentError('Refusing an implicit history rewrite.')
            options = [f'--force-with-lease=refs/heads/{base}:{previous}']
        try:
            git(root, 'push', *options, remote, f'{candidate}:refs/heads/{base}')
        except AlignmentError as error:
            raise AlignmentError(f'{remote} rejected alignment: {error}\n'
                                 f'Archives: {prefix}/*. Earlier writes may have succeeded. '
                                 'No snapshot fallback was used; inspect and retry.') from error
    # Fetching verifies what the servers actually expose, not merely a push acknowledgement.
    for remote in tips:
        git(root, 'fetch', '--no-tags', remote, f'+refs/heads/{base}:refs/remotes/{remote}/{base}')
        if oid(root, f'refs/remotes/{remote}/{base}') != candidate or remote_tip(root, remote, base) != candidate:
            raise AlignmentError(f'{remote}/{base} does not expose the target commit. Alignment is incomplete.')
    require_unchanged(root, base, original)
    if ancestor(root, original, candidate):
        git(root, 'merge', '--ff-only', candidate)
    else:
        # Ordinary checkout guards protect files; the old tip remains archived.
        git(root, 'switch', '--detach', candidate)
        git(root, 'update-ref', f'refs/heads/{base}', candidate, original)
        git(root, 'switch', base)
    for suffix in ('source', 'overleaf'):
        git(root, 'update-ref', f'refs/paper-sync/{base}/{suffix}', candidate)
    print(f'Aligned local {base}, GitHub and Overleaf at {candidate}.')


def main():
    parser = argparse.ArgumentParser(prog='paper align-history', description=__doc__)
    parser.add_argument('--base', required=True, help=argparse.SUPPRESS)
    parser.add_argument('--from', dest='preferred', choices=('github', 'overleaf'),
                        help='retain this remote history, archiving and replacing the other if needed')
    parser.add_argument('--dry-run', action='store_true', help='fetch and preview without changing branches or remotes')
    args = parser.parse_args()
    root = Path(git(Path.cwd(), 'rev-parse', '--show-toplevel'))
    common = Path(git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir'))
    with (common / 'paper-align.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise AlignmentError('Another history alignment is running.') from error
        align(root, args.base, args.preferred, args.dry_run)


if __name__ == '__main__':
    try:
        main()
    except (AlignmentError, OSError) as error:
        print('paper align-history: ' + str(error), file=sys.stderr)
        sys.exit(1)
