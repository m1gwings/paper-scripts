"""Reveal a new minimized workspace window without activating another app."""
import json
import shutil
import subprocess
import time


def desktop(*args):
    result = subprocess.run(['workspace-desktop', *args], capture_output=True,
                            text=True, check=True, timeout=7)
    return json.loads(result.stdout)


def snapshot():
    if not shutil.which('workspace-desktop'):
        return None
    try:
        state = desktop('info')
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
    deadline = time.monotonic() + 10
    while True:
        windows = [w for w in desktop('info')['windows'] if w['id'] not in existing
                   and w['app_id'] == app_id and w['title'] == title]
        if len(windows) > 1:
            raise ValueError('Multiple new windows match; leave them minimized rather than reveal an unrelated window.')
        if windows:
            return windows[0]['id']
        if time.monotonic() >= deadline:
            return None
        time.sleep(.08)


def reveal(existing, app_id, title, *, focus=False):
    window = wait_new(existing, app_id, title)
    if window is None:
        return False
    present(window, focus=focus)
    return True


def reveal_existing(app_id, title, *, focus=False):
    """Restore one unique window, activating only with explicit focus permission."""
    windows = [w for w in desktop('info')['windows'] if w.get('id')
               and w['app_id'] == app_id
               and (w['title'] == title or w['title'].startswith(title + ' · '))]
    if len(windows) != 1:
        raise ValueError('Cannot identify a unique Editor window to reveal; close duplicate project windows and retry.')
    present(windows[0]['id'], focus=focus)
    return True
