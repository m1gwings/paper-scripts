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
