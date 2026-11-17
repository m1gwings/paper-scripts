"""Tests for paper note command: python3 -m unittest tests/test_note.py -v."""
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'paper'


class PaperNoteTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='paper-note-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def run_paper(self, *args, input='', cwd=None, ok=True):
        result = subprocess.run(['bash', str(SCRIPT), *args],
                                cwd=cwd or self.root, input=input,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def test_init_does_not_create_template_tex_and_preserves_clean_notes(self):
        self.run_paper('init')
        template_path = self.root / 'notes' / 'template.tex'
        self.assertFalse(template_path.exists())
        self.assertTrue((self.root / 'notes' / 'README.md').is_file())

        # An optional local override _template.tex can still be used if provided
        (self.root / 'notes' / '_template.tex').write_text('Custom local template for @@TITLE@@\n', encoding='utf-8')
        out = self.run_paper('note', 'new', 'custom_note')
        self.assertIn('Created notes/custom_note.tex', out)
        self.assertEqual((self.root / 'notes' / 'custom_note.tex').read_text(encoding='utf-8'),
                         'Custom local template for Custom Note\n')

    def test_create_note_default_title_and_slug(self):
        self.run_paper('init')
        out = self.run_paper('note', 'new', 'fixed_budget')
        self.assertIn('Created notes/fixed_budget.tex', out)
        self.assertIn('Title:   Fixed Budget', out)

        note_file = self.root / 'notes' / 'fixed_budget.tex'
        self.assertTrue(note_file.is_file())
        content = note_file.read_text(encoding='utf-8')
        self.assertIn('Fixed Budget', content)
        self.assertNotIn('@@TITLE@@', content)

    def test_create_note_custom_title_and_shorthand(self):
        self.run_paper('init')
        out = self.run_paper('note', 'lower_bound', '--title', 'Fixed-Budget Lower Bound')
        self.assertIn('Created notes/lower_bound.tex', out)
        self.assertIn('Title:   Fixed-Budget Lower Bound', out)

        note_file = self.root / 'notes' / 'lower_bound.tex'
        self.assertTrue(note_file.is_file())
        content = note_file.read_text(encoding='utf-8')
        self.assertIn('Fixed-Budget Lower Bound', content)

    def test_name_slugification_and_extension_stripping(self):
        self.run_paper('init')
        self.run_paper('note', 'new', 'notes/sample_derivations.tex')
        self.assertTrue((self.root / 'notes' / 'sample_derivations.tex').is_file())

        self.run_paper('note', 'new', 'Algorithm & Complex Proof')
        self.assertTrue((self.root / 'notes' / 'algorithm_complex_proof.tex').is_file())

    def test_refuse_overwrite_without_force(self):
        self.run_paper('init')
        self.run_paper('note', 'new', 'existing_note', '--title', 'Original')
        note_file = self.root / 'notes' / 'existing_note.tex'
        self.assertIn('Original', note_file.read_text(encoding='utf-8'))

        # Refusal
        err = self.run_paper('note', 'new', 'existing_note', '--title', 'Replaced', ok=False)
        self.assertIn('already exists', err)
        self.assertIn('Original', note_file.read_text(encoding='utf-8'))

        # Force overwrite
        self.run_paper('note', 'new', 'existing_note', '--title', 'Replaced', '--force')
        self.assertIn('Replaced', note_file.read_text(encoding='utf-8'))

    def test_list_notes(self):
        self.run_paper('init')
        empty_out = self.run_paper('note', 'list')
        self.assertIn('No research notes found', empty_out)

        self.run_paper('note', 'new', 'alpha_note', '--title', 'Alpha Title')
        self.run_paper('note', 'new', 'beta_note', '--title', 'Beta Title')

        list_out = self.run_paper('note', 'list')
        self.assertIn('alpha_note.tex', list_out)
        self.assertIn('Alpha Title', list_out)
        self.assertIn('beta_note.tex', list_out)
        self.assertIn('Beta Title', list_out)

    def test_build_ignores_template_file(self):
        import sys
        sys.path.insert(0, str(SCRIPT.parent / 'lib'))
        import build
        (self.root / 'notes').mkdir(parents=True, exist_ok=True)
        (self.root / 'notes' / 'template.tex').write_text('\\documentclass{article}\\begin{document}x\\end{document}')
        (self.root / 'notes' / 'real_note.tex').write_text('\\documentclass{article}\\begin{document}x\\end{document}')
        roots = build.find_project_roots(self.root)
        self.assertIn(Path('notes/real_note.tex'), roots)
        self.assertNotIn(Path('notes/template.tex'), roots)


if __name__ == '__main__':
    unittest.main()
