"""Versioned, conservative installation of generated paper infrastructure."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

VERSION = 1
SOURCE = Path(__file__).resolve().parents[1]
LIBRARIES = ['notify.py', 'cloud.py', 'ci.py', 'preview.py', 'preview_notify.py', 'infrastructure.py', 'configure_ci.py']
WORKFLOWS = ['paper-preview.yml', 'paper-publish.yml', 'paper-notify.yml']


def git(*args):
    r = subprocess.run(['git', *args], text=True, capture_output=True)
    return r.stdout.strip() if r.returncode == 0 else ''


def safe_path(path):
    path = Path(path)
    for parent in [*path.parents, path]:
        if parent.is_symlink():
            raise ValueError(f'Refusing symlinked generated path: {parent}')
    if path.exists() and not path.is_file():
        raise ValueError(f'Expected a regular file: {path}')
    for parent in path.parents:
        if parent.exists() and not parent.is_dir():
            raise ValueError(f'Expected a directory: {parent}')
    return path


def read_json(path, default):
    path = safe_path(path)
    if not path.exists():
        return default
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f'{path} must contain a JSON object.')
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def discover():
    ref = git('symbolic-ref', '--quiet', '--short', 'refs/remotes/overleaf/HEAD')
    base = ref.removeprefix('overleaf/') if ref else ''
    if not base:
        for name in ('main', 'master'):
            if git('rev-parse', '--verify', f'refs/remotes/overleaf/{name}'):
                base = name
                break
    url = git('remote', 'get-url', 'overleaf')
    match = re.fullmatch(r'https://(?:git@)?git\.overleaf\.com/([a-zA-Z0-9]+?)/?', url)
    return {'version': VERSION, 'base_branch': base,
            'overleaf_project_id': match[1] if match else '',
            'root_tex': 'main.tex', 'notify_provider': 'none'}


def config():
    value = read_json('.paper/config.json', {})
    version = value.get('version', VERSION)
    if not isinstance(version, int) or version > VERSION:
        raise ValueError('This configuration needs a newer paper-scripts version.')
    for key, default in discover().items():
        value.setdefault(key, default)
    value['version'] = VERSION
    if value['notify_provider'] not in ('none', 'webhook', 'pushover'):
        raise ValueError('notify_provider must be none, webhook, or pushover.')
    return value


def generated():
    files = {'.paper/runtime/paper': (SOURCE / 'paper').read_bytes(),
             '.paper/runtime/.gitignore': b'__pycache__/\n*.pyc\n'}
    for name in LIBRARIES:
        files['.paper/runtime/lib/' + name] = (SOURCE / 'lib' / name).read_bytes()
    for name in WORKFLOWS:
        files['.github/workflows/' + name] = (SOURCE / 'templates' / name).read_bytes()
        # Templates are vendored too, allowing the pinned runtime to repair itself.
        files['.paper/runtime/templates/' + name] = files['.github/workflows/' + name]
    files['.paper/WORKFLOW.md'] = b'''# Paper lifecycle\n\nUse paper start NAME before isolated work, paper commit for local checkpoints,\npaper backup for GitHub backup, and paper publish only on explicit publication\nauthorization. Use paper sync from the base branch when returning to a machine.\nUse paper commands for lifecycle operations; raw Git is reserved for resolving\nconflicts or repairing the implementation. Never commit credentials.\n\nCloud clients need GitHub access (Contents write and Actions read/write),\nPython 3, Git, and gh. Set PAPER_EXECUTION=cloud or git config paper.execution cloud.\nNever provide an Overleaf token to the cloud client. See the setup guide.\n'''
    return files


def plan():
    old = read_json('.paper/manifest.json', {'version': VERSION, 'files': {}})
    if old.get('version', 0) > VERSION:
        raise ValueError('Installed infrastructure is newer than this paper-scripts version.')
    files = generated()
    # Own only untouched generated instructions. Custom AGENTS.md files remain
    # user-owned; the lifecycle reference is available in .paper/WORKFLOW.md.
    agents = safe_path('AGENTS.md')
    source = (SOURCE / 'paper').read_text()
    instructions = source.split("create_init_file AGENTS.md <<'AGENTS'\n", 1)[1].split('\nAGENTS\n', 1)[0].encode() + b'\n'
    if (not agents.exists() or agents.read_bytes() == instructions
            or old.get('files', {}).get('AGENTS.md') == digest(agents.read_bytes())):
        files['AGENTS.md'] = instructions
    for name, data in files.items():
        path = safe_path(name)
        if path.exists() and path.read_bytes() != data:
            previous = old.get('files', {}).get(name)
            if previous is None or digest(path.read_bytes()) != previous:
                raise ValueError(f'Preserving edited/unmanaged file {name}; reconcile it before upgrading.')
    value = config()
    # config is user-owned: preserve custom fields and fill only missing defaults.
    files['.paper/config.json'] = (json.dumps(value, indent=2) + '\n').encode()
    return files


def install():
    files = plan()  # Preflight every conflict before writing any generated file.
    manifest = {'version': VERSION, 'files': {name: digest(data) for name, data in files.items()
                                            if name != '.paper/config.json'}}
    files['.paper/manifest.json'] = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()
    for name, data in files.items():
        path = Path(name)
        if path.exists() and path.read_bytes() == data:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replacement; an interrupted install is repairable by another init.
        temporary = path.with_name(path.name + '.paper-new')
        if temporary.exists() or temporary.is_symlink():
            raise ValueError(f'Remove or review leftover temporary file {temporary}.')
        try:
            with temporary.open('xb') as stream:
                stream.write(data)
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()
        print(f'Installed {name}')
    Path('.paper/runtime/paper').chmod(0o755)
    print(f'Paper infrastructure version {VERSION}. Review and commit generated files before enabling Actions.')
    if not config()['overleaf_project_id']:
        print('Set overleaf_project_id and base_branch in .paper/config.json before using cloud commands.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['preflight', 'install', 'get'])
    parser.add_argument('key', nargs='?')
    args = parser.parse_args()
    try:
        if args.action == 'preflight':
            plan()
        elif args.action == 'install':
            install()
        else:
            value = read_json('.paper/config.json', {})
            result = value.get(args.key)
            if not isinstance(result, str) or not result:
                raise ValueError(f'Run paper init and configure {args.key} in .paper/config.json.')
            print(result)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f'paper init: {error}\n')


if __name__ == '__main__':
    main()
