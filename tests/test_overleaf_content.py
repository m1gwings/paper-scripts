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
        self.assertIn('overleaf/master      Manuscript synchronized', self.paper('status'))
        verbose = self.paper('status', '--verbose')
        self.assertIn('overleaf/master      committed files: aligned; history:', verbose)
        self.assertIn('History alignment has been retired', self.paper('align-history', ok=False))
        self.assertIn('History alignment has been retired', self.paper('align-history', '--from', 'github', ok=False))

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

    def publish_from_another_checkout(self):
        self.enable()
        self.paper('publish')
        original = self.repo
        writer = self.root / 'second-checkout'
        self.git('clone', '-q', str(self.root / 'github'), str(writer))
        self.repo = writer
        self.git('remote', 'rename', 'origin', 'github')
        self.git('remote', 'add', 'overleaf', str(self.root / 'overleaf'))
        self.git('fetch', 'overleaf')
        self.git('symbolic-ref', 'refs/remotes/overleaf/HEAD', 'refs/remotes/overleaf/master')
        self.commit(writer, 'main.tex', 'published from another checkout\n')
        self.paper('publish')
        self.repo = original

    def test_existing_stale_sync_refs_do_not_reimport_other_checkout_publication(self):
        self.publish_from_another_checkout()
        self.paper('sync')
        self.assertEqual((self.repo / 'main.tex').read_text(), 'published from another checkout\n')
        self.assertEqual(self.git('rev-parse', 'refs/paper-sync/master/overleaf'),
                         self.git('rev-parse', 'overleaf/master'))
        before = self.git('rev-parse', 'HEAD')
        self.commit(self.repo, 'main.tex', 'new local revision\n')
        self.paper('publish')
        self.assertEqual((self.repo / 'main.tex').read_text(), 'new local revision\n')
        self.assertNotIn('Import Overleaf', self.git('log', '--format=%s', before + '..HEAD'))
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_stale_sync_refs_still_import_genuine_edits_after_new_export(self):
        self.publish_from_another_checkout()
        self.remote_commit('overleaf', 'coauthor.tex', 'genuine remote edit\n')
        self.paper('sync')
        self.assertEqual((self.repo / 'main.tex').read_text(), 'published from another checkout\n')
        self.assertEqual((self.repo / 'coauthor.tex').read_text(), 'genuine remote edit\n')
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_stale_sync_refs_do_not_hide_a_genuine_conflict(self):
        self.publish_from_another_checkout()
        stale = {name: self.git('rev-parse', 'refs/paper-sync/master/' + name)
                 for name in ('source', 'overleaf')}
        self.paper('sync')
        for name, oid in stale.items():
            self.git('update-ref', 'refs/paper-sync/master/' + name, oid)
        self.commit(self.repo, 'main.tex', 'new local revision\n')
        remote = self.remote_commit('overleaf', 'main.tex', 'new coauthor revision\n')
        self.paper('publish', ok=False)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'overleaf'), remote)
        self.assertIn('<<<<<<<', (self.repo / 'main.tex').read_text())

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

    def test_basename_cleanup_preserves_local_files_and_coauthor_imports(self):
        self.enable()
        for name in ('.gitkeep', 'figures/.gitkeep', 'figures/plot.tex'):
            (self.repo / name).parent.mkdir(exist_ok=True)
            self.commit(self.repo, name, 'keep locally\n')
        self.git('push', 'overleaf', 'master')
        config = json.loads((self.repo / '.paper/config.json').read_text())
        config['overleaf_exclude_basenames'] = ['.gitkeep']
        self.commit(self.repo, '.paper/config.json', json.dumps(config))
        self.paper('publish')
        self.assertEqual(self.remote_files(), ['figures/plot.tex', 'main.tex'])
        self.assertTrue((self.repo / 'figures/.gitkeep').exists())
        self.remote_commit('overleaf', 'main.tex', 'coauthor revision\n')
        self.paper('publish')
        self.assertEqual((self.repo / 'main.tex').read_text(), 'coauthor revision\n')
        self.assertTrue((self.repo / '.gitkeep').exists())
        # Opting back into full-tree export restores the preserved placeholders.
        config['overleaf_exclude_basenames'] = []
        self.commit(self.repo, '.paper/config.json', json.dumps(config))
        self.paper('publish')
        self.assertIn('figures/.gitkeep', self.remote_files())

    def test_invalid_basename_fails_before_writes(self):
        self.enable()
        before = self.git('rev-parse', 'master', cwd=self.root / 'overleaf')
        for value in (['figures/.gitkeep'], ['*.tmp'], [1], '.gitkeep'):
            self.commit(self.repo, '.paper/config.json', json.dumps({
                'overleaf_exclude_basenames': value}))
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
