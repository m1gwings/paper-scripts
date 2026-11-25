"""Reveal a new minimized workspace window without activating another app."""
import json
import shutil
import subprocess
import time


WINDOW_MAP_TIMEOUT = 20


def desktop(*args):
    result = subprocess.run(['workspace-desktop', *args], capture_output=True,
                            text=True, check=True, timeout=7)
    return json.loads(result.stdout)


def snapshot():
    if not shutil.which('workspace-desktop'):
        return None
    try:
        state = desktop('info', '--no-focus')
        if 4 in state.get('capabilities', []):
            return {w['id'] for w in state['windows']}
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def present(window, *, focus=False):
    """Unminimize an exact window; activate only for an explicit user request."""
    if not desktop('reveal', '--window', window).get('ok'):
        raise ValueError('The desktop could not reveal the Editor window.')
    if focus and not desktop('focus', '--window', window).get('ok'):
        raise ValueError('The desktop could not activate the Editor window.')


def wait_new(existing, app_id, title):
    """Wait for an exact newly mapped window without revealing or activating it."""
    if existing is None:
        return None
    started = time.monotonic()
    deadline = started + WINDOW_MAP_TIMEOUT
    while True:
        windows = [w for w in desktop('info', '--no-focus')['windows'] if w.get('id') and w['id'] not in existing
                   and w['app_id'] == app_id and w['title'] == title]
        if len(windows) > 1:
            raise ValueError('Multiple new windows match; leave them minimized rather than reveal an unrelated window.')
        if windows:
            return windows[0]['id']
        now = time.monotonic()
        if now >= deadline:
            return None
        elapsed = now - started
        time.sleep(.01 if elapsed < .5 else (.03 if elapsed < 2.0 else .08))


def reveal(existing, app_id, title, *, focus=False):
    window = wait_new(existing, app_id, title)
    if window is None:
        return False
    present(window, focus=focus)
    return True


def existing_window(app_id, title):
    """Resolve one exact identity without probing unrelated keyboard focus."""
    windows = [w for w in desktop('info', '--no-focus')['windows'] if w.get('id')
               and w['app_id'] == app_id
               and (w['title'] == title or w['title'].startswith(title + ' · '))]
    if len(windows) != 1:
        raise ValueError('Cannot identify a unique Editor window to reveal; close duplicate project windows and retry.')
    return windows[0]['id']


def reveal_existing(app_id, title, *, focus=False):
    """Restore one unique window, activating only with explicit focus permission."""
    window = existing_window(app_id, title)
    present(window, focus=focus)
    return window


def single_window(title, remembered=None):
    """The single Editor's desktop window: its remembered ID, else the one exact title.

    Per-project Editors of older releases share the app ID and may share a title
    prefix until they close, so titles alone never select among several windows.
    """
    windows = [w for w in desktop('info', '--no-focus')['windows'] if w.get('id') and w['app_id'] == 'workspace-editor']
    if remembered and any(w['id'] == remembered for w in windows):
        return remembered
    exact = [w['id'] for w in windows if w['title'] == title]
    if len(exact) != 1:
        raise ValueError('Cannot identify the Editor window to reveal; close older per-project Editors and retry.')
    return exact[0]
