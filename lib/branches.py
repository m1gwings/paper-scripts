"""Plan or delete explicitly selected, fully integrated feature branches."""
import argparse
import json
import subprocess
import sys


def git(*args, check=True):
    return subprocess.run(['git', *args], text=True, capture_output=True, check=check)


def ancestor(tip, base):
    return git('merge-base', '--is-ancestor', tip, base, check=False).returncode == 0


def inventory(base):
    local = {}
    for line in git('for-each-ref', '--format=%(refname:strip=2) %(objectname)', 'refs/heads/').stdout.splitlines():
        name, oid = line.rsplit(' ', 1)
        local[name] = oid
    remote = {}
    for line in git('ls-remote', '--heads', 'github').stdout.splitlines():
        oid, ref = line.split()
        remote[ref.removeprefix('refs/heads/')] = oid
    if base not in local or base not in remote:
        raise ValueError('Both local and GitHub base branches must exist.')
    occupied = {line.removeprefix('branch refs/heads/') for line in
                git('worktree', 'list', '--porcelain').stdout.splitlines()
                if line.startswith('branch refs/heads/')}
    result = []
    for name in sorted((local.keys() | remote.keys()) - {base}):
        tips = [mapping[name] for mapping in (local, remote) if name in mapping]
        known = all(git('cat-file', '-e', tip + '^{commit}', check=False).returncode == 0
                    for tip in [*tips, remote[base]])
        reason = ('checked out in a worktree' if name in occupied else
                  'remote objects unavailable; fetch github to verify' if not known else
                  'not merged into both local and GitHub base' if not all(
                      ancestor(tip, target) for tip in tips for target in (local[base], remote[base])) else '')
        result.append(dict(name=name, local=local.get(name), remote=remote.get(name),
                           eligible=not reason, reason=reason))
    return result


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('branches', nargs='*', help='exact branch names to delete')
    parser.add_argument('--all-merged', action='store_true', help='select all eligible branches')
    parser.add_argument('--yes', action='store_true', help='confirm the explicit selection without a prompt')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if args.all_merged and args.branches:
        parser.error('Choose exact names or --all-merged.')
    selected = bool(args.branches or args.all_merged)
    if selected and not args.dry_run:
        # The caller checks cleanliness and ongoing operations. Do not switch a
        # dirty checkout or rewrite the base; fetching only refreshes knowledge.
        git('fetch', '--prune', 'github')
    rows = inventory(args.base)
    names = set(args.branches) if args.branches else {
        row['name'] for row in rows if args.all_merged and row['eligible']}
    by_name = {row['name']: row for row in rows}
    for name in sorted(names):
        if name not in by_name or not by_name[name]['eligible']:
            raise ValueError(f'Refusing {name}: ' + by_name.get(name, {}).get('reason', 'not a feature branch'))
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(f"{row['name']}: " + ('merged; eligible' if row['eligible'] else 'keep; ' + row['reason']))
        if not rows:
            print('No feature branches found.')
    if not selected or args.dry_run:
        if not args.json:
            print('No branches deleted. Select exact names or --all-merged to delete.')
        return 0
    if not names:
        print('No eligible branches selected.')
        return 0
    print('Delete selected merged branches: ' + ', '.join(sorted(names)))
    if not args.yes and input("Type 'DELETE MERGED BRANCHES' to confirm: ") != 'DELETE MERGED BRANCHES':
        print('Cancelled.')
        return 0
    # Re-evaluate ancestry and worktree ownership after the human prompt.
    fresh = {row['name']: row for row in inventory(args.base)}
    if any(fresh.get(name) != by_name[name] for name in names):
        raise ValueError('Branches changed during review; inspect a fresh plan.')
    remote = [by_name[name] for name in sorted(names) if by_name[name]['remote']]
    if remote:
        # These leases guard deletion only; no branch history is force-updated.
        git('push', '--atomic', *[
            f"--force-with-lease=refs/heads/{row['name']}:{row['remote']}" for row in remote],
            'github', *[':refs/heads/' + row['name'] for row in remote])
    if any(by_name[name]['local'] for name in names):
        git('switch', args.base)
    for name in sorted(names):
        row = by_name[name]
        if row['local']:
            if git('rev-parse', 'refs/heads/' + name).stdout.strip() != row['local']:
                raise ValueError(f'Local branch changed; retained {name}.')
            git('branch', '-d', '--', name)
    print('Selected merged branches removed. Other branches and Overleaf were preserved.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(run())
    except (OSError, ValueError, EOFError, subprocess.CalledProcessError) as error:
        print('paper clear-feature-branches: ' + str(error), file=sys.stderr)
        sys.exit(1)
