import json
from pathlib import Path
import shutil
import subprocess
import test_workflow

SOURCE = Path(__file__).resolve().parents[1]
BLANK = r'''\documentclass{article}
\usepackage{graphicx} % Required for inserting images
\title{My new paper}
\author{Cristiano Migali}
\date{October 2026}
\begin{document}
\maketitle
\section{Introduction}
\end{document}
'''


class ScaffoldTest(test_workflow.WorkflowTest):
    def test_blank_overleaf_is_scaffolded_with_metadata_and_no_codex_config(self):
        (self.repo / 'main.tex').write_text(BLANK)
        output = self.paper('init')
        self.assertIn('stock blank Overleaf', output)
        self.assertIn('paper publish', output)
        self.assertIn(r'\title{My new paper}', (self.repo / 'main.tex').read_text())
        self.assertIn(r'\author{Cristiano Migali}', (self.repo / 'main.tex').read_text())
        self.assertIn(r'\date{October 2026}', (self.repo / 'main.tex').read_text())
        self.assertTrue((self.repo / 'content/01_introduction.tex').exists())
        self.assertTrue((self.repo / 'appendix/01_proofs.tex').exists())
        self.assertFalse((self.repo / '.codex/config.toml').exists())
        config = json.loads((self.repo / '.paper/config.json').read_text())
        self.assertEqual(config['drafting_api'], 'agent-v1')
        self.assertEqual(config['scaffold_type'], 'paper')
        manifest = json.loads((self.repo / '.paper/manifest.json').read_text())
        self.assertIn('papermacros.sty', manifest['files'])
        self.assertNotIn('main.tex', manifest['files'])
        backup = list((self.repo / '.paper/scaffold-backups').glob('*/main.tex'))
        self.assertEqual(len(backup), 1)
        self.assertEqual(backup[0].read_text(), BLANK)

    def test_existing_manuscript_is_preserved_and_force_is_advertised(self):
        original = (self.repo / 'main.tex').read_bytes()
        output = self.paper('init')
        self.assertIn('existing or unrecognized manuscript', output)
        self.assertIn('paper init --force', output)
        self.assertIn('paper create --force', output)
        self.assertEqual((self.repo / 'main.tex').read_bytes(), original)
        self.assertFalse((self.repo / 'papermacros.sty').exists())
        self.assertIn('Never insert undefined commands', (self.repo / 'AGENTS.md').read_text())

    def test_blank_main_with_other_asset_is_not_assumed_empty(self):
        (self.repo / 'main.tex').write_text(BLANK)
        (self.repo / 'important-data.csv').write_text('valuable data')
        self.paper('init')
        self.assertEqual((self.repo / 'main.tex').read_text(), BLANK)
        self.assertFalse((self.repo / 'papermacros.sty').exists())

    def test_force_installs_selected_profile_backs_up_collisions_and_keeps_other_files(self):
        (self.repo / 'projectmacros.tex').write_text('my existing notation')
        (self.repo / 'extra.tex').write_text('unrelated')
        output = self.paper('init', '--force', '--slides')
        self.assertIn('Explicit --force', output)
        self.assertIn('scaffold-backups', output)
        self.assertIn(r'\documentclass{beamer}', (self.repo / 'main.tex').read_text())
        backups = list((self.repo / '.paper/scaffold-backups').iterdir())
        self.assertEqual((backups[0] / 'main.tex').read_text(), 'initial\n')
        self.assertEqual((backups[0] / 'projectmacros.tex').read_text(), 'my existing notation')
        self.assertEqual((self.repo / 'extra.tex').read_text(), 'unrelated')

    def test_repeated_init_preserves_user_sources_and_type(self):
        self.paper('init', '--force', '--poster')
        for name in ('main.tex', 'projectmacros.tex', 'content/01_introduction.tex',
                     'appendix/01_proofs.tex', 'references.bib'):
            (self.repo / name).write_text('my edits in ' + name)
        self.paper('init')
        self.paper('init', '--slides')
        for name in ('main.tex', 'projectmacros.tex', 'content/01_introduction.tex',
                     'appendix/01_proofs.tex', 'references.bib'):
            self.assertEqual((self.repo / name).read_text(), 'my edits in ' + name)
        self.assertEqual(json.loads((self.repo / '.paper/config.json').read_text())[
            'scaffold_type'], 'poster')

    def test_macro_upgrade_is_conservative_and_user_source_is_not_regenerated(self):
        self.paper('init', '--force')
        (self.repo / 'main.tex').write_text('my manuscript')
        tooling = self.root / 'tooling'
        shutil.copytree(SOURCE, tooling, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        package = tooling / 'templates/latex/papermacros.sty'
        package.write_text(package.read_text() + '\n% newer package\n')
        result = subprocess.run(['bash', str(tooling / 'paper'), 'init'], cwd=self.repo,
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.repo / 'papermacros.sty').read_text().endswith('% newer package\n'))
        self.assertEqual((self.repo / 'main.tex').read_text(), 'my manuscript')
        (self.repo / 'papermacros.sty').write_text('my edited shared macros')
        result = subprocess.run(['bash', str(tooling / 'paper'), 'init'], cwd=self.repo,
                                env=self.env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.repo / 'papermacros.sty').read_text(), 'my edited shared macros')
        self.paper('init', '--force')
        self.assertTrue(any(p.read_text() == 'my edited shared macros'
                            for p in (self.repo / '.paper/scaffold-backups').glob('*/papermacros.sty')))

    def test_force_cannot_overwrite_edited_workflow_or_follow_symlink(self):
        self.paper('init')
        workflow = self.repo / '.github/workflows/paper-preview.yml'
        workflow.write_text('my custom workflow')
        self.paper('init', '--force', ok=False)
        self.assertEqual((self.repo / 'main.tex').read_text(), 'initial\n')
        self.assertFalse((self.repo / '.paper/scaffold-backups').exists())
        workflow.unlink()
        target = self.repo / 'outside.tex'
        target.write_text('keep me')
        (self.repo / 'main.tex').unlink()
        (self.repo / 'main.tex').symlink_to(target)
        self.paper('init', '--force', ok=False)
        self.assertEqual(target.read_text(), 'keep me')
        self.assertFalse((self.repo / '.paper/scaffold-backups').exists())

    def test_vendored_runtime_can_scaffold_and_repair_macro_package(self):
        self.paper('init')
        result = subprocess.run(['bash', '.paper/runtime/paper', 'init', '--force', '--slides'],
                                cwd=self.repo, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        package = self.repo / 'papermacros.sty'
        expected = package.read_bytes()
        package.unlink()
        result = subprocess.run(['bash', '.paper/runtime/paper', 'init'],
                                cwd=self.repo, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(package.read_bytes(), expected)


for name in list(test_workflow.WorkflowTest.__dict__):
    if name.startswith('test_'):
        setattr(ScaffoldTest, name, None)
