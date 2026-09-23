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
        agents = (self.repo / 'AGENTS.md').read_text()
        self.assertIn('paper-scripts:begin managed-tasking', agents)
        self.assertIn('tasks/NNN_short_name/task.md', agents)
        self.assertTrue((self.repo / 'tasks/index.md').exists())

    def test_mismatched_existing_project_refused(self):
        result = subprocess.run(['bash', str(INIT), 'wrongproject', 'owner/paper', str(self.repo)],
                                cwd=self.root, env=self.env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.repo / '.paper').exists())

    def test_new_repository_commits_and_pushes_canonical_initialization(self):
        fresh = self.root / 'fresh'
        github = self.root / 'new-github'
        config = self.root / 'gitconfig'
        config.write_text(
            f'[url "{self.root / "overleaf"}"]\n'
            '    insteadOf = https://git@git.overleaf.com/abc123\n')
        gh = self.root / 'tools/gh'
        gh.write_text(
            '#!/bin/sh\n'
            'case "$1 $2" in\n'
            '"auth status") exit 0;;\n'
            '"repo create")\n'
            '  git init --bare -q "$TEST_GITHUB_REMOTE" &&\n'
            '  git remote add github "$TEST_GITHUB_REMOTE" &&\n'
            '  git push -q -u github HEAD;;\n'
            '*) exit 99;;\n'
            'esac\n')
        gh.chmod(0o755)
        env = dict(self.env, GIT_CONFIG_GLOBAL=str(config),
                   TEST_GITHUB_REMOTE=str(github))
        result = subprocess.run(
            ['bash', str(INIT), 'abc123', 'owner/new-paper', str(fresh)],
            cwd=self.root, env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git('status', '--porcelain', cwd=fresh), '')
        self.assertEqual(self.git('log', '-1', '--format=%s', cwd=fresh),
                         'Initialize paper workflow')
        agents = (fresh / 'AGENTS.md').read_text()
        self.assertIn('paper-scripts:begin managed-tasking', agents)
        self.assertIn('tasks/NNN_short_name/task.md', agents)
        self.assertEqual(
            self.git('--git-dir', str(github), 'show', 'master:AGENTS.md', cwd=self.root),
            agents.rstrip())

for name in list(test_workflow.WorkflowTest.__dict__):
    if name.startswith('test_'):
        setattr(ExistingInitTest, name, None)
