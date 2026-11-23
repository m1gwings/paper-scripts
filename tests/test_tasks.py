"""Local integration tests: python3 -m unittest discover -s tests -v."""
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'paper'


class PaperTasksTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='paper tasks ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def run_paper(self, *args, input='', cwd=None, ok=True):
        result = subprocess.run(['bash', str(SCRIPT), *args],
                                cwd=cwd or self.root, input=input,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def task(self, name='001_example', status='active'):
        folder = self.root / 'tasks' / name
        folder.mkdir(parents=True)
        (folder / 'task.md').write_text(
            f'# {name}\n\nStatus: {status}\n\n## Steps\n\n'
            '- [x] Derive\n- [ ] Verify\n\n## Current checkpoint\n\n'
            '- Next concrete action: Check the constants.\n')
        return folder

    def test_init_preserves_files_and_recovers_missing_files(self):
        self.run_paper('init')
        agents = self.root / 'AGENTS.md'
        self.assertIn('Preserve existing notation, macros, labels, and references', agents.read_text())
        self.assertIn('conference, journal, or presentation style files', agents.read_text())
        self.assertIn('## Notifications', agents.read_text())
        self.assertIn('paper notify --title', (self.root / '.paper/WORKFLOW.md').read_text())
        self.assertIn('ignored `output/`', (self.root / '.paper/WORKFLOW.md').read_text())
        self.assertIn('paper-scripts:begin managed-tasking', agents.read_text())
        self.assertIn('tasks/NNN_slug/task.md', agents.read_text())
        self.assertFalse((self.root / 'tasks').exists())
        agents.write_text('Personal instructions\n')
        self.run_paper('init')
        self.assertTrue(agents.read_text().startswith('Personal instructions\n'))
        self.assertIn('paper-scripts:begin managed-notifications', agents.read_text())
        self.assertIn('Discord is the default delivery provider', (self.root / '.paper/WORKFLOW.md').read_text())
        self.assertIn('paper-scripts:begin managed-tasking', agents.read_text())

    def test_init_retires_only_unmodified_committed_task_queue(self):
        tasks = self.root / 'tasks'
        tasks.mkdir()
        (tasks / 'index.md').write_text('| Task | Status | Record |\n')
        (tasks / 'template.md').write_text('# NNN: Task title\n')
        git = ['git', '-C', str(self.root), '-c', 'user.name=T', '-c', 'user.email=t@example.com']
        subprocess.run([*git, 'add', 'tasks'], check=True)
        subprocess.run([*git, 'commit', '-qm', 'queue'], check=True)
        (tasks / 'template.md').write_text('# Edited\n')
        output = self.run_paper('init')
        self.assertFalse((tasks / 'index.md').exists())
        self.assertIn('Retired tasks/index.md', output)
        self.assertTrue((tasks / 'template.md').exists())
        self.assertIn('Kept tasks/template.md', output)

    def test_status_reads_generated_records(self):
        folder = self.root / 'tasks' / '001_regret_bound'
        folder.mkdir(parents=True)
        (folder / 'task.md').write_text(
            '<!-- agents-workspace:begin task-record -->\n<!-- Generated. -->\n# Regret bound\n\n'
            'Status: paused\nTask: ' + 'a' * 32 + '\nUpdated: 2026-11-23\n\n## Objective\n\nTighten it.\n\n'
            '## Current checkpoint\n\nLemma 2 verified.\n\nNext: Rewrite Lemma 3.\n'
            '<!-- agents-workspace:end task-record -->\n')
        output = self.run_paper('task', 'status')
        self.assertIn('paused   -      001_regret_bound: Regret bound', output)
        self.assertIn('Next: Rewrite Lemma 3.', output)

    def test_status_filters_counts_and_nested_directory(self):
        active = self.task()
        self.task('002_finished', 'done')
        self.task('003_invalid', 'verified')
        output = self.run_paper('task', 'status', cwd=active)
        self.assertIn('001_example', output)
        self.assertIn('1/2', output)
        self.assertIn('Next: Check the constants.', output)
        self.assertIn('unknown', output)
        self.assertNotIn('002_finished', output)
        self.assertIn('002_finished', self.run_paper('task', 'status', '--all'))
        self.assertIn('001_example', self.run_paper('task'))

    def test_missing_and_duplicate_metadata(self):
        folder = self.task()
        record = folder / 'task.md'
        record.write_text('# Title\nStatus: active\nStatus: done\n\n## Steps\n')
        self.assertIn('unknown', self.run_paper('task', 'status'))
        record.unlink()
        self.assertIn('Missing regular task.md', self.run_paper('task', 'status'))

    def test_delete_is_confirmed_selective_and_recoverable(self):
        self.run_paper('init')
        selected = self.task()
        other = self.task('002_keep', 'blocked')
        index = self.root / 'tasks' / 'index.md'  # a legacy queue awaiting retirement
        original = '| Task | Status | Record |\n| --- | --- | --- |' + (
            '\n| Selected | active | [Record](001_example/task.md) |\n'
            '| Keep | blocked | [Record](002_keep/task.md) |\n')
        index.write_text(original)
        note = self.root / 'notes' / 'proof.md'
        note.write_text('Mathematics\n')
        self.assertIn('Cancelled', self.run_paper('task', 'delete', '1'))
        self.assertTrue(selected.exists())
        self.assertEqual(index.read_text(), original)
        self.run_paper('task', 'delete', '001', input='001_example\n')
        self.assertFalse(selected.exists())
        self.assertTrue(other.exists())
        self.assertNotIn('[Record](001_example/task.md)', index.read_text())
        self.assertIn('[Record](002_keep/task.md)', index.read_text())
        batch, = (self.root / 'tasks' / '.trash').iterdir()
        self.assertTrue((batch / '001_example' / 'task.md').exists())
        self.assertEqual((batch / 'index.md.before').read_text(), original)
        self.assertEqual(note.read_text(), 'Mathematics\n')
        self.assertNotIn('001_example', self.run_paper('task', 'status', '--all'))

    def test_multiple_delete_and_selection_validation(self):
        first = self.task()
        second = self.task('002_second')
        self.run_paper('task', 'delete', '1', '999', ok=False)
        self.assertTrue(first.exists())
        self.run_paper('task', 'delete', '../notes', ok=False)
        self.run_paper('task', 'delete', '1', '002_second', '1',
                       input='001_example 002_second\n')
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())

    def test_symlink_and_ambiguous_id_protection(self):
        first = self.task()
        self.task('001_duplicate')
        self.run_paper('task', 'delete', '1', ok=False)
        (self.root / 'tasks' / '002_link').symlink_to(first, target_is_directory=True)
        self.assertNotIn('002_link', self.run_paper('task', 'status', '--all'))
        (self.root / 'tasks' / '.trash').symlink_to(self.root, target_is_directory=True)
        self.run_paper('task', 'delete', '001_example', ok=False)
        self.assertTrue(first.exists())

    def test_init_conflict_and_merge_protection(self):
        (self.root / 'notes').symlink_to(self.root, target_is_directory=True)
        self.run_paper('init', ok=False)
        self.assertFalse((self.root / 'AGENTS.md').exists())
        folder = self.task()
        (self.root / '.git' / 'MERGE_HEAD').write_text('0' * 40 + '\n')
        self.run_paper('task', 'delete', '1', input='001_example\n', ok=False)
        self.assertTrue(folder.exists())
        self.assertIn('001_example', self.run_paper('task', 'status'))

    def test_usage_and_no_repository(self):
        self.assertIn('No task records yet', self.run_paper('task', 'status'))
        self.run_paper('task', 'delete', ok=False)
        self.run_paper('task', 'status', '--invalid', ok=False)
        with tempfile.TemporaryDirectory() as outside:
            self.run_paper('task', 'status', cwd=outside, ok=False)
            self.run_paper('init', cwd=outside, ok=False)
            self.run_paper('task', '--help', cwd=outside)
            self.run_paper('init', '--help', cwd=outside)
            self.run_paper('help', cwd=outside)
            self.assertFalse((Path(outside) / 'tasks').exists())


if __name__ == '__main__':
    unittest.main()
