"""Launch or address the independent Micro editor through a private mailbox.

Only open/goto requests are supported. Micro consumes them on its event loop;
no terminal input, editor commands or arbitrary code are injected.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import time


def runtime():
    base = Path(os.environ.get('XDG_RUNTIME_DIR') or f'/tmp/workspace-{os.getuid()}')
    directory = base / 'workspace-editors'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError('Editor runtime must be a directory owned by this user.')
    directory.chmod(0o700)
    return directory


def register(pid, project, session):
    directory = runtime() / f'{pid}-{secrets.token_hex(6)}'
    directory.mkdir(mode=0o700)
    record = {'pid': pid, 'project': str(Path(project).resolve()),
              'session': session or f'micro-{pid}', 'endpoint': str(directory), 'protocol': 1}
    record_path = directory / 'record.json'
    record_path.write_text(json.dumps(record) + '\n')
    record_path.chmod(0o600)
    print(directory)


def live():
    records = []
    for directory in runtime().iterdir():
        try:
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                continue
            record = json.loads((directory / 'record.json').read_text())
            if record['endpoint'] != str(directory) or int(directory.name.split('-')[0]) != record['pid']:
                continue
            os.kill(record['pid'], 0)
            state = directory / 'state'
            if state.exists():
                fields = state.read_text().splitlines()
                record.update(path=fields[0] if fields else '',
                              line=int(fields[1]) if len(fields) > 1 else 1,
                              column=int(fields[2]) if len(fields) > 2 else 1,
                              files=fields[3:])
            records.append(record)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return records


def send(record, path, line, column):
    path = str(Path(path).expanduser().resolve())
    if any(c in path for c in '\n\r\0'):
        raise ValueError('Newlines and NUL are not supported in editor file paths.')
    endpoint = Path(record['endpoint'])
    name = secrets.token_hex(12)
    pending = endpoint / (name + '.pending')
    pending.write_text(f'open\n{path}\n{line}\n{column}\n')
    pending.chmod(0o600)
    pending.rename(endpoint / (name + '.request'))
    response = endpoint / (name + '.done')
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if response.exists():
            result = response.read_text().strip()
            response.unlink()
            if result != 'ok':
                raise ValueError(result or 'Editor rejected the request.')
            return
        time.sleep(.04)
    (endpoint / (name + '.request')).unlink(missing_ok=True)
    raise ValueError('Editor did not acknowledge the request; no keyboard input was sent.')


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='*', help='folder or files; use list to inspect live editors')
    parser.add_argument('--project', help='project root')
    parser.add_argument('--session', help='paired workspace ID')
    parser.add_argument('--line', type=int, default=1)
    parser.add_argument('--column', type=int, default=1)
    parser.add_argument('--new', action='store_true', help='open an independent editor window')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--register', type=int, metavar='PID', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.register:
        register(args.register, args.project or os.environ.get('PROJECT_WORKSPACE_ROOT') or str(Path.cwd()),
                 args.session or os.environ.get('PROJECT_WORKSPACE_ID', ''))
        return 0
    records = live()
    if args.paths == ['list']:
        print(json.dumps(records, indent=2) if args.json else '\n'.join(
            f'{r["session"]}  {r["project"]}  {r.get("path", "")}' for r in records))
        return 0
    files = [Path(p).expanduser().resolve() for p in args.paths]
    folder = files.pop(0) if files and files[0].is_dir() else None
    if any(path.is_dir() for path in files):
        parser.error('Pass at most one folder, followed by file paths.')
    project = args.project or (str(folder) if folder else os.environ.get('PROJECT_WORKSPACE_ROOT'))
    if not project and files:
        result = subprocess.run(['git', '-C', str(files[0].parent), 'rev-parse', '--show-toplevel'],
                                capture_output=True, text=True)
        project = result.stdout.strip() if result.returncode == 0 else str(files[0].parent)
    project = str(Path(project or '.').expanduser().resolve())
    session = args.session or os.environ.get('PROJECT_WORKSPACE_ID')
    matches = [r for r in records if r['project'] == project and (not session or r['session'] == session)]
    if len(matches) > 1 and not args.new:
        raise ValueError('Multiple editors match; select --session from workspace-edit list.')
    if matches and not args.new:
        for path in files:
            send(matches[0], path, max(1, args.line), max(1, args.column))
        if args.json:
            print(json.dumps(matches[0]))
        return 0
    from project_open import run as launch
    command = ['--terminal', project]
    if args.new:
        command.append('--new')
    if session:
        command += ['--session', session]
    command += ['--line', str(max(1, args.line)), '--column', str(max(1, args.column))]
    for path in files:
        command += ['--file', str(path)]
    return launch(command)


if __name__ == '__main__':
    try:
        sys.exit(run())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'workspace-edit: {error}', file=sys.stderr)
        sys.exit(1)
