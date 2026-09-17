import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_workflow


class InfrastructureTest(test_workflow.WorkflowTest):
    def test_idempotent_upgrade_preserves_user_configuration(self):
        self.paper('init')
        config = self.repo / '.paper/config.json'
        value = json.loads(config.read_text())
        self.assertEqual(value['base_branch'], 'master')
        value['root_tex'] = 'manuscript.tex'
        value['custom'] = 'preserved'
        config.write_text(json.dumps(value))
        self.paper('init')
        before = {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob('*')
                  if p.is_file() and '.git' not in p.parts}
        self.paper('init')
        after = {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob('*')
                 if p.is_file() and '.git' not in p.parts}
        self.assertEqual(before, after)
        self.assertEqual(json.loads(config.read_text())['custom'], 'preserved')
        target = self.repo / '.github/workflows/paper-preview.yml'
        target.unlink()
        self.paper('init')
        self.assertTrue(target.exists())
        notify = self.repo / '.github/workflows/paper-notify.yml'
        self.assertIn('Notification provider is not configured', notify.read_text())

    def test_custom_workflow_and_symlinks_not_overwritten(self):
        workflows = self.repo / '.github/workflows'
        workflows.mkdir(parents=True)
        target = workflows / 'paper-publish.yml'
        target.write_text('custom workflow')
        self.paper('init', ok=False)
        self.assertEqual(target.read_text(), 'custom workflow')
        self.assertFalse((self.repo / 'AGENTS.md').exists())
        target.unlink()
        target.symlink_to(self.repo / 'main.tex')
        self.paper('init', ok=False)
        self.assertFalse((self.repo / 'AGENTS.md').exists())

    def test_modified_generated_file_and_future_version_refused(self):
        self.paper('init')
        target = self.repo / '.paper/runtime/paper'
        original = target.read_bytes()
        target.write_bytes(original + b'\n# user edit\n')
        self.paper('init', ok=False)
        self.assertTrue(target.read_bytes().endswith(b'# user edit\n'))
        target.write_bytes(original)
        manifest = self.repo / '.paper/manifest.json'
        value = json.loads(manifest.read_text())
        value['version'] = 999
        manifest.write_text(json.dumps(value))
        self.paper('init', ok=False)

    def test_vendored_runtime_can_repair_itself(self):
        self.paper('init')
        target = self.repo / '.github/workflows/paper-preview.yml'
        target.unlink()
        subprocess.run(['bash', '.paper/runtime/paper', 'init'], cwd=self.repo,
                       env=self.env, check=True, capture_output=True)
        self.assertTrue(target.exists())
        self.git('add', '.')
        self.git('commit', '-qm', 'generated infrastructure')
        cache = self.repo / '.paper/runtime/lib/__pycache__'
        cache.mkdir(exist_ok=True)
        (cache / 'example.pyc').write_bytes(b'cache')
        self.assertEqual(self.git('status', '--porcelain'), '')

for name in list(test_workflow.WorkflowTest.__dict__):
    if name.startswith('test_'):
        setattr(InfrastructureTest, name, None)
