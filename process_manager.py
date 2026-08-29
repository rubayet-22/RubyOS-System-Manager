import os
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import psutil

REFRESH_INTERVAL = 2.0   # seconds between process-list refreshes
POLL_INTERVAL_MS = 200   # how often the GUI drains the refresh queue

COLUMNS = ("pid", "ppid", "name", "cpu", "memory", "status", "threads")
COLUMN_HEADINGS = {
    "pid": "PID",
    "ppid": "Parent PID",
    "name": "Name",
    "cpu": "CPU %",
    "memory": "Memory %",
    "status": "Status",
    "threads": "Threads",
}

# Windows priority classes, ordered lowest to highest, used by the priority
# dialog on Windows. On POSIX a plain nice-value entry is used instead.
WINDOWS_PRIORITIES = [
    ("Idle", "IDLE_PRIORITY_CLASS"),
    ("Below Normal", "BELOW_NORMAL_PRIORITY_CLASS"),
    ("Normal", "NORMAL_PRIORITY_CLASS"),
    ("Above Normal", "ABOVE_NORMAL_PRIORITY_CLASS"),
    ("High", "HIGH_PRIORITY_CLASS"),
    ("Realtime", "REALTIME_PRIORITY_CLASS"),
]


class ProcessManager(ttk.Frame):
    """Process listing plus terminate / suspend / resume / priority controls."""

    def __init__(self, parent, status_callback=None):
        super().__init__(parent)
        self.status_callback = status_callback

        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread = None
        self._after_id = None

        self._own_pid = os.getpid()
        self._rows = []              # most recently received row dicts
        self._sort_column = "cpu"
        self._sort_reverse = True
        self._active_filter = ""     # applied search text (empty = no filter)
        self._pending_highlight_pid = None  # PID to select on the next render

        self._build_widgets()

        self._thread = threading.Thread(
            target=self._refresh_loop, daemon=True, name="ProcessManager-refresh"
        )
        self._thread.start()
        self._after_id = self.after(POLL_INTERVAL_MS, self._drain_queue)

    # -------------------------------------------------------------- widgets

    def _build_widgets(self):
        search_bar = ttk.Frame(self)
        search_bar.pack(fill=tk.X, padx=8, pady=(6, 0))

        ttk.Label(search_bar, text="Search Process:").pack(side=tk.LEFT)

        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_bar, textvariable=self.search_var, width=30)
        search_entry.pack(side=tk.LEFT, padx=(4, 4))
        search_entry.bind("<Return>", lambda event: self._on_search())

        ttk.Button(search_bar, text="Search", command=self._on_search).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(search_bar, text="Clear", command=self._on_clear_search).pack(
            side=tk.LEFT, padx=4
        )

        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=8, pady=6)

        ttk.Button(toolbar, text="Terminate", command=self._on_terminate).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(toolbar, text="Suspend", command=self._on_suspend).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(toolbar, text="Resume", command=self._on_resume).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(toolbar, text="Set Priority", command=self._on_priority).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(toolbar, text="Launch Process", command=self._on_launch_process).pack(
            side=tk.LEFT, padx=4
        )

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self.tree = ttk.Treeview(
            tree_frame, columns=COLUMNS, show="headings", selectmode="browse"
        )
        for col in COLUMNS:
            self.tree.heading(
                col, text=COLUMN_HEADINGS[col],
                command=lambda c=col: self._on_sort(c),
            )
            anchor = tk.W if col == "name" else tk.CENTER
            if col == "name":
                width = 220
            elif col == "ppid":
                width = 100
            else:
                width = 90
            self.tree.column(col, width=width, anchor=anchor)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.LEFT, fill=tk.Y)

    # ------------------------------------------------------------------ data

    def _refresh_loop(self):
        """Worker thread: snapshot the process table until stopped."""
        while not self._stop_event.is_set():
            rows = []
            for proc in psutil.process_iter(
                attrs=["pid", "ppid", "name", "cpu_percent", "memory_percent",
                       "status", "num_threads"]
            ):
                try:
                    info = proc.info
                    rows.append({
                        "pid": info["pid"],
                        "ppid": info["ppid"] if info["ppid"] is not None else 0,
                        "name": info["name"] or "",
                        "cpu": info["cpu_percent"] or 0.0,
                        "memory": info["memory_percent"] or 0.0,
                        "status": info["status"] or "",
                        "threads": info["num_threads"] or 0,
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # Process exited or is inaccessible between iteration and
                    # read (including its ppid) - skip it rather than let one
                    # row kill the refresh.
                    continue

            self._queue.put(rows)
            self._wake_event.wait(REFRESH_INTERVAL)
            self._wake_event.clear()

    def _drain_queue(self):
        """GUI thread: apply the newest snapshot to the tree, then reschedule."""
        latest = None
        try:
            while True:
                latest = self._queue.get_nowait()
        except queue.Empty:
            pass

        if latest is not None:
            self._rows = latest
            self._render_rows()

        self._after_id = self.after(POLL_INTERVAL_MS, self._drain_queue)

    def _render_rows(self):
        """Filter self._rows, sort by the active column, repopulate the tree."""
        previous_selected_pid = self._selected_pid()
        highlight_pid = self._pending_highlight_pid

        rows = self._rows
        if self._active_filter:
            query = self._active_filter.lower()
            rows = [
                r for r in rows
                if query in str(r["pid"])
                or query in str(r["ppid"])
                or query in r["name"].lower()
            ]

        rows = sorted(rows, key=lambda r: r[self._sort_column], reverse=self._sort_reverse)

        self.tree.delete(*self.tree.get_children())
        for row in rows:
            values = (
                row["pid"], row["ppid"], row["name"], f"{row['cpu']:.1f}",
                f"{row['memory']:.1f}", row["status"], row["threads"],
            )
            item_id = self.tree.insert("", tk.END, iid=str(row["pid"]), values=values)

            if highlight_pid is not None and row["pid"] == highlight_pid:
                self.tree.selection_set(item_id)
                self.tree.see(item_id)
            elif highlight_pid is None and row["pid"] == previous_selected_pid:
                self.tree.selection_set(item_id)

        if highlight_pid is not None:
            # One-shot: whether or not it was found in this render, don't
            # keep chasing it on future refreshes.
            self._pending_highlight_pid = None

    def _on_search(self):
        """Apply the search box text as a PID / Parent PID / Name filter."""
        self._active_filter = self.search_var.get().strip()
        self._render_rows()

    def _on_clear_search(self):
        """Clear the search box and remove the active filter."""
        self.search_var.set("")
        self._active_filter = ""
        self._render_rows()

    def _on_sort(self, column):
        """Toggle sort direction for the clicked column and re-render."""
        if self._sort_column == column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = False
        self._render_rows()

    def _selected_pid(self):
        """Return the PID of the selected row, or None if nothing is selected."""
        selection = self.tree.selection()
        if not selection:
            return None
        return int(selection[0])

    # --------------------------------------------------------------- actions

    def _on_terminate(self):
        """Confirm, then psutil.Process(pid).terminate(). Refuses own PID."""
        pid = self._selected_pid()
        if pid is None:
            return
        if pid == self._own_pid:
            messagebox.showwarning(
                "Not allowed", "Refusing to terminate RubyOS System Manager itself."
            )
            return

        if not messagebox.askyesno(
            "Confirm Terminate", f"Terminate process {pid}?"
        ):
            return

        self._run_process_action(pid, lambda p: p.terminate(), "terminate")

    def _on_suspend(self):
        """psutil.Process(pid).suspend() on the selected process."""
        pid = self._selected_pid()
        if pid is None:
            return
        self._run_process_action(pid, lambda p: p.suspend(), "suspend")

    def _on_resume(self):
        """psutil.Process(pid).resume() on the selected process."""
        pid = self._selected_pid()
        if pid is None:
            return
        self._run_process_action(pid, lambda p: p.resume(), "resume")

    def _on_priority(self):
        """Ask for a priority level, then psutil.Process(pid).nice(value)."""
        pid = self._selected_pid()
        if pid is None:
            return
        if pid == self._own_pid:
            messagebox.showwarning(
                "Not allowed", "Refusing to change priority of RubyOS System Manager itself."
            )
            return

        if os.name == "nt":
            value = self._ask_windows_priority()
        else:
            value = simpledialog.askinteger(
                "Set Priority",
                "Nice value (-20 highest priority .. 19 lowest priority):",
                minvalue=-20, maxvalue=19,
            )
        if value is None:
            return

        self._run_process_action(pid, lambda p: p.nice(value), "set priority for")

    def _on_launch_process(self):
        """Ask for an executable, then subprocess.Popen() a real new process.

        This is real OS process creation: Windows assigns the new process a
        genuine PID and records this application's own PID as its parent -
        visible afterwards in the Parent PID column once the list refreshes.
        """
        name = simpledialog.askstring(
            "Launch Process",
            "Executable name or path (e.g. notepad.exe, calc.exe):",
        )
        if not name:
            return
        name = name.strip()
        if not name:
            return

        try:
            proc = subprocess.Popen([name])
        except FileNotFoundError:
            messagebox.showerror(
                "Launch failed",
                f"'{name}' was not found. Check the name or path and try again.",
            )
            return
        except PermissionError:
            messagebox.showerror(
                "Launch failed", f"Permission denied trying to launch '{name}'."
            )
            return
        except OSError as exc:
            messagebox.showerror("Launch failed", f"Could not launch '{name}': {exc}")
            return

        if self.status_callback:
            self.status_callback(f"Launched '{name}' as PID {proc.pid}.")

        # Remember the new PID so the next render selects/scrolls to it
        # automatically once it shows up in a real psutil scan.
        self._pending_highlight_pid = proc.pid

        # Wake the refresh thread immediately instead of waiting up to
        # REFRESH_INTERVAL, so the new process (and its Parent PID) shows up
        # in the tree right away.
        self._wake_event.set()

    def _ask_windows_priority(self):
        """Show a small dialog listing Windows priority classes; return the value."""
        names = [name for name, _ in WINDOWS_PRIORITIES]
        choice = {"value": None}

        dialog = tk.Toplevel(self)
        dialog.title("Set Priority")
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        dialog.resizable(False, False)

        ttk.Label(dialog, text="Priority class:").pack(padx=12, pady=(12, 4))

        selected = tk.StringVar(value="Normal")
        combo = ttk.Combobox(
            dialog, textvariable=selected, values=names, state="readonly"
        )
        combo.pack(padx=12, pady=4)

        def on_ok():
            label = selected.get()
            for name, const_name in WINDOWS_PRIORITIES:
                if name == label:
                    choice["value"] = getattr(psutil, const_name)
                    break
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        button_row = ttk.Frame(dialog)
        button_row.pack(pady=(4, 12))
        ttk.Button(button_row, text="OK", command=on_ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(button_row, text="Cancel", command=on_cancel).pack(side=tk.LEFT, padx=4)

        dialog.wait_window()
        return choice["value"]

    def _run_process_action(self, pid, action, verb):
        """Run a psutil action on pid, reporting the errors that genuinely occur."""
        try:
            proc = psutil.Process(pid)
            action(proc)
            if self.status_callback:
                self.status_callback(f"{verb.capitalize()}d process {pid}.")
        except psutil.NoSuchProcess:
            messagebox.showerror(
                "No such process", f"Process {pid} no longer exists."
            )
        except psutil.AccessDenied:
            messagebox.showerror(
                "Access denied", f"Access denied trying to {verb} process {pid}."
            )
        except psutil.ZombieProcess:
            messagebox.showerror(
                "Zombie process", f"Process {pid} is a zombie and cannot be controlled."
            )

    # -------------------------------------------------------------- lifecycle

    def shutdown(self):
        """Stop the refresh thread. Called by main.py on window close."""
        self._stop_event.set()
        self._wake_event.set()

        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None

        if self._thread is not None:
            self._thread.join(timeout=REFRESH_INTERVAL + 1)
