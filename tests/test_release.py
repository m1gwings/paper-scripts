"""The release manifest links working launchers from outside the checkout."""
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class ReleaseManifestTest(unittest.TestCase):
    def test_declared_launchers_work_through_links(self):
        manifest = tomllib.loads((SOURCE / 'release.toml').read_text())
        self.assertEqual(manifest['name'], 'paper-scripts')
        commands = {Path(target).name: rel for target, rel in manifest['links'].items()}
        self.assertEqual(set(commands), {'paper', 'project-open', 'project-terminal', 'workspace-edit'})
        with tempfile.TemporaryDirectory(prefix='paper links ') as folder:
            for name, rel in commands.items():
                (Path(folder) / name).symlink_to(SOURCE / rel)
            result = subprocess.run([str(Path(folder) / 'paper'), 'help'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('clear-feature-branches', result.stdout)
            for name in ('project-open', 'project-terminal', 'workspace-edit'):
                result = subprocess.run([str(Path(folder) / name), '--help'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
