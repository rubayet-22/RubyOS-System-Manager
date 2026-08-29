import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import psutil

from process_manager import WINDOWS_PRIORITIES

ANALYSIS_INTERVAL = 2.0   # seconds between optimization scans - a CPU Heavy
                          # process needs only ONE cycle to be detected and
                          # recommended/acted on, so this interval IS the
                          # detection latency; kept short for that reason
POLL_INTERVAL_MS = 200    # how often the GUI drains the analysis queue

CPU_HEAVY_THRESHOLD = 50.0     # percent
MEM_HEAVY_THRESHOLD = 20.0     # percent of total RAM
IDLE_CPU_THRESHOLD = 1.0       # percent
IDLE_STREAK_REQUIRED = 30      # consecutive low-CPU scans (~60s at 2s/scan) -
                                # a process has to sit idle for a full minute,
                                # not just one quiet moment, before it's flagged
IDLE_MIN_MEMORY_PERCENT = 0.5  # percent of total RAM - below this, a process
                                # holds too small a footprint to be worth
                                # bothering the user about, even if idle

PROTECTED_NAMES = {
    "system", "system idle process", "registry", "memory compression",
    "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe",
    "lsass.exe", "explorer.exe", "svchost.exe", "dwm.exe", "fontdrvhost.exe",
}

COLUMNS = ("pid", "name", "cpu", "memory", "priority", "recommendation", "action")
COLUMN_HEADINGS = {
    "pid": "PID",
    "name": "Process Name",
    "cpu": "CPU %",
    "memory": "Memory %",
    "priority": "Current Priority",
    "recommendation": "Recommendation",
    "action": "Action",
}

# Reuse the exact priority-class table process_manager.py already built,
# instead of redefining Windows priority constants a second time.
_WINDOWS_LABEL_BY_VALUE = {}
if os.name == "nt":
    for _label, _const_name in WINDOWS_PRIORITIES:
        _WINDOWS_LABEL_BY_VALUE[getattr(psutil, _const_name)] = _label


def _priority_label(nice_value):
    """Human-readable current priority, matching process_manager.py's naming."""
    if nice_value is None:
        return "N/A"
    if os.name == "nt":
        return _WINDOWS_LABEL_BY_VALUE.get(nice_value, str(nice_value))
    return str(nice_value)


def _is_normal_priority(nice_value):
    """True if there is still a Normal -> Below Normal step left to suggest.

    Used both to decide whether "Idle" is even worth flagging (no point
    recommending a priority drop that already happened) and, later, whether
    Auto Optimization Mode should actually act on this process.
    """
    if nice_value is None:
        return False
    if os.name == "nt":
        return nice_value == psutil.NORMAL_PRIORITY_CLASS
    return 0 <= nice_value < 10


class AdaptiveOptimizer(ttk.Frame):
    """Recommends (and optionally applies) real process priority changes."""

    def __init__(self, parent, status_callback=None):
        super().__init__(parent)
        self.status_callback = status_callback

        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._auto_event = threading.Event()   # set = Auto Optimization Mode
        self._thread = None
        self._after_id = None

        self._own_pid = os.getpid()
        self._idle_streaks = {}     # pid -> consecutive low-CPU scan count,
                                     # worker-thread-only state (single writer)
        self._logged_categories = {}  # pid -> last category logged, worker-only

        self._build_widgets()

        self._thread = threading.Thread(
            target=self._analysis_loop, daemon=True, name="Optimizer-analysis"
        )
        self._thread.start()
        self._after_id = self.after(POLL_INTERVAL_MS, self._drain_queue)

    # -------------------------------------------------------------- widgets

    def _build_widgets(self):
        status_frame = ttk.Frame(self)
        status_frame.pack(fill=tk.X, padx=8, pady=(8, 4))

        self.status_var = tk.StringVar(
            value="System Optimization: ACTIVE (Recommendation Mode)"
        )
        ttk.Label(
            status_frame, textvariable=self.status_var,
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w")

        overview_frame = ttk.LabelFrame(self, text="Current Resource Overview")
        overview_frame.pack(fill=tk.X, padx=8, pady=4)

        self.cpu_overview_var = tk.StringVar(value="CPU Usage: -- %")
        ttk.Label(overview_frame, textvariable=self.cpu_overview_var).pack(
            anchor="w", padx=8, pady=(6, 0)
        )
        self.cpu_overview_bar = ttk.Progressbar(
            overview_frame, maximum=100, mode="determinate"
        )
        self.cpu_overview_bar.pack(fill=tk.X, padx=8, pady=(0, 6))

        self.mem_overview_var = tk.StringVar(value="RAM Usage: -- %")
        ttk.Label(overview_frame, textvariable=self.mem_overview_var).pack(
            anchor="w", padx=8, pady=(0, 0)
        )
        self.mem_overview_bar = ttk.Progressbar(
            overview_frame, maximum=100, mode="determinate"
        )
        self.mem_overview_bar.pack(fill=tk.X, padx=8, pady=(0, 8))

        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=8, pady=4)

        ttk.Button(toolbar, text="Analyze Now", command=self._on_analyze_now).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        self.enable_auto_button = ttk.Button(
            toolbar, text="Enable Auto Optimization", command=self._on_enable_auto
        )
        self.enable_auto_button.pack(side=tk.LEFT, padx=4)
        self.disable_auto_button = ttk.Button(
            toolbar, text="Disable Auto Optimization",
            command=self._on_disable_auto, state=tk.DISABLED,
        )
        self.disable_auto_button.pack(side=tk.LEFT, padx=4)

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 4))

        self.tree = ttk.Treeview(
            tree_frame, columns=COLUMNS, show="headings", selectmode="browse"
        )
        widths = {
            "pid": 70, "name": 160, "cpu": 70, "memory": 80,
            "priority": 110, "recommendation": 320, "action": 140,
        }
        for col in COLUMNS:
            self.tree.heading(col, text=COLUMN_HEADINGS[col])
            anchor = tk.W if col in ("name", "recommendation") else tk.CENTER
            self.tree.column(col, width=widths[col], anchor=anchor)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.LEFT, fill=tk.Y)

        log_frame = ttk.LabelFrame(self, text="Optimization Log")
        log_frame.pack(fill=tk.BOTH, padx=8, pady=(0, 8))

        self.log_text = tk.Text(log_frame, height=8, state=tk.DISABLED, wrap="word")
        log_vsb = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_vsb.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=4)
        log_vsb.pack(side=tk.LEFT, fill=tk.Y, pady=4, padx=(0, 4))

    # --------------------------------------------------------------- thread

    def _analysis_loop(self):
        """Worker thread: scan real processes and classify them every cycle.

        Runs independently of the GUI thread so a slow scan (hundreds of
        processes, each a small blocking psutil call) never freezes the
        window. Only ever writes to self._queue - never to a Tk widget.
        """
        self._warm_up_cpu_percent()

        while not self._stop_event.is_set():
            try:
                snapshot = self._run_one_cycle()
                self._queue.put(snapshot)
            except Exception:
                # A single bad cycle (e.g. a transient psutil/OS hiccup)
                # must never take the analysis thread down.
                self._queue.put({
                    "cpu_overall": 0.0, "mem_percent": 0.0,
                    "rows": [], "log_lines": [],
                })

            self._wake_event.wait(ANALYSIS_INTERVAL)
            self._wake_event.clear()

    def _warm_up_cpu_percent(self):
        """Prime psutil's per-process CPU counters before the first real cycle.

        psutil.Process.cpu_percent() reports usage SINCE THE LAST CALL - the
        very first call for any process always returns 0.0 (there is no
        "since" yet). Without this, a genuinely CPU Heavy process would be
        invisible for one full ANALYSIS_INTERVAL after startup, because its
        first-ever reading is always zero. One throwaway scan here plus a
        short pause means the first REAL cycle already has a valid delta to
        report, instead of the recommendation showing up one interval late.
        """
        try:
            list(psutil.process_iter(attrs=["cpu_percent"]))
        except Exception:
            pass
        self._stop_event.wait(0.5)

    def _run_one_cycle(self):
        """Real one-shot scan: real psutil data in, classified rows out."""
        cpu_overall = psutil.cpu_percent(interval=None)
        mem_percent = psutil.virtual_memory().percent
        auto_mode = self._auto_event.is_set()

        rows = []
        log_lines = []
        seen_pids = set()

        # "status" is intentionally not requested: nothing in this module
        # displays or uses it, and skipping it avoids one extra psutil call
        # per process on every single scan.
        for proc in psutil.process_iter(
            attrs=["pid", "name", "cpu_percent", "memory_percent", "nice"]
        ):
            try:
                info = proc.info
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

            pid = info["pid"]
            name = info["name"] or ""

            # Important Process Protection: never analyze or touch these.
            if pid == self._own_pid or name.lower() in PROTECTED_NAMES:
                continue

            seen_pids.add(pid)
            cpu = info["cpu_percent"] or 0.0
            mem_pct = info["memory_percent"] or 0.0
            nice_value = info["nice"]  # None if psutil couldn't read it (AccessDenied)

            category = self._classify(pid, cpu, mem_pct, nice_value)
            if category is None:
                continue

            recommendation, action, log_line = self._decide_action(
                pid, name, cpu, category, nice_value, auto_mode
            )

            if log_line is not None:
                log_lines.append(log_line)

            rows.append({
                "pid": pid,
                "name": name,
                "cpu": cpu,
                "memory": mem_pct,
                "priority": _priority_label(nice_value),
                "recommendation": recommendation,
                "action": action,
            })

        # Forget idle-streak/log-category memory for processes that no
        # longer exist, so it can't grow without bound over a long session.
        for pid in list(self._idle_streaks):
            if pid not in seen_pids:
                del self._idle_streaks[pid]
        for pid in list(self._logged_categories):
            if pid not in seen_pids:
                del self._logged_categories[pid]

        return {
            "cpu_overall": cpu_overall, "mem_percent": mem_percent,
            "rows": rows, "log_lines": log_lines,
        }

    def _classify(self, pid, cpu, mem_pct, nice_value):
        """CPU Heavy > Memory Heavy > sustained Idle; None = nothing to report.

        Idle detection is intentionally tight, to keep the table meaningful
        instead of flooded: a typical Windows machine has 100+ background
        processes that sit near 0% CPU almost permanently, so "CPU < 1%" by
        itself would flag most of the process table. Three extra conditions
        cut that down to processes actually worth a recommendation:
          1. IDLE_STREAK_REQUIRED - sustained idle (~1 minute), not one quiet
             sampling tick.
          2. IDLE_MIN_MEMORY_PERCENT - skip processes with a negligible
             memory footprint; there is nothing meaningful to reclaim from
             them even if their priority were lowered.
          3. Already-optimized priority - if the process isn't at Normal
             priority any more, there is no recommendation left to make.
        """
        if cpu > CPU_HEAVY_THRESHOLD:
            self._idle_streaks[pid] = 0
            return "CPU Heavy"

        if mem_pct > MEM_HEAVY_THRESHOLD:
            self._idle_streaks[pid] = 0
            return "Memory Heavy"

        if cpu < IDLE_CPU_THRESHOLD:
            streak = self._idle_streaks.get(pid, 0) + 1
            self._idle_streaks[pid] = streak
            if (
                streak >= IDLE_STREAK_REQUIRED
                and mem_pct >= IDLE_MIN_MEMORY_PERCENT
                and _is_normal_priority(nice_value)
            ):
                return "Idle"
            return None

        self._idle_streaks[pid] = 0
        return None

    def _decide_action(self, pid, name, cpu, category, nice_value, auto_mode):
        """Build the recommendation/action text, applying a real change if
        Auto Optimization Mode is on and the process is currently Normal
        priority. Returns (recommendation, action, log_line_or_None).
        """
        timestamp = time.strftime("%H:%M:%S")
        log_line = None
        if self._logged_categories.get(pid) != category:
            self._logged_categories[pid] = category
            log_line = f"{timestamp}\n{name} detected as {category.lower()} (PID {pid})"

        if category == "Memory Heavy":
            return "Process is using excessive memory.", "Warning Only", log_line

        if category == "CPU Heavy":
            recommendation = (
                f"{name} is consuming {cpu:.0f}% CPU. Lowering priority may "
                "improve system responsiveness."
            )
        else:  # Idle
            recommendation = (
                f"{name} has been idle (<{IDLE_CPU_THRESHOLD:.0f}% CPU) for an "
                "extended period. Suggest lowering priority."
            )

        action, extra_log = self._apply_or_suggest_priority(pid, name, nice_value, auto_mode)
        if extra_log is not None:
            log_line = f"{log_line}\n{extra_log}" if log_line else extra_log
        return recommendation, action, log_line

    def _apply_or_suggest_priority(self, pid, name, nice_value, auto_mode):
        """Real psutil.Process.nice() change in Auto mode; suggestion only otherwise.

        Only ever steps a process down ONE level from Normal to Below Normal -
        the exact transition described in the spec - and only ever lowers
        priority, never terminates a process. Re-reading the real priority
        from the OS every cycle means an already-lowered process naturally
        stops being "actionable" without needing any extra bookkeeping.
        """
        if nice_value is None:
            return "Suggested", None

        if not _is_normal_priority(nice_value):
            return "Already Optimized", None

        if os.name == "nt":
            target_value = psutil.BELOW_NORMAL_PRIORITY_CLASS
            current_label, target_label = "Normal", "Below Normal"
        else:
            target_value = min(nice_value + 5, 19)
            current_label, target_label = str(nice_value), str(target_value)

        if not auto_mode:
            return "Suggested", None

        try:
            psutil.Process(pid).nice(target_value)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return "Action Failed", None

        timestamp = time.strftime("%H:%M:%S")
        log_line = (
            f"{timestamp}\nPriority changed: {current_label} -> {target_label} "
            f"for {name} (PID {pid})"
        )
        return "Priority Lowered", log_line

    # ------------------------------------------------------------ GUI thread

    def _drain_queue(self):
        """GUI thread: apply the latest snapshot, append ALL new log lines.

        Unlike a live "current value" (CPU%, the table), log entries are
        historical events - if two analysis cycles queue up before a drain,
        both cycles' log lines must be kept, even though only the newest
        cycle's table/overview values are shown.
        """
        latest_snapshot = None
        all_log_lines = []
        try:
            while True:
                payload = self._queue.get_nowait()
                latest_snapshot = payload
                all_log_lines.extend(payload["log_lines"])
        except queue.Empty:
            pass

        if latest_snapshot is not None:
            self._apply_snapshot(latest_snapshot)
        for line in all_log_lines:
            self._append_log(line)

        self._after_id = self.after(POLL_INTERVAL_MS, self._drain_queue)

    def _apply_snapshot(self, snapshot):
        self.cpu_overview_var.set(f"CPU Usage: {snapshot['cpu_overall']:.1f} %")
        self.cpu_overview_bar["value"] = snapshot["cpu_overall"]
        self.mem_overview_var.set(f"RAM Usage: {snapshot['mem_percent']:.1f} %")
        self.mem_overview_bar["value"] = snapshot["mem_percent"]

        selection = self.tree.selection()
        selected_pid = int(selection[0]) if selection else None

        self.tree.delete(*self.tree.get_children())
        for row in sorted(snapshot["rows"], key=lambda r: r["cpu"], reverse=True):
            values = (
                row["pid"], row["name"], f"{row['cpu']:.1f}",
                f"{row['memory']:.1f}", row["priority"],
                row["recommendation"], row["action"],
            )
            item_id = self.tree.insert("", tk.END, iid=str(row["pid"]), values=values)
            if row["pid"] == selected_pid:
                self.tree.selection_set(item_id)

    def _append_log(self, line):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, line + "\n\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    # --------------------------------------------------------------- actions

    def _on_analyze_now(self):
        """Wake the analysis thread immediately instead of waiting out the interval."""
        self._wake_event.set()
        if self.status_callback:
            self.status_callback("Optimizer: analyzing processes now...")

    def _on_enable_auto(self):
        self._auto_event.set()
        self.status_var.set("System Optimization: ACTIVE (Auto Optimization Mode)")
        self.enable_auto_button.configure(state=tk.DISABLED)
        self.disable_auto_button.configure(state=tk.NORMAL)
        if self.status_callback:
            self.status_callback("Auto Optimization Mode enabled.")

    def _on_disable_auto(self):
        self._auto_event.clear()
        self.status_var.set("System Optimization: ACTIVE (Recommendation Mode)")
        self.enable_auto_button.configure(state=tk.NORMAL)
        self.disable_auto_button.configure(state=tk.DISABLED)
        if self.status_callback:
            self.status_callback("Auto Optimization Mode disabled.")

    # -------------------------------------------------------------- lifecycle

    def shutdown(self):
        """Stop the analysis thread. Called by main.py on window close."""
        self._stop_event.set()
        self._wake_event.set()

        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None

        if self._thread is not None:
            self._thread.join(timeout=ANALYSIS_INTERVAL + 1)
