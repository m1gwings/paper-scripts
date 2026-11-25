"""The shared build watcher with disposable projects and private runtime state."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

SOURCE = Path(__file__).resolve().parents[1]
DOCUMENT = '\\documentclass{article}\\begin{document}%s\\end{document}\n'


class BuildWatcherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='paper watch ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.lib = SOURCE / 'lib'
        self.env = dict(os.environ, HOME=str(self.root), XDG_RUNTIME_DIR=str(self.root / 'run'),
                        XDG_STATE_HOME=str(self.root / 'state'), XDG_CACHE_HOME=str(self.root / 'cache'),
                        GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1', PAPER_OVERLEAF_AUTO='0')
        self.addCleanup(self.shutdown)

    def project(self, name, body='Project text', rc=None):
        directory = self.root / name
        directory.mkdir()
        subprocess.run(['git', 'init', '-q', str(directory)], check=True, env=self.env)
        (directory / 'main.tex').write_text(DOCUMENT % body)
        if rc:
            (directory / '.latexmkrc').write_text(rc)
        return directory

    def watch(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(self.lib / 'build_watcher.py'), *map(str, args)],
                                env=self.env, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result.stdout

    def status(self):
        return json.loads(self.watch('status', '--json'))

    def daemon_log(self):
        path = self.root / 'state/paper/watch.log'
        return path.read_text() if path.exists() else ''

    def wait(self, condition, message, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(.05)
        self.fail(message() if callable(message) else message)

    def state(self, project):
        try:
            return json.loads((project / 'output/.latex/main.build.json').read_text())
        except (OSError, ValueError):
            return {}

    def idle(self):
        status = self.status()
        return not any(p['building'] for p in status['projects'])

    def shutdown(self):
        if not (self.root / 'run/paper/watch.sock').exists():
            return
        try:
            self.wait(self.idle, 'builds did not finish')
        finally:
            self.watch('stop')
            self.wait(lambda: not (self.root / 'run/paper/watch.sock').exists(), 'watcher did not stop')

    def test_one_daemon_builds_every_project_and_exits_with_the_last(self):
        first, second = self.project('first', 'First'), self.project('second', 'Second')
        self.assertIn('Watching', self.watch('register', first, '--client', 'editor'))
        self.watch('register', second / 'main.tex', '--client', 'reader')  # Any path inside the root.
        self.wait(lambda: self.state(first).get('state') == 'success' and self.state(second).get('state') == 'success',
                  self.daemon_log)
        status = self.status()
        self.assertEqual({p['root']: p['clients'] for p in status['projects']},
                         {str(first.resolve()): ['editor'], str(second.resolve()): ['reader']})
        self.assertTrue((first / 'output/main.pdf').is_file())
        self.assertTrue((first / 'output/.latex/main.log').is_file())
        self.assertIn('Watching main.tex', (first / 'output/.latex/.watch.log').read_text())
        self.assertEqual(self.daemon_log().count('serving from'), 1)

        # A second client keeps the project; it stops with its last client.
        self.watch('register', first, '--client', 'reader')
        self.watch('unregister', first, '--client', 'editor')
        self.assertEqual(len(self.status()['projects']), 2)
        self.watch('unregister', first, '--client', 'reader')
        self.assertEqual([p['root'] for p in self.status()['projects']], [str(second.resolve())])
        self.wait(self.idle, 'builds did not finish')
        self.watch('unregister', second, '--client', 'reader')
        self.wait(lambda: not (self.root / 'run/paper/watch.sock').exists(), 'watcher did not exit')
        self.assertFalse(self.status()['running'])
        self.assertIn('exiting', self.daemon_log())

    def test_saved_sources_rebuild_and_failures_stay_in_their_project(self):
        good, broken = self.project('good', 'Good'), self.project('broken', '\\undefinedmacro')
        self.watch('register', good)
        self.watch('register', broken)
        self.wait(lambda: self.state(good).get('state') == 'success' and self.state(broken).get('state') == 'failed',
                  self.daemon_log)
        self.assertIn('Undefined control sequence', self.state(broken)['error'])
        self.wait(self.idle, 'builds did not finish')
        before = self.state(good)['updated']
        (good / 'main.tex').write_text(DOCUMENT % 'Good, revised')
        self.wait(lambda: self.state(good).get('updated', 0) > before and self.state(good)['state'] == 'success',
                  self.daemon_log)
        (broken / 'main.tex').write_text(DOCUMENT % 'Repaired')
        self.wait(lambda: self.state(broken).get('state') == 'success', self.daemon_log)
        self.assertEqual(len(self.status()['projects']), 2)

    def test_projects_build_concurrently_while_each_project_stays_serialized(self):
        slow = self.project('slow', 'Slow', rc='$pdflatex = "sleep 4; pdflatex %O %S";\n')
        quick = self.project('quick', 'Quick')
        self.watch('register', slow)
        self.wait(lambda: any(p['building'] for p in self.status()['projects']), 'slow build did not start')
        self.watch('register', quick)
        self.wait(lambda: self.state(quick).get('state') == 'success', self.daemon_log, timeout=15)
        building = {p['root']: p['building'] for p in self.status()['projects']}
        self.assertEqual(building[str(slow.resolve())], 'main.tex')
        self.assertEqual(self.state(slow).get('state'), 'building')

    def test_clients_with_a_pid_unregister_when_their_process_exits(self):
        project = self.project('editor-owned')
        owner = subprocess.Popen(['sleep', '30'])
        self.addCleanup(owner.wait)
        self.addCleanup(owner.kill)
        self.watch('register', project, '--client', 'editor', '--pid', owner.pid)
        self.wait(lambda: self.state(project).get('state') == 'success', self.daemon_log)
        self.wait(self.idle, 'builds did not finish')
        owner.kill()
        self.wait(lambda: not (self.root / 'run/paper/watch.sock').exists(), self.daemon_log, timeout=10)
        self.assertIn('Client exited: editor', self.daemon_log())

    def test_existing_per_project_watcher_keeps_the_project_until_it_stops(self):
        project = self.project('legacy')
        (project / 'output/.latex').mkdir(parents=True)
        with (project / 'output/.latex/.project.watch.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.watch('register', project)
            self.wait(lambda: self.status()['projects'][0]['state'] == 'external', 'lock was not respected')
            time.sleep(1)
            self.assertFalse((project / 'output/main.pdf').exists())
        self.wait(lambda: self.state(project).get('state') == 'success', self.daemon_log)

    def test_projects_without_latex_documents_are_not_watched(self):
        plain = self.root / 'plain'
        plain.mkdir()
        self.assertIn('not a Git repository', self.watch('register', plain))
        subprocess.run(['git', 'init', '-q', str(plain)], check=True, env=self.env)
        (plain / 'notes.md').write_text('# Notes\n')
        self.assertIn('no LaTeX documents', self.watch('register', plain))
        self.assertFalse((self.root / 'run/paper/watch.sock').exists())
        self.assertIn('No watched projects', self.watch('status'))
        self.watch('unregister', plain)

    def test_rewritten_runtime_reloads_without_losing_registrations(self):
        runtime = self.root / 'runtime'
        shutil.copytree(SOURCE / 'lib', runtime, ignore=shutil.ignore_patterns('__pycache__'))
        self.lib = runtime
        project = self.project('reloaded')
        self.watch('register', project, '--client', 'editor')
        self.wait(lambda: self.state(project).get('state') == 'success', self.daemon_log)
        self.wait(self.idle, 'builds did not finish')
        pid = self.status()['pid']
        script = runtime / 'build_watcher.py'
        script.write_text(script.read_text() + '\n# Upgraded runtime.\n')
        self.wait(lambda: 'reloading watcher' in self.daemon_log(), self.daemon_log, timeout=10)
        self.wait(lambda: self.daemon_log().count('serving from') == 2, self.daemon_log, timeout=10)
        status = self.status()
        self.assertEqual(status['pid'], pid)
        self.assertEqual([p['clients'] for p in status['projects']], [['editor']])
        self.assertFalse(list((self.root / 'run/paper').glob('watch-*.json')))


if __name__ == '__main__':
    unittest.main()
