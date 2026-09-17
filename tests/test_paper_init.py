import os
from pathlib import Path
import subprocess
import test_workflow

INIT = Path(__file__).resolve().parents[1] / 'paper-init'


class ExistingInitTest(test_workflow.WorkflowTest):
    def setUp(self):
        super().setUp()
        self.git('remote', 'set-url', 'github', 'https://github.com/owner/paper.git')
        self.git('remote', 'set-url', 'overleaf', 'https://git@git.overleaf.com/abc123')
        tools = self.root / 'tools'
        tools.mkdir()
        gh = tools / 'gh'
        gh.write_text('#!/bin/sh\ncase "$1 $2" in\n"auth status") exit 0;;\n"repo view") echo owner/paper;;\n*) exit 99;;\nesac\n')
        gh.chmod(0o755)
        self.env['PATH'] = str(tools) + os.pathsep + os.environ['PATH']

    def test_existing_directory_upgraded_without_repointing_or_committing(self):
        head = self.git('rev-parse', 'HEAD')
        result = subprocess.run(['bash', str(INIT), 'abc123', 'owner/paper', str(self.repo)],
                                cwd=self.root, env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertEqual(self.git('remote', 'get-url', 'overleaf'), 'https://git@git.overleaf.com/abc123')
        self.assertTrue((self.repo / '.paper/manifest.json').exists())

    def test_mismatched_existing_project_refused(self):
        result = subprocess.run(['bash', str(INIT), 'wrongproject', 'owner/paper', str(self.repo)],
                                cwd=self.root, env=self.env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.repo / '.paper').exists())

for name in list(test_workflow.WorkflowTest.__dict__):
    if name.startswith('test_'):
        setattr(ExistingInitTest, name, None)
