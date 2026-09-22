"""Real Git integration tests; neither network nor user credentials are used."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'paper'


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='paper workflow ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null',
                        GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0',
                        GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@example.invalid',
                        GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@example.invalid')
        self.repo = self.root / 'local'
        self.git('init', '-q', '-b', 'master', str(self.repo), cwd=self.root)
        self.commit(self.repo, 'main.tex', 'initial\n')
        for remote in ['github', 'overleaf']:
            bare = self.root / remote
            self.git('clone', '-q', '--bare', str(self.repo), str(bare))
            self.git('remote', 'add', remote, str(bare))
        self.git('fetch', '--all')
        self.git('symbolic-ref', 'refs/remotes/overleaf/HEAD', 'refs/remotes/overleaf/master')
        self.other = self.root / 'other'
        self.git('clone', '-q', str(self.root / 'overleaf'), str(self.other))

    def git(self, *args, cwd=None, ok=True):
        r = subprocess.run(['git', *args], cwd=cwd or self.repo,
                           env=self.env, text=True, capture_output=True)
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r.stdout.strip()

    def paper(self, *args, ok=True, env=None, input_text=None):
        r = subprocess.run(['bash', str(SCRIPT), *args], cwd=self.repo,
                           env=env or self.env, text=True, capture_output=True,
                           input=input_text)
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r.stdout + r.stderr

    def commit(self, repo, name, text):
        (repo / name).write_text(text)
        self.git('add', name, cwd=repo)
        self.git('commit', '-qm', name, cwd=repo)
        return self.git('rev-parse', 'HEAD', cwd=repo)

    def remote_commit(self, remote, name, text):
        clone = self.root / ('writer-' + remote)
        self.git('clone', '-q', str(self.root / remote), str(clone))
        oid = self.commit(clone, name, text)
        self.git('push', '-q', 'origin', 'master', cwd=clone)
        return oid

    def test_start_includes_both_remotes_without_publishing(self):
        gh = self.remote_commit('github', 'cloud.tex', 'cloud\n')
        ol = self.remote_commit('overleaf', 'collaborator.tex', 'collaborator\n')
        self.paper('start', 'experiment')
        self.assertEqual(self.git('branch', '--show-current'), 'experiment')
        self.assertTrue((self.repo / 'cloud.tex').exists())
        self.assertTrue((self.repo / 'collaborator.tex').exists())
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'github'), gh)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'overleaf'), ol)

    def test_publish_reconciles_and_keeps_feature(self):
        self.paper('start', 'experiment')
        self.commit(self.repo, 'feature.tex', 'feature\n')
        self.remote_commit('github', 'cloud.tex', 'cloud\n')
        self.remote_commit('overleaf', 'coauthor.tex', 'coauthor\n')
        self.paper('publish')
        self.assertEqual(self.git('branch', '--show-current'), 'master')
        final = self.git('rev-parse', 'master')
        for remote in ['github', 'overleaf']:
            self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / remote), final)
        self.assertEqual(self.git('rev-parse', 'experiment'), final)
        for file in ['feature.tex', 'cloud.tex', 'coauthor.tex']:
            self.assertTrue((self.repo / file).exists())

    def test_dirty_and_conflicting_start_never_creates_feature(self):
        (self.repo / 'dirty').write_text('dirty')
        self.paper('start', 'experiment', ok=False)
        (self.repo / 'dirty').unlink()
        self.commit(self.repo, 'main.tex', 'local\n')
        self.remote_commit('overleaf', 'main.tex', 'remote\n')
        self.paper('start', 'experiment', ok=False)
        self.git('show-ref', '--verify', 'refs/heads/experiment', ok=False)
        self.assertTrue((self.repo / '.git' / 'rebase-merge').exists())

    def test_sync_requires_base_and_fetches_cloud_work(self):
        self.remote_commit('github', 'cloud.tex', 'cloud\n')
        self.paper('sync')
        self.assertTrue((self.repo / 'cloud.tex').exists())
        self.paper('start', 'experiment')
        self.paper('sync', ok=False)

    def test_backup_cannot_overwrite_fresh_remote_work(self):
        remote_oid = self.remote_commit('github', 'cloud.tex', 'cloud\n')
        self.commit(self.repo, 'local.tex', 'local\n')
        self.git('fetch', 'github')
        self.paper('backup', ok=False)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'github'), remote_oid)

    def test_invalid_existing_and_unreachable_start(self):
        for name in ['master', 'bad name', '--force']:
            self.paper('start', name, ok=False)
        self.git('remote', 'set-url', 'github', str(self.root / 'missing'))
        self.paper('start', 'experiment', ok=False)
        self.assertEqual(self.git('branch', '--show-current'), 'master')

    def test_nonstandard_base(self):
        for repo in [self.repo, self.root / 'github', self.root / 'overleaf']:
            self.git('branch', '-m', 'master', 'collaboration', cwd=repo)
        self.git('fetch', '--all', '--prune')
        self.git('symbolic-ref', 'refs/remotes/overleaf/HEAD', 'refs/remotes/overleaf/collaboration')
        self.paper('start', 'experiment')
        self.commit(self.repo, 'feature.tex', 'feature\n')
        self.paper('publish')
        self.assertEqual(self.git('branch', '--show-current'), 'collaboration')

    def test_clear_feature_branches_replaces_clear_experiments(self):
        self.paper('start', 'published-feature')
        self.git('switch', 'master')
        self.git('branch', 'local-feature')
        self.git('push', '-q', 'github', 'master:refs/heads/remote-feature')

        self.paper('clear-experiments', ok=False)
        output = self.paper('clear-feature-branches',
                            input_text='DELETE FEATURE BRANCHES\n')

        self.assertIn('All feature branches removed.', output)
        self.assertEqual(self.git('for-each-ref', '--format=%(refname:short)',
                                  'refs/heads/'), 'master')
        self.assertEqual(self.git('for-each-ref', '--format=%(refname:short)',
                                  'refs/heads/', cwd=self.root / 'github'), 'master')


if __name__ == '__main__':
    unittest.main()

class LeaseTest(WorkflowTest):
    def test_background_fetch_cannot_refresh_publication_lease(self):
        # The hook models a concurrent writer and an editor auto-fetch occurring
        # after our synchronization snapshot but before publication.
        writer = self.root / 'concurrent-writer'
        self.git('clone', '-q', str(self.root / 'github'), str(writer))
        competing = self.commit(writer, 'concurrent.tex', 'keep this work\n')
        self.git('push', 'origin', 'HEAD:refs/heads/concurrent', cwd=writer)
        self.commit(self.repo, 'local.tex', 'local\n')
        self.remote_commit('overleaf', 'coauthor.tex', 'coauthor\n')
        hook = self.repo / '.git/hooks/post-rewrite'
        import shlex
        hook.write_text('#!/bin/sh\n' +
                        'git --git-dir=' + shlex.quote(str(self.root / 'github')) +
                        ' update-ref refs/heads/master ' + competing + '\n' +
                        'git fetch github\n')
        hook.chmod(0o755)
        self.paper('publish', ok=False)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'github'), competing)
        self.assertNotEqual(self.git('rev-parse', 'master', cwd=self.root / 'overleaf'),
                            self.git('rev-parse', 'master'))

for name in list(WorkflowTest.__dict__):
    if name.startswith('test_'):
        setattr(LeaseTest, name, None)
