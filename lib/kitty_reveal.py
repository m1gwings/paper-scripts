"""Reveal a Kitty tab without activating its desktop window (no terminal UI)."""
from kittens.tui.handler import result_handler


def main(args):
    pass


@result_handler(no_ui=True)
def handle_result(args, answer, target_window_id, boss):
    window = boss.window_id_map.get(target_window_id)
    tab = window.tabref() if window else None
    if tab is None:
        raise ValueError('The requested Editor pane is no longer available.')
    manager = boss.os_window_map.get(window.os_window_id)
    if manager is None:
        raise ValueError('The requested Editor window is no longer available.')
    # focus-tab calls Boss.set_active_window(switch_os_window_if_needed=True).
    # Address this window's tab manager directly, without desktop activation.
    manager.set_active_tab(tab)
    return True
