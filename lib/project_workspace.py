"""Private, local control endpoints for project Kitty workspaces."""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import re


def runtime_directory():
    base = os.environ.get('XDG_RUNTIME_DIR')
    root = Path(base) / 'project-workspaces' if base else Path(tempfile.gettempdir()) / f'project-workspaces-{os.getuid()}'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError('Workspace runtime directory must be a directory owned by this user.')
    root.chmod(0o700)
    return root


def prepare(directory, name, identifier=None):
    root = runtime_directory()
    identifier = identifier or uuid.uuid4().hex[:16]
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', identifier):
        raise ValueError('Workspace ID must contain 1–40 letters, numbers, underscores or hyphens.')
    address = root / (identifier + '.sock')
    if len(os.fsencode(address)) > 100:
        raise ValueError('XDG_RUNTIME_DIR is too long for a Unix socket path.')
    return {'id': identifier, 'root': str(Path(directory).resolve()), 'name': name,
            'socket': str(address), 'created': time.time()}


def register(record, pid):
    record = dict(record, pid=pid)
    with (runtime_directory() / (record['id'] + '.json')).open('x') as handle:
        os.chmod(handle.name, 0o600)
        json.dump(record, handle)


def remote(record, *args):
    result = subprocess.run(['kitty', '@', '--to', 'unix:' + record['socket'], *args],
                            text=True, capture_output=True, timeout=8, stdin=subprocess.DEVNULL)
    if result.returncode:
        raise ValueError(result.stderr.strip() or 'Kitty control command failed.')
    return result.stdout


def live_workspaces():
    result = []
    directory = runtime_directory()
    for path in sorted(directory.glob('*.json')):
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                continue
            record = json.loads(path.read_text())
            # A record can only refer to its own endpoint in this private directory.
            if record['id'] != path.stem or record['socket'] != str(directory / (path.stem + '.sock')):
                continue
            address = Path(record['socket'])
            if not address.is_socket() or address.stat().st_uid != os.getuid():
                continue
            windows = json.loads(remote(record, 'ls'))
            tabs = []
            for window in windows:
                for tab in window.get('tabs', []):
                    tabs.append({'id': tab['id'], 'title': tab['title'],
                                 'layout': tab.get('layout', 'fat'),
                                 'enabled_layouts': tab.get('enabled_layouts', ['fat:bias=74', 'stack']),
                                 'active_window': next((p['id'] for p in tab.get('windows', []) if p.get('is_active')), None),
                                 'panes': [{'id': pane['id'], 'title': pane['title']}
                                           for pane in tab.get('windows', [])]})
            if tabs:
                result.append(dict(record, tabs=tabs))
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            continue
    return result


def choose(records, project=None, identifier=None):
    if identifier:
        records = [record for record in records if record['id'] == identifier]
    if project:
        root = str(Path(project).expanduser().resolve())
        records = [record for record in records if record['root'] == root]
    elif not identifier:
        current = Path(os.environ.get('PROJECT_WORKSPACE_ROOT') or Path.cwd()).resolve()
        records = [record for record in records if current == Path(record['root']) or current.is_relative_to(record['root'])]
        if records:
            longest = max(len(record['root']) for record in records)
            records = [record for record in records if len(record['root']) == longest]
    if not records:
        raise ValueError('No live managed workspace matches. Open the project with paper open or project-open first.')
    if len(records) > 1:
        raise ValueError('Multiple workspaces match; select --workspace ID from project-terminal list. Matches: ' +
                         ', '.join(record['id'] for record in records))
    return records[0]


def launch(record, *, title, cwd=None, command=(), split=False, tab=None, keep_focus=True):
    if not title.strip() or any(ord(c) < 32 or ord(c) == 127 for c in title):
        raise ValueError('The terminal title must be a nonempty, single-line name.')
    directory = Path(cwd or record['root']).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f'Not a directory: {directory}')
    selected = next((item for item in record['tabs'] if item['id'] == tab), None) if tab is not None else record['tabs'][0]
    if selected is None:
        raise ValueError('That tab does not belong to the selected workspace.')
    args = ['launch', '--match', f'id:{selected["id"]}', '--type', 'window' if split else 'tab',
            '--title', title, '--cwd', str(directory)]
    if not split:
        args.extend(['--tab-title', title])
    if keep_focus:
        args.append('--keep-focus')
    for key, value in [('PROJECT_WORKSPACE_ID', record['id']), ('PROJECT_WORKSPACE_ROOT', record['root']),
                       ('PROJECT_WORKSPACE_NAME', record['name'])]:
        args.extend(['--env', key + '=' + value])
    if command:
        # Pass user command arguments literally, never type them into a busy shell.
        # An interactive shell remains available when the requested process exits.
        script = '"$@"; result=$?; printf "\\nProcess exited (%s). Shell ready.\\n" "$result"; exec bash -i'
        args.extend(['bash', '-ic', script, 'project-terminal', *command])
    else:
        args.extend(['bash', '-i'])
    pane = remote(record, *args).strip()
    return {'workspace': record['id'], 'project': record['root'], 'title': title,
            'window_id': int(pane), 'split': split}


def toggle_terminal(record, mode='toggle', tab_id=None):
    """Hide/reveal terminal panes without closing them or touching their input."""
    tabs = [t for t in record['tabs'] if tab_id is None or t['id'] == tab_id]
    editors = [(t, p) for t in tabs for p in t['panes'] if p['title'] == 'Editor']
    if len(editors) != 1:
        raise ValueError('Select the unique Editor tab with --tab; no panes were changed.')
    tab, editor = editors[0]
    terminals = [p for p in tab['panes'] if p['id'] != editor['id']]
    visible = bool(terminals) and (tab.get('layout') != 'stack' or tab.get('active_window', editor['id']) != editor['id'])
    show = not visible if mode == 'toggle' else mode == 'show'
    if show:
        layout = next((value for value in tab.get('enabled_layouts', ['fat:bias=74']) if value.split(':')[0] != 'stack'), None)
        if layout is None:
            raise ValueError('This tab has no split layout enabled.')
        if not terminals:
            created = launch(record, title='Shell', split=True, tab=tab['id'])
            terminals = [{'id': created['window_id'], 'title': 'Shell'}]
        remote(record, 'goto-layout', '--match', f'id:{tab["id"]}', layout)
        remote(record, 'focus-window', '--match', f'id:{terminals[0]["id"]}')
    else:
        remote(record, 'focus-window', '--match', f'id:{editor["id"]}')
        remote(record, 'goto-layout', '--match', f'id:{tab["id"]}', 'stack')
    return {'workspace': record['id'], 'tab': tab['id'], 'terminal_visible': show}


def run(argv=None):
    parser = argparse.ArgumentParser(description='Add interactive terminals to an existing project Kitty window.')
    commands = parser.add_subparsers(dest='action', required=True)
    listing = commands.add_parser('list', help='list live project workspaces and their tabs/panes')
    listing.add_argument('--json', action='store_true')
    toggle = commands.add_parser('toggle', help='show/hide the editor terminal, preserving its process and height')
    toggle.add_argument('--project')
    toggle.add_argument('--workspace')
    toggle.add_argument('--tab', type=int)
    modes = toggle.add_mutually_exclusive_group()
    modes.add_argument('--show', action='store_const', const='show', dest='mode')
    modes.add_argument('--hide', action='store_const', const='hide', dest='mode')
    toggle.add_argument('--json', action='store_true')
    add = commands.add_parser('run', help='open a task tab (or split), optionally running a command')
    add.add_argument('--project', help='project root of the target editor window')
    add.add_argument('--workspace', help='explicit workspace ID when several windows match')
    add.add_argument('--cwd', help='command directory, which may be a sibling experiment repository')
    add.add_argument('--title', default='Terminal')
    add.add_argument('--split', action='store_true', help='add a split instead of a new tab')
    add.add_argument('--tab', type=int, help='target an existing Kitty tab ID (default: editor tab)')
    focus = add.add_mutually_exclusive_group()
    focus.add_argument('--keep-focus', action='store_true', default=True, help='preserve keyboard focus (default)')
    focus.add_argument('--focus', action='store_false', dest='keep_focus', help='explicitly focus the new task pane')
    add.add_argument('--json', action='store_true')
    add.add_argument('command', nargs=argparse.REMAINDER, help='-- PROGRAM ARG ...; shell remains after exit')
    args = parser.parse_args(argv)
    records = live_workspaces()
    if args.action == 'list':
        if args.json:
            print(json.dumps(records, indent=2))
        elif not records:
            print('No live managed workspaces. Open a project with paper open or project-open.')
        else:
            for record in records:
                print(f'{record["id"]}  {record["name"]}\n  {record["root"]}')
                for tab in record['tabs']:
                    print(f'  Tab {tab["id"]}: {tab["title"]}  (' + ', '.join(
                        f'{pane["title"]} #{pane["id"]}' for pane in tab['panes']) + ')')
        return 0
    record = choose(records, args.project, args.workspace)
    if args.action == 'toggle':
        result = toggle_terminal(record, args.mode or 'toggle', args.tab)
        print(json.dumps(result) if args.json else ('Terminal shown.' if result['terminal_visible'] else 'Terminal hidden.'))
        return 0
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    result = launch(record, title=args.title, cwd=args.cwd, command=command,
                    split=args.split, tab=args.tab, keep_focus=args.keep_focus)
    if args.json:
        print(json.dumps(result))
    else:
        print(f'Opened {result["title"]} in {record["name"]} (workspace {record["id"]}, pane {result["window_id"]}).')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(run())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'project-terminal: {error}', file=sys.stderr)
        sys.exit(1)
