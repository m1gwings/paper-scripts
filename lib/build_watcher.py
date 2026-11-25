"""One per-user build watcher for every LaTeX project open in Editor or Reader.

Clients register project roots over a private Unix socket; the daemon starts on
the first registration and exits when no project remains. Each build runs as a
`build.py build SOURCE` child in its project, so outputs, logs and status files
are exactly those of `paper build`, a failure stays inside its project, and
different projects build concurrently while each project's builds are serialized.
"""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import time

PROTOCOL = 1
POLL_INTERVAL = .5      # dependency stamps of tracked documents
SCAN_INTERVAL = 2.      # document discovery, watch-lock retries, client liveness
STARTUP_GRACE = 10.     # a daemon nobody registers with exits
CONNECT_TIMEOUT = 5.
LOG_LIMIT = 1 << 20
LIB = Path(__file__).resolve().parent
RUNTIME_FILES = ('build_watcher.py', 'build.py', 'tex_environment.py', 'overleaf_build.py')


def runtime_directory():
    base = os.environ.get('XDG_RUNTIME_DIR')
    directory = Path(base) / 'paper' if base else Path(f'/tmp/paper-{os.getuid()}')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = directory.lstat()
    if info.st_uid != os.getuid() or not directory.is_dir() or directory.is_symlink():
        raise OSError(f'Unsafe watcher directory: {directory}')
    if info.st_mode & 0o077:
        directory.chmod(0o700)
    return directory


def socket_path():
    return runtime_directory() / 'watch.sock'


def daemon_log():
    state = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'paper'
    state.mkdir(parents=True, exist_ok=True)
    return state / 'watch.log'


def open_log(path):
    """Append to a bounded log: start afresh once it exceeds LOG_LIMIT."""
    try:
        large = path.stat().st_size > LOG_LIMIT
    except FileNotFoundError:
        large = False
    return path.open('w' if large else 'a')


def process_fields(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    except (OSError, IndexError):
        return None


def process_start(pid):
    fields = process_fields(pid)
    return fields[19] if fields else None


def process_alive(pid, start):
    """Alive and the same process: a reused PID or an unreaped zombie is gone."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    fields = process_fields(pid)
    if fields is None:
        return start is None
    return fields[0] != 'Z' and (start is None or fields[19] == start)


# Client side ----------------------------------------------------------------

def project_root(directory):
    """The Git top level that `paper build` uses, or None."""
    if directory.is_file():
        directory = directory.parent
    try:
        result = subprocess.run(['git', '-C', str(directory), 'rev-parse', '--show-toplevel'],
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(result.stdout.removesuffix('\n')).resolve() if not result.returncode else None


@contextmanager
def inside(directory):
    previous = os.getcwd()
    os.chdir(directory)
    try:
        yield
    finally:
        os.chdir(previous)


def is_latex_project(root):
    if (root / '.paper/config.json').is_file():
        return True
    sys.path.insert(0, str(LIB))
    import build
    with inside(root):
        return bool(build.find_project_roots(root))


def exchange(message, spawn=False):
    """Send one request; start the daemon when asked and none is listening."""
    path = socket_path()
    started, spawned = None, 0
    deadline = time.monotonic() + CONNECT_TIMEOUT
    while True:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(CONNECT_TIMEOUT)
                connection.connect(str(path))
                connection.sendall(json.dumps(message).encode() + b'\n')
                data = b''
                while not data.endswith(b'\n'):
                    chunk = connection.recv(65536)
                    if not chunk:
                        raise ConnectionResetError('watcher closed the connection')
                    data += chunk
                return json.loads(data)
        except (FileNotFoundError, ConnectionRefusedError, ConnectionResetError, BrokenPipeError):
            if not spawn:
                return None
            if time.monotonic() > deadline:
                raise OSError('The build watcher did not start; see ' + str(daemon_log()))
            if spawned < 3 and (started is None or started.poll() is not None):
                spawned += 1
                environment = {k: v for k, v in os.environ.items() if not k.startswith('PROJECT_WORKSPACE_')}
                with open_log(daemon_log()) as log:
                    started = subprocess.Popen([sys.executable, str(LIB / 'build_watcher.py'), 'serve'],
                                               stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                               cwd='/', env=environment, start_new_session=True)
            time.sleep(.02)


def register(directory, client='cli', pid=None):
    """Register a project root; returns the daemon's reply (watched or not)."""
    root = project_root(Path(directory).expanduser())
    if root is None:
        return dict(ok=True, watched=False, root=str(directory), reason='not a Git repository')
    if not is_latex_project(root):
        return dict(ok=True, watched=False, root=str(root), reason='no LaTeX documents')
    return exchange(dict(protocol=PROTOCOL, op='register', root=str(root), client=client, pid=pid,
                         start=process_start(pid) if pid else None, runtime=str(LIB)), spawn=True)


def unregister(directory, client='cli', everyone=False):
    directory = Path(directory).expanduser()
    root = project_root(directory) or directory.resolve()
    reply = exchange(dict(protocol=PROTOCOL, op='unregister', root=str(root), client=client, all=everyone))
    return reply or dict(ok=True, root=str(root), watched=False)


# Daemon ---------------------------------------------------------------------

def say(*parts):
    print(time.strftime('%Y-%m-%d %H:%M:%S'), *parts, flush=True)


class Project:
    def __init__(self, root, runtime):
        self.root = Path(root)
        self.runtime = runtime
        self.clients = {}           # name -> [pid, start] or None
        self.lock = None            # output/.latex/.project.watch.lock
        self.source_locks = {}
        self.tracked = {}           # source -> out, pdf, previous dependency stamps
        self.skipped = set()
        self.child = None
        self.child_source = None
        self.before = None
        self.next_scan = 0.
        self.state = 'starting'
        self.error = ''

    def record(self):
        return dict(root=str(self.root), clients=sorted(self.clients), state=self.state,
                    building=str(self.child_source) if self.child else None,
                    sources=[str(source) for source in self.tracked], runtime=self.runtime,
                    error=self.error)

    def release(self):
        for handle in [*self.source_locks.values(), self.lock]:
            if handle:
                try:
                    handle.close()
                except OSError:
                    pass
        self.source_locks.clear()
        self.tracked.clear()
        self.lock = None


class Daemon:
    def __init__(self, listener, lock):
        self.listener = listener
        self.lock = lock
        self.projects = {}
        self.started = time.monotonic()
        self.stopping = False
        self.ever_registered = False
        sys.path.insert(0, str(LIB))
        import build
        import overleaf_build
        self.build, self.overleaf = build, overleaf_build
        self.runtime = self.runtime_stamps()

    # Requests -------------------------------------------------------------
    def handle(self, message):
        op = message.get('op')
        if op == 'status':
            return dict(ok=True, running=True, pid=os.getpid(), protocol=PROTOCOL, runtime=str(LIB),
                        projects=[p.record() for p in self.projects.values()])
        if op == 'stop':
            self.stopping = True
            return dict(ok=True)
        root = message.get('root')
        if not isinstance(root, str) or not os.path.isabs(root):
            return dict(ok=False, error='root must be an absolute path')
        client = str(message.get('client') or 'cli')
        if op == 'register':
            if not os.path.isdir(root):
                return dict(ok=False, error=f'not a directory: {root}')
            project = self.projects.get(root)
            if project is None:
                project = self.projects[root] = Project(root, message.get('runtime') or str(LIB))
            elif message.get('runtime'):
                project.runtime = message['runtime']
            pid = message.get('pid')
            project.clients[client] = [int(pid), message.get('start')] if pid else None
            self.ever_registered = True
            say('Registered', root, 'client', client, f'pid {pid}' if pid else '')
            return dict(ok=True, watched=True, **project.record())
        if op == 'unregister':
            project = self.projects.get(root)
            if project:
                if message.get('all'):
                    project.clients.clear()
                project.clients.pop(client, None)
                if not project.clients:
                    self.remove(project, 'unregistered')
            return dict(ok=True, root=root, watched=root in self.projects)
        return dict(ok=False, error=f'unknown request: {op}')

    def serve_connection(self, connection):
        with connection:
            connection.settimeout(1)
            try:
                data = b''
                while not data.endswith(b'\n') and len(data) < 65536:
                    chunk = connection.recv(65536)
                    if not chunk:
                        return
                    data += chunk
                message = json.loads(data)
                reply = self.handle(message) if isinstance(message, dict) else dict(ok=False, error='bad request')
            except (OSError, ValueError) as error:
                reply = dict(ok=False, error=str(error))
            try:
                connection.sendall(json.dumps(reply).encode() + b'\n')
            except OSError:
                pass

    def accept_pending(self, timeout):
        ready, _, _ = select.select([self.listener], [], [], max(0., timeout))
        while ready:
            try:
                connection, _ = self.listener.accept()
            except BlockingIOError:
                break
            self.serve_connection(connection)
            ready, _, _ = select.select([self.listener], [], [], 0)

    # Projects -------------------------------------------------------------
    def remove(self, project, why):
        self.projects.pop(str(project.root), None)
        project.release()
        root = project.root
        for key in [key for key in self.build._DEPENDENCIES if key[0] == root]:
            del self.build._DEPENDENCIES[key]
        say('Stopped watching', root, f'({why})')

    def acquire(self, project):
        """Share the project lock with `paper build --watch`: whoever holds it builds."""
        output_latex = Path('output/.latex')
        output_latex.mkdir(parents=True, exist_ok=True)
        legacy = Path('output/.project.watch.lock')
        if legacy.exists():
            try:
                with legacy.open('a') as handle:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(handle, fcntl.LOCK_UN)
                legacy.unlink(missing_ok=True)
            except BlockingIOError:
                return False
        handle = (output_latex / '.project.watch.lock').open('a')
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return False
        project.lock = handle
        return True

    def scan(self, project):
        build = self.build
        if project.lock is None and not self.acquire(project):
            if project.state != 'external':
                self.project_log(project, 'Another continuous builder is watching the project; waiting.')
            project.state = 'external'
            return
        self.overleaf.refresh_async()
        current = set(build.find_project_roots(project.root))
        for source in [s for s in project.tracked if s not in current]:
            del project.tracked[source]
            handle = project.source_locks.pop(source, None)
            if handle:
                handle.close()
        for source in sorted(current - set(project.tracked)):
            out = Path('output') / source.parent
            aux = build.auxiliary_directory(source)
            out.mkdir(parents=True, exist_ok=True)
            aux.mkdir(parents=True, exist_ok=True)
            handle = (aux / f'.{source.stem}.watch.lock').open('a')
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.close()
                if source not in project.skipped:
                    project.skipped.add(source)
                    self.project_log(project, f'Another watcher is already watching {source}; skipping.')
                continue
            project.skipped.discard(source)
            project.source_locks[source] = handle
            build.tex_environment.prepare_auxiliary_tree(aux)
            project.tracked[source] = dict(out=out, pdf=(out / (source.stem + '.pdf')).resolve(), previous=None)
            self.project_log(project, f'Watching {source}; PDF: {out / (source.stem + ".pdf")}.')
        project.state = 'watching'

    def project_log(self, project, text):
        try:
            with open_log(project.root / 'output/.latex/.watch.log') as log:
                log.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {text}\n')
        except OSError:
            pass

    def dependency_stamps(self, source, info):
        tracked = self.build.dependencies(source, info['out'])
        tracked.add(info['pdf'])
        return {path: self.build.file_stamp(path) for path in tracked}

    def finish(self, project):
        source, info = project.child_source, project.tracked.get(project.child_source)
        code = project.child.returncode
        project.child = project.child_source = None
        if info is not None:
            # Retain pre-build stamps so saves during compilation are retried.
            tracked = self.build.dependencies(source, info['out'])
            info['previous'] = {path: project.before.get(path) for path in tracked}
            info['previous'][info['pdf']] = self.build.file_stamp(info['pdf'])
            # Rotate: a document saved continuously cannot starve the others.
            project.tracked[source] = project.tracked.pop(source)
        project.before = None
        project.error = f'{source}: build exited with status {code}' if code else ''

    def start(self, project, source, before):
        project.before = before
        project.child_source = source
        self.project_log(project, f'Building {source}.')
        builder = Path(project.runtime) / 'build.py'
        if not builder.is_file():
            builder = LIB / 'build.py'
        with open_log(project.root / 'output/.latex/.watch.log') as log:
            project.child = subprocess.Popen([sys.executable, str(builder), 'build', str(source)],
                                             cwd=project.root, stdin=subprocess.DEVNULL,
                                             stdout=log, stderr=subprocess.STDOUT)

    def tick(self, project, now):
        if project.child is not None:
            if project.child.poll() is None:
                return
            self.finish(project)
        if now >= project.next_scan:
            project.next_scan = now + SCAN_INTERVAL
            self.scan(project)
        if project.lock is None:
            return
        for source, info in list(project.tracked.items()):
            current = self.dependency_stamps(source, info)
            if current != info['previous']:
                self.start(project, source, current)
                return

    def prune_clients(self):
        for project in list(self.projects.values()):
            for name, owner in list(project.clients.items()):
                if owner and not process_alive(*owner):
                    del project.clients[name]
                    say('Client exited:', name, project.root)
            if not project.clients:
                self.remove(project, 'all clients exited')
            elif not project.root.is_dir():
                self.remove(project, 'project directory removed')

    def runtime_stamps(self):
        return {name: self.build.file_stamp(LIB / name) for name in RUNTIME_FILES}

    def runtime_updated(self):
        """A rewritten runtime (`paper init` upgrade or checkout) reloads the daemon."""
        current = self.runtime_stamps()
        if current == self.runtime:
            return False
        time.sleep(.2)
        if current != self.runtime_stamps():
            return False
        try:
            for name in RUNTIME_FILES:
                compile((LIB / name).read_bytes(), str(LIB / name), 'exec')
        except (OSError, SyntaxError):
            return False
        return True

    def reload(self):
        state = {root: dict(clients=p.clients, runtime=p.runtime) for root, p in self.projects.items()}
        handoff = runtime_directory() / f'watch-{os.getpid()}.json'
        handoff.write_text(json.dumps(state))
        for project in self.projects.values():
            project.release()
        say('Build runtime updated; reloading watcher.')
        for handle in (self.listener, self.lock):
            os.set_inheritable(handle.fileno(), True)
        os.execv(sys.executable, [sys.executable, str(LIB / 'build_watcher.py'), 'serve',
                                  '--restore', str(handoff), '--listen-fd', str(self.listener.fileno()),
                                  '--lock-fd', str(self.lock.fileno())])

    def restore(self, path):
        try:
            state = json.loads(Path(path).read_text())
        finally:
            Path(path).unlink(missing_ok=True)
        for root, value in state.items():
            if os.path.isdir(root):
                project = self.projects[root] = Project(root, value.get('runtime') or str(LIB))
                project.clients = value.get('clients') or {}
                self.ever_registered = True

    def run(self):
        next_poll = next_scan = 0.
        while True:
            now = time.monotonic()
            self.accept_pending(next_poll - now)
            now = time.monotonic()
            if now >= next_scan:
                next_scan = now + SCAN_INTERVAL
                self.prune_clients()
                if not any(p.child for p in self.projects.values()) and self.runtime_updated():
                    self.reload()
            if now >= next_poll:
                next_poll = now + POLL_INTERVAL
                for project in list(self.projects.values()):
                    try:
                        os.chdir(project.root)
                        self.tick(project, now)
                        if project.error.startswith('scan:'):
                            project.error = ''
                    except Exception as error:  # One project's failure never stops the others.
                        project.error = f'scan: {error}'
                        say('Error in', project.root, repr(error))
                    finally:
                        os.chdir('/')
            if self.stopping:
                return
            if not self.projects and (self.ever_registered or now - self.started > STARTUP_GRACE):
                # Serve requests that raced with the last unregistration first.
                self.accept_pending(0)
                if not self.projects:
                    return


def serve(args):
    directory = runtime_directory()
    path = directory / 'watch.sock'
    if args.lock_fd is not None:
        lock = os.fdopen(args.lock_fd, 'a')
        listener = socket.socket(fileno=args.listen_fd)
    else:
        lock = (directory / 'watch.lock').open('a')
        deadline = time.monotonic() + CONNECT_TIMEOUT
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                try:
                    if exchange(dict(protocol=PROTOCOL, op='status')):
                        return 0  # Another daemon already serves this user.
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    say('Another watcher holds the lock without serving; giving up.')
                    return 1
                time.sleep(.05)
        path.unlink(missing_ok=True)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)
        try:
            listener.bind(str(path))
        finally:
            os.umask(old)
        listener.listen(32)
    os.set_inheritable(listener.fileno(), False)
    os.set_inheritable(lock.fileno(), False)
    listener.setblocking(False)
    daemon = Daemon(listener, lock)
    if args.restore:
        daemon.restore(args.restore)

    def stop(signum, frame):
        daemon.stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    say('Build watcher', os.getpid(), 'serving from', LIB)
    try:
        daemon.run()
    finally:
        path.unlink(missing_ok=True)
        listener.close()
        for project in list(daemon.projects.values()):
            project.release()
        say('Build watcher', os.getpid(), 'exiting.')
        lock.close()
    return 0


def run(argv=None):
    parser = argparse.ArgumentParser(prog='paper watch', description=__doc__.split('\n\n')[0])
    commands = parser.add_subparsers(dest='command', required=True)
    add = commands.add_parser('register', help='watch a project until its clients unregister')
    add.add_argument('root')
    add.add_argument('--client', default='cli', help='registrant name, e.g. editor or reader (default: cli)')
    add.add_argument('--pid', type=int, help='unregister the client automatically when this process exits')
    add.add_argument('--json', action='store_true')
    remove = commands.add_parser('unregister', help='drop one client; the project stops with its last client')
    remove.add_argument('root')
    remove.add_argument('--client', default='cli')
    remove.add_argument('--all', action='store_true', help='drop every client of the project')
    remove.add_argument('--json', action='store_true')
    status = commands.add_parser('status', help='list watched projects')
    status.add_argument('--json', action='store_true')
    commands.add_parser('stop', help='stop the watcher; running builds finish on their own')
    daemon = commands.add_parser('serve', help=argparse.SUPPRESS)
    daemon.add_argument('--restore')
    daemon.add_argument('--listen-fd', type=int)
    daemon.add_argument('--lock-fd', type=int)
    args = parser.parse_args(argv)

    if args.command == 'serve':
        return serve(args)
    if args.command == 'register':
        if args.pid is not None and args.pid <= 0:
            parser.error('--pid must be positive')
        reply = register(args.root, args.client, args.pid)
    elif args.command == 'unregister':
        reply = unregister(args.root, args.client, args.all)
    elif args.command == 'status':
        reply = exchange(dict(protocol=PROTOCOL, op='status')) or dict(ok=True, running=False, projects=[])
    else:
        reply = exchange(dict(protocol=PROTOCOL, op='stop')) or dict(ok=True)
    if not reply.get('ok'):
        print(f'paper watch: {reply.get("error", "request failed")}', file=sys.stderr)
        return 1
    if getattr(args, 'json', False):
        print(json.dumps(reply, indent=2))
    elif args.command == 'register':
        print(f'Watching {reply["root"]}.' if reply.get('watched')
              else f'Not watching {reply["root"]}: {reply.get("reason")}.')
    elif args.command == 'status':
        if not reply.get('projects'):
            print('No watched projects.')
        for project in reply.get('projects', []):
            detail = f'building {project["building"]}' if project['building'] else project['state']
            print(f'{project["root"]}  {detail}  [{", ".join(project["clients"])}]'
                  + (f'  {project["error"]}' if project['error'] else ''))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(run())
    except OSError as error:
        print(f'paper watch: {error}', file=sys.stderr)
        sys.exit(1)
