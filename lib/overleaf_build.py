"""Automatic, cached Overleaf HTTP enrollment; never requires an agent."""
import argparse
import fcntl
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
import tex_environment

CACHE = Path('output/.overleaf')
STATUS = CACHE/'status.json'
INTERVAL = 300
_PROJECTS = {}


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {} if default is None else default


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(value, indent=2)+'\n'); temporary.replace(path)
    if path == STATUS:
        main = Path(read('.paper/config.json').get('root_tex', 'main.tex'))
        for folder in (Path('output/.latex')/main.parent, Path('output')/main.parent):
            build_state = folder/(main.stem+'.build.json')
            state = read(build_state)
            if state and state.get('warning') != value.get('warning', ''):
                write(build_state, dict(state, warning=value.get('warning', '')))



def project_id():
    cwd = str(Path.cwd())
    if cwd in _PROJECTS:
        return _PROJECTS[cwd]
    result = subprocess.run(['git', 'remote', 'get-url', 'overleaf'], capture_output=True, text=True)
    match = re.fullmatch(r'https://(?:git@)?git\.overleaf\.com/([a-fA-F0-9]{24})/?', result.stdout.strip())
    _PROJECTS[cwd] = match[1] if match else None
    return _PROJECTS[cwd]


def warning():
    if not project_id():
        return ''
    state = read(STATUS)
    if state.get('warning'):
        return state['warning']
    if not state.get('last_success'):
        return 'Overleaf verification pending. Local preview is not yet verified against Overleaf.'
    if time.time()-state['last_success'] > 24*60*60:
        return 'Overleaf verification is stale. The local preview uses the last saved environment.'
    return ''


def package_names(log, catalogue):
    """Map actual compiler input paths to TeX Live packages, including RELOC trees."""
    log_text = Path(log).read_text(errors='replace')
    inputs = set(re.findall(r'texmf-dist/[^\s()<>\[\]{}]+', log_text))
    generated_fonts = set(re.findall(r'/([^/\s<>]+)\.\d+pk', log_text))
    inputs |= {p.replace('texmf-dist/', 'RELOC/', 1) for p in list(inputs)}
    result = set()
    for entry in catalogue.split('\n\n'):
        name = re.search(r'^name (\S+)$', entry, re.M)
        if name and any((line.strip().split(' ', 1)[0] in inputs or (Path(line.strip().split(' ', 1)[0]).stem in generated_fonts and Path(line.strip().split(' ', 1)[0]).suffix in ('.mf', '.tfm'))) for line in entry.splitlines() if line.startswith(' ')):
            result.add(name[1])
    return result


def recipe_for(metadata, log):
    match = re.fullmatch(r'texlive-full:(\d{4})\.1', metadata['image'])
    profile = Path(__file__).with_name('texlive_'+match[1]+'.json') if match else None
    if profile is None or not profile.is_file():
        raise ValueError('No verified restoration profile for '+metadata['image']+'. The previous environment is retained.')
    recipe = read(profile)
    tex_environment.validate_recipe(recipe)
    if 'scheme-full' not in recipe['packages']:
        # Resolve new document dependencies against the same immutable catalogue.
        catalogue = CACHE/('catalogue-'+recipe['catalogue_sha256']+'.xz')
        if not catalogue.is_file():
            from tex_install import download
            download(recipe['repository']+'/tlpkg/texlive.tlpdb.xz', catalogue, recipe['catalogue_sha256'])
        data = catalogue.read_bytes()
        if hashlib.sha256(data).hexdigest() != recipe['catalogue_sha256']:
            raise ValueError('Frozen package catalogue checksum mismatch')
        recipe['packages'] = sorted(set(recipe['packages']) | package_names(log, lzma.decompress(data).decode()))
    return recipe


def source_digest(path):
    digest = hashlib.sha256()
    with zipfile.ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if not name.endswith('/'):
                digest.update(name.encode()+b'\0'+hashlib.sha256(archive.read(name)).digest())
    return digest.hexdigest()


def verify_snapshot(candidate):
    """Build the exact cloud source in isolation; never touch current Editor buffers."""
    source = CACHE/'source.zip'
    if not source.is_file():
        raise ValueError('Matching Overleaf source archive is missing; PDF parity is unverified.')
    root = Path.cwd()
    with tempfile.TemporaryDirectory(prefix='paper-overleaf-verify-') as temporary:
        temporary = Path(temporary)
        with zipfile.ZipFile(source) as archive:
            if sum(item.file_size for item in archive.infolist()) > 512*1024*1024:
                raise ValueError('Overleaf source archive exceeds the verification size limit')
            for item in archive.infolist():
                path = Path(item.filename)
                if path.is_absolute() or '..' in path.parts or ((item.external_attr >> 16) & 0o170000) == 0o120000:
                    raise ValueError('Unsafe path in Overleaf source archive')
            archive.extractall(temporary)
        write(temporary/tex_environment.MANIFEST, candidate)
        subprocess.run(['git', 'init', '-q', str(temporary)], check=True, capture_output=True)
        env = dict(os.environ, PAPER_OVERLEAF_AUTO='0')
        verification_log = root/CACHE/'verification.log'
        with verification_log.open('w') as output:
            process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('build.py').resolve()), 'build'],
                                       cwd=temporary, env=env, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=output, start_new_session=True)
            try:
                status = process.wait(timeout=600)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise ValueError('Isolated local verification exceeded ten minutes; the compiler process was stopped. See the verification log.') from None
        if status:
            raise ValueError('Isolated local build of Overleaf source failed. See the verification log; previous environment retained.')
        main = Path(candidate['main'])
        drift = tex_environment.differences(temporary/'output/.latex'/main.parent/(main.stem+'.log'), candidate)
        if drift:
            with verification_log.open('a') as output:
                output.write('\n'.join(drift)+'\n')
            raise ValueError('Local compiler/package versions differ from the actual Overleaf build. See the verification log.')
        shutil.copyfile(temporary/'output'/main.parent/(main.stem+'.pdf'), root/CACHE/'verification.pdf')
        pages = tex_environment.compare_pdfs(temporary/'output'/main.parent/(main.stem+'.pdf'), root/CACHE/'output.pdf', 72)
        if pages:
            raise ValueError('Local and Overleaf rendered output differ on '+', '.join(pages)+'. Compare verification.pdf with output.pdf in the verification cache.')
        return dict(dpi=72, source_sha256=source_digest(source), environment_sha256=hashlib.sha256(json.dumps(candidate['baseline'], sort_keys=True).encode()).hexdigest(), verified_at=time.time())


def record_failure(code, message):
    previous = read(STATUS)
    state = dict(previous, checked_at=time.time(), code=code,
                 warning='Overleaf verification unavailable: '+message)
    write(STATUS, state)
    return state


def refresh(install=False, fresh=False, helper=None):
    project = project_id()
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        return {}
    if not project:
        return {}
    CACHE.mkdir(parents=True, exist_ok=True)
    with (CACHE/'refresh.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return read(STATUS)
        executable = helper or os.environ.get('PAPER_OVERLEAF_HELPER') or shutil.which('workspace-overleaf')
        if not executable:
            return record_failure('helper_missing', 'HTTP connector is not installed. Restore workspace-overleaf; local compilation can continue.')
        command = [executable, 'capture', '--project', project, '--output', str(CACHE.resolve()), '--source']
        if fresh:
            command.append('--fresh')
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=420)
            if result.returncode:
                try:
                    failure = json.loads(result.stderr.strip().splitlines()[-1])
                except (ValueError, IndexError):
                    failure = dict(code='http_unavailable', error='HTTP connector failed; run workspace-overleaf diagnose to inspect it.')
                return record_failure(failure.get('code', 'http_unavailable'), failure.get('error', 'HTTP connector unavailable'))
            metadata = read(CACHE/'capture.json')
            if metadata.get('project_id') != project or metadata.get('status') != 'success':
                return record_failure('interface_changed', 'HTTP capture did not return valid project metadata.')
            log = CACHE/'output.log'
            baseline = tex_environment.environment(log)
            recipe = recipe_for(metadata, log)
            candidate = dict(version=1, main=tex_environment.source_path(metadata['main']), compiler=metadata['compiler'],
                             recipe=recipe, baseline=baseline, overleaf_image=metadata['image'], jobname='output')
            previous = read(tex_environment.MANIFEST)
            # Loaded packages change with the manuscript; do not dirty a lockfile on every refresh.
            if previous and all(previous.get(k) == candidate.get(k) for k in ('main', 'compiler', 'overleaf_image', 'recipe')):
                candidate = previous
            if install:
                from tex_install import main
                main(recipe)
                old_status = read(STATUS)
                same_source = old_status.get('proof', {}).get('source_sha256') == source_digest(CACHE/'source.zip')
                cloud_environment = hashlib.sha256(json.dumps(baseline, sort_keys=True).encode()).hexdigest()
                same_environment = old_status.get('proof', {}).get('environment_sha256') == cloud_environment
                proof = old_status.get('proof') if same_source and same_environment and previous == candidate else verify_snapshot(dict(candidate, baseline=baseline))
                # Publish the lock only after the new environment passes actual build parity.
                if candidate != previous:
                    write(tex_environment.MANIFEST, candidate)
            else:
                proof = read(STATUS).get('proof')
            project_config = read('.paper/config.json')
            if project_config and project_config.get('root_tex') != metadata['main']:
                write('.paper/config.json', dict(project_config, root_tex=metadata['main']))
            root = tex_environment.installation_root(recipe)
            ready = bool(proof) and (root/'.paper-recipe.json').is_file() and (root/'bin/x86_64-linux'/metadata['compiler']).is_file()
            state = dict(version=1, project_id=project, checked_at=time.time(), last_success=time.time() if ready else read(STATUS).get('last_success'),
                         code='current' if ready else 'installation_pending', image=metadata['image'], compiler=metadata['compiler'],
                         main=metadata['main'], warning='' if ready else 'Overleaf environment captured; native toolchain restoration is pending.',
                         transport='http', proof=proof if install else read(STATUS).get('proof'))
            write(STATUS, state)
            return state
        except (OSError, ValueError, KeyError, subprocess.SubprocessError, SystemExit) as error:
            return record_failure('restoration_unavailable', str(error) if isinstance(error, (ValueError, SystemExit)) else 'HTTP capture or native environment restoration failed; previous verification is retained.')


def refresh_async():
    """Bounded local scheduling only; HTTP/downloads never run on the editing path."""
    if os.environ.get('PAPER_OVERLEAF_AUTO') == '0' or os.environ.get('GITHUB_ACTIONS') == 'true' or not project_id():
        return
    state = read(STATUS)
    if time.time()-max(state.get('checked_at', 0), state.get('scheduled_at', 0)) < INTERVAL:
        return
    write(STATUS, dict(state, scheduled_at=time.time()))
    CACHE.mkdir(parents=True, exist_ok=True)
    with (CACHE/'refresh.log').open('a') as output:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'refresh', '--install'],
                         stdin=subprocess.DEVNULL, stdout=output, stderr=output, start_new_session=True)


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['refresh', 'status'])
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--fresh', action='store_true')
    args = parser.parse_args(argv)
    result = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if result.returncode:
        parser.error('Not inside a Git repository')
    os.chdir(result.stdout.rstrip('\n'))
    state = read(STATUS) if args.action == 'status' else refresh(args.install, args.fresh)
    print(json.dumps(state, indent=2))
    return int(bool(state.get('warning')))


if __name__ == '__main__':
    sys.exit(run())
