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
AGENT_CLEANUP_BEGIN = '<!-- paper-scripts:begin managed-feature-cleanup -->'
AGENT_CLEANUP_END = '<!-- paper-scripts:end managed-feature-cleanup -->'
AGENT_TASKING_BEGIN = '<!-- paper-scripts:begin managed-tasking -->'
AGENT_TASKING_END = '<!-- paper-scripts:end managed-tasking -->'


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
    for kind in ('paper', 'poster'):
        name = f'AGENTS.{kind}.md'
        files['.paper/runtime/templates/' + name] = (SOURCE / 'templates' / name).read_bytes()
    files['.codex/config.toml'] = b'''#:schema https://developers.openai.com/codex/config-schema.json
# Trusted-project default for the Codex desktop app, CLI, and IDE extension.
# Codex cloud chats currently do not accept a repository-level default model.
model = "gpt-5.6-sol"
'''
    files['.paper/WORKFLOW.md'] = b'''# Paper lifecycle\n\nUse paper start NAME before isolated work, paper commit for local checkpoints,\npaper backup for GitHub backup, and paper publish only on explicit publication\nauthorization. Use paper sync from the base branch when returning to a machine.\nAfter publishing feature work, verify that the remaining non-base branches are\nintegrated, then remove them with paper clear-feature-branches. Use paper commands\nfor lifecycle operations; raw Git is reserved for resolving conflicts or repairing\nthe implementation. Never commit credentials.\n\nUse paper notify for notifications. It dispatches the trusted GitHub Actions\nworkflow; local and cloud agents never receive provider credentials.\n\nCloud clients need GitHub access (Contents write and Actions read/write),\nPython 3, Git, and gh. Set PAPER_EXECUTION=cloud or git config paper.execution cloud.\nNever provide an Overleaf or notification token to the cloud client. See the setup guide.\n'''
    return files


def agent_template(kind='paper'):
    return (SOURCE / 'templates' / f'AGENTS.{kind}.md').read_text()


def managed_agent_block(template, begin, end_marker):
    start = template.index(begin)
    end = template.index(end_marker, start) + len(end_marker)
    return template[start:end] + '\n'


def merge_agent_instructions(current, template):
    if current == template:
        return template
    block = managed_agent_block(template, AGENT_BLOCK_BEGIN, AGENT_BLOCK_END)
    if AGENT_BLOCK_BEGIN in current:
        start = current.index(AGENT_BLOCK_BEGIN)
        end = current.index(AGENT_BLOCK_END, start) + len(AGENT_BLOCK_END)
        suffix = current[end:]
        if suffix.startswith('\n'):
            suffix = suffix[1:]
        current = current[:start] + block + suffix
    else:
        heading = '## Notifications\n'
        start = current.find(heading)
        if start >= 0:
            end = current.find('\n## ', start + len(heading))
            end = len(current) if end < 0 else end + 1
            old = current[start:end]
            if 'paper notify --title' in old and 'protected GitHub' in old:
                current = current[:start] + block + current[end:]
        if AGENT_BLOCK_BEGIN not in current:
            separator = '' if not current or current.endswith('\n\n') else ('\n' if current.endswith('\n') else '\n\n')
            current = current + separator + block

    cleanup = managed_agent_block(template, AGENT_CLEANUP_BEGIN, AGENT_CLEANUP_END)
    if AGENT_CLEANUP_BEGIN in current:
        start = current.index(AGENT_CLEANUP_BEGIN)
        end = current.index(AGENT_CLEANUP_END, start) + len(AGENT_CLEANUP_END)
        suffix = current[end:]
        if suffix.startswith('\n'):
            suffix = suffix[1:]
        current = current[:start] + cleanup + suffix
    else:
        lines = current.splitlines(keepends=True)
        for index, line in enumerate(lines):
            if '.paper/WORKFLOW.md' in line and 'paper publish' in line:
                lines.insert(index + 1, cleanup)
                current = ''.join(lines)
                break
        else:
            separator = ('' if not current or current.endswith('\n\n')
                         else ('\n' if current.endswith('\n') else '\n\n'))
            current = current + separator + cleanup

    tasking = managed_agent_block(template, AGENT_TASKING_BEGIN, AGENT_TASKING_END)
    if AGENT_TASKING_BEGIN in current:
        start = current.index(AGENT_TASKING_BEGIN)
        end = current.index(AGENT_TASKING_END, start) + len(AGENT_TASKING_END)
        suffix = current[end:]
        if suffix.startswith('\n'):
            suffix = suffix[1:]
        return current[:start] + tasking + suffix

    # Migrate the unmarked tasking section generated by older paper-scripts.
    start = current.find('## Tasks and resumption\n')
    delegation = current.find('## Token use and delegation\n', start) if start >= 0 else -1
    if delegation >= 0:
        end = current.find('\n## ', delegation + len('## Token use and delegation\n'))
        end = len(current) if end < 0 else end + 1
        old = current[start:end]
        if ('tasks/NNN_short_name/task.md' in old
                and 'The main agent owns the task checkpoint' in old):
            return current[:start] + tasking + current[end:]

    separator = ('' if not current or current.endswith('\n\n')
                 else ('\n' if current.endswith('\n') else '\n\n'))
    return current + separator + tasking


def plan(poster=False):
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
    value = config()
    if poster:
        value['document_type'] = 'poster'
    kind = value.get('document_type', 'paper')
    if kind not in ('paper', 'poster'):
        raise ValueError('document_type must be paper or poster.')
    template = agent_template(kind)
    current = agents.read_text() if agents.exists() else template
    # Explicit mode selection may replace the untouched standard template only.
    if poster and current == agent_template('paper'):
        current = template
    files['AGENTS.md'] = merge_agent_instructions(current, template).encode()
    # config is user-owned: preserve custom fields and fill only missing defaults.
    files['.paper/config.json'] = (json.dumps(value, indent=2) + '\n').encode()
    return files


def install(poster=False):
    files = plan(poster)  # Preflight every conflict before writing any generated file.
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
    parser.add_argument('--poster', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'preflight':
            plan(args.poster)
        elif args.action == 'install':
            install(args.poster)
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
