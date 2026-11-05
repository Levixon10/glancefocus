"""X11 backend for any EWMH-compliant window manager (GNOME/KDE on X11, Xfce, Openbox, …).

Needs `pip install "glancefocus[x11]"` (python-xlib).
"""

from __future__ import annotations

from glancefocus.geometry import Monitor, Rect, Window, assign_monitor
from glancefocus.platforms.base import Platform, PlatformError

ALL_DESKTOPS = 0xFFFFFFFF


class X11(Platform):
    name = "x11"
    status = "experimental"

    def __init__(self):
        try:
            from Xlib import X, display, error
            from Xlib.protocol import event
        except ImportError as e:
            raise PlatformError('X11 support needs python-xlib: pip install "glancefocus[x11]"') from e
        self._X, self._event, self._error = X, event, error
        try:
            self._d = display.Display()
        except Exception as e:  # noqa: BLE001 - Xlib raises many types here
            raise PlatformError(f"cannot connect to X display: {e}") from e
        self._root = self._d.screen().root
        self._atoms: dict[str, int] = {}

    def _atom(self, name: str) -> int:
        if name not in self._atoms:
            self._atoms[name] = self._d.intern_atom(name)
        return self._atoms[name]

    def _prop(self, win, name: str):
        p = win.get_full_property(self._atom(name), self._X.AnyPropertyType)
        return p.value if p is not None else None

    def monitors(self) -> list[Monitor]:
        try:
            reply = self._root.xrandr_get_monitors(is_active=True)
            mons = [
                Monitor(
                    self._d.get_atom_name(m.name) or f"monitor-{i}",
                    Rect(float(m.x), float(m.y), float(m.width_in_pixels), float(m.height_in_pixels)),
                )
                for i, m in enumerate(reply.monitors)
            ]
            if mons:
                return mons
        except Exception:  # noqa: BLE001 - RandR missing or too old
            pass
        s = self._d.screen()
        return [Monitor("screen", Rect(0.0, 0.0, float(s.width_in_pixels), float(s.height_in_pixels)))]

    def windows(self) -> list[Window]:
        monitors = self.monitors()
        ids = self._prop(self._root, "_NET_CLIENT_LIST_STACKING")
        if ids is None:
            ids = self._prop(self._root, "_NET_CLIENT_LIST")
        if ids is None:
            raise PlatformError("window manager does not support EWMH (_NET_CLIENT_LIST)")
        current = self._prop(self._root, "_NET_CURRENT_DESKTOP")
        current = int(current[0]) if current is not None and len(current) else None
        active = self._prop(self._root, "_NET_ACTIVE_WINDOW")
        active = int(active[0]) if active is not None and len(active) else 0

        hidden = self._atom("_NET_WM_STATE_HIDDEN")
        skip_types = {self._atom(t) for t in ("_NET_WM_WINDOW_TYPE_DOCK", "_NET_WM_WINDOW_TYPE_DESKTOP")}

        result = []
        for wid in reversed(list(ids)):  # stacking order is bottom → top
            win = self._d.create_resource_object("window", int(wid))
            try:
                desktop = self._prop(win, "_NET_WM_DESKTOP")
                if current is not None and desktop is not None and len(desktop):
                    if int(desktop[0]) not in (current, ALL_DESKTOPS):
                        continue
                if hidden in set(self._prop(win, "_NET_WM_STATE") or []):
                    continue
                if skip_types & set(self._prop(win, "_NET_WM_WINDOW_TYPE") or []):
                    continue
                if win.get_attributes().map_state != self._X.IsViewable:
                    continue
                geom = win.get_geometry()
                origin = self._root.translate_coords(win, 0, 0)
                name = self._prop(win, "_NET_WM_NAME")
                title = name.decode("utf-8", "replace") if isinstance(name, bytes) else (win.get_wm_name() or "")
                cls = win.get_wm_class()
            except self._error.XError:
                continue
            rect = Rect(float(origin.x), float(origin.y), float(geom.width), float(geom.height))
            result.append(
                Window(
                    id=str(int(wid)),
                    title=str(title),
                    app=cls[1] if cls else "",
                    rect=rect,
                    monitor=assign_monitor(rect, monitors),
                    focused=int(wid) == active,
                    z=len(result),
                )
            )
        return result

    def focus_window(self, window: Window) -> None:
        X = self._X
        win = self._d.create_resource_object("window", int(window.id))
        ev = self._event.ClientMessage(
            window=win,
            client_type=self._atom("_NET_ACTIVE_WINDOW"),
            data=(32, [2, X.CurrentTime, 0, 0, 0]),  # 2 = request from a pager/tool
        )
        self._root.send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
        self._d.flush()

    def cursor_pos(self) -> tuple[float, float] | None:
        p = self._root.query_pointer()
        return float(p.root_x), float(p.root_y)
