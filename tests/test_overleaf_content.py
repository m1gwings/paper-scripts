"""Filtered publication and imports against real disposable Git remotes."""
import json
import unittest

import test_workflow


class FilteredWorkflowTest(unittest.TestCase):
    setUp = test_workflow.WorkflowTest.setUp
    git = test_workflow.WorkflowTest.git
    paper = test_workflow.WorkflowTest.paper
    commit = test_workflow.WorkflowTest.commit
    remote_commit = test_workflow.WorkflowTest.remote_commit

    def enable(self, extra=()):
        (self.repo / '.paper').mkdir(exist_ok=True)
        self.commit(self.repo, '.paper/config.json', json.dumps({
            'overleaf_exclude': ['.paper/', '.github/', '.codex/', 'AGENTS.md', 'tasks/', 'notes/', *extra]}))
        for name in ('tasks', 'notes', '.codex', '.github'):
            (self.repo / name).mkdir(exist_ok=True)
            self.commit(self.repo, name + '/record.md', name + '\n')
        self.commit(self.repo, 'AGENTS.md', 'instructions\n')

    def remote_files(self):
        return self.git('ls-tree', '-r', '--name-only', 'master', cwd=self.root / 'overleaf').splitlines()

    def test_cleanup_metadata_only_noop_and_status(self):
        self.enable()
        # Simulate legacy publication, then migrate without rewriting history.
        self.git('push', 'overleaf', 'master')
        old = self.git('rev-parse', 'master', cwd=self.root / 'overleaf')
        self.paper('publish')
        self.assertEqual(self.remote_files(), ['main.tex'])
        exported = self.git('rev-parse', 'master', cwd=self.root / 'overleaf')
        self.assertEqual(self.git('rev-parse', exported + '^'), old)
        self.assertTrue((self.repo / 'tasks/record.md').exists())
        self.commit(self.repo, 'tasks/record.md', 'updated\n')
        self.paper('publish')
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'overleaf'), exported)
        self.assertIn('overleaf/master      committed files: aligned', self.paper('status'))
        self.assertIn('intentionally have different trees', self.paper('align-history', ok=False))
        self.assertIn('intentionally have different trees', self.paper('align-history', '--from', 'github', ok=False))

    def test_fresh_clone_parallel_edits_deletions_and_metadata(self):
        self.enable()
        self.commit(self.repo, 'delete.tex', 'delete me\n')
        self.commit(self.repo, 'rename.tex', 'rename me\n')
        self.paper('publish')
        # A genuine fresh GitHub clone, without machine-local synchronization refs.
        fresh = self.root / 'fresh'
        self.git('clone', '-q', str(self.root / 'github'), str(fresh))
        self.repo = fresh
        self.git('remote', 'rename', 'origin', 'github')
        self.git('remote', 'add', 'overleaf', str(self.root / 'overleaf'))
        self.git('fetch', 'overleaf')
        self.git('symbolic-ref', 'refs/remotes/overleaf/HEAD', 'refs/remotes/overleaf/master')
        self.commit(self.repo, 'notes/record.md', 'local notes\n')
        self.commit(self.repo, 'main.tex', 'local manuscript\n')
        self.git('pull', '--ff-only', cwd=self.other)
        self.git('rm', 'delete.tex', cwd=self.other)
        self.git('mv', 'rename.tex', 'renamed.tex', cwd=self.other)
        (self.other / 'tasks').mkdir()
        self.commit(self.other, 'tasks/unwanted.md', 'never import\n')
        self.commit(self.other, 'coauthor.tex', 'coauthor\n')
        self.git('push', 'origin', 'master', cwd=self.other)
        self.paper('publish')
        self.assertEqual((self.repo / 'notes/record.md').read_text(), 'local notes\n')
        self.assertEqual((self.repo / 'main.tex').read_text(), 'local manuscript\n')
        self.assertTrue((self.repo / 'renamed.tex').exists())
        self.assertFalse((self.repo / 'delete.tex').exists())
        self.assertFalse((self.repo / 'tasks/unwanted.md').exists())
        self.assertEqual(self.remote_files(), ['coauthor.tex', 'main.tex', 'renamed.tex'])
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_conflicting_manuscript_stops_without_remote_writes(self):
        self.enable()
        self.paper('publish')
        self.commit(self.repo, 'main.tex', 'local\n')
        previous = self.remote_commit('overleaf', 'main.tex', 'coauthor\n')
        self.paper('publish', ok=False)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'overleaf'), previous)
        self.assertTrue((self.repo / 'tasks/record.md').exists())

    def test_first_import_ignores_remote_metadata_deletion(self):
        self.enable()
        self.git('push', 'overleaf', 'master')
        self.git('pull', '--ff-only', cwd=self.other)
        self.git('rm', '-r', 'notes', 'tasks', cwd=self.other)
        self.commit(self.other, 'coauthor.tex', 'coauthor\n')
        self.git('push', 'origin', 'master', cwd=self.other)
        self.commit(self.repo, 'notes/record.md', 'preserve this\n')
        self.paper('publish')
        self.assertEqual((self.repo / 'notes/record.md').read_text(), 'preserve this\n')
        self.assertEqual(self.remote_files(), ['coauthor.tex', 'main.tex'])

    def test_overrides_unusual_names_and_policy_changes(self):
        self.enable(['private/'])
        (self.repo / 'private').mkdir()
        self.commit(self.repo, 'private/space\nname', 'private\n')
        self.commit(self.repo, 'figure space\nname.tex', 'keep\n')
        self.paper('publish')
        self.git('cat-file', '-e', 'master:figure space\nname.tex', cwd=self.root / 'overleaf')
        self.git('cat-file', '-e', 'master:private/space\nname', cwd=self.root / 'overleaf', ok=False)
        config = json.loads((self.repo / '.paper/config.json').read_text())
        config['overleaf_exclude'].remove('private/')
        self.commit(self.repo, '.paper/config.json', json.dumps(config))
        self.paper('publish')
        self.git('cat-file', '-e', 'master:private/space\nname', cwd=self.root / 'overleaf')

    def test_invalid_policy_fails_before_writes(self):
        self.enable()
        self.commit(self.repo, '.paper/config.json', '{"overleaf_exclude": ["../tasks"]}')
        before = self.git('rev-parse', 'master', cwd=self.root / 'overleaf')
        self.paper('publish', ok=False)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'overleaf'), before)

    def test_same_manuscript_file_advances_after_export_and_metadata_only_commit(self):
        self.enable()
        self.commit(self.repo, 'main.tex', 'published revision\n')
        self.paper('publish')
        self.commit(self.repo, 'notes/record.md', 'new local notes\n')
        self.paper('publish')
        self.remote_commit('overleaf', 'main.tex', 'coauthor revision\n')
        self.commit(self.repo, 'local.tex', 'parallel local source\n')
        self.paper('publish')
        self.assertEqual((self.repo / 'main.tex').read_text(), 'coauthor revision\n')
        self.assertEqual((self.repo / 'notes/record.md').read_text(), 'new local notes\n')
        self.assertEqual(self.remote_files(), ['local.tex', 'main.tex'])
