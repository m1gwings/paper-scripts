"""Select and launch an optional external document reader, independent of builds."""
import os
from pathlib import Path
import shutil
import subprocess
import json


def open_pdf(pdf, project=None, session=None, background=False):
    viewer = os.environ.get('PAPER_PDF_VIEWER') or (
        'workspace-read' if shutil.which('workspace-read') else 'evince' if shutil.which('evince') else 'xdg-open')
    if not shutil.which(viewer):
        raise ValueError(f"PDF viewer '{viewer}' is not installed.")
    command = [viewer]
    if Path(viewer).name == 'workspace-read':
        command.append('--json')
        if project:
            command += ['--project', str(project)]
        if session:
            command += ['--session', session]
        if background:
            command += ['--background']
    elif not Path(pdf).is_file():
        return  # Native reader can wait for the first build; ordinary viewers cannot.
    command += [str(Path(pdf).resolve())]
    if Path(viewer).name != 'workspace-read':
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=12)
    if result.returncode:
        raise ValueError(result.stderr.strip() or 'Cannot open PDF reader.')
    return json.loads(result.stdout) if Path(viewer).name == 'workspace-read' else None
