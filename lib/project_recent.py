"""Best-effort, local-only shortlist of the five most recently opened projects."""
import os
from pathlib import Path
import tempfile

from project_metadata import metadata


def remember(directory):
    try:
        directory = Path(directory).resolve()
        info = metadata(directory)
        label = info['project_name']
        if info['document_type']:
            label += ' (' + info['document_type'] + ')'
        label = label.replace('|', '/')
        if any(ord(c) < 32 for c in str(directory)):
            return
        state = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'project-open'
        state.mkdir(parents=True, exist_ok=True)
        cache = state / 'recent-projects.md'
        entries = [(label, str(directory))]
        for line in cache.read_text().splitlines() if cache.exists() else []:
            if line.startswith('- ') and ' | ' in line:
                name, path = line[2:].split(' | ', 1)
                if Path(path).is_absolute() and Path(path).is_dir() and path not in {p for _, p in entries}:
                    entries.append((name, path))
        text = '# Recent projects\n' + ''.join(f'- {name} | {path}\n' for name, path in entries[:5])
        with tempfile.NamedTemporaryFile(mode='w', dir=state, prefix='.recent-', delete=False) as temporary:
            temporary.write(text)
        try:
            os.replace(temporary.name, cache)
        finally:
            Path(temporary.name).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass  # A disposable cache must never prevent opening a project.
