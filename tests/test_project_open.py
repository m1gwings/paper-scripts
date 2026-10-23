"""Exercise the public launchers without opening desktop applications."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


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
    'NO_COLOR': os.environ.get('NO_COLOR'), 'CODEX_CI': os.environ.get('CODEX_CI')
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
        self.assertIn('layout tall:bias=72', data['session'])
        self.assertIn('launch --title Shell', data['session'])
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
        self.launch('--terminal', script=runtime / 'paper')
        self.assertEqual(self.record()['program'], 'kitty')

    def test_terminal_startup_failure_is_reported(self):
        (self.bin / 'kitty').write_text('#!/bin/sh\necho "Unsupported layout" >&2\nexit 3\n')
        output = self.launch('--terminal', ok=False)
        self.assertIn('Unsupported layout', output)
        self.assertIn('Kitty startup log:', output)


if __name__ == '__main__':
    unittest.main()
