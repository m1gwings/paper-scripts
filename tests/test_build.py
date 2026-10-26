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

    def test_watcher_manual_builds_and_clean_never_overlap(self):
        fake_bin = self.root / 'bin'
        fake_bin.mkdir()
        compiler = fake_bin / 'latexmk'
        compiler.write_text('''#!/usr/bin/python3
import os,sys,time
from pathlib import Path
out=Path('output'); out.mkdir(exist_ok=True)
try: (out/'busy').mkdir()
except FileExistsError:
    (out/'overlap').touch(); sys.exit(99)
try:
    with (out/'calls').open('a') as f: f.write('clean\\n' if '-C' in sys.argv else 'build\\n')
    time.sleep(.4)
    if '-C' in sys.argv: (out/'main.pdf').unlink(missing_ok=True)
    else:
        (out/'main.pdf').write_text(Path('body.tex').read_text())
        (out/'main.fls').write_text('INPUT main.tex\\nINPUT body.tex\\n')
finally: (out/'busy').rmdir()
''')
        compiler.chmod(0o755)
        self.env['PATH'] = str(fake_bin) + os.pathsep + self.env['PATH']
        with (self.root / 'watch.log').open('w') as log:
            watcher = subprocess.Popen(['bash', str(SCRIPT), 'build', '--watch'], cwd=self.root,
                                       env=self.env, stdout=log, stderr=log, start_new_session=True)
            clients = []
            try:
                deadline = time.monotonic() + 10
                while not (self.root / 'output/busy').exists():
                    self.assertIsNone(watcher.poll())
                    self.assertLess(time.monotonic(), deadline, (self.root / 'watch.log').read_text())
                    time.sleep(.02)
                for action in ('build', 'clean', 'build'):
                    clients.append(subprocess.Popen(['bash', str(SCRIPT), action], cwd=self.root,
                                   env=self.env, stdout=log, stderr=log))
                for client in clients:
                    self.assertEqual(client.wait(timeout=15), 0, (self.root / 'watch.log').read_text())
                (self.root / 'body.tex').write_text('Saved after concurrent builds.\n')
                deadline = time.monotonic() + 10
                while True:
                    pdf = self.root / 'output/main.pdf'
                    if pdf.exists() and 'Saved after concurrent' in pdf.read_text(): break
                    self.assertIsNone(watcher.poll())
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(.05)
                self.assertFalse((self.root / 'output/overlap').exists())
                # Watching must settle instead of repeatedly rebuilding its own output.
                time.sleep(1)
                calls = (self.root / 'output/calls').read_text()
                time.sleep(1)
                self.assertEqual(calls, (self.root / 'output/calls').read_text())
            finally:
                os.killpg(watcher.pid, signal.SIGINT)
                watcher.wait(timeout=5)
                for client in clients:
                    if client.poll() is None: client.terminate(); client.wait()

    def test_watcher_tracks_bibliography_and_recovers_after_a_failed_save(self):
        (self.root / 'body.tex').write_text('First version.\\nocite{entry}\\bibliographystyle{plain}\\bibliography{refs}\n')
        bibliography = self.root / 'refs.bib'
        bibliography.write_text('@book{entry,author={Alice Author},title={Initial title},year={2020}}\n')
        with (self.root / 'watch.log').open('w') as log:
            watcher = subprocess.Popen(['bash', str(SCRIPT), 'build', '--watch'], cwd=self.root,
                                       env=self.env, stdout=log, stderr=log, start_new_session=True)
            def wait_for(text):
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    self.assertIsNone(watcher.poll(), (self.root / 'watch.log').read_text())
                    pdf = self.root / 'output/main.pdf'
                    if pdf.exists():
                        result = subprocess.run(['pdftotext', str(pdf), '-'], capture_output=True, text=True)
                        if text in result.stdout: return
                    time.sleep(.1)
                self.fail((self.root / 'watch.log').read_text())
            try:
                wait_for('Initial title')
                bibliography.write_text('@book{entry,author={Alice Author},title={Revised title},year={2020}}\n')
                wait_for('Revised title')
                (self.root / 'body.tex').write_text('\\UndefinedControlSequence\n')
                deadline = time.monotonic() + 10
                while 'Undefined control sequence' not in (self.root / 'watch.log').read_text():
                    self.assertLess(time.monotonic(), deadline, (self.root / 'watch.log').read_text())
                    time.sleep(.1)
                (self.root / 'body.tex').write_text('Recovered after a failed save.\n')
                wait_for('Recovered after a failed save')
            finally:
                os.killpg(watcher.pid, signal.SIGINT)
                watcher.wait(timeout=5)

    def test_first_build_keeps_a_dependency_saved_while_it_is_being_discovered(self):
        fake_bin = self.root / 'bin'; fake_bin.mkdir()
        dependency = self.root / 'part.fragment'
        dependency.write_text('Before the save')
        compiler = fake_bin / 'latexmk'
        compiler.write_text('''#!/usr/bin/python3
from pathlib import Path
import time
out=Path('output'); out.mkdir(exist_ok=True)
text=Path('part.fragment').read_text()
(out/'started').touch()
while not (out/'continue').exists(): time.sleep(.02)
(out/'main.pdf').write_text(text)
(out/'main.fls').write_text('INPUT main.tex\\nINPUT part.fragment\\n')
''')
        compiler.chmod(0o755)
        env = dict(self.env, PATH=str(fake_bin) + os.pathsep + self.env['PATH'])
        with (self.root / 'watch.log').open('w') as log:
            watcher = subprocess.Popen(['bash', str(SCRIPT), 'build', '--watch'], cwd=self.root,
                                       env=env, stdout=log, stderr=log, start_new_session=True)
            try:
                deadline = time.monotonic() + 10
                while not (self.root / 'output/started').exists():
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(.02)
                dependency.write_text('Saved during the first build')
                (self.root / 'output/continue').touch()
                while True:
                    pdf = self.root / 'output/main.pdf'
                    if pdf.exists() and pdf.read_text() == 'Saved during the first build': break
                    self.assertIsNone(watcher.poll())
                    self.assertLess(time.monotonic(), deadline, (self.root / 'watch.log').read_text())
                    time.sleep(.05)
            finally:
                os.killpg(watcher.pid, signal.SIGINT)
                watcher.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
