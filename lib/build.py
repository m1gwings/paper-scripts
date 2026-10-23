"""Canonical local PDF builds and continuous preview, independent of an IDE."""
import argparse
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'clean', 'view'))
    parser.add_argument('--watch', action='store_true', help='rebuild after source saves until Ctrl+C')
    parser.add_argument('source', nargs='?', default='main.tex')
    args = parser.parse_args(argv)
    if args.watch and args.action != 'build':
        parser.error('--watch is only available for build')
    result = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if result.returncode:
        parser.error('Not inside a Git repository.')
    root = Path(result.stdout.removesuffix('\n'))
    os.chdir(root)
    source = Path(args.source)
    if (source.is_absolute() or '..' in source.parts or source.suffix != '.tex'
            or str(source).startswith('-') or any(c in str(source) for c in '\n\r')):
        parser.error('Source must be a relative .tex path inside the repository.')
    if not source.is_file() or not source.resolve().is_relative_to(root.resolve()):
        parser.error(f'Cannot find a source inside the repository: {source}')
    out = Path('output') / source.parent
    if not (root / out).resolve().is_relative_to(root.resolve()):
        parser.error('Output directory must remain inside the repository.')
    out.mkdir(parents=True, exist_ok=True)
    pdf = out / (source.stem + '.pdf')
    if pdf.is_symlink():
        parser.error('Refusing a symlinked PDF output.')
    if not shutil.which('latexmk'):
        parser.error("Required command 'latexmk' is not installed.")
    command = ['latexmk', '-pdf', '-interaction=nonstopmode', '-file-line-error',
               '-halt-on-error', '-synctex=1', f'-outdir={out}', f'-auxdir={out}']
    if args.action == 'clean':
        command.append('-C')
    if args.watch:
        command.extend(['-pvc', '-view=none'])
    command.append(str(source))
    lock = None
    if args.watch:
        lock = (out / f'.{source.stem}.watch.lock').open('a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f'A continuous builder is already watching {source}.')
            return 0
        print(f'Watching {source}; PDF: {pdf}. Stop with Ctrl+C.', flush=True)
    try:
        status = subprocess.run(command).returncode
    finally:
        if lock:
            lock.close()
    if status or args.action == 'clean':
        return status
    if not pdf.is_file():
        parser.error(f'Build produced no PDF at {pdf}.')
    print(f'PDF: {pdf.resolve()}', flush=True)
    if args.action == 'view':
        viewer = os.environ.get('PAPER_PDF_VIEWER') or ('evince' if shutil.which('evince') else 'xdg-open')
        if not shutil.which(viewer):
            parser.error(f"PDF viewer '{viewer}' is not installed.")
        subprocess.Popen([viewer, str(pdf.resolve())], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        sys.exit(130)
    except OSError as error:
        print(f'paper: {error}', file=sys.stderr)
        sys.exit(1)
