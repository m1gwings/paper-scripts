import os
from pathlib import Path
import subprocess
import test_workflow

PAPER = Path(__file__).resolve().parents[1] / 'paper'
TEMPLATES = PAPER.parent / 'templates'


class ExistingCreateTest(test_workflow.WorkflowTest):
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
        result = subprocess.run(['bash', str(PAPER), 'create', 'abc123', 'owner/paper', str(self.repo)],
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
        result = subprocess.run(['bash', str(PAPER), 'create', 'wrongproject', 'owner/paper', str(self.repo)],
                                cwd=self.root, env=self.env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.repo / '.paper').exists())

    def initialize_new(self, *arguments, directory, kind):
        fresh = self.root / directory
        overleaf_head = self.git('rev-parse', 'master', cwd=self.root / 'overleaf')
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
            ['bash', str(getattr(self, 'entrypoint', PAPER)), 'create', *arguments],
            cwd=self.root, env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((fresh / '.codex/config.toml').exists())
        self.assertEqual(self.git('status', '--porcelain', cwd=fresh), '')
        self.assertEqual(self.git('log', '-1', '--format=%s', cwd=fresh),
                         'Initialize paper workflow')
        agents = (fresh / 'AGENTS.md').read_text()
        self.assertEqual(agents, (TEMPLATES / f'AGENTS.{kind}.md').read_text())
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'overleaf'),
                         overleaf_head)
        self.assertEqual(self.git('config', 'remote.pushDefault', cwd=fresh), 'github')
        self.assertEqual(self.git('rev-parse', '--abbrev-ref', '@{upstream}', cwd=fresh),
                         'github/master')
        self.assertIn('paper-scripts:begin managed-tasking', agents)
        self.assertIn('tasks/NNN_short_name/task.md', agents)
        self.assertEqual(
            self.git('--git-dir', str(github), 'show', 'master:AGENTS.md', cwd=self.root),
            agents.rstrip())

    def test_vendored_runtime_supports_creation(self):
        self.paper('init')
        self.entrypoint = self.repo / '.paper/runtime/paper'
        self.initialize_new('--slides', 'abc123', 'owner/new-slides',
                            directory='slides', kind='slides')

    def test_force_creation_commits_the_entire_starter_to_github_only(self):
        self.initialize_new('--force', '--slides', 'abc123', 'owner/new-slides',
                            directory='slides', kind='slides')
        fresh = self.root / 'slides'
        self.assertTrue((fresh / 'papermacros.sty').exists())
        self.assertIn(r'\documentclass{beamer}', (fresh / 'main.tex').read_text())
        self.assertEqual(self.git('--git-dir', str(self.root / 'new-github'), 'show',
                                  'master:papermacros.sty', cwd=self.root),
                         (fresh / 'papermacros.sty').read_text().rstrip())

    def test_new_repository_commits_and_pushes_canonical_initialization(self):
        self.initialize_new('abc123', 'owner/new-paper', 'fresh',
                            directory='fresh', kind='paper')

    def test_default_paper_directory_and_template_unchanged(self):
        self.initialize_new('abc123', 'owner/new-paper', directory='paper', kind='paper')
        self.assertFalse((self.root / 'poster').exists())
        self.assertFalse((self.root / 'slides').exists())

    def test_poster_default_directory_and_template(self):
        self.initialize_new('--poster', 'abc123', 'owner/new-poster',
                            directory='poster', kind='poster')
        self.assertFalse((self.root / 'paper').exists())

    def test_poster_explicit_directory_and_trailing_flag(self):
        self.initialize_new('abc123', 'owner/new-poster', 'custom poster', '--poster',
                            directory='custom poster', kind='poster')
        self.assertFalse((self.root / 'poster').exists())

    def test_slides_default_directory_and_template(self):
        self.initialize_new('--slides', 'abc123', 'owner/new-slides',
                            directory='slides', kind='slides')
        self.assertFalse((self.root / 'paper').exists())

    def test_slides_explicit_directory_and_trailing_flag(self):
        self.initialize_new('abc123', 'owner/new-slides', 'custom slides', '--slides',
                            directory='custom slides', kind='slides')
        self.assertFalse((self.root / 'slides').exists())

    def test_end_of_options_allows_directory_with_leading_dash(self):
        self.initialize_new('--poster', 'abc123', 'owner/new-poster', '--', './-poster',
                            directory='-poster', kind='poster')

    def test_existing_directory_receives_poster_instructions_without_commit(self):
        head = self.git('rev-parse', 'HEAD')
        result = subprocess.run(
            ['bash', str(PAPER), 'create', '--poster', 'abc123', 'owner/paper', str(self.repo)],
            cwd=self.root, env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertEqual((self.repo / 'AGENTS.md').read_text(),
                         (TEMPLATES / 'AGENTS.poster.md').read_text())

    def test_existing_directory_receives_slides_instructions_without_commit(self):
        head = self.git('rev-parse', 'HEAD')
        result = subprocess.run(
            ['bash', str(PAPER), 'create', '--slides', 'abc123', 'owner/paper', str(self.repo)],
            cwd=self.root, env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertEqual((self.repo / 'AGENTS.md').read_text(),
                         (TEMPLATES / 'AGENTS.slides.md').read_text())

    def test_help_and_invalid_arguments_do_not_authenticate_or_create_files(self):
        marker = self.root / 'gh-called'
        gh = self.root / 'tools/gh'
        gh.write_text('#!/bin/sh\ntouch "$TEST_GH_CALLED"\nexit 99\n')
        env = dict(self.env, TEST_GH_CALLED=str(marker))
        for args in [('--help',), ('-h',), ('--poster', '--help'), ('--slides', '--help')]:
            with self.subTest(args=args):
                result = subprocess.run(['bash', str(PAPER), 'create', *args], cwd=self.root,
                                        env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('--poster', result.stdout)
                self.assertIn('./poster', result.stdout)
                self.assertIn('--slides', result.stdout)
                self.assertIn('./slides', result.stdout)
        for args in [(), ('--poster',), ('--slides',),
                     ('--poster', 'abc123'), ('--slides', 'abc123'),
                     ('abc123', 'repo', 'dir', 'extra'),
                     ('--poster', 'abc123', 'repo', '--typo'),
                     ('--slides', 'abc123', 'repo', '--typo'),
                     ('--poster', '--slides', 'abc123', 'repo'),
                     ('--slides', '--poster', 'abc123', 'repo')]:
            with self.subTest(args=args):
                result = subprocess.run(['bash', str(PAPER), 'create', *args], cwd=self.root,
                                        env=env, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())
        self.assertFalse((self.root / 'paper').exists())
        self.assertFalse((self.root / 'poster').exists())
        self.assertFalse((self.root / 'slides').exists())

for name in list(test_workflow.WorkflowTest.__dict__):
    if name.startswith('test_'):
        setattr(ExistingCreateTest, name, None)
