"""Real build/watch checks using disposable sources, with no project remotes."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'paper'


@unittest.skipUnless(shutil.which('latexmk') and shutil.which('pdftotext'), 'TeX tools unavailable')
class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='paper build ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1')
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True, env=self.env)
        (self.root / 'main.tex').write_text('\\documentclass{article}\n'
                                          '\\begin{document}\\input{body}\\end{document}\n')
        (self.root / 'body.tex').write_text('First version.\n')

    def paper(self, *args, ok=True):
        r = subprocess.run(['bash', str(SCRIPT), *args], cwd=self.root, env=self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
        return r.stdout + r.stderr

    def pdf_text(self, relative='output/main.pdf'):
        return subprocess.check_output(['pdftotext', str(self.root / relative), '-'], text=True)

    def test_output_clean_and_alternative_root(self):
        self.paper('build')
        self.assertIn('First version', self.pdf_text())
        self.assertFalse((self.root / 'main.pdf').exists())
        self.assertFalse((self.root / 'main.aux').exists())
        variants = self.root / 'variants'
        variants.mkdir()
        (variants / 'draft.tex').write_text('\\documentclass{article}\n'
                                          '\\begin{document}Different root.\\end{document}\n')
        self.paper('build', 'variants/draft.tex')
        self.assertIn('Different root', self.pdf_text('output/variants/draft.pdf'))
        self.paper('clean')
        self.assertFalse((self.root / 'output/main.pdf').exists())
        self.assertTrue((self.root / 'output/variants/draft.pdf').exists())
        self.assertTrue((self.root / 'main.tex').exists())

    def test_saved_dependency_rebuilds_without_an_editor_extension(self):
        with (self.root / 'watch.log').open('w') as log:
            watcher = subprocess.Popen(['bash', str(SCRIPT), 'build', '--watch'], cwd=self.root,
                                       env=self.env, stdout=log, stderr=log, start_new_session=True)
            def wait_for_text(text):
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if watcher.poll() is not None:
                        self.fail((self.root / 'watch.log').read_text())
                    if (self.root / 'output/main.pdf').exists():
                        result = subprocess.run(['pdftotext', str(self.root / 'output/main.pdf'), '-'],
                                                capture_output=True, text=True)
                        if result.returncode == 0 and text in result.stdout:
                            return
                    time.sleep(.25)
                self.fail('Watcher did not update PDF: ' + (self.root / 'watch.log').read_text())
            try:
                wait_for_text('First version')
                duplicate = self.paper('build', '--watch')
                self.assertIn('already watching', duplicate)
                (self.root / 'body.tex').write_text('Second version.\n')
                wait_for_text('Second version')
            finally:
                os.killpg(watcher.pid, signal.SIGINT)
                try:
                    watcher.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(watcher.pid, signal.SIGKILL)
                    watcher.wait()

    def test_invalid_source_and_external_output_are_rejected(self):
        self.paper('build', '../secret.tex', ok=False)
        with tempfile.TemporaryDirectory() as outside:
            (self.root / 'output').symlink_to(outside, target_is_directory=True)
            self.paper('build', ok=False)
            self.assertEqual(list(Path(outside).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
