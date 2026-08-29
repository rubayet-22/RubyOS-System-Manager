import tkinter as tk
from tkinter import ttk

from monitor import SystemMonitor
from process_manager import ProcessManager
from file_explorer import FileExplorer
from optimizer import AdaptiveOptimizer

APP_TITLE = "RubyOS System Manager"
APP_GEOMETRY = "1000x650"


class RubyOSApp:
    """Top-level application window: notebook, tabs and status bar."""

    def __init__(self, root):
        self.root = root
        self.tabs = []          # feature frames, each exposing shutdown()

        self.root.title(APP_TITLE)
        self.root.geometry(APP_GEOMETRY)
        self.root.minsize(800, 500)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(
            self.root, textvariable=self.status_var, anchor="w",
            relief=tk.SUNKEN, padding=(6, 2),
        )
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        monitor_tab = SystemMonitor(self.notebook, status_callback=self.set_status)
        process_tab = ProcessManager(self.notebook, status_callback=self.set_status)
        file_tab = FileExplorer(self.notebook, status_callback=self.set_status)
        optimizer_tab = AdaptiveOptimizer(self.notebook, status_callback=self.set_status)

        self.notebook.add(monitor_tab, text="System Monitor")
        self.notebook.add(process_tab, text="Process Manager")
        self.notebook.add(file_tab, text="File Explorer")
        self.notebook.add(optimizer_tab, text="Optimizer")

        self.tabs = [monitor_tab, process_tab, file_tab, optimizer_tab]

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def set_status(self, message):
        """Write a message into the shared status bar (called by the tabs)."""
        self.status_var.set(message)

    def on_close(self):
        """Stop every tab's worker threads, then destroy the window.

        Each tab's shutdown() runs even if another tab's shutdown() raises -
        an exception here is a Tk callback exception, which Tk swallows after
        printing a traceback, silently skipping the rest of this method
        (including root.destroy()) if it isn't caught here first.
        """
        for tab in self.tabs:
            try:
                tab.shutdown()
            except Exception:
                import traceback
                traceback.print_exc()
        self.root.destroy()


def main():
    root = tk.Tk()
    RubyOSApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
