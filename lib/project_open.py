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
from project_metadata import metadata
from project_recent import remember
from project_workspace import prepare, register
from viewer import open_pdf


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
    'window_border_width=2',
]


def ensure_watcher(directory, source, identifier):
    """Restore Build when paper open reuses an editor opened standalone."""
    lock_path = directory / 'output' / source.parent / f'.{source.stem}.watch.lock'
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


def run(argv=None):
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
    if not paper:
        parser.add_argument('directory', nargs='?', default='.', help='project directory (default: current)')
    args = parser.parse_args(argv)

    if paper:
        if not shutil.which('git'):
            parser.error("Required command 'git' is not installed.")
        result = subprocess.run(['git', 'rev-parse', '--show-toplevel'],
                                text=True, capture_output=True)
        if result.returncode:
            parser.error('Not inside a Git repository.')
        # Git adds one trailing newline. Preserve whitespace in the directory name.
        directory = Path(result.stdout.removesuffix('\n'))
        configured = ''
        if not args.editor and not os.environ.get('PAPER_EDITOR'):
            result = subprocess.run(['git', 'config', '--get', 'paper.editor'],
                                    text=True, capture_output=True)
            if result.returncode not in (0, 1):
                parser.error(result.stderr.strip() or 'Cannot read paper.editor.')
            configured = result.stdout.strip()
        editor = args.editor or os.environ.get('PAPER_EDITOR') or configured or 'vscode'
    else:
        directory = Path(args.directory).expanduser().resolve()
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
        result = subprocess.run(['code', '--new-window', str(directory)]).returncode
        if result == 0:
            remember(directory)
        return result

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
    def reader_for(identifier, arrange=True):
        if paper and not args.no_reader and ((directory / source).is_file() or pdf.is_file()):
            try:
                result = open_pdf(pdf, directory, identifier, background=True)
                if (arrange and result and shutil.which('workspace-layout') and
                        os.environ.get('WORKSPACE_AUTO_LAYOUT', '1') != '0'):
                    layout = subprocess.run(['workspace-layout', '--apply', '--editor-title', f'Editor — {label}',
                                             '--reader-title', result['windowTitle'], '--editor-session', identifier], capture_output=True,
                                            text=True, timeout=20)
                    if layout.returncode:
                        print('Desktop layout: ' + (layout.stderr.strip() or 'placement was not verified'), file=sys.stderr)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                print(f'Editor remains available; PDF reader: {error}', file=sys.stderr)
    if not args.new:
        from workspace_edit import live, send
        matches = [r for r in live() if r['project'] == str(directory) and
                   (not args.session or args.session == r['session'])]
        if len(matches) > 1:
            parser.error('Multiple editors match; select --session or use --new.')
        if matches:
            for file in args.file:
                send(matches[0], file, max(1, args.line), max(1, args.column))
            if paper and (directory / source).is_file():
                try:
                    ensure_watcher(directory, source, matches[0]['session'])
                except (OSError, subprocess.SubprocessError) as error:
                    print(f'Editor reused; could not verify/start the build watcher: {error}', file=sys.stderr)
            reader_for(matches[0]['session'], arrange=False)
            print(f'Reused editor workspace {matches[0]["session"]}.')
            remember(directory)
            return 0
    session = 'new_tab ' + ('Paper' if paper else 'Editor') + '\n' + SESSION
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
    command = [kitty, '--listen-on', 'unix:' + workspace['socket'], '--directory', str(directory),
               '--class', 'workspace-editor', '--name', 'workspace-editor',
               '--title', f'Editor — {label}', '--session', '-']
    for override in KITTY_OVERRIDES:
        command.extend(['--override', override])
    toggle = shlex.join([sys.executable, str(Path(__file__).with_name('project_workspace.py')), 'toggle',
                        '--workspace', workspace['id']])
    command.extend(['--override', 'map ctrl+grave launch --type=background ' + toggle])
    env = os.environ.copy()
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
        register(workspace, process.pid)
        try:
            process.communicate(session, timeout=1)
        except subprocess.TimeoutExpired:
            reader_for(workspace['id'])
            remember(directory)
            return 0
        if process.returncode:
            log.seek(0)
            print(log.read(), file=sys.stderr, end='')
            print(f'Kitty startup log: {log.name}', file=sys.stderr)
        else:
            reader_for(workspace['id'])
            remember(directory)
        return process.returncode


if __name__ == '__main__':
    try:
        sys.exit(run())
    except (OSError, ValueError) as error:
        print(f'project-open: {error}', file=sys.stderr)
        sys.exit(1)
