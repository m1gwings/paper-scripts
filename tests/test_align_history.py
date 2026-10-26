"""Real-Git history convergence, explicit replacement, archives and rejection."""
import shlex
import unittest

import test_workflow


class AlignHistoryTest(test_workflow.WorkflowTest):
    def assert_aligned(self):
        result = self.git('rev-parse', 'HEAD')
        for remote in ('github', 'overleaf'):
            self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / remote), result)
        return result

    def diverge(self):
        local = self.commit(self.repo, 'local.tex', 'local\n')
        github = self.remote_commit('github', 'cloud.tex', 'cloud\n')
        overleaf = self.remote_commit('overleaf', 'collaborator.tex', 'collaborator\n')
        return local, github, overleaf

    def test_alignment_preserves_both_histories_and_all_files(self):
        originals = self.diverge()
        for remote in ('github', 'overleaf'):
            self.git('config', 'receive.denyNonFastforwards', 'true', cwd=self.root / remote)
        self.paper('align-history')
        final = self.assert_aligned()
        for previous in originals:
            self.git('merge-base', '--is-ancestor', previous, final)
        for name in ('local.tex', 'cloud.tex', 'collaborator.tex'):
            self.assertTrue((self.repo / name).exists())
        tags = self.git('tag', '-l', 'paper-history-backup/*')
        self.assertEqual(len(tags.splitlines()), 4)
        self.assertEqual(self.git('tag', '-l', 'paper-history-backup/*', cwd=self.root / 'github'), tags)
        self.paper('align-history')
        self.assertEqual(self.assert_aligned(), final)
        self.assertEqual(self.git('tag', '-l', 'paper-history-backup/*'), tags)

    def test_equal_file_trees_are_joined_without_replaying_old_changes(self):
        self.commit(self.repo, 'main.tex', 'intermediate\n')
        local = self.commit(self.repo, 'main.tex', 'final\n')
        self.git('push', 'github', 'master')
        overleaf = self.commit(self.other, 'main.tex', 'final\n')
        self.git('push', 'origin', 'master', cwd=self.other)
        self.paper('align-history')
        final = self.assert_aligned()
        self.git('merge-base', '--is-ancestor', local, final)
        self.git('merge-base', '--is-ancestor', overleaf, final)
        self.assertEqual((self.repo / 'main.tex').read_text(), 'final\n')

    def test_dry_run_leaves_checkout_branches_and_remote_tags_unchanged(self):
        local, github, overleaf = self.diverge()
        index = (self.repo / '.git/index').read_bytes()
        result = self.paper('align-history', '--from', 'overleaf', '--dry-run')
        self.assertIn('replace with an explicit lease', result)
        self.assertEqual(self.git('rev-parse', 'HEAD'), local)
        self.assertEqual((self.repo / '.git/index').read_bytes(), index)
        self.assertEqual(self.git('status', '--porcelain'), '')
        self.assertEqual(self.git('tag', '-l'), '')
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'github'), github)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'overleaf'), overleaf)
        self.assertEqual(len(self.git('worktree', 'list', '--porcelain').split('worktree ')) - 1, 1)

    def check_direction(self, selected):
        local, github, overleaf = self.diverge()
        self.paper('align-history', '--from', selected)
        final = self.assert_aligned()
        preferred = {'github': github, 'overleaf': overleaf}[selected]
        self.assertEqual(self.git('rev-parse', final + '^'), preferred)
        archives = self.git('for-each-ref', '--format=%(objectname)', 'refs/tags/paper-history-backup/').splitlines()
        for commit in (local, github, overleaf):
            self.assertIn(commit, archives)
        for name in ('local.tex', 'cloud.tex', 'collaborator.tex'):
            self.assertTrue((self.repo / name).exists())

    def test_retain_github_history_archives_overleaf_without_losing_files(self):
        self.check_direction('github')

    def test_retain_overleaf_history_archives_github_without_losing_files(self):
        self.check_direction('overleaf')

    def test_snapshot_content_base_handles_later_edits_and_fresh_clone_records(self):
        self.commit(self.repo, 'main.tex', 'intermediate\n')
        self.commit(self.repo, 'main.tex', 'published\n')
        self.commit(self.other, 'main.tex', 'published\n')
        self.git('push', 'origin', 'master', cwd=self.other)
        self.paper('publish')
        self.commit(self.repo, 'local.tex', 'new local\n')
        self.remote_commit('overleaf', 'collaborator.tex', 'new collaborator\n')
        for suffix in ('source', 'overleaf'):
            self.git('update-ref', '-d', 'refs/paper-sync/master/' + suffix)
        # Equal-content publication can have only local sync refs. Make an actual
        # snapshot with its portable Paper-source trailer before testing recovery.
        self.paper('publish')
        self.commit(self.repo, 'main.tex', 'next revision\n')
        self.git('pull', '--ff-only', cwd=self.other)
        self.commit(self.other, 'collaborator.tex', 'updated collaborator\n')
        self.git('push', 'origin', 'master', cwd=self.other)
        for suffix in ('source', 'overleaf'):
            self.git('update-ref', '-d', 'refs/paper-sync/master/' + suffix)
        self.paper('align-history')
        self.assert_aligned()
        self.assertEqual((self.repo / 'main.tex').read_text(), 'next revision\n')
        self.assertEqual((self.repo / 'collaborator.tex').read_text(), 'updated collaborator\n')

    def test_conflicts_leave_original_checkout_and_remotes_untouched(self):
        local = self.commit(self.repo, 'main.tex', 'local\n')
        remote = self.remote_commit('overleaf', 'main.tex', 'remote\n')
        for options in ((), ('--from', 'github'), ('--from', 'overleaf')):
            self.assertIn('Content reconciliation failed', self.paper('align-history', *options, ok=False))
            self.assertEqual(self.git('rev-parse', 'HEAD'), local)
            self.assertEqual((self.repo / 'main.tex').read_text(), 'local\n')
            self.assertEqual(self.git('status', '--porcelain'), '')
            self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'overleaf'), remote)
            self.assertEqual(self.git('tag', '-l'), '')

    def test_dirty_feature_cloud_and_invalid_options_are_refused(self):
        (self.repo / 'dirty').write_text('keep\n')
        self.paper('align-history', ok=False)
        (self.repo / 'dirty').unlink()
        self.git('switch', '-c', 'feature')
        self.paper('align-history', ok=False)
        self.git('switch', 'master')
        self.paper('align-history', env=dict(self.env, PAPER_EXECUTION='cloud'), ok=False)
        self.paper('align-history', '--from', 'typo', ok=False)

    def test_bridge_rejection_never_falls_back_or_advances_github_base(self):
        local, github, overleaf = self.diverge()
        hook = self.root / 'overleaf/hooks/pre-receive'
        hook.write_text('#!/bin/sh\nwhile read old new ref; do\n'
                        'test -z "$(git rev-list --merges "$old..$new")" || exit 1\ndone\n')
        hook.chmod(0o755)
        result = self.paper('align-history', ok=False)
        self.assertIn('No snapshot fallback', result)
        self.assertEqual(self.git('rev-parse', 'HEAD'), local)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'github'), github)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'overleaf'), overleaf)
        self.paper('align-history', '--from', 'overleaf')
        self.assert_aligned()

    def test_destination_can_refuse_an_explicit_replacement(self):
        local, github, overleaf = self.diverge()
        self.git('config', 'receive.denyNonFastforwards', 'true', cwd=self.root / 'overleaf')
        result = self.paper('align-history', '--from', 'github', ok=False)
        self.assertIn('overleaf rejected alignment', result)
        self.assertEqual(self.git('rev-parse', 'HEAD'), local)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'github'), github)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'overleaf'), overleaf)

    def test_explicit_lease_rejects_concurrent_writer_even_after_background_fetch(self):
        local, github, overleaf = self.diverge()
        writer = self.root / 'concurrent-writer'
        self.git('clone', '-q', str(self.root / 'github'), str(writer))
        competing = self.commit(writer, 'concurrent.tex', 'keep concurrent work\n')
        hook = self.repo / '.git/hooks/pre-push'
        hook.write_text('#!/bin/sh\n[ "$1" = github ] || exit 0\nwhile read lref loid rref roid; do\n'
                        'if test "$rref" = refs/heads/master; then\n'
                        f'git -C {shlex.quote(str(writer))} push -q origin master || exit 1\n'
                        'git fetch -q github || exit 1\nfi\ndone\n')
        hook.chmod(0o755)
        result = self.paper('align-history', '--from', 'overleaf', ok=False)
        self.assertIn('github rejected alignment', result)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'github'), competing)
        self.assertEqual(self.git('rev-parse', 'HEAD'), local)
        self.assertEqual(self.git('rev-parse', 'refs/remotes/github/master'), competing)
        hook.unlink()
        self.paper('align-history', '--from', 'overleaf')
        self.assert_aligned()
        self.assertTrue((self.repo / 'concurrent.tex').exists())

    def test_new_local_edits_during_archiving_are_preserved_and_stop_publication(self):
        local, github, overleaf = self.diverge()
        hook = self.repo / '.git/hooks/pre-push'
        target = shlex.quote(str(self.repo / 'main.tex'))
        hook.write_text(f'#!/bin/sh\nprintf "New user edit\\n" > {target}\n')
        hook.chmod(0o755)
        result = self.paper('align-history', ok=False)
        self.assertIn('Local work changed', result)
        self.assertEqual((self.repo / 'main.tex').read_text(), 'New user edit\n')
        self.assertEqual(self.git('rev-parse', 'HEAD'), local)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'github'), github)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'overleaf'), overleaf)

    def test_archive_push_failure_stops_before_either_remote_base_changes(self):
        local, github, overleaf = self.diverge()
        hook = self.root / 'github/hooks/pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        self.paper('align-history', '--from', 'overleaf', ok=False)
        self.assertEqual(self.git('rev-parse', 'HEAD'), local)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'github'), github)
        self.assertEqual(self.git('rev-parse', 'master', cwd=self.root / 'overleaf'), overleaf)

    def test_success_requires_actual_remote_commit_identity(self):
        local, github, overleaf = self.diverge()
        hook = self.root / 'overleaf/hooks/post-receive'
        hook.write_text('#!/bin/sh\nwhile read old new ref; do\n'
                        'tree=$(git rev-parse "$new^{tree}")\n'
                        'changed=$(printf "Bridge regenerated history\\n" | git commit-tree "$tree" -p "$new")\n'
                        'git update-ref "$ref" "$changed" "$new" || exit 1\ndone\n')
        hook.chmod(0o755)
        result = self.paper('align-history', ok=False)
        self.assertIn('Alignment is incomplete', result)
        self.assertEqual(self.git('rev-parse', 'HEAD'), local)


if __name__ == '__main__':
    unittest.main()
