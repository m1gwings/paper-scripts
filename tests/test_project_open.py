"""Exercise the public launchers without opening desktop applications."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import fcntl


SOURCE = Path(__file__).resolve().parents[1]


class ProjectOpenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='paper editor ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'project $(touch INJECTED)'
        self.project.mkdir()
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'launch.json'
        self.env = dict(os.environ, HOME=str(self.root),
                        XDG_STATE_HOME=str(self.root / 'state'),
                        XDG_RUNTIME_DIR=str(self.root / 'runtime'),
                        PATH=str(self.bin) + os.pathsep + os.defpath,
                        GIT_CONFIG_GLOBAL=str(self.root / 'gitconfig'),
                        GIT_CONFIG_NOSYSTEM='1', LAUNCH_LOG=str(self.log),
                        NO_COLOR='1', CODEX_CI='1')
        self.env.pop('PAPER_EDITOR', None)
        for command in ('kitty', 'code', 'micro'):
            stub = self.bin / command
            stub.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
from pathlib import Path
Path(os.environ['LAUNCH_LOG']).write_text(json.dumps({
    'program': Path(sys.argv[0]).name, 'args': sys.argv[1:], 'cwd': os.getcwd(),
    'session': sys.stdin.read() if Path(sys.argv[0]).name == 'kitty' else '',
    'NO_COLOR': os.environ.get('NO_COLOR'), 'CODEX_CI': os.environ.get('CODEX_CI'),
    'project_name': os.environ.get('PROJECT_WORKSPACE_NAME')
}))
''')
            stub.chmod(0o755)
        self.git('init', '-q', str(self.project))

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.project, env=self.env,
                              text=True, capture_output=True, check=True).stdout

    def launch(self, *args, cwd=None, generic=False, env=None, script=None, ok=True):
        program = script or SOURCE / ('project-open' if generic else 'paper')
        command = ['bash', str(program), *([] if generic else ['open']), *args]
        result = subprocess.run(command, cwd=cwd or self.project, env=env or self.env,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def record(self):
        return json.loads(self.log.read_text())

    def test_default_vscode_opens_repository_root_without_remotes(self):
        nested = self.project / 'notes'
        nested.mkdir()
        before = self.git('status', '--porcelain')
        self.launch(cwd=nested)
        self.assertEqual(self.record()['program'], 'code')
        self.assertEqual(self.record()['args'], ['--new-window', str(self.project)])
        self.assertEqual(self.git('status', '--porcelain'), before)
        self.assertFalse((self.project / 'INJECTED').exists())

    def test_configuration_environment_and_explicit_flag_precedence(self):
        self.git('config', '--global', 'paper.editor', 'terminal')
        self.launch()
        self.assertEqual(self.record()['program'], 'kitty')
        self.git('config', 'paper.editor', 'vscode')
        self.launch()
        self.assertEqual(self.record()['program'], 'code')
        env = dict(self.env, PAPER_EDITOR='terminal')
        self.launch(env=env)
        self.assertEqual(self.record()['program'], 'kitty')
        self.launch('--vscode', env=env)
        self.assertEqual(self.record()['program'], 'code')
        self.launch('--terminal')
        self.assertEqual(self.record()['program'], 'kitty')

    def test_generic_directory_and_workspace_contract(self):
        self.launch(str(self.project), generic=True, cwd=self.root)
        data = self.record()
        self.assertEqual(data['program'], 'kitty')
        self.assertEqual(data['cwd'], str(self.project))
        self.assertEqual(data['args'][data['args'].index('--directory') + 1], str(self.project))
        self.assertEqual(data['args'][data['args'].index('--session') + 1], '-')
        self.assertIn('launch --title Editor micro', data['session'])
        self.assertIn('layout fat:bias=74', data['session'])
        self.assertIn('launch --title Shell', data['session'])
        self.assertIn('allow_remote_control=socket-only', data['args'])
        self.assertIn('--listen-on', data['args'])
        records = list((self.root / 'runtime/project-workspaces').glob('*.json'))
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0].read_text())['root'], str(self.project.resolve()))
        self.assertIsNone(data['NO_COLOR'])
        self.assertIsNone(data['CODEX_CI'])
        self.launch('--vscode', str(self.root), generic=True)
        self.assertEqual(self.record()['args'], ['--new-window', str(self.root)])

    def test_invalid_options_and_defaults_do_not_launch(self):
        for args in [('--terminal', '--vscode'), ('--unknown',), ('unexpected-path',)]:
            self.launch(*args, ok=False)
        self.git('config', 'paper.editor', 'misspelled')
        self.assertIn('terminal or vscode', self.launch(ok=False))
        self.assertFalse(self.log.exists())
        self.launch('--vscode')
        self.assertEqual(self.record()['program'], 'code')

    def test_help_outside_repository_and_missing_dependency(self):
        self.assertIn('paper.editor', self.launch('--help', cwd=self.root))
        self.launch(cwd=self.root, ok=False)
        self.launch(str(self.root / 'missing'), generic=True, ok=False)
        (self.bin / 'micro').unlink()
        self.assertIn("'micro' is not installed", self.launch('--terminal', ok=False))
        self.assertFalse(self.log.exists())

    def test_initialized_consumer_has_self_contained_open_command(self):
        subprocess.run(['bash', str(SOURCE / 'paper'), 'init'], cwd=self.project,
                       env=self.env, capture_output=True, text=True, check=True)
        runtime = self.project / '.paper/runtime'
        self.assertTrue((runtime / 'lib/project_open.py').is_file())
        self.assertTrue((runtime / 'lib/build.py').is_file())
        self.assertTrue((runtime / 'lib/project_workspace.py').is_file())
        self.launch('--terminal', script=runtime / 'paper')
        self.assertEqual(self.record()['program'], 'kitty')
        self.assertIn('new_tab Build', self.record()['session'])
        self.assertIn(str(runtime / 'lib/build.py'), self.record()['session'])

    def test_terminal_startup_failure_is_reported(self):
        (self.bin / 'kitty').write_text('#!/bin/sh\necho "Unsupported layout" >&2\nexit 3\n')
        output = self.launch('--terminal', ok=False)
        self.assertIn('Unsupported layout', output)
        self.assertIn('Kitty startup log:', output)

    def test_project_metadata_controls_title_prompt_and_watch_source(self):
        (self.project / '.paper').mkdir()
        (self.project / '.paper/config.json').write_text(json.dumps({
            'project_name': 'CMABs with Ranking Feedback',
            'document_type': 'poster', 'root_tex': 'poster.tex'}))
        self.launch('--terminal')
        record = self.record()
        self.assertEqual(record['project_name'], 'CMABs with Ranking Feedback')
        self.assertIn('Editor — CMABs with Ranking Feedback · Poster', record['args'])
        self.assertIn('--watch poster.tex', record['session'])
        self.assertFalse((self.project / 'INJECTED').exists())

    def test_project_name_survives_reinitialization(self):
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        for _ in range(2):
            subprocess.run(['bash', str(SOURCE / 'paper'), 'init'], cwd=self.project,
                           env=self.env, capture_output=True, text=True, check=True)
            path = self.project / '.paper/config.json'
            config = json.loads(path.read_text())
            self.assertTrue(config['project_name'])
            config['project_name'] = 'My informal project name'
            path.write_text(json.dumps(config))
        self.assertEqual(json.loads(path.read_text())['project_name'], 'My informal project name')

    def test_native_reader_receives_session_output_and_optional_layout(self):
        viewer_log, layout_log = self.root / 'reader.json', self.root / 'layout.json'
        for name, log, response in [('workspace-read', viewer_log, {'ok': True, 'windowTitle': 'Preview · Reader'}),
                                    ('workspace-layout', layout_log, {'monitor_assignments_verified': True})]:
            stub = self.bin / name
            stub.write_text(f'#!{sys.executable}\nimport json,sys\nfrom pathlib import Path\n'
                            f'Path({str(log)!r}).write_text(json.dumps(sys.argv[1:]))\n'
                            f'print({json.dumps(response)!r})\n')
            stub.chmod(0o755)
        (self.project / 'main.tex').write_text('A source fixture.\n')
        self.launch('--terminal')
        viewer = json.loads(viewer_log.read_text())
        self.assertIn('--background', viewer)
        self.assertEqual(viewer[-1], str(self.project / 'output/main.pdf'))
        self.assertEqual(viewer[viewer.index('--project') + 1], str(self.project))
        records = list((self.root / 'runtime/project-workspaces').glob('*.json'))
        self.assertEqual(viewer[viewer.index('--session') + 1], json.loads(records[0].read_text())['id'])
        self.assertIn('--apply', json.loads(layout_log.read_text()))
        self.assertFalse((self.project / 'INJECTED').exists())

    def test_reused_standalone_editor_restores_only_a_missing_build_watcher(self):
        endpoint = self.root / f'runtime/workspace-editors/{os.getpid()}-fixture'
        endpoint.mkdir(parents=True)
        (endpoint / 'record.json').write_text(json.dumps({'pid': os.getpid(), 'project': str(self.project),
            'session': 'paired', 'endpoint': str(endpoint), 'protocol': 1}))
        log = self.root / 'build.json'
        stub = self.bin / 'project-terminal'
        stub.write_text(f'#!{sys.executable}\nimport json,sys\nfrom pathlib import Path\n'
                        f'Path({str(log)!r}).write_text(json.dumps(sys.argv[1:]))\n')
        stub.chmod(0o755)
        (self.project / 'main.tex').write_text('Source fixture.\n')
        self.assertIn('Reused editor', self.launch('--terminal', '--no-reader'))
        command = json.loads(log.read_text())
        self.assertEqual(command[command.index('--workspace') + 1], 'paired')
        self.assertEqual(command[-3:], ['build', '--watch', 'main.tex'])
        self.assertFalse(self.log.exists())  # No duplicate desktop editor.
        log.unlink()
        (self.project / 'output').mkdir()
        with (self.project / 'output/.main.watch.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.launch('--terminal', '--no-reader')
            self.assertFalse(log.exists())  # Existing watcher remains the only one.


if __name__ == '__main__':
    unittest.main()
