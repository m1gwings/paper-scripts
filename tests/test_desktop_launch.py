"""Passive launch identity and pre-map hints; no desktop/input automation."""
import ctypes
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, SOURCE / 'lib' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


DESKTOP = module('desktop_launch')
KITTY = module('kitty_passive')


class PassiveLaunchTest(unittest.TestCase):
    def test_reveal_targets_only_the_new_window_even_with_the_same_title(self):
        windows = [{'id': identity, 'app_id': 'workspace-editor', 'title': 'Editor'} for identity in ('old', 'new')]
        with patch.object(DESKTOP, 'desktop', side_effect=[{'windows': windows}, {'ok': True}]) as call:
            self.assertTrue(DESKTOP.reveal({'old'}, 'workspace-editor', 'Editor'))
        self.assertEqual(call.call_args.args, ('reveal', '--window', 'new'))

    def test_ambiguous_reveal_leaves_windows_minimized(self):
        windows = [{'id': identity, 'app_id': 'workspace-editor', 'title': 'Editor'} for identity in ('one', 'two')]
        with patch.object(DESKTOP, 'desktop', return_value={'windows': windows}) as call:
            with self.assertRaisesRegex(ValueError, 'Multiple new windows'):
                DESKTOP.reveal(set(), 'workspace-editor', 'Editor')
            call.assert_called_once_with('info')

    def test_reused_window_is_unminimized_without_activation(self):
        windows=[{'id':'target','app_id':'workspace-editor','title':'Editor — Example · Paper'}]
        with patch.object(DESKTOP,'desktop',side_effect=[{'windows':windows},{'ok':True}]) as call:
            self.assertTrue(DESKTOP.reveal_existing('workspace-editor','Editor — Example'))
        self.assertEqual(call.call_args.args,('reveal','--window','target'))

    def test_duplicate_reused_windows_are_not_guessed(self):
        windows=[{'id':identity,'app_id':'workspace-editor','title':'Editor — Example'} for identity in ('one','two')]
        with patch.object(DESKTOP,'desktop',return_value={'windows':windows}) as call:
            with self.assertRaisesRegex(ValueError,'unique Editor'):
                DESKTOP.reveal_existing('workspace-editor','Editor — Example')
            call.assert_called_once_with('info')

    def test_explicit_open_reveals_before_activating_the_same_window(self):
        windows = [{'id': 'target', 'app_id': 'workspace-editor', 'title': 'Editor — Example'}]
        with patch.object(DESKTOP, 'desktop', side_effect=[{'windows': windows}, {'ok': True}, {'ok': True}]) as call:
            self.assertTrue(DESKTOP.reveal_existing('workspace-editor', 'Editor — Example', focus=True))
        self.assertEqual([c.args for c in call.call_args_list], [
            ('info',), ('reveal', '--window', 'target'), ('focus', '--window', 'target')])

    def test_failed_reveal_is_reported_without_activation(self):
        windows = [{'id': 'target', 'app_id': 'workspace-editor', 'title': 'Editor'}]
        with patch.object(DESKTOP, 'desktop', side_effect=[{'windows': windows}, {'ok': False}]) as call:
            with self.assertRaisesRegex(ValueError, 'could not reveal'):
                DESKTOP.reveal(set(), 'workspace-editor', 'Editor', focus=True)
        self.assertEqual(call.call_count, 2)

    def test_slow_editor_can_map_after_the_old_three_second_budget(self):
        windows = [{'id': 'late', 'app_id': 'workspace-editor', 'title': 'Editor'}]
        with patch.object(DESKTOP.time, 'monotonic', side_effect=[0, 4]), \
                patch.object(DESKTOP.time, 'sleep'), \
                patch.object(DESKTOP, 'desktop', side_effect=[{'windows': []}, {'windows': windows}, {'ok': True}]):
            self.assertTrue(DESKTOP.reveal(set(), 'workspace-editor', 'Editor'))

    def test_initial_minimized_hint_preserves_input_and_icon_settings(self):
        hints = KITTY.WMHints(flags=1 | 4, input=1, initial_state=1, icon_pixmap=99)
        library = Mock()
        library.XOpenDisplay.return_value = 123
        library.XGetWMHints.return_value = ctypes.pointer(hints)
        with patch.object(KITTY.C, 'CDLL', return_value=library):
            KITTY.before_show(456)
        self.assertEqual(hints.flags, 1 | 2 | 4)
        self.assertEqual(hints.initial_state, 3)
        self.assertEqual(hints.input, 1)
        self.assertEqual(hints.icon_pixmap, 99)
        self.assertEqual(library.XSetWMHints.call_args.args[:2], (123, 456))
        library.XSync.assert_called_once_with(123, 0)
        library.XCloseDisplay.assert_called_once_with(123)
