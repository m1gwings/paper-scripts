#!/usr/bin/env -S python3 -I -S
"""Micro's project hook, `$WORKSPACE_EDITOR_PROJECT_HOOK`, called in the background:

    HOOK ROOT           the active tab's project changed (empty ROOT: a Loose file)
    HOOK --opened ROOT  the project gained its first tab
    HOOK --closed ROOT  the project lost its last tab (Micro has already asked)
    HOOK --busy ROOT    print what runs in the project's shell or task tabs, if anything

It speaks Kitty's remote-control protocol on the Editor's socket directly, without
spawning a client, and runs one in-process kitten (editor_shells.py), so a
project switch is a single redraw.
"""
import json
import os
import socket
import sys

HERE = os.path.dirname(os.path.realpath(__file__))


def call(address, *args):
    command = {'cmd': 'kitten', 'version': [0, 51, 0], 'no_response': False,
               'payload': {'kitten': os.path.join(HERE, 'editor_shells.py'), 'args': list(args)}}
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(5)
        connection.connect(address)
        connection.sendall(b'\x1bP@kitty-cmd' + json.dumps(command).encode() + b'\x1b\\')
        data = b''
        while not data.endswith(b'\x1b\\'):
            chunk = connection.recv(65536)
            if not chunk:
                break
            data += chunk
    reply = json.loads(data[len(b'\x1bP@kitty-cmd'):-2] or b'{}')
    if not reply.get('ok'):
        raise ValueError(reply.get('error') or 'The Editor rejected the project change.')
    return json.loads(reply.get('data') or '{}')


def watch(action, root):
    """Register or unregister the project with the shared build watcher (no-op outside LaTeX)."""
    import subprocess
    paper = os.path.join(os.path.dirname(HERE), 'paper')
    pid = os.environ.get('KITTY_PID', '') if action == 'register' else ''
    try:
        subprocess.Popen([paper, 'watch', action, root, '--client', 'editor', *(['--pid', pid] if pid else [])],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def main(argv):
    flag = argv[0] if argv[:1] and argv[0] in ('--opened', '--closed', '--busy') else ''
    rest = argv[1:] if flag else argv
    if len(rest) != 1 or (rest[0] and not os.path.isabs(rest[0])) or (flag and not rest[0]):
        print('usage: editor_hook.py [--opened|--closed|--busy] ROOT (absolute; empty for Loose)', file=sys.stderr)
        return 2
    root = os.path.realpath(rest[0]) if rest[0] else ''
    address = os.environ.get('KITTY_LISTEN_ON', '')
    if not address.startswith('unix:'):
        runtime = os.environ.get('XDG_RUNTIME_DIR') or f'/tmp/project-workspaces-{os.getuid()}'
        address = 'unix:' + os.path.join(runtime, 'project-workspaces', 'editor.sock')
    address = address[len('unix:'):]
    if flag == '--busy':
        text = call(address, 'busy', root).get('text', '')
        if text:
            print(text)
        return 0
    if flag == '--closed':
        call(address, 'close', root, '--force')
        watch('unregister', root)
        return 0
    result = call(address, 'prepare' if flag else 'activate', root)
    if flag or result.get('started_shell'):
        watch('register', root)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except (OSError, ValueError) as error:
        print(f'editor_hook: {error}', file=sys.stderr)
        sys.exit(1)
