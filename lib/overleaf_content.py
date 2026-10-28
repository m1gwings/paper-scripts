"""Project Overleaf content without touching the working tree or real index.

Exclusions are repository-relative file/directory names, not glob patterns.
Missing settings retain the legacy full-tree contract until paper init upgrades it.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

DEFAULT_EXCLUDES = ['.paper/', '.github/', '.codex/', '.agents/', '.vscode/', '.gitignore', 'AGENTS.md', 'tasks/', 'notes/']


def exclusions(value=None):
    path = Path('.paper/config.json')
    if value is None:
        value = json.loads(path.read_text()) if path.exists() else {}
    value = value.get('overleaf_exclude', [])
    if not isinstance(value, list) or any(
            not isinstance(p, str) or not p.rstrip('/') or p.startswith('/')
            or any(c in p for c in '*?[]\\\n\r')
            or any(c in ('', '.', '..', '.git') for c in p.rstrip('/').split('/'))
            for p in value):
        raise ValueError('overleaf_exclude must be a list of relative file/directory paths (no globs).')
    return [p.rstrip('/').encode() for p in value]


def git(*args, input=None, env=None):
    return subprocess.run(['git', *args], input=input, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout


def entries(ref):
    return [entry for entry in git('ls-tree', '-rz', ref).split(b'\0') if entry]


def excluded(entry, policy):
    name = entry.split(b'\t', 1)[1]
    return any(name == p or name.startswith(p + b'/') for p in policy)


def make_tree(records):
    with tempfile.TemporaryDirectory(prefix='paper-content-') as temporary:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(temporary) / 'index'))
        git('read-tree', '--empty', env=env)
        git('update-index', '-z', '--index-info', input=b'\0'.join(records) + b'\0' if records else b'', env=env)
        return git('write-tree', env=env).decode().strip()


def project(ref, policy):
    if not policy:
        return git('rev-parse', ref + '^{tree}').decode().strip()
    return make_tree([e for e in entries(ref) if not excluded(e, policy)])


def imported_tree(source, remote, policy):
    # Remote owns manuscript paths; metadata is inherited from the merge base.
    # Thus remote deletions affect only manuscript paths and local metadata edits
    # remain ordinary changes relative to the synthetic import's first parent.
    return make_tree([e for e in entries(remote) if not excluded(e, policy)] +
                     [e for e in entries(source) if excluded(e, policy)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['tree', 'equal', 'import-tree', 'enabled', 'validate', 'status'])
    parser.add_argument('refs', nargs='*')
    args = parser.parse_args()
    policy = exclusions()
    if args.operation == 'validate':
        return 0
    if args.operation == 'enabled':
        return 0 if policy else 1
    if args.operation == 'tree':
        print(project(args.refs[0], policy))
    elif args.operation == 'status':
        # Sidebar polling is read-only: compare tree entries, without creating
        # temporary indexes or writing projected Git objects.
        local, remote = ({e.split(b'\t', 1)[1]: e.split(b'\t', 1)[0]
                          for e in entries(ref) if not excluded(e, policy)}
                         for ref in args.refs)
        names = sorted(p for p in local.keys() | remote.keys() if local.get(p) != remote.get(p))
        print(json.dumps({'same_content': not names,
                          'paths': [os.fsdecode(p) for p in names]}))
    elif args.operation == 'equal':
        return 0 if project(args.refs[0], policy) == project(args.refs[1], policy) else 1
    else:
        print(imported_tree(*args.refs, policy))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit('paper content: ' + str(error))
