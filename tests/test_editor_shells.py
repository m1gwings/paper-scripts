"""Single Editor: project shells, hook protocol, routing and grouping.

The Kitty integration test needs a headless X display; set
WORKSPACE_KITTY_TEST_DISPLAY (for example a private Xvfb `:93`) to run it.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'lib'))
import project_open  # noqa: E402
import project_workspace  # noqa: E402
import workspace_edit  # noqa: E402


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SHELLS = load('editor_shells_under_test', SOURCE / 'lib/editor_shells.py')
HOOK = load('editor_hook_under_test', SOURCE / 'lib/editor_hook.py')


class FakeWindow:
    def __init__(self, **user_vars):
        self.user_vars = dict(user_vars)


class FakeTab:
    def __init__(self, *windows):
        self.list = list(windows)
        self.windows = SimpleNamespace(iter_tab_windows=lambda: iter(self.list))


class FakeManager:
    def __init__(self, *tabs, active=0):
        self.tabs = list(tabs)
        self.active_tab_idx = active

    def __iter__(self):
        return iter(self.tabs)

    def swap_tabs(self, a, b):
        self.tabs[a], self.tabs[b] = self.tabs[b], self.tabs[a]

    def _set_active_tab(self, index, store_in_history=True):
        self.active_tab_idx = index


class GroupingTest(unittest.TestCase):
    def test_new_task_tab_joins_the_end_of_its_group_and_keeps_the_active_tab(self):
        editor = FakeTab(FakeWindow(workspace_role='editor'), FakeWindow(workspace_project='/a'))
        build_a, build_b = FakeTab(FakeWindow(workspace_project='/a')), FakeTab(FakeWindow(workspace_project='/b'))
        manager = FakeManager(editor, build_a, build_b, active=2)
        # The Editor tab hosts every project's shell; it never anchors a group.
        self.assertEqual(SHELLS.group_end(manager, '/a', editor), 2)
        self.assertIsNone(SHELLS.group_end(manager, '/c', editor))
        created_tab = SimpleNamespace(set_title=lambda title: None)
        with mock.patch.dict(sys.modules, {'kitty.tabs': SimpleNamespace(Tab=lambda *a, **k: created_tab)}):
            manager.mark_tab_bar_dirty = lambda: None
            tab = SHELLS.new_tab(manager, 'Experiments', 2)
        self.assertEqual(manager.tabs.index(tab), 2)
        self.assertIs(manager.tabs[manager.active_tab_idx], build_b)

    def test_parked_panes_never_anchor_a_group(self):
        parked = FakeTab(FakeWindow(workspace_project='/a', workspace_parked='1'))
        manager = FakeManager(FakeTab(FakeWindow(workspace_role='editor')), parked)
        self.assertIs(SHELLS.park_tab(manager), parked)
        self.assertIsNone(SHELLS.group_end(manager, '/a'))

    def test_names_follow_project_metadata_and_are_cached_per_editor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'stopped_ranking'
            (root / '.paper').mkdir(parents=True)
            cache = {}
            self.assertEqual(SHELLS.display_name(str(root), cache=cache), 'Stopped Ranking')
            (root / '.paper/config.json').write_text(json.dumps({'project_name': 'Renamed'}))
            self.assertEqual(SHELLS.display_name(str(root), cache=cache), 'Stopped Ranking')
            self.assertEqual(SHELLS.display_name(str(root), 'Explicit', cache), 'Explicit')
            self.assertEqual(cache[str(root)], 'Explicit')

    def test_kitten_rejects_unknown_actions(self):
        with self.assertRaisesRegex(ValueError, 'Usage'):
            SHELLS.run(['swap', '/a'], SimpleNamespace(window_id_map={}))


class HookTest(unittest.TestCase):
    def serve(self, address, replies):
        received = []
        server = socket.socket(socket.AF_UNIX)
        server.bind(address)
        server.listen()

        def loop():
            for reply in replies:
                connection, _ = server.accept()
                data = b''
                while not data.endswith(b'\x1b\\'):
                    data += connection.recv(65536)
                received.append(json.loads(data[len(b'\x1bP@kitty-cmd'):-2]))
                connection.sendall(b'\x1bP@kitty-cmd' + json.dumps(
                    {'ok': True, 'data': json.dumps(reply)}).encode() + b'\x1b\\')
                connection.close()
            server.close()
        thread = threading.Thread(target=loop)
        thread.start()
        return received, thread

    def test_hook_forms_use_one_in_process_kitten_call_each(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as temp:
            address = os.path.join(temp, 'k.sock')
            replies = [{'ok': True, 'started_shell': True}, {'ok': True}, {'ok': True, 'text': 'Shell: sleep 9'},
                       {'ok': True}, {'ok': True}]
            received, thread = self.serve(address, replies)
            output = io.StringIO()
            with mock.patch.dict(os.environ, KITTY_LISTEN_ON='unix:' + address), \
                    mock.patch.object(HOOK, 'watch') as watch, contextlib.redirect_stdout(output):
                self.assertEqual(HOOK.main([temp]), 0)
                self.assertEqual(HOOK.main(['']), 0)
                self.assertEqual(HOOK.main(['--busy', temp]), 0)
                self.assertEqual(HOOK.main(['--opened', temp]), 0)
                self.assertEqual(HOOK.main(['--closed', temp]), 0)
            thread.join(5)
        root = os.path.realpath(temp)
        self.assertEqual([r['payload']['args'] for r in received],
                         [['activate', root], ['activate', ''], ['busy', root], ['prepare', root],
                          ['close', root, '--force']])
        self.assertTrue(all(r['cmd'] == 'kitten' and r['payload']['kitten'].endswith('editor_shells.py')
                            for r in received))
        self.assertEqual(output.getvalue(), 'Shell: sleep 9\n')
        self.assertEqual([c.args for c in watch.call_args_list],
                         [('register', root), ('register', root), ('unregister', root)])

    def test_hook_rejects_relative_roots_and_unknown_flags(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(HOOK.main(['relative']), 2)
            self.assertEqual(HOOK.main(['--opened', '']), 2)
            self.assertEqual(HOOK.main(['--bogus', '/x']), 2)


class RoutingTest(unittest.TestCase):
    def setUp(self):
        # Keep loose-file fixtures outside any repository surrounding TMPDIR.
        self.tmp = tempfile.TemporaryDirectory(dir=Path.home(), prefix='.editor-routing-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.env = mock.patch.dict(os.environ, XDG_RUNTIME_DIR=str(self.root), XDG_CACHE_HOME=str(self.root / 'cache'))
        self.env.start()
        self.addCleanup(self.env.stop)
        self.paper = self.root / 'paper'
        (self.paper / 'sub').mkdir(parents=True)
        (self.paper / '.git').mkdir()
        self.single = {'id': 'editor', 'root': '', 'name': 'Editor', 'single': True,
                       'socket': '', 'projects': [str(self.paper)]}

    def test_project_root_prefers_the_deepest_registered_root(self):
        nested = self.paper / 'sub'
        (self.root / 'cache/workspace').mkdir(parents=True)
        (self.root / 'cache/workspace/project-roots.json').write_text(json.dumps(
            {'version': 1, 'roots': [{'root': str(self.paper)}, {'root': str(nested)}]}))
        self.assertEqual(project_workspace.project_root(nested / 'file.tex'), str(nested))
        (self.root / 'cache/workspace/project-roots.json').unlink()
        self.assertEqual(project_workspace.project_root(nested / 'file.tex'), str(self.paper))
        self.assertIsNone(project_workspace.project_root(self.root / 'loose.txt'))

    def test_home_and_filesystem_root_never_claim_loose_files(self):
        (self.root / '.git').mkdir()
        cache = self.root / 'cache/workspace'
        cache.mkdir(parents=True)
        (cache / 'project-roots.json').write_text(json.dumps({
            'roots': [{'root': str(self.root)}, {'root': '/'}]}))
        with mock.patch.object(Path, 'home', return_value=self.root):
            self.assertIsNone(project_workspace.project_root(self.root / 'loose.txt'))
            self.assertEqual(project_workspace.project_root(self.paper / 'main.tex'), str(self.paper))

    def test_task_terminals_target_the_single_editor_unless_only_a_legacy_window_has_the_project(self):
        legacy = {'id': 'old', 'root': str(self.paper), 'name': 'Paper'}
        chosen = project_workspace.choose([legacy, self.single], str(self.paper))
        self.assertEqual((chosen['id'], chosen['root']), ('editor', str(self.paper)))
        self.single['projects'] = []
        self.assertEqual(project_workspace.choose([legacy, self.single], str(self.paper))['id'], 'old')
        other = self.root / 'other'
        other.mkdir()
        self.assertEqual(project_workspace.choose([legacy, self.single], str(other))['root'], str(other))
        self.assertEqual(project_workspace.choose([legacy, self.single], identifier='old')['id'], 'old')

    def test_single_editor_task_is_one_grouped_kitten_call_with_a_literal_command(self):
        record = dict(self.single, root=str(self.paper))
        with mock.patch.object(project_workspace, 'remote', return_value=json.dumps(
                {'ok': True, 'window_id': 9})) as remote:
            result = project_workspace.launch(record, title='Experiments', command=['./run.sh', 'a b'])
        args = remote.call_args.args
        self.assertEqual(args[1:4], ('kitten', str(SOURCE / 'lib/editor_shells.py'), 'task'))
        spec = json.loads(args[4])
        self.assertEqual((spec['root'], spec['title'], spec['kind'], spec['focus']),
                         (str(self.paper), 'Experiments', 'tab', False))
        self.assertEqual(spec['command'][-2:], ['./run.sh', 'a b'])
        self.assertEqual(result['window_id'], 9)
        with self.assertRaisesRegex(ValueError, 'omit --tab'):
            project_workspace.launch(record, title='Build', tab=3)

    def test_opens_go_to_the_single_editor_and_legacy_editors_keep_their_explicit_sessions(self):
        single = {'session': 'editor', 'project': str(self.paper), 'files': []}
        legacy = {'session': 'old', 'project': str(self.paper), 'files': [str(self.paper / 'main.tex')]}
        args = SimpleNamespace(new=False, navigation=False, if_open=False)
        file = [self.paper / 'main.tex']
        self.assertEqual(workspace_edit.select([legacy, single], str(self.paper), None, 'open', file, args), [single])
        self.assertEqual(workspace_edit.select([legacy], str(self.paper), None, 'open', file, args), [])
        self.assertEqual(workspace_edit.select([legacy, single], str(self.paper), 'old', 'open', file, args), [legacy])
        self.assertEqual(workspace_edit.select([legacy, single], str(self.paper), None, 'status', file, args), [legacy])
        args.navigation = True
        self.assertEqual(workspace_edit.select([legacy], str(self.paper), None, 'open', file, args), [legacy])

    def test_show_project_without_an_editor_is_a_quiet_no_op(self):
        output = io.StringIO()
        with mock.patch.object(project_workspace, 'editor_record', return_value=None), \
                contextlib.redirect_stdout(output):
            self.assertEqual(workspace_edit.run(['show-project', str(self.paper)]), 0)
        self.assertEqual(json.loads(output.getvalue())['skipped'], 'not_running')
        # workspace-focus detects support from the help text.
        self.assertIn('show-project', subprocess.run([sys.executable, str(SOURCE / 'lib/workspace_edit.py'), '--help'],
                                                     capture_output=True, text=True).stdout)

    def test_show_project_forwards_to_micro_and_swaps_the_shell(self):
        micro = {'session': 'editor', 'project': str(self.paper)}
        with mock.patch.object(project_workspace, 'editor_record', return_value=self.single), \
                mock.patch.object(project_workspace, 'activate', return_value={'ok': True}) as activate, \
                mock.patch.object(workspace_edit, 'live', return_value=[micro]), \
                mock.patch.object(workspace_edit, 'send', return_value={'ok': True}) as send, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(workspace_edit.run(['show-project', str(self.paper)]), 0)
        send.assert_called_once_with(micro, str(self.paper), action='show-project')
        activate.assert_called_once_with(self.single, self.paper)

    def test_show_project_leaves_the_shell_when_micro_rejects_the_switch(self):
        micro = {'session': 'editor', 'project': str(self.paper)}
        with mock.patch.object(project_workspace, 'editor_record', return_value=self.single), \
                mock.patch.object(project_workspace, 'activate') as activate, \
                mock.patch.object(workspace_edit, 'live', return_value=[micro]), \
                mock.patch.object(workspace_edit, 'send', side_effect=ValueError('Editor did not acknowledge')):
            with self.assertRaisesRegex(ValueError, 'did not acknowledge'):
                workspace_edit.run(['show-project', str(self.paper)])
            activate.assert_not_called()

    def test_opening_a_folder_switches_the_existing_editor(self):
        micro = {'session': 'editor', 'project': str(self.paper)}
        with mock.patch.object(project_workspace, 'editor_record', return_value=self.single), \
                mock.patch.object(project_workspace, 'activate') as activate, \
                mock.patch.object(workspace_edit, 'live', return_value=[micro]), \
                mock.patch.object(workspace_edit, 'send', return_value={'ok': True}) as send:
            self.assertEqual(workspace_edit.run([str(self.paper)]), 0)
            send.assert_called_once_with(micro, str(self.paper), action='show-project')
            activate.assert_called_once_with(self.single, str(self.paper))

    def test_single_editor_presents_without_falling_through_to_legacy_controls(self):
        micro = {'session': 'editor', 'project': str(self.paper), 'protocol': 4}
        for flag in ('--focus', '--reveal'):
            with self.subTest(flag=flag), mock.patch.object(workspace_edit, 'live', return_value=[micro]), \
                    mock.patch.object(workspace_edit, 'send', return_value={'ok': True}), \
                    mock.patch.object(workspace_edit, 'reveal_single') as reveal:
                self.assertEqual(workspace_edit.run(['view', str(self.paper / 'main.tex'), flag]), 0)
                reveal.assert_called_once_with(micro, focus=flag == '--focus')

    def test_startup_session_marks_every_pane_and_quotes_paths(self):
        project = self.root / 'a b $(x)'
        (project / '.paper').mkdir(parents=True)
        (project / '.paper/config.json').write_text('{}')
        session = project_open.single_session(str(project), 'A B', [str(project / 'main.tex')], 4, 2)
        import shlex
        lines = [shlex.split(line) for line in session.splitlines()]
        launches = [line for line in lines if line[0] == 'launch']
        self.assertEqual([l[l.index('--title') + 1] for l in launches], ['Editor', 'Shell', 'Build'])
        self.assertIn('workspace_role=editor', launches[0])
        self.assertNotIn(f'workspace_project={project}', launches[0])  # Micro serves every project.
        self.assertTrue(all(f'workspace_project={project}' in l for l in launches[1:]))
        self.assertEqual(launches[0][-2:], ['+4:2', str(project / 'main.tex')])
        self.assertEqual(launches[2][-1], str(project / 'output/.latex/.watch.log'))


KITTY = shutil.which('workspace-kitty') or shutil.which('kitty')


@unittest.skipUnless(os.environ.get('WORKSPACE_KITTY_TEST_DISPLAY') and KITTY, 'needs a headless X display')
class KittyIntegrationTest(unittest.TestCase):
    """Real swaps in a private Kitty on a headless display (never the user's session)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.projects = [root / name for name in ('alpha', 'beta')]
        for project in self.projects:
            (project / '.paper').mkdir(parents=True)
            (project / '.paper/config.json').write_text('{}')
        self.socket = str(root / 'k.sock')
        env = {key: value for key, value in os.environ.items() if not key.startswith(('KITTY_', 'WAYLAND'))}
        env.update(DISPLAY=os.environ['WORKSPACE_KITTY_TEST_DISPLAY'], XDG_CONFIG_HOME=str(root / 'config'),
                   XDG_CACHE_HOME=str(root / 'cache'), KITTY_CONFIG_DIRECTORY=str(root / 'config'))
        (root / 'config').mkdir()
        command = [KITTY, '--listen-on', 'unix:' + self.socket, '-o', 'linux_display_server=x11',
                   '--title', 'Editor — Alpha', '--session', '-']
        for override in project_open.KITTY_OVERRIDES + project_open.SINGLE_KITTY_OVERRIDES:
            command += ['--override', override]
        self.kitty = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, env=env, text=True, start_new_session=True)
        session = project_open.single_session(str(self.projects[0]), 'Alpha').replace('micro', 'cat')
        self.kitty.stdin.write(session)
        self.kitty.stdin.close()
        self.addCleanup(self.close)
        deadline = time.monotonic() + 10
        while not Path(self.socket).is_socket():
            self.assertLess(time.monotonic(), deadline, 'Kitty did not start')
            time.sleep(.05)
        self.env = mock.patch.dict(os.environ, KITTY_LISTEN_ON='unix:' + self.socket)
        self.env.start()
        self.addCleanup(self.env.stop)

    def close(self):
        self.kitty.terminate()
        try:
            self.kitty.wait(5)
        except subprocess.TimeoutExpired:
            self.kitty.kill()

    def tabs(self):
        result = subprocess.run([KITTY, '@', '--to', 'unix:' + self.socket, 'ls'], capture_output=True, text=True)
        return [(t['title'], t['is_active'], [w['user_vars'].get('workspace_project', '') for w in t['windows']])
                for o in json.loads(result.stdout) for t in o['tabs']]

    def test_swaps_park_shells_invisibly_and_keep_groups(self):
        alpha, beta = map(str, self.projects)
        with mock.patch.object(HOOK, 'watch'):
            first = HOOK.call(self.socket, 'activate', beta)
            self.assertTrue(first['started_shell'])
            timings = [HOOK.call(self.socket, 'activate', root)['ms'] for root in (alpha, beta) * 5]
        self.assertLess(max(timings), 100)
        tabs = self.tabs()
        self.assertEqual([t[0] for t in tabs], ['Editor', 'Build', 'Parked shells', 'Build'])
        self.assertEqual(tabs[0][1:], (True, ['', beta]))
        self.assertEqual(tabs[2][2], [alpha])
        self.assertEqual(HOOK.call(self.socket, 'busy', alpha)['busy'], [])
        HOOK.call(self.socket, 'close', alpha, '--force')
        time.sleep(.3)
        self.assertNotIn(alpha, [p for t in self.tabs() for p in t[2]])


if __name__ == '__main__':
    unittest.main()
