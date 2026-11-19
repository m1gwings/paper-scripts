"""Real build/watch checks using disposable sources, with no project remotes."""
import os
import json
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

    def test_failed_build_retains_pdf_and_reports_error_then_recovers(self):
        self.paper('build')
        pdf = self.root / 'output/main.pdf'
        previous = pdf.read_bytes()
        aux = self.root / 'output/.latex'
        def published_map():
            info = pdf.stat()
            return aux / '.synctex/main' / f'{info.st_mtime_ns}-{info.st_size}' / 'main.synctex.gz'

        old_map = published_map()
        map_data = old_map.read_bytes()
        self.assertEqual(map_data, (aux / 'main.synctex.gz').read_bytes())
        stale_map = aux / 'main.synctex'
        stale_map.write_bytes(b'old uncompressed map')
        os.utime(stale_map, ns=(1, 1))
        self.paper('build')
        self.assertEqual(published_map(), old_map)
        self.assertFalse(old_map.with_suffix('').exists())
        (aux / 'main.synctex.gz').write_bytes(b'overwritten compiler map')
        (self.root / 'body.tex').write_text(r'Broken \undefinedcommand' + '\n')
        self.paper('build', ok=False)
        self.assertEqual(pdf.read_bytes(), previous)
        self.assertEqual(published_map(), old_map)
        self.assertEqual(old_map.read_bytes(), map_data)
        state = json.loads((self.root / 'output/.latex/main.build.json').read_text())
        self.assertEqual(state['state'], 'failed')
        self.assertIn('Undefined control', state['error'])
        self.assertEqual(state['file'], './body.tex')
        self.assertEqual(state['line'], 1)
        (self.root / 'body.tex').write_text('Recovered.\n')
        self.paper('build')
        self.assertIn('Recovered', self.pdf_text())
        self.assertEqual(published_map().read_bytes(), (aux / 'main.synctex.gz').read_bytes())
        self.assertFalse(old_map.exists())
        self.assertEqual(json.loads((self.root / 'output/.latex/main.build.json').read_text())['state'], 'success')

    def test_corrupt_pdf_is_not_retained_as_last_good(self):
        pdf = self.root / 'output/main.pdf'
        (self.root / 'output').mkdir(exist_ok=True)
        pdf.write_bytes(b'%PDF-1.5 truncated stub without EOF')
        (self.root / 'body.tex').write_text(r'Broken \undefinedcommand' + '\n')
        self.paper('build', ok=False)
        self.assertEqual(pdf.read_bytes(), b'%PDF-1.5 truncated stub without EOF')
        (self.root / 'body.tex').write_text('Valid version.\n')
        self.paper('build')
        self.assertIn('Valid version', self.pdf_text())
        last_good = (self.root / 'output/.latex/main.pdf.last-good').read_bytes()
        self.assertIn(b'%PDF-', last_good)
        self.assertIn(b'%%EOF', last_good[-2048:])
        # An unchanged staged build must repair a corrupt published copy too.
        pdf.write_bytes(b'corrupt published copy')
        self.paper('build')
        self.assertIn('Valid version', self.pdf_text())

    def test_output_clean_and_alternative_root(self):
        self.paper('build')
        self.assertIn('First version', self.pdf_text())
        self.assertFalse((self.root / 'main.pdf').exists())
        self.assertFalse((self.root / 'main.aux').exists())
        self.assertEqual({p.name for p in (self.root / 'output').iterdir()}, {'main.pdf', '.latex'})
        self.assertTrue((self.root / 'output/.latex/main.aux').is_file())
        self.assertTrue((self.root / 'output/.latex/main.synctex.gz').is_file())
        study = self.root / 'output/study'
        study.mkdir()
        (study / 'metadata.json').write_text('preserve study')
        variants = self.root / 'variants'
        variants.mkdir()
        (variants / 'draft.tex').write_text('\\documentclass{article}\n'
                                          '\\begin{document}Different root.\\end{document}\n')
        self.paper('build', 'variants/draft.tex')
        self.assertIn('Different root', self.pdf_text('output/variants/draft.pdf'))
        self.paper('clean')
        self.assertFalse((self.root / 'output/main.pdf').exists())
        self.assertFalse((self.root / 'output/.latex/.synctex/main').exists())
        self.assertTrue((self.root / 'output/.latex/variants/.synctex/draft').exists())
        self.assertTrue((self.root / 'output/variants/draft.pdf').exists())
        self.assertTrue((self.root / 'main.tex').exists())
        self.assertEqual((study / 'metadata.json').read_text(), 'preserve study')

    def test_clean_output_clutter_moves_checks_and_unlinks_locks(self):
        self.paper('build')
        out = self.root / 'output'
        # Add diverse clutter
        (out / '.build.lock').touch()
        (out / '.main.watch.lock').touch()
        (out / 'citation_check.tex').write_text('check tex')
        (out / 'citation_check.pdf').write_text('%PDF-check')
        (out / 'layout_check-1.png').write_text('fake png')
        (out / 'comment.cut').write_text('cut file')
        (out / 'main.auxlock').write_text('auxlock')
        review_dir = out / 'final-uif-review'
        review_dir.mkdir()
        (review_dir / 'page.png').write_text('review png')
        empty_dir = out / 'appendix'
        empty_dir.mkdir()

        # Re-building or cleaning cleans the clutter
        self.paper('build')

        self.assertTrue((out / 'main.pdf').exists())
        self.assertFalse((out / '.build.lock').exists())
        self.assertFalse((out / '.main.watch.lock').exists())
        self.assertFalse((out / 'citation_check.tex').exists())
        self.assertFalse((out / 'citation_check.pdf').exists())
        self.assertFalse((out / 'layout_check-1.png').exists())
        self.assertFalse((out / 'comment.cut').exists())
        self.assertFalse((out / 'main.auxlock').exists())
        self.assertFalse((out / 'final-uif-review').exists())
        self.assertFalse(empty_dir.exists())

        # Checks are safely preserved in .latex/checks/ and .latex/reviews/
        self.assertTrue((out / '.latex/checks/citation_check.tex').exists())
        self.assertTrue((out / '.latex/checks/citation_check.pdf').exists())
        self.assertTrue((out / '.latex/checks/layout_check-1.png').exists())
        self.assertTrue((out / '.latex/comment.cut').exists())
        self.assertTrue((out / '.latex/main.auxlock').exists())
        self.assertTrue((out / '.latex/reviews/final-uif-review/page.png').exists())

    def test_explicit_watch_root_rebuilds_saved_dependencies(self):
        with (self.root / 'watch.log').open('w') as log:
            watcher = subprocess.Popen(['bash', str(SCRIPT), 'build', '--watch', 'main.tex'], cwd=self.root,
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
                for args in [('--watch', 'main.tex'), ('main.tex', '--watch')]:
                    duplicate = self.paper('build', *args)
                    self.assertIn('already watching', duplicate)
                (self.root / 'body.tex').write_text('Second version.\n')
                wait_for_text('Second version')
            finally:
                if watcher.poll() is None:
                    os.killpg(watcher.pid, signal.SIGINT)
                try:
                    watcher.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(watcher.pid, signal.SIGKILL)
                    watcher.wait()

    def test_watcher_tracks_ews_pdf_inputs_without_rebuilding_its_own_output(self):
        study = self.root / 'output/study'
        study.mkdir(parents=True)
        scratch = self.root / 'figure_source'
        scratch.mkdir()

        def figure(text):
            (scratch / 'figure.tex').write_text(
                r'\documentclass{article}\pagestyle{empty}\begin{document}'
                + text + r'\end{document}')
            subprocess.run(['latexmk', '-pdf', '-interaction=nonstopmode', 'figure.tex'],
                           cwd=scratch, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                           check=True, timeout=20)
            shutil.copyfile(scratch / 'figure.pdf', study / 'figure.pdf')

        figure('Initial experiment figure')
        (self.root / 'main.tex').write_text(
            r'\documentclass{article}\usepackage{graphicx}\begin{document}'
            r'\includegraphics[width=3cm]{output/study/figure.pdf}\end{document}')
        with (self.root / 'watch.log').open('w') as log:
            watcher = subprocess.Popen(['bash', str(SCRIPT), 'build', '--watch'], cwd=self.root,
                                       env=self.env, stdout=log, stderr=log, start_new_session=True)
            def wait_for(text):
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    self.assertIsNone(watcher.poll(), (self.root / 'watch.log').read_text())
                    pdf = self.root / 'output/main.pdf'
                    if pdf.exists():
                        result = subprocess.run(['pdftotext', str(pdf), '-'],
                                                capture_output=True, text=True)
                        if text in result.stdout:
                            return
                    time.sleep(.1)
                self.fail((self.root / 'watch.log').read_text())
            try:
                wait_for('Initial experiment figure')
                figure('Updated experiment figure')
                wait_for('Updated experiment figure')
                time.sleep(1.5)
                state = self.root / 'output/.latex/main.build.json'
                stamp = state.stat().st_mtime_ns
                time.sleep(1)
                self.assertEqual(state.stat().st_mtime_ns, stamp)
            finally:
                os.killpg(watcher.pid, signal.SIGINT)
                watcher.wait(timeout=5)

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
aux=Path(next(a.split('=',1)[1] for a in sys.argv if a.startswith('-outdir=')))
try: (out/'busy').mkdir()
except FileExistsError:
    (out/'overlap').touch(); sys.exit(99)
try:
    with (out/'calls').open('a') as f: f.write('clean\\n' if '-C' in sys.argv else 'build\\n')
    time.sleep(.4)
    if '-C' in sys.argv: (out/'main.pdf').unlink(missing_ok=True)
    else:
        (aux/'main.pdf').write_text('%PDF-1.5 '+ ' ' * 100 + Path('body.tex').read_text() + '%%EOF')
        (aux/'main.fls').write_text('INPUT main.tex\\nINPUT body.tex\\n')
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
import sys,time
out=Path('output'); out.mkdir(exist_ok=True)
aux=Path(next(a.split('=',1)[1] for a in sys.argv if a.startswith('-outdir=')))
text=Path('part.fragment').read_text()
(out/'started').touch()
while not (out/'continue').exists(): time.sleep(.02)
(aux/'main.pdf').write_text('%PDF-1.5 '+ ' ' * 100 + text + '%%EOF')
(aux/'main.fls').write_text('INPUT main.tex\\nINPUT part.fragment\\n')
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
                    if pdf.exists() and 'Saved during the first build' in pdf.read_text(): break
                    self.assertIsNone(watcher.poll())
                    self.assertLess(time.monotonic(), deadline, (self.root / 'watch.log').read_text())
                    time.sleep(.05)
            finally:
                os.killpg(watcher.pid, signal.SIGINT)
                watcher.wait(timeout=5)

    def test_watch_entire_project_builds_top_level_and_notes_and_ignores_fragments(self):
        (self.root / 'macros.tex').write_text(r'\newcommand{\greeting}{Hello}' + '\n')
        (self.root / 'body.tex').write_text(r'\greeting\ world.' + '\n')
        (self.root / 'main.tex').write_text(r'\documentclass{article}\input{macros}\begin{document}\input{body}\end{document}' + '\n')
        (self.root / 'coverletter.tex').write_text(r'\documentclass{article}\begin{document}Cover letter text.\end{document}' + '\n')
        notes_dir = self.root / 'notes'
        notes_dir.mkdir()
        (notes_dir / 'idea.tex').write_text(r'\documentclass{article}\begin{document}Note text.\end{document}' + '\n')

        with (self.root / 'watch.log').open('w') as log:
            watcher = subprocess.Popen(['bash', str(SCRIPT), 'build', '--watch'], cwd=self.root,
                                       env=self.env, stdout=log, stderr=log, start_new_session=True)
            def wait_for(relative_pdf, text):
                deadline = time.monotonic() + 20
                pdf = self.root / relative_pdf
                while time.monotonic() < deadline:
                    self.assertIsNone(watcher.poll(), (self.root / 'watch.log').read_text())
                    if pdf.exists():
                        result = subprocess.run(['pdftotext', str(pdf), '-'], capture_output=True, text=True)
                        if text in result.stdout:
                            return
                    time.sleep(.1)
                self.fail(f'Timed out waiting for {text} in {relative_pdf}:\n' + (self.root / 'watch.log').read_text())

            try:
                wait_for('output/main.pdf', 'Hello world')
                wait_for('output/coverletter.pdf', 'Cover letter text')
                wait_for('output/notes/idea.pdf', 'Note text')
                self.assertFalse((self.root / 'output/macros.pdf').exists())
                self.assertFalse((self.root / 'output/body.pdf').exists())

                # Granular rebuild: update notes/idea.tex
                cover_mtime = (self.root / 'output/coverletter.pdf').stat().st_mtime_ns
                time.sleep(0.1)
                (notes_dir / 'idea.tex').write_text(r'\documentclass{article}\begin{document}Updated note text.\end{document}' + '\n')
                wait_for('output/notes/idea.pdf', 'Updated note text')
                self.assertEqual((self.root / 'output/coverletter.pdf').stat().st_mtime_ns, cover_mtime)

                # Shared dependency update: update macros.tex
                idea_mtime = (self.root / 'output/notes/idea.pdf').stat().st_mtime_ns
                time.sleep(0.1)
                (self.root / 'macros.tex').write_text(r'\newcommand{\greeting}{Greetings}' + '\n')
                wait_for('output/main.pdf', 'Greetings world')
                self.assertEqual((self.root / 'output/notes/idea.pdf').stat().st_mtime_ns, idea_mtime)
            finally:
                os.killpg(watcher.pid, signal.SIGINT)
                watcher.wait(timeout=5)

    def test_watch_project_dynamically_discovers_new_note(self):
        with (self.root / 'watch.log').open('w') as log:
            watcher = subprocess.Popen(['bash', str(SCRIPT), 'build', '--watch'], cwd=self.root,
                                       env=self.env, stdout=log, stderr=log, start_new_session=True)
            def wait_for(relative_pdf, text):
                deadline = time.monotonic() + 20
                pdf = self.root / relative_pdf
                while time.monotonic() < deadline:
                    self.assertIsNone(watcher.poll(), (self.root / 'watch.log').read_text())
                    if pdf.exists():
                        result = subprocess.run(['pdftotext', str(pdf), '-'], capture_output=True, text=True)
                        if text in result.stdout:
                            return
                    time.sleep(.1)
                self.fail(f'Timed out waiting for {text} in {relative_pdf}:\n' + (self.root / 'watch.log').read_text())

            try:
                wait_for('output/main.pdf', 'First version')
                notes = self.root / 'notes'
                notes.mkdir()
                (notes / 'draft.tex').write_text(r'\documentclass{article}\begin{document}Dynamic note content.\end{document}' + '\n')
                wait_for('output/notes/draft.pdf', 'Dynamic note content')
            finally:
                os.killpg(watcher.pid, signal.SIGINT)
                watcher.wait(timeout=5)

    def test_watch_project_locking_prevents_duplicate_project_watchers(self):
        with (self.root / 'watch.log').open('w') as log:
            watcher = subprocess.Popen(['bash', str(SCRIPT), 'build', '--watch'], cwd=self.root,
                                       env=self.env, stdout=log, stderr=log, start_new_session=True)
            try:
                deadline = time.monotonic() + 15
                while not (self.root / 'output/main.pdf').exists():
                    self.assertIsNone(watcher.poll())
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(.1)
                second = subprocess.run(['bash', str(SCRIPT), 'build', '--watch'], cwd=self.root,
                                        env=self.env, capture_output=True, text=True, timeout=10)
                self.assertEqual(second.returncode, 0)
                self.assertIn('already watching the project', second.stdout)
            finally:
                os.killpg(watcher.pid, signal.SIGINT)
                watcher.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
