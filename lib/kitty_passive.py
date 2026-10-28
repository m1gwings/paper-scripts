"""Start Kitty with an ICCCM minimized hint before its first X11 map.

Kitty's ordinary --start-as minimized minimizes after mapping, which briefly
steals focus on COSMIC. Use Kitty's pre-show callback, then let the launcher
reveal the mapped window through workspace-desktop without activating it.
"""
import ctypes as C
import sys


class WMHints(C.Structure):
    _fields_ = [('flags', C.c_long), ('input', C.c_int), ('initial_state', C.c_int),
                ('icon_pixmap', C.c_ulong), ('icon_window', C.c_ulong),
                ('icon_x', C.c_int), ('icon_y', C.c_int),
                ('icon_mask', C.c_ulong), ('window_group', C.c_ulong)]


def before_show(window_id):
    if not isinstance(window_id, int) or not window_id:
        raise RuntimeError('Passive Kitty startup requires an X11 window.')
    x = C.CDLL('libX11.so.6')
    x.XOpenDisplay.argtypes = [C.c_char_p]
    x.XOpenDisplay.restype = C.c_void_p
    x.XGetWMHints.argtypes = [C.c_void_p, C.c_ulong]
    x.XGetWMHints.restype = C.POINTER(WMHints)
    x.XSetWMHints.argtypes = [C.c_void_p, C.c_ulong, C.POINTER(WMHints)]
    x.XSync.argtypes = [C.c_void_p, C.c_int]
    x.XCloseDisplay.argtypes = [C.c_void_p]
    x.XFree.argtypes = [C.c_void_p]
    display = x.XOpenDisplay(None)
    if not display:
        raise RuntimeError('Cannot open X11 display for passive Kitty startup.')
    pointer = None
    try:
        pointer = x.XGetWMHints(display, window_id)
        hints = pointer.contents if pointer else WMHints()
        hints.flags |= 2  # StateHint; preserve the existing input/icon/group hints.
        hints.initial_state = 3  # IconicState before the compositor maps it.
        x.XSetWMHints(display, window_id, C.byref(hints))
        x.XSync(display, 0)
    finally:
        if pointer:
            x.XFree(pointer)
        x.XCloseDisplay(display)


def main():
    from kitty.main import run_app, main as kitty_main
    run_app.first_window_callback = before_show
    sys.argv += ['--override', 'linux_display_server=x11']
    # +runpy's preparsed C options precede these overrides; reparse our argv.
    getattr(sys, 'kitty_run_data', {}).pop('cli_flags', None)
    kitty_main()


if __name__ == '__main__':
    main()
