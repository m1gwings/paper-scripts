"""Conservative, copy-once LaTeX starters; reusable macros remain versioned."""
from pathlib import Path
import re
import shutil
import uuid

PACKAGE = 'papermacros.sty'
PROJECT_FILES = ('main.tex', 'projectmacros.tex', 'references.bib',
                 'content/01_introduction.tex', 'appendix/01_proofs.tex',
                 'algs/.gitkeep', 'figures/.gitkeep', 'tables/.gitkeep')
IGNORED_DIRECTORIES = {'.git', '.paper', '.github', '.codex', 'notes', 'tasks'}
BUILD_FILES = {'main' + suffix for suffix in
               ('.pdf', '.aux', '.log', '.out', '.bbl', '.blg', '.fdb_latexmk',
                '.fls', '.synctex.gz', '.toc', '.nav', '.snm', '.vrb')}


def safe_path(name):
    path = Path(name)
    for parent in [*path.parents, path]:
        if parent.is_symlink():
            raise ValueError(f'Refusing symlinked scaffold path: {parent}')
    if path.exists() and not path.is_file():
        raise ValueError(f'Expected a regular scaffold file: {path}')
    for parent in path.parents:
        if parent.exists() and not parent.is_dir():
            raise ValueError(f'Expected a scaffold directory: {parent}')
    return path


def source_files():
    """Include untracked assets and links; they can be substantive source too."""
    import os
    names = []
    for root, directories, files in os.walk('.', followlinks=False):
        if root == '.':
            directories[:] = [p for p in directories if p not in IGNORED_DIRECTORIES]
        for name in list(directories):
            path = Path(root) / name
            if path.is_symlink():
                names.append(path.as_posix())
                directories.remove(name)
                return sorted(names)  # Any source symlink makes this non-blank.
        for name in files:
            path = Path(root) / name
            if path.as_posix() not in {'.gitignore', 'AGENTS.md'} | BUILD_FILES:
                names.append(path.as_posix())
                if names != ['main.tex']:
                    return sorted(names)  # One additional asset is already decisive.
    return sorted(names)


def blank_metadata(text):
    """Recognize complete stock skeletons, never arbitrary 'small' manuscripts."""
    text = re.sub(r'(?<!\\)%[^\n]*', '', text)
    field = r'[^{}%]*'
    pattern = (r'\s*\\documentclass\s*\{article\}\s*'
               r'(?:\\usepackage\s*\{graphicx\}\s*)?'
               r'(?:\\title\s*\{(?P<title>' + field + r')\}\s*)?'
               r'(?:\\author\s*\{(?P<author>' + field + r')\}\s*)?'
               r'(?:\\date\s*\{(?P<date>\\today|' + field + r')\}\s*)?'
               r'\\begin\s*\{document\}\s*'
               r'(?:\\maketitle\s*)?'
               r'(?:\\section\s*\{Introduction\}\s*)?'
               r'\\end\s*\{document\}\s*')
    match = re.fullmatch(pattern, text)
    return {k: v for k, v in match.groupdict().items() if v is not None} if match else None


def plan(source, kind, config, manifest, force=False):
    package = (source / 'templates/latex' / PACKAGE).read_bytes()
    installed = bool(config.get('scaffold_type') or PACKAGE in manifest.get('files', {}))
    if installed and not force:
        return {PACKAGE: package}, None, (
            'Detected an installed paper-scripts structure. Preserving manuscript sources; '
            'checking the shared macro package for a conservative upgrade. '
            'Use paper init --force to reinstall the selected starter (replaced files are backed up).')
    names = source_files()
    metadata = {}
    if not names:
        state = 'an empty source tree'
    elif names == ['main.tex'] and not Path('main.tex').is_symlink():
        metadata = blank_metadata(Path('main.tex').read_text())
        state = 'a stock blank Overleaf project' if metadata is not None else None
    else:
        state = None
    if state is None and not force:
        return {}, None, (
            'Detected an existing or unrecognized manuscript. Preserving all manuscript '
            'sources, macros, and bibliography; installing workflow tools only. '
            'To install the paper-scripts structure explicitly, use paper init --force '
            '(or paper create --force when creating a project). Replaced starter files '
            'will be backed up; unrelated files will be retained.')
    metadata = metadata or {}
    files = {name: (source / 'templates/latex' / kind / name).read_bytes()
             for name in PROJECT_FILES}
    main = files['main.tex'].decode()
    for key, default in (('title', 'Untitled project'), ('author', 'Author'), ('date', r'\today')):
        main = main.replace('@@' + key.upper() + '@@', metadata.get(key, default))
    files['main.tex'] = main.encode()
    files[PACKAGE] = package
    for name in files:
        safe_path(name)
    reason = 'Explicit --force requested' if force else f'Detected {state}'
    return files, kind, (
        f'{reason}. Installing the {kind} starter structure. '
        'Existing files at starter paths will be backed up before replacement; '
        'unrelated files will be retained. Overleaf changes require paper publish.')


def backup(files):
    replacements = [name for name, data in files.items()
                    if name in PROJECT_FILES + (PACKAGE,)
                    and safe_path(name).exists() and Path(name).read_bytes() != data]
    if not replacements:
        return
    # New private directory per operation; source paths were preflighted above.
    directory = Path('.paper/scaffold-backups') / uuid.uuid4().hex
    safe_path(directory / 'placeholder')
    directory.mkdir(parents=True, exist_ok=False)
    for name in replacements:
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(name, target)
    print(f'Preserved previous starter files in {directory}/: ' + ', '.join(replacements))
