#!/usr/bin/env python3
"""Restore the isolated, frozen project TeX toolchain; requires Python, Perl, tar/xz."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile


def download(url, destination, expected):
    subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                    '--max-time', '120', url, '--output', str(destination)], check=True)
    data = destination.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit('Archive checksum mismatch: ' + url)
    destination.write_bytes(data)


def main(config=None):
    from tex_environment import load, installation_root
    config = load()['recipe'] if config is None else config
    engine = config.get('engine_command', 'pdftex')
    root = installation_root(config)
    binaries = root/'bin/x86_64-linux'
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise SystemExit('This pinned restoration recipe supports Linux x86_64.')
    root.parent.mkdir(parents=True, exist_ok=True)
    with (root.parent/(root.name+'.install.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        repository = config['repository']
        stamp = root/'.paper-recipe.json'
        installed = json.loads(stamp.read_text()) if stamp.is_file() else {}
        same = {k:v for k,v in installed.items() if k != 'packages'} == {k:v for k,v in config.items() if k != 'packages'}
        covered = 'scheme-full' in installed.get('packages', []) or set(config['packages']) <= set(installed.get('packages', []))
        if same and covered:
            version = subprocess.check_output([str(binaries/engine), '--version'], text=True).splitlines()[0]
            if version == config['engine_version']:
                print('Pinned TeX toolchain already installed: ' + str(binaries))
                return
        with tempfile.TemporaryDirectory(prefix='paper_texlive_') as scratch:
            scratch = Path(scratch)
            download(repository+'/tlpkg/texlive.tlpdb.xz', scratch/'catalogue.xz', config['catalogue_sha256'])
            if not (binaries/'tlmgr').is_file():
                if root.exists() and any(root.iterdir()):
                    raise SystemExit('Incomplete TeX tree; inspect before resuming: ' + str(root))
                archive = scratch/'installer.tar.gz'
                download(repository+'/install-tl-unx.tar.gz', archive, config['installer_sha256'])
                with tarfile.open(archive) as bundle:
                    bundle.extractall(scratch, filter='data')
                profile = scratch/'install.profile'
                trees = dict(TEXDIR=root, TEXMFLOCAL=root/'texmf-local',
                             TEXMFSYSCONFIG=root/'texmf-config', TEXMFSYSVAR=root/'texmf-var',
                             TEXMFHOME=root/'texmf-home', TEXMFVAR=root/'user-var',
                             TEXMFCONFIG=root/'user-config')
                profile.write_text('selected_scheme scheme-basic\n' +
                    ''.join(f'{key} {value}\n' for key, value in trees.items()) +
                    'binary_x86_64-linux 1\ntlpdbopt_install_docfiles 0\n'
                    'tlpdbopt_install_srcfiles 0\ntlpdbopt_autobackup 0\ninstopt_adjustpath 0\n')
                installer = next(scratch.glob('install-tl-*/install-tl'))
                subprocess.run(['perl', str(installer), '--profile', str(profile),
                                '--repository', repository], check=True)
            subprocess.run([str(binaries/'tlmgr'), '--repository', repository,
                            'install', *config['packages']], check=True)
            version = subprocess.check_output([str(binaries/engine), '--version'], text=True).splitlines()[0]
            if version != config['engine_version']:
                # Overleaf 2025 combines the original engine with newer packages.
                if 'engine_repository' not in config:
                    raise SystemExit('Engine differs; recipe needs a verified engine_repository.')
                engine_repository = config['engine_repository']
                download(engine_repository+'/tlpkg/texlive.tlpdb.xz', scratch/'engine-catalogue.xz',
                         config['engine_catalogue_sha256'])
                subprocess.run([str(binaries/'tlmgr'), 'repository', 'set', repository+'#main',
                                engine_repository+'#overleaf-engine'], check=True)
                subprocess.run([str(binaries/'tlmgr'), 'pinning', 'add', 'overleaf-engine',
                                engine+'.x86_64-linux'], check=True)
                subprocess.run([str(binaries/'tlmgr'), 'install', '--reinstall',
                                engine+'.x86_64-linux'], check=True)
                env = os.environ.copy()
                env['PATH'] = str(binaries)+os.pathsep+env.get('PATH', '')
                subprocess.run([str(binaries/'fmtutil-sys'), '--byengine', engine], env=env, check=True)
                version = subprocess.check_output([str(binaries/engine), '--version'], text=True).splitlines()[0]
                if version != config['engine_version']:
                    raise SystemExit('Restored engine differs from the verified Overleaf engine.')
        stamp.write_text(json.dumps(dict(config, packages=sorted(set(config['packages']) | set(installed.get('packages', []) if same else []))), sort_keys=True)+'\n')
    print('Project TeX toolchain restored: ' + str(binaries))


if __name__ == '__main__':
    main()
