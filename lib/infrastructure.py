"""Versioned, conservative installation of generated paper infrastructure."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

VERSION = 3
SOURCE = Path(__file__).resolve().parents[1]
LIBRARIES = ['notify.py', 'cloud.py', 'ci.py', 'preview.py', 'preview_notify.py', 'infrastructure.py', 'configure_ci.py']
WORKFLOWS = ['paper-preview.yml', 'paper-publish.yml', 'paper-notify.yml']
AGENT_BLOCK_BEGIN = '<!-- paper-scripts:begin managed-notifications -->'
AGENT_BLOCK_END = '<!-- paper-scripts:end managed-notifications -->'


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
            'root_tex': 'main.tex', 'notify_provider': 'discord', 'pushover_device': ''}


def config():
    value = read_json('.paper/config.json', {})
    existing = bool(value)
    version = value.get('version', 0 if existing else VERSION)
    if not isinstance(version, int) or version > VERSION:
        raise ValueError('This configuration needs a newer paper-scripts version.')
    for key, default in discover().items():
        value.setdefault(key, default)
    # Version 3 makes Discord the selected backend for this personal workflow.
    # Credentials remain absent until the owner runs configure-notifications.
    if existing and version < 3 and value.get('notify_provider') in ('none', 'pushover'):
        value['notify_provider'] = 'discord'
    value['version'] = VERSION
    if value['notify_provider'] not in ('none', 'discord', 'webhook', 'pushover'):
        raise ValueError('notify_provider must be none, discord, webhook, or pushover.')
    if not isinstance(value['pushover_device'], str):
        raise ValueError('pushover_device must be a device name or an empty string.')
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
    files['.codex/config.toml'] = b'''#:schema https://developers.openai.com/codex/config-schema.json
# Trusted-project default for the Codex desktop app, CLI, and IDE extension.
# Codex cloud chats currently do not accept a repository-level default model.
model = "gpt-5.6-sol"
'''
    files['.paper/WORKFLOW.md'] = b'''# Paper lifecycle\n\nUse paper start NAME before isolated work, paper commit for local checkpoints,\npaper backup for GitHub backup, and paper publish only on explicit publication\nauthorization. Use paper sync from the base branch when returning to a machine.\nUse paper commands for lifecycle operations; raw Git is reserved for resolving\nconflicts or repairing the implementation. Never commit credentials.\n\nUse paper notify for notifications. It dispatches the trusted GitHub Actions\nworkflow; local and cloud agents never receive provider credentials.\n\nCloud clients need GitHub access (Contents write and Actions read/write),\nPython 3, Git, and gh. Set PAPER_EXECUTION=cloud or git config paper.execution cloud.\nNever provide an Overleaf or notification token to the cloud client. See the setup guide.\n'''
    return files


def agent_template():
    source = (SOURCE / 'paper').read_text()
    return source.split("create_init_file AGENTS.md <<'AGENTS'\n", 1)[1].split('\nAGENTS\n', 1)[0] + '\n'


def managed_agent_block(template):
    start = template.index(AGENT_BLOCK_BEGIN)
    end = template.index(AGENT_BLOCK_END, start) + len(AGENT_BLOCK_END)
    return template[start:end] + '\n'


def merge_agent_instructions(current, template):
    if current == template:
        return template
    block = managed_agent_block(template)
    if AGENT_BLOCK_BEGIN in current:
        start = current.index(AGENT_BLOCK_BEGIN)
        end = current.index(AGENT_BLOCK_END, start) + len(AGENT_BLOCK_END)
        suffix = current[end:]
        if suffix.startswith('\n'):
            suffix = suffix[1:]
        return current[:start] + block + suffix
    heading = '## Notifications\n'
    start = current.find(heading)
    if start >= 0:
        end = current.find('\n## ', start + len(heading))
        end = len(current) if end < 0 else end + 1
        old = current[start:end]
        if 'paper notify --title' in old and 'protected GitHub' in old:
            return current[:start] + block + current[end:]
    separator = '' if not current or current.endswith('\n\n') else ('\n' if current.endswith('\n') else '\n\n')
    return current + separator + block


def plan():
    old = read_json('.paper/manifest.json', {'version': VERSION, 'files': {}})
    if old.get('version', 0) > VERSION:
        raise ValueError('Installed infrastructure is newer than this paper-scripts version.')
    files = generated()
    agents = safe_path('AGENTS.md')
    for name, data in files.items():
        path = safe_path(name)
        if path.exists() and path.read_bytes() != data:
            previous = old.get('files', {}).get(name)
            if previous is None or digest(path.read_bytes()) != previous:
                raise ValueError(f'Preserving edited/unmanaged file {name}; reconcile it before upgrading.')
    template = agent_template()
    current = agents.read_text() if agents.exists() else template
    files['AGENTS.md'] = merge_agent_instructions(current, template).encode()
    value = config()
    # config is user-owned: preserve custom fields and fill only missing defaults.
    files['.paper/config.json'] = (json.dumps(value, indent=2) + '\n').encode()
    return files


def install():
    files = plan()  # Preflight every conflict before writing any generated file.
    manifest = {'version': VERSION, 'files': {name: digest(data) for name, data in files.items()
                                            if name not in ('.paper/config.json', 'AGENTS.md')}}
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
