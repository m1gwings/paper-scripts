"""Old history-alignment invocations are inert compatibility errors."""
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'paper'


class RetiredHistoryTest(unittest.TestCase):
    def test_old_invocations_stop_without_a_repository_or_network(self):
        with tempfile.TemporaryDirectory() as directory:
            for options in ([], ['--help'], ['--dry-run'], ['--from', 'overleaf'], ['--from', 'github']):
                result = subprocess.run(['bash', str(SCRIPT), 'align-history', *options],
                                        cwd=directory, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('History alignment has been retired', result.stderr)
                self.assertIn('paper sync', result.stderr)
                self.assertIn('paper publish', result.stderr)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_normal_help_no_longer_advertises_alignment(self):
        result = subprocess.run(['bash', str(SCRIPT), '--help'], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('align-history', result.stdout)
