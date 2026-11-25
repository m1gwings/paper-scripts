"""Project shells of the single Editor: one per project, the active one below Micro.

A no-UI kitten that runs inside the Editor's Kitty process, so every change below
happens in one event-loop turn and is drawn once:

    kitty @ --to SOCKET kitten editor_shells.py activate ROOT [NAME]   (empty ROOT: Loose file)
    kitty @ --to SOCKET kitten editor_shells.py prepare ROOT [NAME]
    kitty @ --to SOCKET kitten editor_shells.py busy ROOT
    kitty @ --to SOCKET kitten editor_shells.py task JSON
    kitty @ --to SOCKET kitten editor_shells.py close ROOT [--force]
    kitty @ --to SOCKET kitten editor_shells.py status

Kitty windows carry user variables: Micro has ``workspace_role=editor``; every
project pane has ``workspace_project=ROOT``. Panes of inactive projects wait in
one tab whose windows carry ``workspace_parked=1``; the Editor's
``tab_bar_filter`` hides that tab, and Kitty restricts tab navigation to shown
tabs. Each call prints one JSON object. Nothing here activates the desktop
window: Kitty's ``launch --keep-focus`` would, so new panes are created normally
and the previous active pane is restored afterwards.
"""
import json
import os
import time

PROJECT = 'workspace_project'
ROLE = 'workspace_role'
PARKED = 'workspace_parked'
PARK_TITLE = 'Parked shells'
TAB_BAR_FILTER = f'not var:{PARKED}'


def main(args):
    pass


def editor_window(boss):
    for window in tuple(boss.window_id_map.values()):
        if window.user_vars.get(ROLE) == 'editor' and window.tabref() is not None:
            return window
    raise ValueError('This Kitty has no Editor pane.')


def group_heads(tab):
    """Main window of each ordinary group, in layout order (docks travel with them)."""
    for group in tuple(tab.windows.iter_all_layoutable_groups()):
        window = tab.windows.window_for_id(group.main_window_id)
        if window is not None and not tab.windows.is_in_os_window_dock(window):
            yield window


def park_tab(manager):
    for tab in manager:
        if any(w.user_vars.get(PARKED) for w in tab.windows.iter_tab_windows()):
            return tab
    return None


def new_tab(manager, title, index=None):
    """Insert a tab without activating it, so it never enters the tab history."""
    from kitty.tabs import Tab
    tab = Tab(manager, no_initial_window=True)
    tab.set_title(title)
    manager.tabs.append(tab)
    active = manager.active_tab_idx
    position = len(manager.tabs) - 1
    while index is not None and position > index:
        manager.swap_tabs(position, position - 1)
        position -= 1
    if index is not None and index <= active < len(manager.tabs) - 1:
        manager._set_active_tab(active + 1, store_in_history=False)
    manager.mark_tab_bar_dirty()
    return tab


def new_park_tab(manager):
    return new_tab(manager, PARK_TITLE)


def group_end(manager, root, editor_tab=None):
    """Index after the last tab of root's group, or None to append a new group."""
    last = None
    for index, tab in enumerate(manager.tabs):
        if tab is not editor_tab and any(w.user_vars.get(PROJECT) == root and not w.user_vars.get(PARKED)
               for w in tab.windows.iter_tab_windows()):
            last = index
    return None if last is None else last + 1


def move(boss, window, source, target, *, parked):
    if parked:
        window.set_user_var(PARKED, '1')
    else:
        window.set_user_var(PARKED, None)
    target.attach_windows(source.detach_window(window))


def display_name(root, name='', cache=None):
    """The project name used by the launchers (project_metadata.metadata), cached per Editor."""
    cache = {} if cache is None else cache
    if name:
        cache[root] = name
        return name
    if root in cache:
        return cache[root]
    cache[root] = metadata_name(root)
    return cache[root]


def metadata_name(root):
    import runpy
    here = os.path.dirname(metadata_name.__code__.co_filename)
    try:
        return runpy.run_path(os.path.join(here, 'project_metadata.py'))['metadata'](root)['project_name']
    except (OSError, ValueError, KeyError):
        return os.path.basename(root.rstrip('/')) or root


def names(boss):
    """Names survive between kitten runs on the Editor's Boss object."""
    if not hasattr(boss, 'workspace_project_names'):
        boss.workspace_project_names = {}
    return boss.workspace_project_names


def shell_environment(root, name):
    return {'PROJECT_WORKSPACE_ROOT': root, 'PROJECT_WORKSPACE_NAME': name,
            'PROJECT_WORKSPACE_ID': os.environ.get('PROJECT_WORKSPACE_ID', 'editor')}


def open_pane(boss, tab, root, name, *, title, role, cwd=None, command=(), kind='window', env=None):
    from kitty.launch import launch, parse_launch_args
    args = [f'--type={kind}', '--title', title, '--cwd', cwd or root,
            '--var', f'{ROLE}={role}', '--var', f'{PROJECT}={root}']
    if kind == 'os-window-dock':
        args += ['--dock-edge=bottom', '--dock-size=25%']
    for key, value in dict(shell_environment(root, name), **(env or {})).items():
        args += ['--env', f'{key}={value}']
    spec = parse_launch_args(args + list(command or ()))  # empty: the user's shell
    window = launch(boss, spec.opts, spec.args, target_tab=tab, force_target_tab=True)
    if window is None:
        raise ValueError(f'Kitty could not start {title}.')
    return window


def is_latex(root):
    return os.path.isfile(os.path.join(root, '.paper/config.json')) or os.path.isfile(os.path.join(root, 'main.tex'))


def start_build_view(boss, manager, editor_tab, root, name):
    """Build tab: follows the shared watcher's compiler output for this project."""
    log = os.path.join(root, 'output/.latex/.watch.log')
    target = new_tab(manager, 'Build', group_end(manager, root, editor_tab))
    # exec keeps tail as the pane's root process, so closing never asks about it.
    return open_pane(boss, target, root, name, title='Build', role='build',
                     command=['bash', '-c', 'exec tail -n 200 -F -- "$1" 2>/dev/null', 'build', log])


def start_shell(boss, tab, root, name):
    return open_pane(boss, tab, root, name, title='Shell', role='shell')


def set_title(editor, name):
    from kitty.fast_data_types import set_os_window_title
    set_os_window_title(editor.os_window_id, f'Editor — {name}' if name else 'Editor')


def prepare(boss, root, name=''):
    """A project gained its first tab: start its shell (parked unless active) and Build tab."""
    editor = editor_window(boss)
    tab = editor.tabref()
    manager = tab.tab_manager_ref()
    name = display_name(root, name, names(boss))
    result = {'ok': True, 'project': root, 'started_shell': False}
    if any(w.user_vars.get(PROJECT) == root and w.user_vars.get(ROLE) == 'shell' for w in boss.window_id_map.values()):
        return result
    active, active_tab = tab.active_window, manager.active_tab
    with boss.suppress_focus_change_events():
        if editor.user_vars.get(PROJECT + '_active') == root:
            start_shell(boss, tab, root, name)
        else:
            start_shell(boss, park_tab(manager) or new_park_tab(manager), root, name).set_user_var(PARKED, '1')
        start_extras(boss, manager, tab, root, name)
        if manager.active_tab is not active_tab and active_tab in manager.tabs:
            manager.set_active_tab(active_tab)
        if active is not None and active in tab.windows:
            tab.set_active_window(active)
    result['started_shell'] = True
    return result


def start_extras(boss, manager, editor_tab, root, name):
    if is_latex(root) and not any(w.user_vars.get(PROJECT) == root and w.user_vars.get(ROLE) == 'build'
                                  for w in boss.window_id_map.values()):
        start_build_view(boss, manager, editor_tab, root, name)


def activate(boss, root, name=''):
    started = time.perf_counter()
    editor = editor_window(boss)
    if not root:  # A Loose file: its project-less tab keeps the current shell.
        set_title(editor, '')
        return {'ok': True, 'project': '', 'started_shell': False}
    tab = editor.tabref()
    manager = tab.tab_manager_ref()
    name = display_name(root, name, names(boss))
    previous = editor.user_vars.get(PROJECT + '_active', '')
    active, active_tab = tab.active_window, manager.active_tab
    outgoing = [w for w in group_heads(tab) if w is not editor and w.user_vars.get(PROJECT, previous) != root]
    parked = park_tab(manager)
    incoming = [w for w in group_heads(parked) if w.user_vars.get(PROJECT) == root] if parked else []
    has_shell = any(w.user_vars.get(PROJECT) == root and w.user_vars.get(ROLE) == 'shell'
                    for w in boss.window_id_map.values())
    focus_shell = active is not None and active is not editor and active in outgoing
    started_shell = False
    with boss.suppress_focus_change_events():
        if outgoing:
            parked = parked or new_park_tab(manager)
            for window in outgoing:
                if not window.user_vars.get(PROJECT) and previous:
                    window.set_user_var(PROJECT, previous)  # e.g. a Ctrl+Shift+Enter split
                move(boss, window, tab, parked, parked=True)
        for window in incoming:
            move(boss, window, parked, tab, parked=False)
        if not has_shell:
            start_shell(boss, tab, root, name)
            started_shell = True
            start_extras(boss, manager, tab, root, name)
        shell = next((w for w in group_heads(tab) if w.user_vars.get(PROJECT) == root
                      and w.user_vars.get(ROLE) == 'shell'), None)
        if focus_shell and shell is not None:
            tab.set_active_window(shell)
        elif active is not None and active in tab.windows:
            tab.set_active_window(active)
        else:
            tab.set_active_window(editor)
        if parked is not None and not parked.windows.has_tab_windows:
            boss._cleanup_tab_after_window_removal(parked)
        if manager.active_tab is not active_tab and active_tab in manager.tabs:
            manager.set_active_tab(active_tab)
    editor.set_user_var(PROJECT + '_active', root)
    editor.set_user_var(PROJECT + '_name', name)
    set_title(editor, name)
    return {'ok': True, 'project': root, 'name': name, 'parked': len(outgoing), 'shown': len(incoming),
            'started_shell': started_shell, 'ms': round((time.perf_counter() - started) * 1000, 3)}


def task(boss, spec):
    """Open a task tab (end of its project's group), split or OS-window dock."""
    root, title, kind = spec['root'], spec['title'], spec.get('kind', 'tab')
    editor = editor_window(boss)
    tab = editor.tabref()
    manager = tab.tab_manager_ref()
    name = display_name(root, spec.get('name', ''), names(boss))
    active_tab, active = manager.active_tab, tab.active_window
    visible = kind != 'window' or editor.user_vars.get(PROJECT + '_active') == root
    with boss.suppress_focus_change_events():
        if kind == 'tab':
            target = new_tab(manager, title, group_end(manager, root, tab))
            window = open_pane(boss, target, root, name, title=title, role='task', cwd=spec.get('cwd'),
                               command=spec.get('command'), env=spec.get('env'))
        elif kind == 'window':
            # A split of an inactive project waits with that project's shell.
            target = tab if visible else (park_tab(manager) or new_park_tab(manager))
            window = open_pane(boss, target, root, name, title=title, role='task', cwd=spec.get('cwd'),
                               command=spec.get('command'), env=spec.get('env'))
            if not visible:
                window.set_user_var(PARKED, '1')
        elif kind == 'dock':
            window = open_pane(boss, tab, root, name, title=title, role='task', cwd=spec.get('cwd'),
                               command=spec.get('command'), env=spec.get('env'), kind='os-window-dock')
        else:
            raise ValueError('Task kind must be tab, window or dock.')
        if spec.get('focus') and visible:
            target_tab = window.tabref()
            manager.set_active_tab(target_tab)
            target_tab.set_active_window(window)
        else:
            if manager.active_tab is not active_tab:
                manager.set_active_tab(active_tab)
            if active is not None and active in tab.windows:
                tab.set_active_window(active)
    return {'ok': True, 'project': root, 'title': title, 'window_id': window.id, 'kind': kind}


def project_windows(boss, root):
    return [w for w in boss.window_id_map.values() if w.user_vars.get(PROJECT) == root]


def busy(window):
    """A program other than the pane's own shell owns the terminal."""
    try:
        return not window.root_in_foreground_processes
    except Exception:
        return False


def running(window):
    """Short description of the foreground program, e.g. 'python3 train.py'."""
    try:
        processes = [p for p in window.child.foreground_processes if p['pid'] != window.child.pid]
        command = list((processes[-1]['cmdline'] if processes else None) or ())[:4]
        if command:
            command[0] = os.path.basename(command[0])
        return ' '.join(command) or 'a program'
    except Exception:
        return 'a program'


def busy_report(boss, root):
    items = [{'id': w.id, 'title': w.title, 'program': running(w)}
             for w in project_windows(boss, root) if busy(w)]
    return {'ok': True, 'project': root, 'busy': items,
            'text': '; '.join(f"{item['title']}: {item['program']}" for item in items)}


def close(boss, root, force=False):
    windows = project_windows(boss, root)
    running = [{'id': w.id, 'title': w.title} for w in windows if busy(w)]
    if running and not force:
        return {'ok': False, 'project': root, 'busy': running}
    for window in windows:
        boss.mark_window_for_close(window)
    return {'ok': True, 'project': root, 'closed': len(windows)}


def status(boss):
    editor = editor_window(boss)
    projects = {}
    for window in boss.window_id_map.values():
        root = window.user_vars.get(PROJECT)
        if root:
            entry = projects.setdefault(root, {'windows': 0, 'parked': False})
            entry['windows'] += 1
            entry['parked'] = entry['parked'] or bool(window.user_vars.get(PARKED))
    return {'ok': True, 'active': editor.user_vars.get(PROJECT + '_active', ''),
            'name': editor.user_vars.get(PROJECT + '_name', ''), 'projects': projects}


def run(args, boss):
    if args[:1] == ['prepare'] and len(args) in (2, 3):
        return prepare(boss, args[1], args[2] if len(args) == 3 else '')
    if args[:1] == ['busy'] and len(args) == 2:
        return busy_report(boss, args[1])
    if args[:1] == ['activate'] and len(args) in (2, 3):
        return activate(boss, args[1], args[2] if len(args) == 3 else '')
    if args[:1] == ['close'] and len(args) in (2, 3) and args[2:] in ([], ['--force']):
        return close(boss, args[1], force=args[2:] == ['--force'])
    if args[:1] == ['task'] and len(args) == 2:
        return task(boss, json.loads(args[1]))
    if args == ['status']:
        return status(boss)
    raise ValueError('Usage: editor_shells.py activate|prepare ROOT [NAME] | busy ROOT | task JSON | close ROOT [--force] | status')


try:
    from kittens.tui.handler import result_handler
except ImportError:  # imported by tests outside Kitty
    def result_handler(**kwargs):
        return lambda function: function


@result_handler(no_ui=True)
def handle_result(args, answer, target_window_id, boss):
    return json.dumps(run(list(args[1:]), boss))
