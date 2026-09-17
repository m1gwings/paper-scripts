import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'lib/preview.py'


class PreviewTest(unittest.TestCase):
    def test_real_latex_build_when_installed(self):
        import shutil
        if not shutil.which('latexmk'):
            self.skipTest('latexmk is not installed')
        with tempfile.TemporaryDirectory(prefix='paper preview ') as tmp:
            root = Path(tmp)
            (root / '.paper').mkdir()
            (root / '.paper/config.json').write_text(json.dumps({'root_tex': 'main.tex'}))
            (root / 'main.tex').write_text('\\documentclass{article}\n\\begin{document}\nPreview works.\\end{document}\n')
            # -norc must prevent arbitrary project Perl from running.
            (root / '.latexmkrc').write_text('die "project configuration executed";')
            result = subprocess.run(['python3', str(SCRIPT)], cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((root / '.paper-preview/paper.pdf').read_bytes().startswith(b'%PDF'))

    def test_root_cannot_escape_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.paper').mkdir()
            (root / '.paper/config.json').write_text(json.dumps({'root_tex': '../secret.tex'}))
            result = subprocess.run(['python3', str(SCRIPT)], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('relative .tex', result.stderr)
