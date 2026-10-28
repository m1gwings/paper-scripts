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


def reveal(existing, app_id, title):
    if existing is None:
        return False
    deadline = time.monotonic() + 3
    while True:
        windows = [w for w in desktop('info')['windows'] if w['id'] not in existing
                   and w['app_id'] == app_id and w['title'] == title]
        if len(windows) > 1:
            raise ValueError('Multiple new windows match; leave them minimized rather than reveal an unrelated window.')
        if windows:
            desktop('reveal', '--window', windows[0]['id'])
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(.08)
