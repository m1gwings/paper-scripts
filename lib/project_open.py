"""Open a local project in a graphical editor or a Kitty/Micro workspace."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import shlex


SESSION = """layout tall:bias=72
launch --title Editor micro
focus
launch --title Shell
"""

# Apply only to windows opened by this launcher; keep global Kitty settings intact.
KITTY_OVERRIDES = [
    'enabled_layouts=tall:bias=72,stack',
    'window_padding_width=4 14',
    'map ctrl+alt+left neighboring_window left',
    'map ctrl+alt+right neighboring_window right',
    'map ctrl+alt+up neighboring_window up',
    'map ctrl+alt+down neighboring_window down',
    'map ctrl+shift+enter launch --cwd=current',
    'map ctrl+shift+z toggle_layout stack',
]


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

    required = ('kitty', 'micro') if editor == 'terminal' else ('code',)
    for command in required:
        if not shutil.which(command):
            parser.error(f"Required command '{command}' is not installed.")

    if editor == 'vscode':
        return subprocess.run(['code', '--new-window', str(directory)]).returncode

    label = (f'{directory.parent.name}/{directory.name}'
             if directory.name in ('paper', 'poster', 'slides') else directory.name)
    session = SESSION
    if paper:
        # Keep the source watcher in its own tab, leaving the project shell free.
        build_command = shlex.join(['python3', str(Path(__file__).with_name('build.py')),
                                    'build', '--watch'])
        session += f'new_tab Build\nlaunch --title "PDF build" {build_command}\n'
    command = ['kitty', '--directory', str(directory),
               '--title', f'Kitty — {label}', '--session', '-']
    for override in KITTY_OVERRIDES:
        command.extend(['--override', override])
    env = os.environ.copy()
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
            process.communicate(session, timeout=1)
        except subprocess.TimeoutExpired:
            return 0
        if process.returncode:
            log.seek(0)
            print(log.read(), file=sys.stderr, end='')
            print(f'Kitty startup log: {log.name}', file=sys.stderr)
        return process.returncode


if __name__ == '__main__':
    try:
        sys.exit(run())
    except OSError as error:
        print(f'project-open: {error}', file=sys.stderr)
        sys.exit(1)
