import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_workflow

TEMPLATES = Path(__file__).resolve().parents[1] / 'templates'


class InfrastructureTest(test_workflow.WorkflowTest):
    def test_explicit_poster_mode_replaces_only_untouched_paper_template(self):
        self.paper('init')
        self.paper('init', '--poster')
        agents = self.repo / 'AGENTS.md'
        self.assertEqual(agents.read_text(), (TEMPLATES / 'AGENTS.poster.md').read_text())
        custom = (TEMPLATES / 'AGENTS.paper.md').read_text() + '\nMy custom rule.\n'
        agents.write_text(custom)
        self.paper('init', '--poster')
        self.assertEqual(agents.read_text(), custom)

    def test_poster_selection_persists_and_vendored_runtime_recovers_agents(self):
        self.paper('init', '--poster')
        agents = self.repo / 'AGENTS.md'
        expected = (TEMPLATES / 'AGENTS.poster.md').read_text()
        self.assertEqual(agents.read_text(), expected)
        self.assertEqual(json.loads((self.repo / '.paper/config.json').read_text())[
            'document_type'], 'poster')
        before = {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob('*')
                  if p.is_file() and '.git' not in p.parts}
        self.paper('init')
        self.paper('init', '--poster')
        after = {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob('*')
                 if p.is_file() and '.git' not in p.parts}
        self.assertEqual(before, after)
        agents.unlink()
        subprocess.run(['bash', '.paper/runtime/paper', 'init'], cwd=self.repo,
                       env=self.env, check=True, capture_output=True)
        self.assertEqual(agents.read_text(), expected)
        for kind in ('paper', 'poster'):
            name = f'AGENTS.{kind}.md'
            self.assertEqual((self.repo / '.paper/runtime/templates' / name).read_bytes(),
                             (TEMPLATES / name).read_bytes())

    def test_poster_preserves_custom_agents_and_configuration(self):
        agents = self.repo / 'AGENTS.md'
        agents.write_text('# My poster\n\nKeep my theme instructions.\n')
        self.paper('init', '--poster')
        self.assertTrue(agents.read_text().startswith('# My poster\n\nKeep my theme instructions.\n'))
        self.assertIn('GH_TOKEN', agents.read_text())
        config = self.repo / '.paper/config.json'
        value = json.loads(config.read_text())
        value['root_tex'] = 'poster.tex'
        value['custom'] = 'preserved'
        config.write_text(json.dumps(value))
        self.paper('init')
        self.assertEqual(json.loads(config.read_text()), value)

    def test_poster_and_paper_templates_share_generic_workflow_instructions(self):
        paper = (TEMPLATES / 'AGENTS.paper.md').read_text()
        poster = (TEMPLATES / 'AGENTS.poster.md').read_text()
        # Only the title and LaTeX editing guidance differ.
        self.assertEqual(paper.split('## Project and editing\n', 1)[1].split('## LaTeX')[0],
                         poster.split('## Project and editing\n', 1)[1].split('## Poster LaTeX')[0])
        marker = '<!-- paper-scripts:begin managed-notifications -->'
        self.assertEqual(paper.split(marker, 1)[1], poster.split(marker, 1)[1])

    def test_invalid_init_option_and_document_type_do_not_write_files(self):
        self.paper('init', '--typo', ok=False)
        self.paper('init', '--poster', 'extra', ok=False)
        self.assertFalse((self.repo / '.paper').exists())
        (self.repo / '.paper').mkdir()
        config = self.repo / '.paper/config.json'
        config.write_text('{"document_type": "unknown"}\n')
        self.paper('init', ok=False)
        self.assertFalse((self.repo / 'AGENTS.md').exists())
        self.assertFalse((self.repo / 'tasks').exists())

    def test_idempotent_upgrade_preserves_user_configuration(self):
        self.paper('init')
        config = self.repo / '.paper/config.json'
        value = json.loads(config.read_text())
        self.assertEqual(value['base_branch'], 'master')
        self.assertEqual(value['notify_provider'], 'discord')
        self.assertEqual(value['version'], 3)
        self.assertNotIn('document_type', value)
        self.assertEqual((self.repo / 'AGENTS.md').read_text(),
                         (TEMPLATES / 'AGENTS.paper.md').read_text())
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
        codex = self.repo / '.codex/config.toml'
        self.assertIn('model = "gpt-5.6-sol"', codex.read_text())

    def test_version_two_notification_config_migrates_to_discord(self):
        paper = self.repo / '.paper'
        paper.mkdir()
        (paper / 'config.json').write_text(json.dumps({
            'version': 2,
            'base_branch': 'master',
            'overleaf_project_id': '',
            'root_tex': 'main.tex',
            'notify_provider': 'pushover',
            'pushover_device': 'phone',
            'custom': 'preserved',
        }))
        self.paper('init')
        value = json.loads((paper / 'config.json').read_text())
        self.assertEqual(value['notify_provider'], 'discord')
        self.assertEqual(value['pushover_device'], 'phone')
        self.assertEqual(value['custom'], 'preserved')

    def test_custom_agents_managed_notification_section_is_updated(self):
        agents = self.repo / 'AGENTS.md'
        agents.write_text(
            '# Personal instructions\n\nKeep this paragraph.\n\n## Notifications\n\n'
            '- Use only `paper notify --title "TITLE"`; credentials stay in protected GitHub.\n\n'
            '## Personal section\n\nKeep this too.\n')
        self.paper('init')
        text = agents.read_text()
        self.assertIn('Keep this paragraph.', text)
        self.assertIn('Keep this too.', text)
        self.assertIn('paper-scripts:begin managed-notifications', text)
        self.assertIn('## Codex Cloud GitHub access', text)
        self.assertIn('expect `GH_TOKEN` to be configured as a secret environment variable', text)
        self.assertIn('token is available in their Google Drive', text)
        self.assertIn('Local Codex clients and other local agents', text)
        self.assertIn('Discord is the default delivery provider', text)
        self.assertIn('paper-scripts:begin managed-feature-cleanup', text)
        self.assertIn('paper clear-feature-branches', text)
        self.assertIn('paper-scripts:begin managed-tasking', text)
        self.assertIn('## Tasks and resumption', text)
        self.assertIn('tasks/NNN_short_name/task.md', text)
        self.assertIn('## Token use and delegation', text)
        before = text
        self.paper('init')
        self.assertEqual(agents.read_text(), before)

    def test_unmarked_generated_tasking_section_is_migrated(self):
        agents = self.repo / 'AGENTS.md'
        agents.write_text(
            '# Personal instructions\n\n'
            '## Tasks and resumption\n\n'
            '- Before substantial work, use `tasks/NNN_short_name/task.md`.\n\n'
            '## Token use and delegation\n\n'
            '- The main agent owns the task checkpoint.\n\n'
            '## Personal section\n\nKeep this too.\n')
        self.paper('init')
        text = agents.read_text()
        self.assertEqual(text.count('## Tasks and resumption'), 1)
        self.assertIn('paper-scripts:begin managed-tasking', text)
        self.assertIn('Keep this too.', text)

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
