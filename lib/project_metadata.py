"""Human-facing project metadata, shared by initialization and local launchers."""
import json
from pathlib import Path
import re

ACRONYMS = {'cmabs': 'CMABs', 'rum': 'RUM', 'mnl': 'MNL', 'rl': 'RL',
            'ml': 'ML', 'ltr': 'LTR', 'phd': 'PhD'}
SMALL_WORDS = {'with', 'of', 'the', 'in', 'for', 'and', 'to', 'from'}


def infer_name(directory):
    directory = Path(directory)
    name = directory.parent.name if directory.name in ('paper', 'poster', 'slides') else directory.name
    words = re.split(r'[_\s-]+', name)
    return ' '.join(ACRONYMS.get(word.lower(), word.lower() if index and word.lower() in SMALL_WORDS
                                else word.capitalize()) for index, word in enumerate(words) if word)


def metadata(directory):
    directory = Path(directory)
    path = directory / '.paper/config.json'
    value = json.loads(path.read_text()) if path.is_file() else {}
    if not isinstance(value, dict):
        raise ValueError('.paper/config.json must contain a JSON object.')
    name = value.get('project_name', infer_name(directory))
    if not isinstance(name, str) or not name.strip() or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError('project_name must be a nonempty, single-line display name.')
    component = value.get('document_type') or (directory.name if directory.name in ('paper', 'poster', 'slides') else '')
    if component not in ('', 'paper', 'poster', 'slides'):
        raise ValueError('document_type must be paper, poster, or slides.')
    source = value.get('root_tex', 'main.tex')
    if not isinstance(source, str) or any(ord(c) < 32 for c in source):
        raise ValueError('root_tex must be a single-line source path.')
    return {'project_name': name.strip(), 'document_type': component, 'root_tex': source}
