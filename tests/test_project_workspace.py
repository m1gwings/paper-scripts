"""Workspace selection, private runtime state, and literal command launch contracts."""
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('project_workspace', SOURCE / 'lib/project_workspace.py')
WORKSPACE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(WORKSPACE)
spec = importlib.util.spec_from_file_location('workspace_editor_cli', SOURCE / 'lib/workspace_edit.py')
EDITOR = importlib.util.module_from_spec(spec)
spec.loader.exec_module(EDITOR)


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='workspace-control-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, XDG_RUNTIME_DIR=str(self.root))
        self.env.start()
        self.addCleanup(self.env.stop)
        self.project = self.root / 'paper'
        self.project.mkdir()
        self.record = WORKSPACE.prepare(self.project, 'Friendly project name')
        self.record['tabs'] = [{'id': 5, 'title': 'Paper', 'panes': [{'id': 2, 'title': 'Editor'}]}]

    def test_editor_reveal_uses_its_existing_terminal_tab_without_desktop_focus(self):
        editor = dict(project=str(self.project), session=self.record['id'], kitty_window='2', protocol=2)
        with patch.dict(sys.modules, {'project_workspace': WORKSPACE}), \
             patch.object(EDITOR, 'live', return_value=[editor]), \
             patch.object(EDITOR, 'send', return_value={'ok': True}) as send, \
             patch.object(WORKSPACE, 'live_workspaces', return_value=[self.record]), \
             patch.object(WORKSPACE, 'remote', return_value='') as remote, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(EDITOR.run(['view', str(self.project / 'proof.tex'), '--project', str(self.project),
                                         '--line', '42', '--highlight', '--reveal']), 0)
            remote.assert_called_once_with(self.record, 'focus-tab', '--match', 'id:5')
            self.assertTrue(send.call_args.kwargs['highlight'])
            self.assertEqual(send.call_args.args[2], 42)

    def test_old_editor_cannot_silently_ignore_source_link_guards(self):
        editor = dict(project=str(self.project), session=self.record['id'], protocol=1)
        output = io.StringIO()
        with patch.object(EDITOR, 'live', return_value=[editor]), patch.object(EDITOR, 'send') as send, \
             contextlib.redirect_stdout(output):
            self.assertEqual(EDITOR.run([str(self.project / 'proof.tex'), '--project', str(self.project),
                '--if-open', '--if-clean', '--highlight', '--json']), 0)
            send.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['skipped'], 'editor_needs_restart')

    def test_terminal_toggle_retains_processes_and_restores_the_cached_split(self):
        tab = self.record['tabs'][0]
        tab.update(layout='fat', active_window=3, enabled_layouts=['fat:bias=74', 'stack'])
        tab['panes'].append({'id': 3, 'title': 'Shell'})
        with patch.object(WORKSPACE, 'remote') as remote:
            self.assertFalse(WORKSPACE.toggle_terminal(self.record)['terminal_visible'])
            self.assertEqual([c.args[1] for c in remote.call_args_list], ['focus-window', 'goto-layout'])
            self.assertEqual(remote.call_args.args[-1], 'stack')
        tab.update(layout='stack', active_window=2)
        with patch.object(WORKSPACE, 'remote') as remote:
            self.assertTrue(WORKSPACE.toggle_terminal(self.record)['terminal_visible'])
            self.assertEqual(remote.call_args_list[0].args[-1], 'fat:bias=74')
            self.assertEqual(remote.call_args_list[1].args[-1], 'id:3')
        self.assertEqual([p['id'] for p in tab['panes']], [2, 3])

    def test_terminal_toggle_refuses_ambiguous_editors(self):
        self.record['tabs'].append(dict(self.record['tabs'][0], id=6))
        with patch.object(WORKSPACE, 'remote') as remote:
            with self.assertRaisesRegex(ValueError, 'unique Editor'):
                WORKSPACE.toggle_terminal(self.record)
            remote.assert_not_called()

    def test_private_runtime_and_live_listing_strip_environment_and_stale_entries(self):
        WORKSPACE.register(self.record, os.getpid())
        self.assertEqual(WORKSPACE.runtime_directory().stat().st_mode & 0o777, 0o700)
        path = WORKSPACE.runtime_directory() / (self.record['id'] + '.json')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        WORKSPACE.register(WORKSPACE.prepare(self.project, 'Stale'), 999999)
        with socket.socket(socket.AF_UNIX) as endpoint:
            endpoint.bind(self.record['socket'])
            response = [{'tabs': [{'id': 5, 'title': 'Paper', 'windows': [
                {'id': 2, 'title': 'Editor', 'env': {'PRIVATE_VALUE': 'do-not-return'}}]}]}]
            with patch.object(WORKSPACE, 'remote', return_value=json.dumps(response)):
                records = WORKSPACE.live_workspaces()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['tabs'][0]['panes'], [{'id': 2, 'title': 'Editor'}])
        self.assertNotIn('PRIVATE_VALUE', json.dumps(records))
        self.assertNotIn('do-not-return', path.read_text())

    def test_explicit_project_and_ambiguous_window_selection(self):
        self.assertEqual(WORKSPACE.choose([self.record], str(self.project))['id'], self.record['id'])
        second = dict(self.record, id='another')
        with self.assertRaisesRegex(ValueError, 'Multiple workspaces'):
            WORKSPACE.choose([self.record, second], str(self.project))
        self.assertEqual(WORKSPACE.choose([self.record, second], identifier='another')['id'], 'another')
        with self.assertRaisesRegex(ValueError, 'No live managed workspace'):
            WORKSPACE.choose([self.record], str(self.root / 'unrelated'))

    def test_command_arguments_are_literal_and_experiment_cwd_does_not_retarget_window(self):
        experiment = self.root / 'experiment $(touch INJECTED)'
        experiment.mkdir()
        command = ['python3', '-c', 'print("literal `command` and $value")', 'a b', '; touch INJECTED']
        with patch.object(WORKSPACE, 'remote', return_value='42\n') as remote:
            result = WORKSPACE.launch(self.record, title='Experiments', cwd=str(experiment), command=command)
        args = remote.call_args.args
        self.assertEqual(args[0], self.record)
        self.assertIn('id:5', args)
        self.assertEqual(args[args.index('--cwd') + 1], str(experiment))
        self.assertEqual(list(args[-len(command):]), command)
        self.assertIn('"$@"', args[args.index('-ic') + 1])
        self.assertEqual(result['window_id'], 42)
        self.assertFalse((experiment / 'INJECTED').exists())

    def test_split_is_explicit_and_cannot_target_an_unrelated_tab(self):
        with patch.object(WORKSPACE, 'remote', return_value='43') as remote:
            WORKSPACE.launch(self.record, title='SSH', split=True, keep_focus=True)
            args = remote.call_args.args
            self.assertEqual(args[args.index('--type') + 1], 'window')
            self.assertIn('--keep-focus', args)
            self.assertNotIn('--tab-title', args)
        with self.assertRaisesRegex(ValueError, 'does not belong'):
            WORKSPACE.launch(self.record, title='SSH', tab=999)

    def test_runtime_symlink_and_invalid_input_are_rejected(self):
        runtime = WORKSPACE.runtime_directory()
        runtime.rmdir()
        runtime.symlink_to(self.project, target_is_directory=True)
        with self.assertRaises(ValueError):
            WORKSPACE.runtime_directory()
        with self.assertRaises(ValueError):
            WORKSPACE.launch(self.record, title='Wrong\nTitle')
        with self.assertRaisesRegex(ValueError, 'Not a directory'):
            WORKSPACE.launch(self.record, title='Shell', cwd=self.project / 'missing')


if __name__ == '__main__':
    unittest.main()
