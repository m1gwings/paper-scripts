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


EDITOR_ID = 'editor'  # the single Editor's workspace ID and Micro session
KITTEN = Path(__file__).with_name('editor_shells.py')
PROJECT_VAR, PARKED_VAR = 'workspace_project', 'workspace_parked'


def project_root(path):
    """Project of a path (design §1): deepest registered root, then .paper/.git, else None."""
    path = Path(path).expanduser().resolve()
    excluded = {Path(path.anchor), Path.home().resolve()}
    cache = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')
    try:
        roots = json.loads((cache / 'workspace/project-roots.json').read_text()).get('roots', [])
        registered = (Path(r['root']) for r in roots if isinstance(r, dict) and isinstance(r.get('root'), str))
        matches = [root for root in registered if root not in excluded and path.is_relative_to(root)]
        if matches:
            return str(max(matches, key=lambda root: len(root.parts)))
    except (OSError, ValueError, AttributeError):
        pass
    for candidate in [path, *path.parents] if path.is_dir() else path.parents:
        if candidate not in excluded and ((candidate / '.paper/config.json').is_file() or (candidate / '.git').exists()):
            return str(candidate)
    return None


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
    path = runtime_directory() / (record['id'] + '.json')
    if path.exists():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('Workspace record must be a regular file owned by this user.')
        previous = json.loads(path.read_text())
        if previous.get('id') != record['id'] or previous.get('root') != record['root']:
            raise ValueError('Workspace session belongs to another project.')
        try:
            os.kill(previous['pid'], 0)
        except ProcessLookupError:
            path.unlink()
        else:
            raise ValueError('This workspace session is already running.')
    with path.open('x') as handle:
        os.chmod(handle.name, 0o600)
        json.dump(record, handle)


def remote(record, *args):
    result = subprocess.run(['kitty', '@', '--to', 'unix:' + record['socket'], *args],
                            text=True, capture_output=True, timeout=8, stdin=subprocess.DEVNULL)
    if result.returncode:
        raise ValueError(result.stderr.strip() or 'Kitty control command failed.')
    return result.stdout


def live_workspaces(session=None, *, inspect_tabs=True):
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
            if session is not None and record['id'] != session:
                continue
            if not inspect_tabs:
                result.append(record)
                continue
            windows = json.loads(remote(record, 'ls'))
            tabs = []
            projects = set()
            for window in windows:
                for tab in window.get('tabs', []):
                    variables = [pane.get('user_vars') or {} for pane in tab.get('windows', [])]
                    projects.update(v[PROJECT_VAR] for v in variables if v.get(PROJECT_VAR))
                    if any(v.get(PARKED_VAR) for v in variables):
                        continue  # the single Editor's hidden tab of inactive project panes
                    docks = {pane_id: group['dock']['scope'] for group in tab.get('groups', [])
                             if group.get('dock') for pane_id in group['windows']}
                    panes = []
                    for pane in tab.get('windows', []):
                        entry = {'id': pane['id'], 'title': pane['title']}
                        if (pane.get('user_vars') or {}).get(PROJECT_VAR):
                            entry['project'] = pane['user_vars'][PROJECT_VAR]
                        if pane['id'] in docks:
                            entry['dock'] = docks[pane['id']]
                        panes.append(entry)
                    tabs.append({'id': tab['id'], 'title': tab['title'],
                                 'layout': tab.get('layout', 'fat'),
                                 'enabled_layouts': tab.get('enabled_layouts', ['fat:bias=74', 'stack']),
                                 'active_window': next((p['id'] for p in tab.get('windows', []) if p.get('is_active')), None),
                                 'panes': panes})
            if tabs:
                result.append(dict(record, tabs=tabs, **({'projects': sorted(projects)} if record.get('single') else {})))
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            continue
    return result


def choose(records, project=None, identifier=None):
    """Select a window. The single Editor serves every project; a legacy
    per-project window still serves its own project unless the single Editor
    already holds that project's panes."""
    single = [record for record in records if record.get('single')]
    if identifier:
        records = [record for record in records if record['id'] == identifier]
    if single and (not identifier or identifier == EDITOR_ID):
        if project:
            root = str(Path(project).expanduser().resolve())
        else:
            root = os.environ.get('PROJECT_WORKSPACE_ROOT') if os.environ.get('PROJECT_WORKSPACE_ID') == EDITOR_ID else None
            root = root or project_root(Path.cwd())
        legacy = [r for r in records if not r.get('single') and r['root'] == root]
        if identifier == EDITOR_ID or (root and (not legacy or root in single[0].get('projects', ()))):
            if not root:
                raise ValueError('Select --project: the current directory belongs to no project.')
            return dict(single[0], root=root, name=Path(root).name)
        records = [r for r in records if not r.get('single')]
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


def editor_call(record, *args):
    """Run one action of the single Editor's in-process kitten."""
    return json.loads(remote(record, 'kitten', str(KITTEN), *args))


def editor_record():
    return next((r for r in live_workspaces(session=EDITOR_ID, inspect_tabs=False) if r.get('single')), None)


def watch(action, root, pid=None, workspace=EDITOR_ID):
    """Register/unregister the project with the shared build watcher (`paper watch`).

    The single Editor is client `editor` (as in editor_hook.py); a per-project Editor
    is `editor:<workspace>`, so closing one Editor never unregisters another."""
    paper = Path(__file__).resolve().parents[1] / 'paper'
    client = 'editor' if workspace == EDITOR_ID else f'editor:{workspace}'
    try:
        subprocess.Popen([str(paper), 'watch', action, str(root), '--client', client,
                          *(['--pid', str(pid)] if pid and action == 'register' else [])],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def activate(record, root, name=''):
    """Show root's shell below Micro; the first activation also starts its Build tab."""
    result = editor_call(record, 'activate', str(Path(root).resolve()), *([name] if name else []))
    if result.get('started_shell'):
        watch('register', result['project'], record.get('pid'))
    return result


def close_project(record, root, force=False):
    """Close root's shell, splits and task tabs; refuse while a program runs unless forced."""
    root = str(Path(root).resolve())
    result = editor_call(record, 'close', root, *(['--force'] if force else []))
    if result.get('ok'):
        watch('unregister', root)
    return result


def wrapped(command):
    # Pass user command arguments literally, never type them into a busy shell.
    # An interactive shell remains available when the requested process exits.
    if not command:
        return ['bash', '-i']
    script = '"$@"; result=$?; printf "\\nProcess exited (%s). Shell ready.\\n" "$result"; exec bash -i'
    return ['bash', '-ic', script, 'project-terminal', *command]


def launch(record, *, title, cwd=None, command=(), split=False, dock=False, tab=None, keep_focus=True):
    if not title.strip() or any(ord(c) < 32 or ord(c) == 127 for c in title):
        raise ValueError('The terminal title must be a nonempty, single-line name.')
    directory = Path(cwd or record['root']).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f'Not a directory: {directory}')
    if record.get('single'):
        if tab is not None:
            raise ValueError('The single Editor places task tabs in their project group; omit --tab.')
        result = editor_call(record, 'task', json.dumps({
            'root': record['root'], 'title': title, 'cwd': str(directory), 'command': wrapped(command),
            'kind': 'dock' if dock else 'window' if split else 'tab', 'focus': not keep_focus}))
        result = {'workspace': record['id'], 'project': record['root'], 'title': title,
                  'window_id': result['window_id'], 'split': split}
        if dock:
            result['dock'] = True
        return result
    selected = next((item for item in record['tabs'] if item['id'] == tab), None) if tab is not None else record['tabs'][0]
    if selected is None:
        raise ValueError('That tab does not belong to the selected workspace.')
    args = ['launch', '--match', f'id:{selected["id"]}', '--title', title, '--cwd', str(directory)]
    if dock:
        args.extend(['--type', 'os-window-dock', '--dock-edge', 'bottom', '--dock-size', '25%'])
    elif split:
        args.extend(['--type', 'window'])
    else:
        args.extend(['--type', 'tab', '--tab-title', title])
    if keep_focus:
        args.append('--keep-focus')
    for key, value in [('PROJECT_WORKSPACE_ID', record['id']), ('PROJECT_WORKSPACE_ROOT', record['root']),
                       ('PROJECT_WORKSPACE_NAME', record['name'])]:
        args.extend(['--env', key + '=' + value])
    args.extend(wrapped(command))
    pane = remote(record, *args).strip()
    result = {'workspace': record['id'], 'project': record['root'], 'title': title,
              'window_id': int(pane), 'split': split}
    if dock:
        result['dock'] = True
    return result


def toggle_terminal(record, mode='toggle', tab_id=None):
    """Hide/reveal terminal panes without closing them or touching their input."""
    tabs = [t for t in record['tabs'] if tab_id is None or t['id'] == tab_id]
    editors = [(t, p) for t in tabs for p in t['panes'] if p['title'] == 'Editor' and not p.get('dock')]
    if len(editors) != 1:
        raise ValueError('Select the unique Editor tab with --tab; no panes were changed.')
    tab, editor = editors[0]
    terminals = [p for p in tab['panes'] if p['id'] != editor['id'] and not p.get('dock')]
    terminal_active = any(p['id'] == tab.get('active_window') for p in terminals)
    visible = bool(terminals) and (tab.get('layout') != 'stack' or terminal_active)
    show = not visible if mode == 'toggle' else mode == 'show'
    if show:
        layout = next((value for value in tab.get('enabled_layouts', ['fat:bias=74']) if value.split(':')[0] != 'stack'), None)
        if layout is None:
            raise ValueError('This tab has no split layout enabled.')
        if not terminals and record.get('single'):
            state = editor_call(record, 'status')
            created = editor_call(record, 'activate', state['active'] or record['root'])
            terminals = [p for p in live_workspaces(session=EDITOR_ID)[0]['tabs'][0]['panes']
                         if p['id'] != editor['id'] and not p.get('dock')][:1]
        elif not terminals:
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
    listing.add_argument('--session', help='inspect only this workspace session ID')
    listing.add_argument('--json', action='store_true')
    toggle = commands.add_parser('toggle', help='show/hide the editor terminal, preserving its process and height')
    toggle.add_argument('--project')
    toggle.add_argument('--workspace')
    toggle.add_argument('--tab', type=int)
    modes = toggle.add_mutually_exclusive_group()
    modes.add_argument('--show', action='store_const', const='show', dest='mode')
    modes.add_argument('--hide', action='store_const', const='hide', dest='mode')
    toggle.add_argument('--json', action='store_true')
    show = commands.add_parser('activate', help="single Editor: show ROOT's shell below Micro")
    show.add_argument('root')
    show.add_argument('--json', action='store_true')
    close = commands.add_parser('close-project', help="single Editor: close ROOT's shell and task tabs")
    close.add_argument('root')
    close.add_argument('--force', action='store_true', help='close even while a program runs')
    close.add_argument('--json', action='store_true')
    add = commands.add_parser('run', help='open a task tab, split or dock, optionally running a command')
    add.add_argument('--project', help='project root of the target editor window')
    add.add_argument('--workspace', help='explicit workspace ID when several windows match')
    add.add_argument('--cwd', help='command directory, which may be a sibling experiment repository')
    add.add_argument('--title', default='Terminal')
    placement = add.add_mutually_exclusive_group()
    placement.add_argument('--split', action='store_true', help='add a split in the selected tab')
    placement.add_argument('--dock', action='store_true', help='dock a terminal below all tabs (Kitty 0.51+)')
    add.add_argument('--tab', type=int, help='target an existing Kitty tab ID (default: editor tab)')
    focus = add.add_mutually_exclusive_group()
    focus.add_argument('--keep-focus', action='store_true', default=True, help='preserve keyboard focus (default)')
    focus.add_argument('--focus', action='store_false', dest='keep_focus', help='explicitly focus the new task pane')
    add.add_argument('--json', action='store_true')
    add.add_argument('command', nargs=argparse.REMAINDER, help='-- PROGRAM ARG ...; shell remains after exit')
    args = parser.parse_args(argv)
    if args.action in ('activate', 'close-project'):
        record = editor_record()
        if record is None:
            raise ValueError('The single Editor is not running.')
        if args.action == 'activate':
            result = activate(record, args.root)
        else:
            result = close_project(record, args.root, args.force)
        if args.json or not result.get('ok'):
            print(json.dumps(result))
        return 0 if result.get('ok') else 3
    target_session = getattr(args, 'session', None) or getattr(args, 'workspace', None)
    records = live_workspaces(session=target_session)
    if args.action == 'list':
        if args.json:
            print(json.dumps(records, indent=2))
        elif not records:
            print('No live managed workspaces. Open a project with paper open or project-open.')
        else:
            for record in records:
                print(f'{record["id"]}  {record["name"]}\n  ' + (record['root'] or ', '.join(record.get('projects', []))))
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
                    split=args.split, dock=args.dock, tab=args.tab, keep_focus=args.keep_focus)
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
