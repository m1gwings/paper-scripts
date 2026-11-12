"""Open a local project in a graphical editor or a Kitty/Micro workspace."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import shlex
import fcntl
import json
import time
from concurrent.futures import ThreadPoolExecutor
from project_metadata import metadata
from project_workspace import prepare, register
from viewer import open_pdf
from desktop_launch import snapshot as desktop_snapshot, wait_new as desktop_wait, present as desktop_present, existing_window


SESSION = """layout fat:bias=74
launch --title Editor micro
focus
launch --title Shell
"""

# Apply only to windows opened by this launcher; keep global Kitty settings intact.
KITTY_OVERRIDES = [
    'allow_remote_control=socket-only',
    'enabled_layouts=fat:bias=74,stack',
    'window_padding_width=4 14',
    'map ctrl+alt+left neighboring_window left',
    'map ctrl+alt+right neighboring_window right',
    'map ctrl+alt+up neighboring_window up',
    'map ctrl+alt+down neighboring_window down',
    'map ctrl+shift+enter launch --cwd=current',
    'map ctrl+shift+z toggle_layout stack',
    # Let Micro select document text; Kitty must not select across its panes.
    'mouse_map shift+left press grabbed',
    'mouse_map shift+left click grabbed',
    'mouse_map shift+left doublepress grabbed',
    'mouse_map shift+left triplepress grabbed',
    'window_border_width=2',
]


def start_session(process, session, address):
    """Deliver the session and stop waiting as soon as Kitty accepts control.

    communicate's timeout is a failure-detection budget, not a startup delay.
    Keep checking early exits while a slow Kitty has not created its socket.
    """
    deadline = time.monotonic() + 1
    try:
        process.communicate(session, timeout=.05)
    except subprocess.TimeoutExpired:
        while not Path(address).is_socket():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                process.communicate(timeout=min(.05, remaining))
                return
            except subprocess.TimeoutExpired:
                pass


def phased_open():
    config = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'project-open/config.json'
    try:
        value = json.loads(config.read_text())
        return not value.get('post_open') or value.get('phased_open') is True
    except FileNotFoundError:
        return True
    except (OSError, ValueError):
        return False


def post_open(directory, identifier, label, no_reader=False, *, phase=None, window=None, reader=None):
    """Run one optional user-level hook; never load commands from a project."""
    config = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'project-open/config.json'
    try:
        if not config.is_file():
            return
        command = json.loads(config.read_text()).get('post_open', [])
        if not command:
            return
        if not isinstance(command, list) or not all(isinstance(part, str) and part for part in command):
            raise ValueError('post_open must be a nonempty command argument array')
        extra = ['--phase', phase] if phase else []
        if phase and window: extra += ['--editor-window', window]
        if phase and reader and reader.get('windowTitle'):
            extra += ['--reader-title', reader['windowTitle']]
        if phase and reader and reader.get('desktopWindow'):
            extra += ['--reader-window', reader['desktopWindow']]
        result = subprocess.run([*command, '--project', str(directory), '--session', identifier,
                                 '--editor-title', f'Editor — {label}',
                                 *extra,
                                 *(['--no-reader'] if no_reader else [])],
                                capture_output=True, text=True, timeout=20)
        if result.stdout:
            print(result.stdout, end='')
        if result.returncode:
            print('Project opened; placement hook incomplete: ' + result.stderr.strip(), file=sys.stderr)
        elif result.stderr:
            print(result.stderr, end='', file=sys.stderr)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'Project opened; post-open hook unavailable: {error}', file=sys.stderr)


def ensure_watcher(directory, source, identifier):
    """Restore Build when paper open reuses an editor opened standalone."""
    # A pinned runtime may still be watching with the previous visible layout.
    for output in ('output/.latex', 'output'):
        lock_path = directory / output / source.parent / f'.{source.stem}.watch.lock'
        if lock_path.exists():
            with lock_path.open('a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return
                fcntl.flock(lock, fcntl.LOCK_UN)
    subprocess.run(['project-terminal', 'run', '--workspace', identifier, '--title', 'Build',
                    '--cwd', str(directory), '--keep-focus', '--', sys.executable,
                    str(Path(__file__).with_name('build.py')), 'build', '--watch', str(source)],
                   check=True, capture_output=True, text=True, timeout=10)


def resolve_target(target, paper, parser):
    """Resolve an explicit directory path, fuzzy query/alias, or default directory."""
    touched = False
    if target:
        cand = Path(target).expanduser()
        if cand.is_dir():
            directory = cand.resolve()
        else:
            wp = shutil.which('workspace-project')
            if wp:
                res = subprocess.run([wp, 'resolve', target, '--touch', '--json'],
                                     capture_output=True, text=True)
                if res.returncode == 0:
                    try:
                        info = json.loads(res.stdout)
                        directory = Path(info['resolved_path'])
                        if not directory.is_dir():
                            parser.error(f"Matched project path does not exist: {directory}")
                        print(f"Matched {info['name']} ({directory})")
                        touched = True
                    except Exception as e:
                        parser.error(f"Error parsing workspace-project result: {e}")
                elif res.returncode == 2:
                    parser.error(res.stderr.strip() or f"Ambiguous query '{target}'.")
                else:
                    parser.error(f"Not a directory and no matching project found for '{target}'.")
            else:
                parser.error(f"Not a directory: {target}")
    else:
        if paper:
            directory = Path.cwd()
        else:
            directory = Path('.').expanduser().resolve()

    if paper:
        if not shutil.which('git'):
            parser.error("Required command 'git' is not installed.")
        result = subprocess.run(['git', '-C', str(directory), 'rev-parse', '--show-toplevel'],
                                text=True, capture_output=True)
        if result.returncode:
            parser.error(f'Not inside a Git repository: {directory}')
        # Git adds one trailing newline. Preserve whitespace in the directory name.
        directory = Path(result.stdout.removesuffix('\n'))

    if not touched:
        wp = shutil.which('workspace-project')
        if wp:
            subprocess.run([wp, 'touch', str(directory)], capture_output=True)

    return directory


def run(argv=None):
    started = time.monotonic()
    trace = os.environ.get('WORKSPACE_STARTUP_TRACE')
    def mark(stage):
        if not trace:
            return
        try:
            fd = os.open(trace, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, 'w') as stream:
                stream.write(json.dumps({'stage': stage, 'ms': round((time.monotonic() - started) * 1000, 2),
                                         'pid': os.getpid()}) + '\n')
        except OSError:
            pass  # Optional diagnostics cannot prevent a project from opening.
    argv = list(sys.argv[1:] if argv is None else argv)
    paper = bool(argv and argv[0] == '--paper')
    if paper:
        argv.pop(0)
    parser = argparse.ArgumentParser(
        prog='paper open' if paper else 'project-open',
        description='Open a project in Kitty with Micro and a project shell, or in VS Code.',
        epilog=("Default: PAPER_EDITOR, then Git's paper.editor, then vscode. "
                "Set with: git config --global paper.editor terminal") if paper else
               'Defaults to terminal. Click a pane to focus it; Ctrl+Shift+Z zooms/restores it.')
    editors = parser.add_mutually_exclusive_group()
    editors.add_argument('--terminal', action='store_const', const='terminal', dest='editor')
    editors.add_argument('--vscode', action='store_const', const='vscode', dest='editor')
    parser.add_argument('--file', action='append', default=[], help='open a file in the editor (repeatable)')
    parser.add_argument('--line', type=int, default=1)
    parser.add_argument('--column', type=int, default=1)
    parser.add_argument('--session', help='explicit paired editor/reader workspace ID')
    parser.add_argument('--new', action='store_true', help='open an additional independent workspace')
    parser.add_argument('--no-reader', action='store_true', help='open only the editor/build workspace')
    parser.add_argument('--no-post-open', action='store_true', help='skip the optional personal placement hook')
    parser.add_argument('--focus', action='store_true', help='reveal and activate the new or existing Editor after project setup')
    parser.add_argument('--read', metavar='FILE', help='open a Markdown file in Reader with a paired, minimized Editor; --focus activates Reader')
    parser.add_argument('--hot', action='store_true', help='list hot projects from registry cache')
    parser.add_argument('--list', action='store_true', help='list all projects in registry')
    parser.add_argument('directory', nargs='?', default=None, help='project directory, ID, or alias (default: current)')
    args = parser.parse_args(argv)

    if args.hot:
        wp = shutil.which('workspace-project')
        if wp:
            return subprocess.run([wp, 'hot']).returncode
        sys.stderr.write("workspace-project tool not found.\n")
        return 1

    if args.list:
        wp = shutil.which('workspace-project')
        if wp:
            return subprocess.run([wp, 'list']).returncode
        sys.stderr.write("workspace-project tool not found.\n")
        return 1

    directory = resolve_target(args.directory, paper, parser)
    reading = None
    if args.read:
        if paper or args.no_reader or args.editor == 'vscode':
            parser.error('--read requires a terminal project with Reader enabled.')
        reading = Path(args.read).expanduser()
        reading = (directory / reading).resolve()
        if not reading.is_file() or reading.suffix.lower() != '.md' or not reading.is_relative_to(directory):
            parser.error('--read must name an existing Markdown file inside the project.')
        if not shutil.which('workspace-read'):
            parser.error('--read requires workspace-read.')
    mark('project_resolved')

    if paper:
        configured = ''
        if not args.editor and not os.environ.get('PAPER_EDITOR'):
            result = subprocess.run(['git', 'config', '--get', 'paper.editor'],
                                    cwd=str(directory), text=True, capture_output=True)
            if result.returncode not in (0, 1):
                parser.error(result.stderr.strip() or 'Cannot read paper.editor.')
            configured = result.stdout.strip()
        editor = args.editor or os.environ.get('PAPER_EDITOR') or configured or 'vscode'
    else:
        editor = args.editor or 'terminal'

    if not directory.is_dir():
        parser.error(f'Not a directory: {directory}')
    if editor not in ('terminal', 'vscode'):
        parser.error('Editor must be terminal or vscode (check PAPER_EDITOR and paper.editor).')

    kitty = os.environ.get('PROJECT_KITTY') or ('workspace-kitty' if shutil.which('workspace-kitty') else 'kitty')
    required = (kitty, 'micro') if editor == 'terminal' else ('code',)
    for command in required:
        if not shutil.which(command):
            parser.error(f"Required command '{command}' is not installed.")

    if editor == 'vscode':
        return subprocess.run(['code', '--new-window', str(directory)]).returncode

    try:
        info = metadata(directory)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    label = info['project_name']
    component = info['document_type'] or ('paper' if paper else '')
    if component:
        label += ' · ' + component.capitalize()
    source = Path(info['root_tex'])
    if source.is_absolute() or '..' in source.parts or source.suffix != '.tex':
        parser.error('root_tex must be a relative .tex path inside the project.')
    pdf = directory / 'output' / source.with_suffix('.pdf')
    def reader_for(identifier):
        if reading:
            return open_pdf(reading, directory, identifier, focus=args.focus)
        if paper and not args.no_reader and ((directory / source).is_file() or pdf.is_file()):
            try:
                # Opening a paper selects/reveals its manuscript. Reader's
                # explicit focus flag is separate from background tab updates.
                state = open_pdf(pdf, directory, identifier)
                mark('reader_ready')
                return state
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                print(f'Editor remains available; PDF reader: {error}', file=sys.stderr)
    independent = args.no_post_open or phased_open()
    def reader_and_place(identifier):
        state = reader_for(identifier)
        if state and not args.no_post_open:
            post_open(directory, identifier, label, phase='reader', reader=state)

    if not args.new:
        from workspace_edit import live, send
        matches = [r for r in live() if r['project'] == str(directory) and
                   (not args.session or args.session == r['session'])]
        if len(matches) > 1:
            parser.error('Multiple editors match; select --session or use --new.')
        if matches:
            if reading:
                # Do not switch/reload existing buffers merely to enter the library.
                window = existing_window('workspace-editor', f'Editor — {label}')
                if not args.no_post_open:
                    post_open(directory, matches[0]['session'], label, phase='editor', window=window)
                from desktop_launch import desktop
                reader_and_place(matches[0]['session'])
                if not desktop('minimize', '--window', window).get('ok'):
                    raise ValueError('Reader opened, but the paired Editor could not be minimized.')
                print(f'Reused editor workspace {matches[0]["session"]}.')
                return 0
            for file in args.file:
                send(matches[0], file, max(1, args.line), max(1, args.column))
            if paper and (directory / source).is_file():
                try:
                    ensure_watcher(directory, source, matches[0]['session'])
                except (OSError, subprocess.SubprocessError) as error:
                    print(f'Editor reused; could not verify/start the build watcher: {error}', file=sys.stderr)
            def reveal_reused(*, phase=None, activate=False, place=True):
                bridge = shutil.which('workspace-desktop')
                window = existing_window('workspace-editor', f'Editor — {label}') if bridge else None
                if place and not args.no_post_open:
                    post_open(directory, matches[0]['session'], label, args.no_reader or not paper, phase=phase, window=window)
                if bridge or args.focus:
                    # A reused workspace may be minimized or showing its Build tab.
                    # Select the exact registered Editor pane without opening files
                    # or changing any buffer/cursor, then restore its desktop window.
                    record = matches[0]
                    pane = record.get('kitty_window', '')
                    if pane.isdecimal():
                        from project_workspace import live_workspaces, remote
                        managed = [w for w in live_workspaces(session=record['session'], inspect_tabs=False)
                                   if w['id'] == record['session'] and w['root'] == str(directory)]
                        if len(managed) != 1:
                            raise ValueError('The selected Editor workspace closed during opening.')
                        if activate and not bridge:
                            remote(managed[0], 'focus-window', '--match', 'id:' + pane)
                        else:
                            remote(managed[0], 'kitten', '--match', 'id:' + pane,
                                   str(Path(__file__).with_name('kitty_reveal.py')))
                    elif activate and not bridge:
                        raise ValueError('Cannot identify the existing Editor pane for activation.')
                    if bridge:
                        desktop_present(window, focus=activate)
                mark('editor_revealed')
                return window
            if independent:
                with ThreadPoolExecutor(max_workers=1) as workers:
                    pending = workers.submit(reader_and_place, matches[0]['session'])
                    window = reveal_reused(phase='editor')
                    pending.result()
                if args.focus:
                    if window:
                        desktop_present(window, focus=True)
                    else:
                        reveal_reused(activate=True, place=False)
            else:
                reader_for(matches[0]['session'])
                reveal_reused(activate=args.focus)
            print(f'Reused editor workspace {matches[0]["session"]}.')
            mark('complete')
            return 0
    session = 'new_tab ' + ('Paper' if paper else 'Editor') + '\n' + SESSION
    if reading and not args.file:
        args.file = [str(reading)]
    if args.file:
        files = [str(Path(file).expanduser().resolve()) for file in args.file]
        location = f'+{max(1, args.line)}:{max(1, args.column)}'
        session = session.replace('launch --title Editor micro',
                                  'launch --title Editor ' + shlex.join(['micro', location, *files]))
    if paper:
        # Keep the source watcher in its own tab, leaving the project shell free.
        build_command = shlex.join(['python3', str(Path(__file__).with_name('build.py')),
                                    'build', '--watch', info['root_tex']])
        session += f'new_tab Build\nlaunch --title "PDF build" {build_command}\n'
    workspace = prepare(directory, info['project_name'], args.session)
    cosmic = 'COSMIC' in os.environ.get('XDG_CURRENT_DESKTOP', '').upper().split(':')
    # On COSMIC, stage the window without activation so the placement hook can
    # move it to its intended monitor. Explicit activation happens last.
    staged = bool(reading) or not args.focus or cosmic
    existing_windows = desktop_snapshot() if staged else None
    command = [kitty, '--listen-on', 'unix:' + workspace['socket'], '--directory', str(directory),
               '--class', 'workspace-editor', '--name', 'workspace-editor',
               '--title', f'Editor — {label}', '--session', '-']
    if staged:
        command += ['--start-as', 'minimized']
        if cosmic:
            helper = Path(__file__).with_name('kitty_passive.py')
            command[1:1] = ['+runpy', f'import runpy; runpy.run_path({str(helper)!r}, run_name="__main__")']
    for override in KITTY_OVERRIDES:
        command.extend(['--override', override])
    toggle = shlex.join([sys.executable, str(Path(__file__).with_name('project_workspace.py')), 'toggle',
                        '--workspace', workspace['id']])
    command.extend(['--override', 'map ctrl+grave launch --type=background ' + toggle])
    env = os.environ.copy()
    if staged:
        env.pop('XDG_ACTIVATION_TOKEN', None)
        env.pop('DESKTOP_STARTUP_ID', None)
    env['PROJECT_WORKSPACE_NAME'] = info['project_name']
    env['PROJECT_WORKSPACE_ROOT'] = str(directory)
    env['PROJECT_WORKSPACE_ID'] = workspace['id']
    for name in ('NO_COLOR', 'CODEX_CI'):
        env.pop(name, None)
    # Kitty's --detach can return success before parsing a broken session.
    # Detach the process ourselves and report failures during initial startup.
    state = Path(env.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'project-open'
    state.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w+', prefix='kitty-', suffix='.log',
                                     dir=state, delete=False) as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log, stderr=log,
                                   text=True, cwd=directory, env=env, start_new_session=True)
        try:
            register(workspace, process.pid)
        except Exception:
            process.terminate()
            try: process.communicate(timeout=2)
            except subprocess.TimeoutExpired: process.kill(); process.communicate()
            raise
        def reveal_editor(phase=None, focus=None):
            activate = args.focus if focus is None else focus
            if not staged:
                if not args.no_post_open: post_open(directory, workspace['id'], label, args.no_reader or not paper, phase=phase)
                return
            try:
                window = desktop_wait(existing_windows, 'workspace-editor', f'Editor — {label}')
                mark('editor_mapped')
                if not args.no_post_open: post_open(directory, workspace['id'], label, args.no_reader or not paper, phase=phase, window=window)
                if window is not None:
                    desktop_present(window, focus=activate)
                    mark('editor_revealed')
                    return window
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                if args.focus:
                    raise ValueError(f'Editor could not be restored: {error}') from error
                print(f'Editor passive reveal: {error}', file=sys.stderr)
            if args.focus:
                raise ValueError('Editor did not become available for activation; project remains open.')
            print('Editor started minimized; workspace-desktop reveal is required to show it without changing keyboard focus.', file=sys.stderr)
        def finish_open():
            if reading:
                # Stage/place the paired Editor but leave it minimized until an
                # explicit Reader source-navigation request reveals it.
                window = desktop_wait(existing_windows, 'workspace-editor', f'Editor — {label}')
                if not args.no_post_open:
                    post_open(directory, workspace['id'], label, phase='editor', window=window)
                reader_and_place(workspace['id'])
                mark('complete')
                return
            if independent:
                # Each app can become usable while the other initializes. Only
                # hooks declaring phase support receive separate placement calls.
                with ThreadPoolExecutor(max_workers=1) as workers:
                    pending = workers.submit(reader_and_place, workspace['id'])
                    window = reveal_editor(phase='editor', focus=False)
                    pending.result()
                if args.focus and window:
                    desktop_present(window, focus=True)
            else:
                # Existing third-party hooks retain their once-per-open contract.
                reader_for(workspace['id'])
                reveal_editor()
            mark('complete')
        start_session(process, session, workspace['socket'])
        mark('kitty_socket_ready')
        if process.poll() is None:
            finish_open()
            return 0
        if process.returncode:
            log.seek(0)
            print(log.read(), file=sys.stderr, end='')
            print(f'Kitty startup log: {log.name}', file=sys.stderr)
        else:
            finish_open()
        return process.returncode


if __name__ == '__main__':
    try:
        sys.exit(run())
    except (OSError, ValueError) as error:
        print(f'project-open: {error}', file=sys.stderr)
        sys.exit(1)
