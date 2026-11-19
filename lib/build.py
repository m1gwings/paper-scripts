"""Canonical local PDF builds and continuous preview, independent of an IDE."""
import argparse
from contextlib import ExitStack
import json
import hashlib
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


def publish_synctex(compiled, pdf, directory, stem):
    """Retain the completed map under the identity of the PDF it describes."""
    info = pdf.stat()
    generation = directory / f'{info.st_mtime_ns}-{info.st_size}'
    generation.mkdir(parents=True, exist_ok=True)
    for suffix in ('.synctex.gz', '.synctex'):
        raw_map = compiled.with_suffix(suffix)
        published = generation / (stem + suffix)
        if raw_map.is_file():
            data = raw_map.read_bytes()
            if published.is_file() and published.read_bytes() == data:
                continue
            pending = published.with_suffix(published.suffix + '.tmp')
            pending.write_bytes(data)
            pending.replace(published)
        else:
            published.unlink(missing_ok=True)
    return generation


def clean_output_clutter(root=None):
    """Ensure output/ contains only deliverables; move compiler/check artifacts to output/.latex/."""
    root = Path(root) if root else Path.cwd()
    out = root / 'output'
    if not out.is_dir():
        return
    aux = out / '.latex'
    checks_dir = aux / 'checks'
    reviews_dir = aux / 'reviews'

    for item in list(out.iterdir()):
        name = item.name
        if name in ('.latex', '.overleaf', 'notes', 'pdf'):
            continue

        # 1. Lock files: unlink if unheld
        if name.startswith('.') and name.endswith('.lock'):
            try:
                with item.open('a') as fl:
                    fcntl.flock(fl, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(fl, fcntl.LOCK_UN)
                item.unlink(missing_ok=True)
            except (BlockingIOError, OSError):
                pass
            continue

        # 2. Compiler auxiliary leftovers (*.auxlock, *.cut)
        if name.endswith(('.auxlock', '.cut')):
            aux.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(item), str(aux / name))
            except OSError:
                pass
            continue

        # 3. Diagnostic / publish logs
        if name.endswith('.log'):
            aux.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(item), str(aux / name))
            except OSError:
                pass
            continue

        # 4. Review images (.png, .jpg, etc.)
        if item.is_file() and item.suffix.lower() in ('.png', '.jpg', '.jpeg', '.svg'):
            checks_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(item), str(checks_dir / name))
            except OSError:
                pass
            continue

        # 5. Ad-hoc TeX checks inside output/ and their matching PDFs
        if item.is_file() and item.suffix == '.tex':
            checks_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(item), str(checks_dir / name))
            except OSError:
                pass
            check_pdf = out / (item.stem + '.pdf')
            if check_pdf.is_file():
                try:
                    shutil.move(str(check_pdf), str(checks_dir / check_pdf.name))
                except OSError:
                    pass
            continue

        # 5b. Ad-hoc check PDFs (without .tex in root, notes or variants)
        if item.is_file() and item.suffix == '.pdf':
            is_check_name = any(t in item.stem.lower() for t in ('check', 'debug', 'refactor_review'))
            has_source = (root / f'{item.stem}.tex').is_file() or (root / 'notes' / f'{item.stem}.tex').is_file() or (root / 'variants' / f'{item.stem}.tex').is_file()
            if is_check_name and not has_source:
                checks_dir.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(item), str(checks_dir / name))
                except OSError:
                    pass
                continue

        # 6. Review directories (e.g. final-uif-review, tikz-review)
        if item.is_dir() and ('review' in name.lower() or 'check' in name.lower()):
            reviews_dir.mkdir(parents=True, exist_ok=True)
            target = reviews_dir / name
            try:
                if target.exists():
                    shutil.rmtree(str(target))
                shutil.move(str(item), str(target))
            except OSError:
                pass
            continue

        # 7. Stray nested output dir (e.g. output/output)
        if item.is_dir() and name == 'output':
            checks_dir.mkdir(parents=True, exist_ok=True)
            for sub in list(item.iterdir()):
                try:
                    if sub.name.endswith('.lock'):
                        sub.unlink(missing_ok=True)
                    else:
                        shutil.move(str(sub), str(checks_dir / sub.name))
                except OSError:
                    pass
            try:
                item.rmdir()
            except OSError:
                pass
            continue

        # 8. Empty directories (e.g. output/appendix if empty)
        if item.is_dir():
            try:
                item.rmdir()
            except OSError:
                pass


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
    is_main_overleaf = tex_environment.MANIFEST.exists() and source == Path(tex_environment.load().get('main', 'main.tex'))
    jobname = 'output' if is_main_overleaf and tex_environment.load().get('jobname') == 'output' else source.stem
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
        # Check and remove stale legacy lock in output/ if unheld
        legacy = out / '.build.lock'
        inherited = []
        if legacy.exists():
            try:
                with legacy.open('a') as fl:
                    fcntl.flock(fl, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(fl, fcntl.LOCK_UN)
                legacy.unlink(missing_ok=True)
            except BlockingIOError:
                old_lock = locks.enter_context(legacy.open('a'))
                fcntl.flock(old_lock, fcntl.LOCK_EX)
                inherited.append(old_lock.fileno())
            except OSError:
                pass
        lock = locks.enter_context((aux / '.build.lock').open('a'))
        fcntl.flock(lock, fcntl.LOCK_EX)
        inherited.append(lock.fileno())
        pdf = out / (source.stem + '.pdf')
        state_file = aux / (source.stem + '.build.json')
        last_good = aux / (source.stem + '.pdf.last-good')
        published_maps = aux / '.synctex' / source.stem
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
                shutil.copy2(pdf, pending_lg)
                pending_lg.replace(last_good)
            except OSError:
                pass
        try:
            previous = json.loads(state_file.read_text())
        except (OSError, ValueError):
            previous = {}
        last_success = previous.get('last_success', pdf.stat().st_mtime if pdf.exists() and is_valid_pdf(old_pdf) else None)
        build_signature = previous.get('build_signature')
        requested_signature = None
        def report(state, **extra):
            value = dict(state=state, source=str(source), pdf=str(pdf), updated=time.time(),
                         last_success=last_success, build_signature=build_signature,
                         warning=overleaf_build.warning(), **extra)
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
                is_main_overleaf = source == Path(config.get('main', 'main.tex'))
                if is_main_overleaf:
                    env = tex_environment.configure_job_environment(env, source, aux, config)
                active[0] = str(tex_environment.installation_root(config['recipe'])/'bin/x86_64-linux/latexmk')
                active[1] = tex_environment.COMPILERS[config['compiler']]
                if config.get('shell_escape') == 'enabled':
                    active.insert(-1, '-shell-escape')
                elif config.get('shell_escape') == 'disabled':
                    active.insert(-1, '-no-shell-escape')
                if is_main_overleaf and config.get('jobname') == 'output':
                    active.insert(-1, '-jobname=output')
                requested_signature = hashlib.sha256(json.dumps(dict(command=active, config=config), sort_keys=True).encode()).hexdigest()
                if not clean and requested_signature != build_signature:
                    # latexmk does not invalidate old outputs for every engine /
                    # shell-mode change. Rebuild once, then retain its fast path.
                    active.insert(-1, '-g')
            status = subprocess.run(active, env=env, pass_fds=tuple(inherited)).returncode
            if not clean and '-jobname=output' in active:
                compiled_log = aux/'output.log'
                if compiled_log.is_file():
                    shutil.copyfile(compiled_log, aux/(source.stem+'.log'))
            if not status and not clean and tex_environment.MANIFEST.exists() and is_main_overleaf:
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
        if not status and not clean:
            try:
                new_data = compiled.read_bytes()
                if not is_valid_pdf(new_data):
                    raise ValueError(f'Invalid compiled PDF: {compiled}')
                pending = pdf
                if not pdf.is_file() or new_data != pdf.read_bytes():
                    pending = aux / (source.stem + '.publish.tmp')
                    pending.write_bytes(new_data)
                generation = publish_synctex(compiled, pending, published_maps, source.stem)
                if pending != pdf:
                    out.mkdir(parents=True, exist_ok=True)
                    pending.replace(pdf)
            except (OSError, ValueError) as error:
                print(f'paper: could not publish the build: {error}', file=sys.stderr)
                status = 1
            else:
                for older in published_maps.iterdir():
                    if older != generation and older.is_dir():
                        shutil.rmtree(older, ignore_errors=True)
                try:
                    pending_lg = last_good.with_suffix('.tmp')
                    shutil.copy2(pdf, pending_lg)
                    pending_lg.replace(last_good)
                except OSError:
                    pass
        if status and not clean and old_pdf is not None and (not pdf.is_file() or pdf.read_bytes() != old_pdf):
            pending = aux / (source.stem + '.publish.tmp')
            pending.write_bytes(old_pdf)
            if old_mtime is not None:
                os.utime(pending, ns=(old_mtime, old_mtime))
            out.mkdir(parents=True, exist_ok=True)
            pending.replace(pdf)
        if clean:
            if not status:
                pdf.unlink(missing_ok=True)
                last_good.unlink(missing_ok=True)
                if published_maps.is_dir():
                    shutil.rmtree(published_maps)
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
            build_signature = requested_signature
            report('success')
        clean_output_clutter(Path.cwd())
        return status


def make_command(source, aux, clean=False):
    command = ['latexmk', '-pdf', '-interaction=nonstopmode', '-file-line-error',
               '-halt-on-error', '-synctex=1', f'-outdir={aux}', f'-auxdir={aux}']
    if clean:
        command.append('-C')
    command.append(str(source))
    return command


def is_root_document(path):
    """Check if a .tex file declares \\documentclass or \\documentstyle (standalone document)."""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                clean_line = re.sub(r'(?<!\\)(?:\\\\)*%.*$', '', line).strip()
                if not clean_line:
                    continue
                if re.search(r'\\(documentclass|documentstyle)\b', clean_line):
                    return True
                if r'\begin{document}' in clean_line:
                    break
    except OSError:
        return False
    return False


def find_project_roots(root):
    """Find all compilable LaTeX root documents inside the project."""
    roots = []
    default_main = 'main.tex'
    if tex_environment.MANIFEST.exists():
        try:
            default_main = tex_environment.load().get('main', default_main)
        except (OSError, ValueError):
            pass
    main_path = root / default_main
    if main_path.is_file() and main_path.suffix == '.tex':
        roots.append(Path(default_main))

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d not in ('output', 'tasks', 'references', 'tools')]
        rel_dir = Path(dirpath).relative_to(root)
        for name in filenames:
            if not name.endswith('.tex') or name.startswith('.') or name.startswith('_') or name in ('template.tex', 'sample.tex'):
                continue
            rel_file = rel_dir / name if str(rel_dir) != '.' else Path(name)
            if rel_file in roots:
                continue
            full_path = root / rel_file
            if full_path.is_file() and is_root_document(full_path):
                roots.append(rel_file)
    return sorted(roots)


def watch_project(root):
    output_latex = Path('output/.latex')
    output_latex.mkdir(parents=True, exist_ok=True)
    legacy = Path('output/.project.watch.lock')
    if legacy.exists():
        try:
            with legacy.open('a') as fl:
                fcntl.flock(fl, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fl, fcntl.LOCK_UN)
            legacy.unlink(missing_ok=True)
        except BlockingIOError:
            print('A continuous builder is already watching the project.', flush=True)
            return 0
        except OSError:
            pass

    with ExitStack() as locks:
        try:
            paths = [output_latex / '.project.watch.lock']
            for path in paths:
                lock = locks.enter_context(path.open('a'))
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('A continuous builder is already watching the project.', flush=True)
            return 0

        source_locks = {}

        def close_source_locks():
            for f in source_locks.values():
                try:
                    f.close()
                except OSError:
                    pass
            source_locks.clear()

        locks.callback(close_source_locks)

        runtime_files = (Path(__file__).resolve(), Path(tex_environment.__file__).resolve(), Path(overleaf_build.__file__).resolve())
        runtime_stamps = {path: file_stamp(path) for path in runtime_files}

        tracked_roots = {}
        print('Watching project for document changes. Stop with Ctrl+C.', flush=True)

        while True:
            current_runtime = {path: file_stamp(path) for path in runtime_files}
            if current_runtime != runtime_stamps:
                time.sleep(.2)
                if current_runtime != {path: file_stamp(path) for path in runtime_files}:
                    continue
                try:
                    for path in runtime_files:
                        compile(path.read_bytes(), str(path), 'exec')
                except (OSError, SyntaxError):
                    continue
                print('Build runtime updated; reloading watcher.', flush=True)
                close_source_locks()
                os.execv(sys.executable, [sys.executable, str(runtime_files[0]), 'build', '--watch'])

            overleaf_build.refresh_async()

            current_roots = set(find_project_roots(root))

            for src in list(tracked_roots.keys()):
                if src not in current_roots:
                    del tracked_roots[src]
                    if src in source_locks:
                        try:
                            source_locks[src].close()
                        except OSError:
                            pass
                        del source_locks[src]

            for src in current_roots:
                if src not in tracked_roots:
                    out = Path('output') / src.parent
                    aux = auxiliary_directory(src)
                    out.mkdir(parents=True, exist_ok=True)
                    aux.mkdir(parents=True, exist_ok=True)
                    tex_environment.prepare_auxiliary_tree(aux)

                    lock_file_path = aux / f'.{src.stem}.watch.lock'
                    try:
                        fl = lock_file_path.open('a')
                        fcntl.flock(fl, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        source_locks[src] = fl
                    except BlockingIOError:
                        print(f'Another watcher is already watching {src}; skipping.', flush=True)
                        continue

                    cmd = make_command(src, aux)
                    pdf = (out / (src.stem + '.pdf')).resolve()
                    print(f'Watching {src}; PDF: {out / (src.stem + ".pdf")}. Stop with Ctrl+C.', flush=True)
                    tracked_roots[src] = {
                        'out': out,
                        'aux': aux,
                        'command': cmd,
                        'pdf': pdf,
                        'previous': None
                    }

            for src, info in list(tracked_roots.items()):
                out = info['out']
                cmd = info['command']
                pdf = info['pdf']
                tracked = dependencies(src, out)
                tracked.add(pdf)
                current = {p: file_stamp(p) for p in tracked}
                if current != info['previous']:
                    before = current
                    compile_locked(cmd, out)
                    tracked = dependencies(src, out)
                    info['previous'] = {p: before.get(p) for p in tracked}
                    info['previous'][pdf] = file_stamp(pdf)

            time.sleep(.5)


def watch(command, source, out):
    aux = auxiliary_directory(source)
    aux.mkdir(parents=True, exist_ok=True)
    legacy = out / f'.{source.stem}.watch.lock'
    if legacy.exists():
        try:
            with legacy.open('a') as fl:
                fcntl.flock(fl, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fl, fcntl.LOCK_UN)
            legacy.unlink(missing_ok=True)
        except BlockingIOError:
            print(f'A continuous builder is already watching {source}.', flush=True)
            return 0
        except OSError:
            pass

    with ExitStack() as locks:
        try:
            paths = [aux / f'.{source.stem}.watch.lock']
            for path in paths:
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
    if not tex_environment.MANIFEST.exists() and not shutil.which('latexmk'):
        parser.error("Required command 'latexmk' is not installed.")
    if args.watch and not args.source:
        return watch_project(root)
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
    command = make_command(source, aux, clean=(args.action == 'clean'))
    if args.watch:
        return watch(command, source, out)
    status = compile_locked(command, out)
    if status or args.action == 'clean':
        if args.action == 'clean':
            clean_output_clutter(root)
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
