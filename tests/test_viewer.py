"""Reader failures must retain the native CLI's actionable diagnostics."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('viewer', Path(__file__).resolve().parents[1] / 'lib/viewer.py')
VIEWER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(VIEWER)


class ViewerTest(unittest.TestCase):
    def test_json_error_survives_empty_stderr(self):
        response = subprocess.CompletedProcess([], 1, '{"ok": false, "error": "Reader did not respond."}', '')
        with patch.dict(VIEWER.os.environ, {'PAPER_PDF_VIEWER': 'workspace-read'}), patch.object(VIEWER.shutil, 'which', return_value='/bin/workspace-read'), patch.object(VIEWER.subprocess, 'run', return_value=response):
            with self.assertRaisesRegex(ValueError, 'Reader did not respond'):
                VIEWER.open_pdf('/tmp/main.pdf')

    def test_plain_stderr_error_is_preserved(self):
        response = subprocess.CompletedProcess([], 1, '', 'Cannot start reader.')
        with patch.dict(VIEWER.os.environ, {'PAPER_PDF_VIEWER': 'workspace-read'}), patch.object(VIEWER.shutil, 'which', return_value='/bin/workspace-read'), patch.object(VIEWER.subprocess, 'run', return_value=response):
            with self.assertRaisesRegex(ValueError, 'Cannot start reader'):
                VIEWER.open_pdf('/tmp/main.pdf')
