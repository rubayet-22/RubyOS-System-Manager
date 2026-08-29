import os
import queue
import threading
import tkinter as tk
from tkinter import ttk

import psutil

SAMPLE_INTERVAL = 1.0   # seconds between samples
POLL_INTERVAL_MS = 200  # how often the GUI drains the sample queue

GB = 1024 ** 3
DISK_PATH = os.path.abspath(os.sep)  # e.g. "C:\\" on Windows, "/" on POSIX


class SystemMonitor(ttk.Frame):
    """Live CPU / RAM / disk readouts backed by a sampler thread."""

    def __init__(self, parent, status_callback=None):
        super().__init__(parent)
        self.status_callback = status_callback

        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = None
        self._after_id = None

        self._core_count = psutil.cpu_count(logical=True) or 1
        self._core_bars = []
        self._core_labels = []

        self._build_widgets()

        self._thread = threading.Thread(
            target=self._sampler_loop, daemon=True, name="SystemMonitor-sampler"
        )
        self._thread.start()
        self._after_id = self.after(POLL_INTERVAL_MS, self._drain_queue)

    # -------------------------------------------------------------- widgets

    def _build_widgets(self):
        padding = {"padx": 10, "pady": 6}

        # CPU section
        cpu_frame = ttk.LabelFrame(self, text="CPU")
        cpu_frame.pack(fill=tk.X, **padding)

        self.cpu_label = ttk.Label(cpu_frame, text="CPU: -- %")
        self.cpu_label.pack(anchor="w", padx=8, pady=(6, 0))

        self.cpu_bar = ttk.Progressbar(cpu_frame, maximum=100, mode="determinate")
        self.cpu_bar.pack(fill=tk.X, padx=8, pady=(0, 8))

        # Per-core section
        core_frame = ttk.LabelFrame(self, text="Per-Core CPU")
        core_frame.pack(fill=tk.X, **padding)

        for i in range(self._core_count):
            row = ttk.Frame(core_frame)
            row.pack(fill=tk.X, padx=8, pady=2)

            label = ttk.Label(row, text=f"Core {i}: -- %", width=14, anchor="w")
            label.pack(side=tk.LEFT)

            bar = ttk.Progressbar(row, maximum=100, mode="determinate")
            bar.pack(side=tk.LEFT, fill=tk.X, expand=True)

            self._core_labels.append(label)
            self._core_bars.append(bar)

        # Memory section
        mem_frame = ttk.LabelFrame(self, text="Memory (RAM)")
        mem_frame.pack(fill=tk.X, **padding)

        self.mem_label = ttk.Label(mem_frame, text="RAM: -- % (-- GB / -- GB)")
        self.mem_label.pack(anchor="w", padx=8, pady=(6, 0))

        self.mem_bar = ttk.Progressbar(mem_frame, maximum=100, mode="determinate")
        self.mem_bar.pack(fill=tk.X, padx=8, pady=(0, 8))

        # Disk section
        disk_frame = ttk.LabelFrame(self, text=f"Disk ({DISK_PATH})")
        disk_frame.pack(fill=tk.X, **padding)

        self.disk_label = ttk.Label(disk_frame, text="Disk: -- % (-- GB / -- GB)")
        self.disk_label.pack(anchor="w", padx=8, pady=(6, 0))

        self.disk_bar = ttk.Progressbar(disk_frame, maximum=100, mode="determinate")
        self.disk_bar.pack(fill=tk.X, padx=8, pady=(0, 8))

    # --------------------------------------------------------------- thread

    def _sampler_loop(self):
        """Worker thread: sample psutil until the stop event is set."""
        while not self._stop_event.is_set():
            try:
                # Blocks for SAMPLE_INTERVAL, measuring per-core usage over
                # that window; the immediate non-blocking call right after
                # reads the overall percent from that same window.
                per_core = psutil.cpu_percent(interval=SAMPLE_INTERVAL, percpu=True)
                overall = psutil.cpu_percent(interval=None)
                memory = psutil.virtual_memory()
                disk = psutil.disk_usage(DISK_PATH)
            except Exception:
                # Sampling errors should not kill the thread; skip this tick.
                self._stop_event.wait(SAMPLE_INTERVAL)
                continue

            sample = {
                "cpu_overall": overall,
                "cpu_per_core": per_core,
                "mem_percent": memory.percent,
                "mem_used_gb": memory.used / GB,
                "mem_total_gb": memory.total / GB,
                "disk_percent": disk.percent,
                "disk_used_gb": disk.used / GB,
                "disk_total_gb": disk.total / GB,
            }
            self._queue.put(sample)

    def _drain_queue(self):
        """GUI thread: apply the newest sample to the widgets, then reschedule."""
        latest = None
        try:
            while True:
                latest = self._queue.get_nowait()
        except queue.Empty:
            pass

        if latest is not None:
            self._apply_sample(latest)

        self._after_id = self.after(POLL_INTERVAL_MS, self._drain_queue)

    def _apply_sample(self, sample):
        self.cpu_label.config(text=f"CPU: {sample['cpu_overall']:.1f} %")
        self.cpu_bar["value"] = sample["cpu_overall"]

        for i, pct in enumerate(sample["cpu_per_core"]):
            if i >= len(self._core_bars):
                break
            self._core_labels[i].config(text=f"Core {i}: {pct:.1f} %")
            self._core_bars[i]["value"] = pct

        self.mem_label.config(
            text=(
                f"RAM: {sample['mem_percent']:.1f} % "
                f"({sample['mem_used_gb']:.1f} GB / {sample['mem_total_gb']:.1f} GB)"
            )
        )
        self.mem_bar["value"] = sample["mem_percent"]

        self.disk_label.config(
            text=(
                f"Disk: {sample['disk_percent']:.1f} % "
                f"({sample['disk_used_gb']:.1f} GB / {sample['disk_total_gb']:.1f} GB)"
            )
        )
        self.disk_bar["value"] = sample["disk_percent"]

    # ------------------------------------------------------------ lifecycle

    def shutdown(self):
        """Stop the sampler thread. Called by main.py on window close."""
        self._stop_event.set()

        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None

        if self._thread is not None:
            self._thread.join(timeout=SAMPLE_INTERVAL + 1)
