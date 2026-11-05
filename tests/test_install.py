"""Check real linked launchers and preservation of unrelated executables."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class InstallTest(unittest.TestCase):
    def test_links_work_outside_checkout(self):
        with tempfile.TemporaryDirectory(prefix='paper links ') as folder:
            target = Path(folder) / 'bin'
            for _ in range(2):
                subprocess.run(['bash', str(SOURCE / 'install.sh'), '--bin-dir', str(target)], check=True, capture_output=True)
            result = subprocess.run([str(target / 'paper'), 'help'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('clear-feature-branches', result.stdout)
            for name in ('project-open', 'project-terminal', 'workspace-edit'):
                result = subprocess.run([str(target / name), '--help'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_collision_preserves_all_targets(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            (target / 'workspace-edit').write_text('unrelated command')
            result = subprocess.run(['bash', str(SOURCE / 'install.sh'), '--bin-dir', folder], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((target / 'workspace-edit').read_text(), 'unrelated command')
            self.assertFalse((target / 'paper').exists())
