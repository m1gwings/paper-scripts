"""Canonical local PDF builds and continuous preview, independent of an IDE."""
import argparse
import json
import fcntl
import os
import re
import time
from pathlib import Path
import shutil
import subprocess
import sys
from viewer import open_pdf


def is_valid_pdf(data):
    if not data or len(data) < 100:
        return False
    return b'%PDF-' in data[:1024] and b'%%EOF' in data[-2048:]


def file_stamp(path):
    try:
        info = path.stat()
        return info.st_mtime_ns, info.st_size, info.st_ino
    except FileNotFoundError:
        return None


def dependencies(source, out):
    """Use TeX's recorder and latexmk's database (which also includes BibTeX)."""
    paths = {source.resolve(), Path('.latexmkrc').resolve(), Path('latexmkrc').resolve()}
    recorder = out / (source.stem + '.fls')
    if recorder.exists():
        paths.update(Path(line[6:]).resolve() for line in recorder.read_text(errors='replace').splitlines()
                     if line.startswith('INPUT '))
    database = out / (source.stem + '.fdb_latexmk')
    if database.exists():
        for line in database.read_text(errors='replace').splitlines():
            match = re.match(r'  "((?:[^"\\]|\\.)*)" \d', line)
            if match:
                name = re.sub(r'\\(["\\])', r'\1', match[1])
                paths.add(Path(name).resolve())
    # Generated inputs change during compilation; they must not trigger a loop.
    output = Path('output').resolve()
    paths = {p for p in paths if not p.is_relative_to(output)}
    # A newly created missing input must also wake a failed build.
    paths.update(p.parent for p in list(paths) if p.is_relative_to(Path.cwd()))
    return paths


def compile_locked(command, out):
    # All roots sharing an auxiliary directory may write the same include files.
    # Keep the descriptor in latexmk too, so an interrupted wrapper cannot release
    # the lock while its child is still writing output.
    with (out / '.build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        source = Path(command[-1])
        pdf = out / (source.stem + '.pdf')
        state_file = out / (source.stem + '.build.json')
        last_good = pdf.with_suffix('.pdf.last-good')
        clean = '-C' in command
        old_pdf = pdf.read_bytes() if pdf.is_file() else None
        old_mtime = pdf.stat().st_mtime_ns if pdf.is_file() else None
        if old_pdf and not is_valid_pdf(old_pdf):
            if last_good.is_file() and is_valid_pdf(last_good.read_bytes()):
                old_pdf = last_good.read_bytes()
                old_mtime = last_good.stat().st_mtime_ns
            else:
                old_pdf = None
                old_mtime = None
        elif old_pdf and is_valid_pdf(old_pdf):
            try:
                pending_lg = last_good.with_suffix('.tmp')
                pending_lg.write_bytes(old_pdf)
                pending_lg.replace(last_good)
            except OSError:
                pass
        try:
            previous = json.loads(state_file.read_text())
        except (OSError, ValueError):
            previous = {}
        last_success = previous.get('last_success', pdf.stat().st_mtime if pdf.exists() and is_valid_pdf(old_pdf) else None)
        def report(state, **extra):
            value = dict(state=state, source=str(source), pdf=str(pdf), updated=time.time(),
                         last_success=last_success, **extra)
            pending = state_file.with_suffix('.json.tmp')
            pending.write_text(json.dumps(value))
            pending.replace(state_file)
        report('building')
        try:
            status = subprocess.run(command, pass_fds=(lock.fileno(),)).returncode
        except BaseException:
            report('failed', error='Compilation interrupted')
            raise
        if status and not clean and old_pdf is not None:
            pending = pdf.with_suffix('.pdf.tmp')
            pending.write_bytes(old_pdf)
            pending.replace(pdf)
            if old_mtime is not None:
                try:
                    os.utime(pdf, ns=(old_mtime, old_mtime))
                except OSError:
                    pass
        elif not status and not clean and pdf.is_file():
            new_data = pdf.read_bytes()
            if is_valid_pdf(new_data):
                try:
                    pending_lg = last_good.with_suffix('.tmp')
                    pending_lg.write_bytes(new_data)
                    pending_lg.replace(last_good)
                except OSError:
                    pass
        if clean:
            report('idle')
        elif status:
            log = out / (source.stem + '.log')
            text = log.read_text(errors='replace') if log.exists() else ''
            match = re.search(r'^(.+?\.tex):(\d+): (.+)$', text, re.M)
            generic = re.search(r'^! (.+)$', text, re.M)
            report('failed', error=match[3] if match else generic[1] if generic else 'Compilation failed; open the build log.',
                   file=match[1] if match else str(source), line=int(match[2]) if match else 1)
        else:
            last_success = pdf.stat().st_mtime if pdf.exists() else None
            report('success')
        return status


def watch(command, source, out):
    with (out / f'.{source.stem}.watch.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f'A continuous builder is already watching {source}.', flush=True)
            return 0
        print(f'Watching {source}; PDF: {out / (source.stem + ".pdf")}. Stop with Ctrl+C.', flush=True)
        previous = None
        while True:
            tracked = dependencies(source, out)
            tracked.add((out / (source.stem + '.pdf')).resolve())
            current = {p: file_stamp(p) for p in tracked}
            if current != previous:
                before = current
                compile_locked(command, out)
                # Retain pre-build stamps so saves during compilation are retried.
                # Newly discovered inputs need a verification pass too: taking
                # their post-build stamp could lose a save during the first build.
                tracked = dependencies(source, out)
                previous = {p: before.get(p) for p in tracked}
                pdf = (out / (source.stem + '.pdf')).resolve()
                previous[pdf] = file_stamp(pdf)
            time.sleep(.5)


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'clean', 'view'))
    parser.add_argument('--watch', action='store_true', help='rebuild after source saves until Ctrl+C')
    parser.add_argument('source', nargs='?', default='main.tex')
    args = parser.parse_intermixed_args(argv)
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
    command.append(str(source))
    if args.watch:
        return watch(command, source, out)
    status = compile_locked(command, out)
    if status or args.action == 'clean':
        return status
    if not pdf.is_file():
        parser.error(f'Build produced no PDF at {pdf}.')
    print(f'PDF: {pdf.resolve()}', flush=True)
    if args.action == 'view':
        open_pdf(pdf, root, os.environ.get('PROJECT_WORKSPACE_ID'))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        sys.exit(130)
    except OSError as error:
        print(f'paper: {error}', file=sys.stderr)
        sys.exit(1)
