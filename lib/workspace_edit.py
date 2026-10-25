"""Launch or address the independent Micro editor through a private mailbox.

Only file/view/status and guarded reload requests are supported. Micro consumes them on its event loop;
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
              'session': session or f'micro-{pid}', 'endpoint': str(directory), 'protocol': 2,
              'kitty_window': os.environ.get('KITTY_WINDOW_ID', '')}
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
            structured = directory / 'state.json'
            if structured.exists():
                record.update(json.loads(structured.read_text()))
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


def send(record, path, line=0, column=1, *, action="open", end_line=0, top_line=0,
         highlight=False, if_open=False, if_clean=False, discard=False, expected_version=""):
    path = str(Path(path).expanduser().resolve()) if path else ''
    if any(c in path for c in '\n\r\0'):
        raise ValueError('Newlines and NUL are not supported in editor file paths.')
    endpoint = Path(record['endpoint'])
    name = secrets.token_hex(12)
    pending = endpoint / (name + '.pending')
    if action not in ('open', 'view', 'status', 'reload'):
        raise ValueError('Unsupported editor action.')
    fields = [action, path, line, column, end_line, top_line, int(highlight), int(if_open),
              int(if_clean), int(discard), expected_version]
    pending.write_text('\n'.join(map(str, fields)) + '\n')
    pending.chmod(0o600)
    pending.rename(endpoint / (name + '.request'))
    response = endpoint / (name + '.done')
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if response.exists():
            result = response.read_text().strip()
            response.unlink()
            if result == 'ok':
                return {'ok': True}
            if result.startswith('{'):
                value = json.loads(result)
                if value.get('ok'):
                    return value
            raise ValueError(result or 'Editor rejected the request.')
        time.sleep(.04)
    (endpoint / (name + '.request')).unlink(missing_ok=True)
    raise ValueError('Editor did not acknowledge the request; no keyboard input was sent.')


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='*', help='folder or files; use list to inspect live editors')
    parser.add_argument('--project', help='project root')
    parser.add_argument('--session', help='paired workspace ID')
    parser.add_argument('--line', type=int, default=0, help='one-based cursor line; omit to preserve it')
    parser.add_argument('--column', type=int, default=1)
    parser.add_argument('--end-line', type=int, default=0, help='inclusive end of the highlighted range')
    parser.add_argument('--top-line', type=int, default=0, help='one-based first visible buffer line')
    parser.add_argument('--highlight', action='store_true', help='temporary display-only line highlight')
    parser.add_argument('--if-open', action='store_true', help='skip rather than open a new buffer/window')
    parser.add_argument('--if-clean', action='store_true', help='skip navigation for an unsaved buffer')
    parser.add_argument('--focus', action='store_true', help='also reveal the managed Kitty editor pane')
    parser.add_argument('--reveal', action='store_true', help='show the editor terminal tab without raising its desktop window')
    parser.add_argument('--discard', action='store_true', help='reload: explicitly discard the inspected buffer edits')
    parser.add_argument('--expected-version', default='', help='reload: buffer hash returned by status')
    parser.add_argument('--new', action='store_true', help='open an independent editor window')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--register', type=int, metavar='PID', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.register:
        register(args.register, args.project or os.environ.get('PROJECT_WORKSPACE_ROOT') or str(Path.cwd()),
                 args.session or os.environ.get('PROJECT_WORKSPACE_ID', ''))
        return 0
    if args.expected_version and (len(args.expected_version) != 64 or any(c not in 'abcdef0123456789' for c in args.expected_version)):
        parser.error('--expected-version must be the SHA256 returned by status.')
    action = 'open'
    if args.paths and args.paths[0] in ('view', 'status', 'reload'):
        action = args.paths.pop(0)
    if (args.discard or args.expected_version) and action != 'reload':
        parser.error('--discard/--expected-version apply only to reload.')
    if action in ('reload', 'view') and len(args.paths) != 1:
        parser.error(f'{action} requires exactly one file.')
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
        modern = action != 'open' or args.if_open or args.if_clean or args.highlight or args.top_line or args.end_line
        if modern and matches[0].get('protocol', 1) < 2:
            if args.if_open:
                if args.json: print(json.dumps({'ok': True, 'skipped': 'editor_needs_restart'}))
                return 0
            raise ValueError('Reopen Editor to enable the updated view/status controls; its current buffers are untouched.')
        result = {'ok': True}
        for path in files or ([None] if action == 'status' else []):
            result = send(matches[0], path, max(0, args.line), max(1, args.column),
                          action=action, end_line=args.end_line, top_line=args.top_line,
                          highlight=args.highlight, if_open=args.if_open, if_clean=args.if_clean,
                          discard=args.discard, expected_version=args.expected_version)
        if (args.focus or args.reveal) and not result.get('skipped'):
            from project_workspace import live_workspaces as workspaces, remote
            selected = [r for r in workspaces() if r['id'] == matches[0]['session']]
            pane = matches[0].get('kitty_window', '')
            if len(selected) == 1 and pane.isdecimal():
                if args.focus:
                    remote(selected[0], 'focus-window', '--match', 'id:' + pane)
                else:
                    tabs = [t for t in selected[0]['tabs'] if any(str(p['id']) == pane for p in t['panes'])]
                    if len(tabs) == 1: remote(selected[0], 'focus-tab', '--match', 'id:' + str(tabs[0]['id']))
            else:
                result['focus_unavailable'] = True
        if args.json or action in ('status', 'reload'):
            print(json.dumps(dict(matches[0], **result)))
        return 0
    if args.if_open:
        if args.json: print(json.dumps({'ok': True, 'skipped': 'not_open'}))
        return 0
    if action in ('status', 'reload', 'view'):
        raise ValueError('No live editor matches. Use workspace-edit list and select --project/--session.')
    from project_open import run as launch
    session = session or secrets.token_hex(8)
    command = ['--terminal', project]
    if args.new:
        command.append('--new')
    if session:
        command += ['--session', session]
    command += ['--line', str(max(1, args.line)), '--column', str(max(1, args.column))]
    for path in files:
        command += ['--file', str(path)]
    result = launch(command)
    if result or not (args.highlight or args.top_line or args.focus or args.reveal or args.json):
        return result
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if any(r['session'] == session and r['project'] == project for r in live()):
            followup = ['--project', project, '--session', session, '--line', str(args.line),
                        '--column', str(args.column), '--end-line', str(args.end_line), '--top-line', str(args.top_line)]
            for flag, enabled in [('--highlight', args.highlight), ('--focus', args.focus), ('--reveal', args.reveal), ('--json', args.json)]:
                if enabled: followup.append(flag)
            return run([*followup, *map(str, files)])
        time.sleep(.08)
    raise ValueError('Editor launched; its updated control interface is not yet available.')


if __name__ == '__main__':
    try:
        sys.exit(run())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'workspace-edit: {error}', file=sys.stderr)
        sys.exit(1)
