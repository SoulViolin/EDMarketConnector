"""Plugin windows management: clear API and visual manager dialog.

This module centralizes all logic for creating, moving and restoring plugin UIs
across detachable windows and the main application host. It provides a thin
visual manager dialog for more transparent control.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import json
import sys
import tkinter as tk
from tkinter import ttk

import plug
from config import config
from l10n import translations as tr
from theme import theme


class PluginWindowManager:
    """Owns the lifecycle of plugin windows and plugin UI hosting.

    The manager keeps a list of window hosts and a mapping of plugins to their
    current host. It does not depend on a specific window implementation;
    instead, a factory is injected that must return an object with attributes:
    - w: tk.Toplevel
    - add_plugin(plugin)
    - remove_plugin(plugin)
    - apply_theme()
    """

    def __init__(self, app: Any, window_factory: Callable[[], Any]):
        self.app = app
        self._window_factory: Callable[[], Any] = window_factory
        self._windows: List[Any] = []

        # Expose for existing helpers (ui_bridge) without breaking API
        self.app._plugin_windows = self._windows
        if not hasattr(self.app, '_plugin_rows'):
            self.app._plugin_rows = {}

    # ---------- Windows lifecycle ----------
    def create_window(self) -> Any:
        win = self._window_factory()
        self._windows.append(win)
        return win

    def close_all_windows(self) -> None:
        for w in list(self._windows):
            try:
                if hasattr(w, 'on_close'):
                    w.on_close()
                else:
                    # Fallback: destroy and detach tracked plugins
                    try:
                        w.w.destroy()
                    except Exception:
                        pass
            except Exception:
                pass

    def close_window(self, target_window: Any) -> None:
        try:
            if target_window in self._windows:
                if hasattr(target_window, 'on_close'):
                    target_window.on_close()
                else:
                    try:
                        target_window.w.destroy()
                    finally:
                        try:
                            self._windows.remove(target_window)
                        except Exception:
                            pass
        except Exception:
            pass

    def apply_theme_to_all(self) -> None:
        self.app.synchronizing_windows = True
        try:
            for win in list(self._windows):
                try:
                    win.apply_theme()
                except Exception:
                    pass
        finally:
            self.app.synchronizing_windows = False

    def minimize_all(self, to_tray: bool = False) -> None:
        for win in list(self._windows):
            try:
                if to_tray:
                    win.w.withdraw()
                else:
                    win.w.iconify()
            except Exception:
                pass

    def restore_all(self) -> None:
        for win in list(self._windows):
            try:
                win.w.deiconify()
            except Exception:
                pass

    # ---------- Plugin movement ----------
    def _remove_from_current_host(self, plugin: Any) -> None:
        row = self.app._plugin_rows.get(plugin)
        if not row:
            return
        host = row.get('host')
        if host == 'main':
            try:
                row['frame'].grid_forget()
                row['frame'].destroy()
            except Exception:
                pass
            try:
                row['sep'].grid_forget()
                row['sep'].destroy()
            except Exception:
                pass
            self.app._plugin_rows.pop(plugin, None)
        else:
            try:
                host.remove_plugin(plugin)
            except Exception:
                pass

    def detach_to_new_window(self, plugin: Any) -> None:
        self._remove_from_current_host(plugin)
        win = self.create_window()
        try:
            win.add_plugin(plugin)
        except Exception:
            self.return_to_main(plugin)

    def move_to_window(self, plugin: Any, target_window: Any) -> None:
        if target_window not in self._windows:
            return
        self._remove_from_current_host(plugin)
        try:
            target_window.add_plugin(plugin)
        except Exception:
            self.return_to_main(plugin)

    def return_to_main(self, plugin: Any) -> None:  # noqa: C901 - mirrors AppWindow logic
        row = self.app._plugin_rows.get(plugin)
        if row and row.get('host') != 'main':
            self._remove_from_current_host(plugin)
        row = self.app._plugin_rows.get(plugin)
        if row and row.get('host') == 'main':
            return

        frame = self.app._plugins_parent_main
        plugin_no = sum(1 for r in self.app._plugin_rows.values() if r.get('host') == 'main')
        plugin_sep = tk.Frame(frame, highlightthickness=1, name=f"plugin_hr_returned_{plugin_no + 1}")
        plugin_frame = tk.Frame(frame, name=f"plugin_returned_{plugin_no + 1}")

        appitem = plugin.get_app(plugin_frame)
        if appitem:
            # Embedding the plugin UI
            plugin_sep.grid(columnspan=2, sticky=tk.EW)
            ui_row = frame.grid_size()[1]
            plugin_frame.grid(row=ui_row, columnspan=2, sticky=tk.NSEW)
            plugin_frame.columnconfigure(1, weight=1)
            if isinstance(appitem, tuple) and len(appitem) == 2:
                ui_row = frame.grid_size()[1]
                appitem[0].grid(row=ui_row, column=0, sticky=tk.W)
                appitem[1].grid(row=ui_row, column=1, sticky=tk.EW)
            else:
                appitem.grid(columnspan=2, sticky=tk.EW)

            for child in plugin_frame.winfo_children():
                try:
                    child.grid_configure(
                        padx=self.app.PADX,
                        pady=(sys.platform != 'win32' or isinstance(child, tk.Frame)) and 2 or 0,
                    )
                except Exception:
                    pass

            # Apply current theme to the returned plugin immediately
            theme.register(plugin_frame)
            try:
                theme.update(plugin_frame)
            except Exception:
                pass
            self.app._plugin_rows[plugin] = {
                'parent': frame,
                'sep': plugin_sep,
                'frame': plugin_frame,
                'host': 'main',
            }
            # Rearrange all plugins in main window according to original order
            try:
                self._regrid_main_plugins()
            except Exception:
                pass
        else:
            plugin_frame.destroy()
            plugin_sep.destroy()

    # ---------- Layout persistence ----------
    def save_layout(self) -> None:
        try:
            layout = {"windows": [], "assignments": {}}
            window_id_by_obj: Dict[Any, str] = {}
            for idx, win in enumerate(self._windows, start=1):
                wid = f"w{idx}"
                try:
                    geom = win.w.geometry()
                    parts = geom.split('+')
                    if len(parts) >= 3:
                        x, y = parts[1], parts[2]
                        geometry = f"+{x}+{y}"
                    else:
                        geometry = ''
                except Exception:
                    geometry = ''
                layout["windows"].append({"id": wid, "geometry": geometry})
                window_id_by_obj[win] = wid

            for plugin, row in list(getattr(self.app, '_plugin_rows', {}).items()):
                try:
                    host = row.get('host')
                    if host == 'main':
                        layout["assignments"][plugin.name] = 'main'
                    else:
                        wid = window_id_by_obj.get(host)
                        if wid:
                            layout["assignments"][plugin.name] = wid
                except Exception:
                    pass

            config.set('plugin_layout', json.dumps(layout))
        except Exception:
            pass

    def restore_layout(self) -> None:
        try:
            data_str = config.get_str('plugin_layout')
            if not data_str:
                return
            data = json.loads(data_str)
            windows = data.get('windows') or []
            assignments: dict = data.get('assignments') or {}

            id_to_window: Dict[str, Any] = {}
            for win_info in windows:
                wid = win_info.get('id')
                if not wid:
                    continue
                win = self.create_window()
                try:
                    geom = win_info.get('geometry')
                    if geom:
                        win.w.geometry(geom)
                except Exception:
                    pass
                id_to_window[wid] = win

            for plugin in plug.PLUGINS:
                try:
                    target = assignments.get(plugin.name)
                    if not target or target == 'main':
                        continue
                    target_win = id_to_window.get(str(target))
                    if target_win:
                        self.move_to_window(plugin, target_win)
                except Exception:
                    pass
        except Exception:
            pass

    # ---------- Helpers: maintain main window order ----------
    def _regrid_main_plugins(self) -> None:
        """Re-grid all plugins hosted in main window to match plug.PLUGINS order.

        Plugins take 2 rows each (separator and frame). We calculate the position
        of each plugin to place them consecutively right before the update button,
        maintaining the order from plug.PLUGINS.
        """
        try:
            # List of plugins currently placed in main window
            current_main = [p for p, r in self.app._plugin_rows.items() if r.get('host') == 'main']
            if not current_main:
                return

            # Final order is according to global PLUGINS order
            ordered = [p for p in plug.PLUGINS if p in current_main]
            if not ordered:
                return

            # Update button row is the anchor for bottom of plugin zone
            try:
                button_row = int(self.app.button.grid_info().get('row', 0))
            except Exception:
                # Fallback: if something went wrong, use current row count
                button_row = self.app._plugins_parent_main.grid_size()[1]

            # Starting row for first plugin (each plugin = 2 rows)
            start_row = max(0, button_row - 2 * len(ordered))

            # Arrange in consecutive rows
            for idx, p in enumerate(ordered):
                rowinfo = self.app._plugin_rows.get(p)
                if not rowinfo:
                    continue
                sep = rowinfo.get('sep')
                frm = rowinfo.get('frame')
                target_sep_row = start_row + 2 * idx
                target_frm_row = target_sep_row + 1
                try:
                    if sep is not None:
                        sep.grid_configure(row=target_sep_row)
                except Exception:
                    pass
                try:
                    if frm is not None:
                        frm.grid_configure(row=target_frm_row)
                except Exception:
                    pass
        except Exception:
            pass

    # ---------- Visual manager dialog ----------
    def open_manager_dialog(self, parent: Optional[tk.Misc] = None) -> None:
        dialog = _PluginWindowsDialog(self, parent or self.app.w)
        dialog.show()


class _PluginWindowsDialog:
    """A simple visual dialog to manage where each plugin UI is hosted."""

    def __init__(self, manager: PluginWindowManager, parent: tk.Misc) -> None:
        self.manager = manager
        self.parent = parent
        self.toplevel: Optional[tk.Toplevel] = None

    def show(self) -> None:
        if self.toplevel and tk.Toplevel.winfo_exists(self.toplevel):
            try:
                self.toplevel.deiconify()
                self.toplevel.lift()
                return
            except Exception:
                pass

        self.toplevel = tk.Toplevel(self.parent)
        self.toplevel.title(tr.tl('Plugin Windows Manager'))
        self.toplevel.resizable(tk.TRUE, tk.TRUE)
        self.toplevel.columnconfigure(0, weight=1)
        self.toplevel.rowconfigure(1, weight=1)

        header = ttk.Frame(self.toplevel)
        header.grid(row=0, column=0, sticky=tk.EW, padx=10, pady=6)
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text=tr.tl('Manage where plugin UIs are shown')).grid(row=0, column=0, sticky=tk.W)
        ttk.Button(header, text=tr.tl('Create window'), command=self._create_window).grid(row=0, column=1, padx=6)
        ttk.Button(header, text=tr.tl('Close all windows'), command=self._close_all).grid(row=0, column=2)

        # Row for closing a specific window
        win_ctrl = ttk.Frame(self.toplevel)
        win_ctrl.grid(row=1, column=0, sticky=tk.EW, padx=10)
        ttk.Label(win_ctrl, text=tr.tl('Windows')+':').grid(row=0, column=0, sticky=tk.W)
        self._windows_combo = ttk.Combobox(win_ctrl, state='readonly', width=24, values=self._window_labels())
        self._windows_combo.grid(row=0, column=1, padx=6, sticky=tk.W)
        ttk.Button(win_ctrl, text=tr.tl('Close selected window'), command=self._close_selected_window).grid(row=0, column=2)

        body = ttk.Frame(self.toplevel)
        body.grid(row=2, column=0, sticky=tk.NSEW, padx=10, pady=6)
        body.columnconfigure(1, weight=1)

        # Table header
        ttk.Label(body, text=tr.tl('Plugin')).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(body, text=tr.tl('Host')).grid(row=0, column=1, sticky=tk.W)
        ttk.Label(body, text=tr.tl('Actions')).grid(row=0, column=2, sticky=tk.W)

        self._rows: List[Dict[str, Any]] = []
        for idx, plugin in enumerate(plug.PLUGINS, start=1):
            ttk.Label(body, text=plugin.name).grid(row=idx, column=0, sticky=tk.W, pady=2)
            host_var = tk.StringVar()
            options = self._host_options()
            host_var.set(self._current_host_label(plugin) or options[0])
            om = ttk.Combobox(body, state='readonly', values=options, textvariable=host_var, width=24)
            om.grid(row=idx, column=1, sticky=tk.EW, pady=2)
            om.bind('<<ComboboxSelected>>', lambda e, p=plugin, v=host_var: self._on_host_change(p, v.get()))
            # Per-plugin action: close hosting window if detached
            action_frame = ttk.Frame(body)
            action_frame.grid(row=idx, column=2, sticky=tk.W)
            close_btn = ttk.Button(action_frame, text=tr.tl('Close window'), command=lambda p=plugin: self._close_host_window(p))
            close_btn.grid(row=0, column=0)
            self._rows.append({"plugin": plugin, "var": host_var, "combo": om, "close": close_btn})

        theme.apply(self.toplevel)
        try:
            self.toplevel.transient(self.parent)
            self.toplevel.grab_set()
        except Exception:
            pass

    def _host_options(self) -> List[str]:
        labels = [tr.tl('Main Window')]
        for i, _ in enumerate(self.manager._windows, start=1):
            labels.append(tr.tl('Window #{N}').format(N=i))
        labels.append(tr.tl('New window…'))
        return labels

    def _window_labels(self) -> List[str]:
        return [tr.tl('Window #{N}').format(N=i) for i, _ in enumerate(self.manager._windows, start=1)]

    def _current_host_label(self, plugin: Any) -> Optional[str]:
        row = self.manager.app._plugin_rows.get(plugin)
        if not row:
            return None
        host = row.get('host')
        if host == 'main':
            return tr.tl('Main Window')
        try:
            idx = self.manager._windows.index(host)
            return tr.tl('Window #{N}').format(N=idx + 1)
        except Exception:
            return None

    def _on_host_change(self, plugin: Any, label: str) -> None:
        if label == tr.tl('Main Window'):
            self.manager.return_to_main(plugin)
        elif label == tr.tl('New window…'):
            win = self.manager.create_window()
            self.manager.move_to_window(plugin, win)
        else:
            # Parse number
            try:
                num = int(label.split('#')[-1])
                idx = max(0, num - 1)
                if 0 <= idx < len(self.manager._windows):
                    self.manager.move_to_window(plugin, self.manager._windows[idx])
            except Exception:
                pass
        self._refresh_options()

    def _refresh_options(self) -> None:
        options = self._host_options()
        for row in self._rows:
            combo: ttk.Combobox = row["combo"]
            var: tk.StringVar = row["var"]
            combo.configure(values=options)
            var.set(self._current_host_label(row["plugin"]) or options[0])
            # Enable/disable close button depending on host
            host_label = self._current_host_label(row["plugin"]) or options[0]
            is_detached = host_label != tr.tl('Main Window')
            try:
                row["close"]["state"] = tk.NORMAL if is_detached else tk.DISABLED
            except Exception:
                pass
        # Refresh windows dropdown
        try:
            labels = self._window_labels()
            self._windows_combo.configure(values=labels)
            if labels:
                self._windows_combo.current(0)
            else:
                self._windows_combo.set('')
        except Exception:
            pass

    def _close_host_window(self, plugin: Any) -> None:
        row = self.manager.app._plugin_rows.get(plugin)
        if not row:
            return
        host = row.get('host')
        if host == 'main' or host not in self.manager._windows:
            return
        self.manager.close_window(host)
        self._refresh_options()

    def _close_selected_window(self) -> None:
        try:
            value = self._windows_combo.get()
            if not value:
                return
            num = int(value.split('#')[-1])
            idx = max(0, num - 1)
            if 0 <= idx < len(self.manager._windows):
                self.manager.close_window(self.manager._windows[idx])
                self._refresh_options()
        except Exception:
            pass

    def _create_window(self) -> None:
        self.manager.create_window()
        self._refresh_options()

    def _close_all(self) -> None:
        self.manager.close_all_windows()
        self._refresh_options()


