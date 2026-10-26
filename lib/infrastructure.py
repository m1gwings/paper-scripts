"""Versioned, conservative installation of generated paper infrastructure."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import scaffold
from project_metadata import infer_name

VERSION = 4
SOURCE = Path(__file__).resolve().parents[1]
LIBRARIES = ['notify.py', 'cloud.py', 'ci.py', 'preview.py', 'preview_notify.py', 'infrastructure.py', 'configure_ci.py', 'create.sh', 'scaffold.py', 'project_open.py', 'build.py', 'project_metadata.py', 'project_workspace.py', 'workspace_edit.py', 'viewer.py']
WORKFLOWS = ['paper-preview.yml', 'paper-publish.yml', 'paper-notify.yml']
DOCUMENT_TYPES = ('paper', 'poster', 'slides')
# Remove only the exact, manifest-owned model default shipped by earlier releases.
RETIRED_FILES = {'.codex/config.toml': '25e69687ee62b45820a6f775de911508c84bc3266e91a630b49e734ad6f562c9'}
AGENT_BLOCK_BEGIN = '<!-- paper-scripts:begin managed-notifications -->'
AGENT_BLOCK_END = '<!-- paper-scripts:end managed-notifications -->'
AGENT_CLEANUP_BEGIN = '<!-- paper-scripts:begin managed-feature-cleanup -->'
AGENT_CLEANUP_END = '<!-- paper-scripts:end managed-feature-cleanup -->'
AGENT_TASKING_BEGIN = '<!-- paper-scripts:begin managed-tasking -->'
AGENT_TASKING_END = '<!-- paper-scripts:end managed-tasking -->'
AGENT_DRAFT_BEGIN = '<!-- paper-scripts:begin managed-drafting -->'
AGENT_DRAFT_END = '<!-- paper-scripts:end managed-drafting -->'


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
            'root_tex': 'main.tex', 'notify_provider': 'discord', 'pushover_device': '',
            'project_name': infer_name(Path.cwd())}


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
    if (not isinstance(value['project_name'], str) or not value['project_name'].strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in value['project_name'])):
        raise ValueError('project_name must be a nonempty, single-line display name.')
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
    for kind in DOCUMENT_TYPES:
        name = f'AGENTS.{kind}.md'
        agent_template(kind)  # Validate editable defaults before any initialization writes.
        files['.paper/runtime/templates/' + name] = (SOURCE / 'templates' / name).read_bytes()
    for path in sorted((SOURCE / 'templates/latex').rglob('*')):
        if path.is_file():
            files['.paper/runtime/templates/latex/' + path.relative_to(SOURCE / 'templates/latex').as_posix()] = path.read_bytes()
    files['.paper/WORKFLOW.md'] = b'''# Paper lifecycle\n\nUse paper start NAME before isolated work, paper commit for local checkpoints,\npaper backup for GitHub backup, and paper publish only with user publication\nauthorization (including existing standing authorization). Use paper sync from the base branch when returning to a machine.\nAfter publishing feature work, verify that the remaining non-base branches are\nintegrated, then remove them with paper clear-feature-branches. Use paper commands\nfor lifecycle operations; raw Git is reserved for resolving conflicts or repairing\nthe implementation. Never commit credentials.\n\nLocal PDF workflow: paper build [ROOT.tex] writes output/ROOT.pdf (main.tex by\ndefault); paper build --watch rebuilds after source saves, and paper view\nbuilds and opens the current PDF externally. Rebuild after document-source\nedits before reporting completion. Keep output/ ignored.\n\nUse paper notify for notifications. It dispatches the trusted GitHub Actions\nworkflow; local and cloud agents never receive provider credentials.\n\nCloud clients need GitHub access (Contents write and Actions read/write),\nPython 3, Git, and gh. Set PAPER_EXECUTION=cloud or git config paper.execution cloud.\nNever provide an Overleaf or notification token to the cloud client. See the setup guide.\n'''
    return files


def agent_template(kind='paper'):
    path = SOURCE / 'templates' / f'AGENTS.{kind}.md'
    template = path.read_text()
    intervals = []
    for begin, end in ((AGENT_BLOCK_BEGIN, AGENT_BLOCK_END),
                       (AGENT_CLEANUP_BEGIN, AGENT_CLEANUP_END),
                       (AGENT_TASKING_BEGIN, AGENT_TASKING_END),
                       (AGENT_DRAFT_BEGIN, AGENT_DRAFT_END)):
        if template.count(begin) != 1 or template.count(end) != 1:
            raise ValueError(f'{path}: keep exactly one {begin} and {end}.')
        start, stop = template.index(begin), template.index(end)
        if stop < start:
            raise ValueError(f'{path}: managed block end precedes its begin marker.')
        intervals.append((start, stop + len(end)))
    intervals.sort()
    if any(left[1] > right[0] for left, right in zip(intervals, intervals[1:])):
        raise ValueError(f'{path}: managed blocks must not overlap or nest.')
    return template


def managed_agent_block(template, begin, end_marker):
    start = template.index(begin)
    end = template.index(end_marker, start) + len(end_marker)
    return template[start:end] + '\n'


def agent_section_end(text, start):
    """Keep the next heading or managed block outside a legacy section."""
    boundary = re.search(r'\n(?=## |<!-- paper-scripts:begin )', text[start:])
    return start + boundary.end() if boundary else len(text)


def merge_agent_instructions(current, template):
    draft = managed_agent_block(template, AGENT_DRAFT_BEGIN, AGENT_DRAFT_END)
    if AGENT_DRAFT_BEGIN in current:
        start = current.index(AGENT_DRAFT_BEGIN)
        stop = current.index(AGENT_DRAFT_END, start) + len(AGENT_DRAFT_END)
        current = current[:start] + draft.rstrip('\n') + current[stop:]
    elif current != template:
        current = current.rstrip() + '\n\n' + draft

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
            end = agent_section_end(current, start + len(heading))
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
        tasks_end = agent_section_end(current, start + len('## Tasks and resumption\n'))
        delegation_end = agent_section_end(current, delegation + len('## Token use and delegation\n'))
        if ('tasks/NNN_short_name/task.md' in current[start:tasks_end]
                and 'The main agent owns the task checkpoint' in current[delegation:delegation_end]):
            # Custom sections may sit between the two legacy generated sections.
            return (current[:start] + tasking + current[tasks_end:delegation]
                    + current[delegation_end:])

    separator = ('' if not current or current.endswith('\n\n')
                 else ('\n' if current.endswith('\n') else '\n\n'))
    return current + separator + tasking


def plan(document_type=None, force=False, verbose=False):
    old = read_json('.paper/manifest.json', {'version': VERSION, 'files': {}})
    if old.get('version', 0) > VERSION:
        raise ValueError('Installed infrastructure is newer than this paper-scripts version.')
    retired_paths(old)  # Validate retired managed paths before any writes.
    files = generated()
    agents = safe_path('AGENTS.md')
    value = config()
    if document_type is not None:
        value['document_type'] = document_type
    kind = value.get('document_type', 'paper')
    if kind not in DOCUMENT_TYPES:
        raise ValueError('document_type must be paper, poster, or slides.')
    sources, scaffold_kind, message = scaffold.plan(SOURCE, kind, value, old, force)
    files.update(sources)
    if scaffold_kind:
        value['scaffold_type'] = scaffold_kind
        value['drafting_api'] = 'agent-v1'
        value['root_tex'] = 'main.tex'
    for name, data in files.items():
        path = safe_path(name)
        if name in scaffold.PROJECT_FILES or (force and name == scaffold.PACKAGE):
            continue
        if path.exists() and path.read_bytes() != data:
            previous = old.get('files', {}).get(name)
            if previous is None or digest(path.read_bytes()) != previous:
                raise ValueError(f'Preserving edited/unmanaged file {name}; reconcile it before upgrading.')
    if sources:
        safe_path('.paper/scaffold-backups/placeholder')
    if verbose:
        print(message)
        if scaffold_kind:
            print('Starter paths: ' + ', '.join(sources))
    template = agent_template(kind)
    current = agents.read_text() if agents.exists() else template
    # Explicit type selection may replace only a recognized untouched default.
    if document_type is not None and matches_agent_default(current, old):
        current = template
    files['AGENTS.md'] = merge_agent_instructions(current, template).encode()
    # config is user-owned: preserve custom fields and fill only missing defaults.
    files['.paper/config.json'] = (json.dumps(value, indent=2) + '\n').encode()
    for name, data in files.items():
        path = Path(name)
        if not path.exists() or path.read_bytes() != data:
            temporary = path.with_name(path.name + '.paper-new')
            if temporary.exists() or temporary.is_symlink():
                raise ValueError(f'Remove or review leftover temporary file {temporary}.')
    return files


def matches_agent_default(current, manifest):
    # Retain recognition across repeated upgrades, even when plain init preserves
    # older editing guidance while refreshing its managed blocks.
    if digest(current.encode()) == manifest.get('agents_default_sha256'):
        return True
    if any(current == agent_template(kind) for kind in DOCUMENT_TYPES):
        return True
    for kind in DOCUMENT_TYPES:
        name = f'.paper/runtime/templates/AGENTS.{kind}.md'
        path = safe_path(name)
        if (path.exists() and digest(path.read_bytes()) == manifest.get('files', {}).get(name)
                and current == path.read_text()):
            return True
    return False


def retired_paths(manifest):
    paths = []
    for name, expected in RETIRED_FILES.items():
        if manifest.get('files', {}).get(name) != expected:
            continue
        path = safe_path(name)
        if path.exists() and digest(path.read_bytes()) == expected:
            paths.append(path)
    return paths


def install(document_type=None, force=False):
    files = plan(document_type, force)  # Preflight every conflict before writing any generated file.
    old = read_json('.paper/manifest.json', {'files': {}})
    agents = Path('AGENTS.md')
    untouched = not agents.exists() or matches_agent_default(agents.read_text(), old)
    scaffold.backup(files)
    for path in retired_paths(old):
        path.unlink()
        print(f'Removed retired generated file {path}')
    manifest = {'version': VERSION, 'files': {name: digest(data) for name, data in files.items()
                                            if name not in ('.paper/config.json', 'AGENTS.md') + scaffold.PROJECT_FILES}}
    if untouched:
        manifest['agents_default_sha256'] = digest(files['AGENTS.md'])
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--poster', action='store_const', const='poster', dest='document_type')
    mode.add_argument('--slides', action='store_const', const='slides', dest='document_type')
    parser.add_argument('--force', action='store_true', help='Reinstall the selected starter; back up replaced files.')
    args = parser.parse_args()
    try:
        if args.action == 'preflight':
            plan(args.document_type, args.force, verbose=True)
        elif args.action == 'install':
            install(args.document_type, args.force)
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
