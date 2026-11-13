"""Canonical local PDF builds and continuous preview, independent of an IDE."""
import argparse
from contextlib import ExitStack
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
import tex_environment
import overleaf_build

_DEPENDENCIES = {}


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


def auxiliary_directory(source):
    """Keep compiler products hidden, mirroring the source directory hierarchy."""
    return Path("output/.latex") / source.parent


def dependencies(source, out):
    """Use TeX's recorder and latexmk's database (which also includes BibTeX)."""
    identity = (Path.cwd(), source, out)
    manifest_stamp = file_stamp(tex_environment.MANIFEST)
    cached = _DEPENDENCIES.get(identity)
    if cached and cached[0] == manifest_stamp and all(file_stamp(path) == stamp for path, stamp in cached[1].items()):
        return set(cached[2])
    paths = set()
    def add_path(name):
        path = Path(name)
        # Keep the lexical input too: retargeting a symlink must wake the
        # watcher even while the recorder/database remain unchanged.
        paths.update((path.absolute(), path.resolve()))
    for path in (tex_environment.MANIFEST, source, '.latexmkrc', 'latexmkrc'):
        add_path(path)
    aux = auxiliary_directory(source)
    jobname = 'output' if tex_environment.MANIFEST.exists() and tex_environment.load().get('jobname') == 'output' else source.stem
    recorder = aux / (jobname + '.fls')
    database = aux / (jobname + '.fdb_latexmk')
    # Capture before parsing: a concurrent compiler update must invalidate the
    # next scan rather than cache an incomplete dependency list as current.
    stamps = {path: file_stamp(path) for path in (recorder, database)}
    if recorder.exists():
        for line in recorder.read_text(errors='replace').splitlines():
            if line.startswith('INPUT '):
                add_path(line[6:])
    if database.exists():
        for line in database.read_text(errors='replace').splitlines():
            match = re.match(r'  "((?:[^"\\]|\\.)*)" \d', line)
            if match:
                name = re.sub(r'\\(["\\])', r'\1', match[1])
                add_path(name)
    # Generated inputs change during compilation; they must not trigger a loop.
    output = Path('output').resolve()
    generated = (output / '.latex').resolve()
    pdf = (out / (source.stem + '.pdf')).resolve()
    paths = {p for p in paths if not p.is_relative_to(generated) and p != pdf}
    # A newly created missing input must also wake a failed build.
    paths.update(p.parent for p in list(paths)
                 if p.is_relative_to(Path.cwd()) and p.parent != output)
    _DEPENDENCIES[identity] = (manifest_stamp, stamps, frozenset(paths))
    return paths


def compile_locked(command, out):
    # All roots sharing an auxiliary directory may write the same include files.
    # Keep the descriptor in latexmk too, so an interrupted wrapper cannot release
    # the lock while its child is still writing output.
    source = Path(command[-1])
    aux = auxiliary_directory(source)
    with ExitStack() as locks:
        # Coordinate with an older pinned builder when its legacy lock exists.
        legacy = out / '.build.lock'
        inherited = []
        if legacy.exists():
            old_lock = locks.enter_context(legacy.open('a'))
            fcntl.flock(old_lock, fcntl.LOCK_EX)
            inherited.append(old_lock.fileno())
        lock = locks.enter_context((aux / '.build.lock').open('a'))
        fcntl.flock(lock, fcntl.LOCK_EX)
        inherited.append(lock.fileno())
        pdf = out / (source.stem + '.pdf')
        state_file = aux / (source.stem + '.build.json')
        last_good = aux / (source.stem + '.pdf.last-good')
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
                         last_success=last_success, warning=overleaf_build.warning(), **extra)
            pending = state_file.with_suffix('.json.tmp')
            pending.write_text(json.dumps(value))
            pending.replace(state_file)
        overleaf_build.refresh_async()
        report('building')
        active = list(command)
        try:
            env = tex_environment.build_environment()
            active = list(command)
            if env is not None:
                config = tex_environment.load()
                env = tex_environment.configure_job_environment(env, source, aux, config)
                active[0] = str(tex_environment.installation_root(config['recipe'])/'bin/x86_64-linux/latexmk')
                active[1] = tex_environment.COMPILERS[config['compiler']]
                if config.get('shell_escape') == 'enabled':
                    active.insert(-1, '-shell-escape')
                elif config.get('shell_escape') == 'disabled':
                    active.insert(-1, '-no-shell-escape')
                if config.get('jobname') == 'output':
                    active.insert(-1, '-jobname=output')
            status = subprocess.run(active, env=env, pass_fds=tuple(inherited)).returncode
            if not clean and '-jobname=output' in active:
                compiled_log = aux/'output.log'
                if compiled_log.is_file():
                    shutil.copyfile(compiled_log, aux/(source.stem+'.log'))
            if not status and not clean and tex_environment.MANIFEST.exists():
                drift = tex_environment.differences(aux / (source.stem + '.log'), strict=False)
                if drift:
                    print('Overleaf environment drift:\n'+'\n'.join(drift), file=sys.stderr)
                    status = 1
        except (OSError, ValueError, KeyError) as error:
            print(f'paper: {error}', file=sys.stderr)
            status = 1
        except BaseException:
            report('failed', error='Compilation interrupted')
            raise
        compiled = aux / ('output.pdf' if '-jobname=output' in active else pdf.name)
        if not status and not clean and (not compiled.is_file() or not is_valid_pdf(compiled.read_bytes())):
            status = 1
        if status and not clean and old_pdf is not None:
            pending = aux / (source.stem + '.publish.tmp')
            pending.write_bytes(old_pdf)
            pending.replace(pdf)
            if old_mtime is not None:
                try:
                    os.utime(pdf, ns=(old_mtime, old_mtime))
                except OSError:
                    pass
        elif not status and not clean and compiled.is_file():
            new_data = compiled.read_bytes()
            if is_valid_pdf(new_data):
                if not pdf.is_file() or new_data != pdf.read_bytes():
                    pending = aux / (source.stem + '.publish.tmp')
                    pending.write_bytes(new_data)
                    pending.replace(pdf)
                try:
                    pending_lg = last_good.with_suffix('.tmp')
                    pending_lg.write_bytes(new_data)
                    pending_lg.replace(last_good)
                except OSError:
                    pass
        if clean:
            if not status:
                pdf.unlink(missing_ok=True)
                last_good.unlink(missing_ok=True)
            report('idle' if not status else 'failed')
        elif status:
            log = aux / (source.stem + '.log')
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
    with ExitStack() as locks:
        try:
            paths = [out / f'.{source.stem}.watch.lock',
                     auxiliary_directory(source) / f'.{source.stem}.watch.lock']
            for path in paths:
                if path == paths[0] and not path.exists():
                    continue
                lock = locks.enter_context(path.open('a'))
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f'A continuous builder is already watching {source}.', flush=True)
            return 0
        print(f'Watching {source}; PDF: {out / (source.stem + ".pdf")}. Stop with Ctrl+C.', flush=True)
        previous = None
        runtime_files = (Path(__file__).resolve(), Path(tex_environment.__file__).resolve(), Path(overleaf_build.__file__).resolve())
        runtime_stamps = {path: file_stamp(path) for path in runtime_files}
        while True:
            current_runtime = {path: file_stamp(path) for path in runtime_files}
            if current_runtime != runtime_stamps:
                # Wait for a complete, syntactically valid runtime replacement.
                time.sleep(.2)
                if current_runtime != {path: file_stamp(path) for path in runtime_files}:
                    continue
                try:
                    for path in runtime_files:
                        compile(path.read_bytes(), str(path), 'exec')
                except (OSError, SyntaxError):
                    continue
                print('Build runtime updated; reloading watcher.', flush=True)
                os.execv(sys.executable, [sys.executable, str(runtime_files[0]), 'build', '--watch', str(source)])
            overleaf_build.refresh_async()
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
    parser.add_argument('source', nargs='?')
    args = parser.parse_intermixed_args(argv)
    if args.watch and args.action != 'build':
        parser.error('--watch is only available for build')
    result = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if result.returncode:
        parser.error('Not inside a Git repository.')
    root = Path(result.stdout.removesuffix('\n'))
    os.chdir(root)
    try:
        default_source = tex_environment.load()['main'] if tex_environment.MANIFEST.exists() else 'main.tex'
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    source = Path(args.source or default_source)
    if (source.is_absolute() or '..' in source.parts or source.suffix != '.tex'
            or str(source).startswith('-') or any(c in str(source) for c in '\n\r')):
        parser.error('Source must be a relative .tex path inside the repository.')
    if not source.is_file() or not source.resolve().is_relative_to(root.resolve()):
        parser.error(f'Cannot find a source inside the repository: {source}')
    out = Path('output') / source.parent
    if not (root / out).resolve().is_relative_to(root.resolve()):
        parser.error('Output directory must remain inside the repository.')
    aux = auxiliary_directory(source)
    if not (root / aux).resolve().is_relative_to(root.resolve()):
        parser.error('Auxiliary directory must remain inside the repository.')
    out.mkdir(parents=True, exist_ok=True)
    aux.mkdir(parents=True, exist_ok=True)
    tex_environment.prepare_auxiliary_tree(aux)
    pdf = out / (source.stem + '.pdf')
    if pdf.is_symlink():
        parser.error('Refusing a symlinked PDF output.')
    if not tex_environment.MANIFEST.exists() and not shutil.which('latexmk'):
        parser.error("Required command 'latexmk' is not installed.")
    command = ['latexmk', '-pdf', '-interaction=nonstopmode', '-file-line-error',
               '-halt-on-error', '-synctex=1', f'-outdir={aux}', f'-auxdir={aux}']
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
    notice = overleaf_build.warning()
    if notice:
        print('Warning: '+notice, file=sys.stderr)
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
