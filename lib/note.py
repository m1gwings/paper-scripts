"""Management and creation of standalone research notes in paper repositories."""
import argparse
import datetime
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


STOP_WORDS = {
    'a', 'an', 'the', 'and', 'but', 'or', 'for', 'nor', 'on', 'at', 'to',
    'from', 'by', 'with', 'in', 'of', 'into', 'onto', 'over'
}


def fail(message):
    raise SystemExit(f'paper note: {message}')


def find_paper_root(start=None):
    """Find the root of the current paper repository."""
    current = Path(start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        if (directory / '.git').is_dir() or (directory / '.paper').is_dir() or (directory / 'AGENTS.md').is_file():
            return directory
    result = subprocess.run(['git', 'rev-parse', '--show-toplevel'],
                            cwd=current, capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    fail('Not inside a Git repository or paper project.')


def title_from_name(raw):
    """Derive a polished Title Case string from a note filename."""
    words = re.findall(r'[a-zA-Z0-9]+', raw)
    if not words:
        return 'Research Note'
    titled = []
    for i, word in enumerate(words):
        if i == 0 or i == len(words) - 1 or word.lower() not in STOP_WORDS:
            titled.append(word.capitalize())
        else:
            titled.append(word.lower())
    return ' '.join(titled)


def sanitize_note_name(name):
    """Normalize input into (clean_filename.tex, default_title)."""
    raw = name.strip()
    if raw.startswith('notes/'):
        raw = raw[6:]
    elif raw.startswith('./notes/'):
        raw = raw[8:]
    if raw.endswith('.tex'):
        raw = raw[:-4]
    slug = re.sub(r'[^a-zA-Z0-9]+', '_', raw).strip('_').lower()
    if not slug:
        fail(f'Invalid note name {name!r}. Use letters, numbers, or underscores.')
    return f'{slug}.tex', title_from_name(raw)


def read_template(root):
    """Locate and read the note template (centralized template by default, optional local _template.tex)."""
    local_override = root / 'notes' / '_template.tex'
    if local_override.is_file():
        return local_override.read_text(encoding='utf-8')
    builtin_tpl = Path(__file__).resolve().parents[1] / 'templates' / 'latex' / 'note.tex'
    if builtin_tpl.is_file():
        return builtin_tpl.read_text(encoding='utf-8')
    fail('Standard note template not found.')


def extract_note_title(path):
    """Extract human-readable title from an existing note file."""
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
        if path.suffix == '.tex':
            m = re.search(r'\\Large\\bfseries\s+([^\\}\n]+)', text)
            if m:
                return m.group(1).strip()
            m = re.search(r'\\title\{([^}]+)\}', text)
            if m:
                return m.group(1).strip()
            m = re.search(r'pdftitle=\{([^}]+)\}', text)
            if m:
                return m.group(1).strip()
        elif path.suffix == '.md':
            m = re.search(r'^#\s+(.+)$', text, re.M)
            if m:
                return m.group(1).strip()
    except OSError:
        pass
    return path.stem.replace('_', ' ').title()


def create_note(name, title=None, open_editor=False, force=False, root=None):
    """Create a new standalone LaTeX research note."""
    root = root or find_paper_root()
    notes_dir = root / 'notes'
    notes_dir.mkdir(parents=True, exist_ok=True)

    clean_filename, default_title = sanitize_note_name(name)
    target = notes_dir / clean_filename

    if target.exists() and not force:
        rel = target.relative_to(root)
        fail(f"'{rel}' already exists. Use --force to overwrite.")

    effective_title = title.strip() if title and title.strip() else default_title
    tpl = read_template(root)
    content = tpl.replace('@@TITLE@@', effective_title)

    target.write_text(content, encoding='utf-8')

    rel_path = target.relative_to(root)
    print(f'Created {rel_path}')
    print(f'Title:   {effective_title}')
    print(f'Compile: paper build {rel_path}')

    if open_editor:
        if shutil.which('workspace-edit'):
            res = subprocess.run(['workspace-edit', str(target.resolve())],
                                 capture_output=True, text=True)
            if res.returncode == 0:
                print('Opened in Editor.')
        else:
            print('workspace-edit not found; opened file on disk.')
    return target


def list_notes(root=None):
    """List research notes in notes/ with title and compilation status."""
    root = root or find_paper_root()
    notes_dir = root / 'notes'
    if not notes_dir.is_dir():
        print('No notes/ directory found.')
        print("Create a note with: paper note new <name>")
        return

    candidates = sorted([
        p for p in notes_dir.iterdir()
        if p.is_file() and not p.name.startswith('.')
        and p.name not in ('README.md', 'template.tex')
        and p.suffix in ('.tex', '.md')
    ])

    if not candidates:
        print('No research notes found in notes/.')
        print('Create a new note with: paper note new <name>')
        return

    records = []
    for p in candidates:
        title = extract_note_title(p)
        stem = p.stem
        pdf_out = root / 'output' / 'notes' / f'{stem}.pdf'
        pdf_aux = root / 'output' / '.latex' / 'notes' / f'{stem}.pdf'
        has_pdf = pdf_out.is_file() or pdf_aux.is_file()
        records.append({
            'name': p.name,
            'title': title,
            'pdf': 'built' if has_pdf else '-'
        })

    max_name = max(max(len(r['name']) for r in records), 15)
    max_title = max(max(len(r['title']) for r in records), 20)

    print(f"{'NOTE':<{max_name}}  {'PDF':<6}  {'TITLE'}")
    print(f"{'-' * max_name}  {'-' * 6}  {'-' * min(max_title, 40)}")
    for r in records:
        print(f"{r['name']:<{max_name}}  {r['pdf']:<6}  {r['title']}")


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    else:
        argv = list(argv)

    if argv and argv[0] not in ('list', 'status', 'new', 'create', 'init', '-h', '--help'):
        argv.insert(0, 'new')

    parser = argparse.ArgumentParser(
        prog='paper note',
        description='Create and manage standalone LaTeX research notes in notes/.'
    )
    subparsers = parser.add_subparsers(dest='subcommand', help='Action to perform')

    # list
    subparsers.add_parser('list', help='List research notes and build status')
    subparsers.add_parser('status', help='List research notes and build status')

    # new / create / init
    for sub in ('new', 'create', 'init'):
        sp = subparsers.add_parser(sub, help='Initialize a new standalone research note')
        sp.add_argument('name', help='Note filename or slug (e.g. fixed_budget or "Lower Bound")')
        sp.add_argument('--title', help='Custom title banner for the note document')
        sp.add_argument('--open', action='store_true', help='Open the new note in Editor')
        sp.add_argument('--force', action='store_true', help='Overwrite existing note if present')

    if not argv:
        list_notes()
        return 0

    args = parser.parse_args(argv)

    if args.subcommand in ('list', 'status'):
        list_notes()
        return 0

    if args.subcommand in ('new', 'create', 'init'):
        create_note(args.name, title=args.title, open_editor=args.open, force=args.force)
        return 0

    parser.print_help()
    return 0


if __name__ == '__main__':
    main()
