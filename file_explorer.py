import os
import shutil
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

import psutil

COLUMNS = ("name", "type", "size", "modified")
COLUMN_HEADINGS = {
    "name": "Name",
    "type": "Type",
    "size": "Size",
    "modified": "Modified",
}


def _format_size(num_bytes):
    """Human-readable size, e.g. 1536 -> '1.5 KB'."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024


def _format_time(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


class FileExplorer(ttk.Frame):
    """Directory browser with create-folder, rename and delete operations."""

    def __init__(self, parent, status_callback=None):
        super().__init__(parent)
        self.status_callback = status_callback

        self.current_path = Path.home()

        self._build_widgets()
        self._populate(self.current_path)

    # -------------------------------------------------------------- widgets

    def _build_widgets(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=8, pady=6)

        ttk.Label(toolbar, text="Drive:").pack(side=tk.LEFT)

        drives = [p.mountpoint for p in psutil.disk_partitions() if p.mountpoint]
        self.drive_var = tk.StringVar(value=str(self.current_path.anchor))
        self.drive_combo = ttk.Combobox(
            toolbar, textvariable=self.drive_var, values=drives,
            state="readonly", width=20,
        )
        self.drive_combo.pack(side=tk.LEFT, padx=(4, 12))
        self.drive_combo.bind("<<ComboboxSelected>>", self._on_drive_selected)

        ttk.Button(toolbar, text="Up", command=self._on_up).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Refresh", command=self._on_refresh).pack(
            side=tk.LEFT, padx=4
        )

        self.path_var = tk.StringVar(value=str(self.current_path))
        ttk.Label(toolbar, textvariable=self.path_var, anchor="w").pack(
            side=tk.LEFT, padx=12, fill=tk.X, expand=True
        )

        action_bar = ttk.Frame(self)
        action_bar.pack(fill=tk.X, padx=8)

        ttk.Button(action_bar, text="New Folder", command=self._on_create_folder).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(action_bar, text="Rename", command=self._on_rename).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(action_bar, text="Delete", command=self._on_delete).pack(
            side=tk.LEFT, padx=4
        )

        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        tree_frame = ttk.Frame(body)
        tree_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(
            tree_frame, columns=COLUMNS, show="headings", selectmode="browse"
        )
        for col in COLUMNS:
            self.tree.heading(col, text=COLUMN_HEADINGS[col])
            anchor = tk.W if col == "name" else tk.CENTER
            width = 260 if col == "name" else 120
            self.tree.column(col, width=width, anchor=anchor)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.LEFT, fill=tk.Y)

        self.tree.bind("<Double-1>", self._on_open)
        self.tree.bind("<<TreeviewSelect>>", self._show_info)

        info_frame = ttk.LabelFrame(body, text="Info")
        info_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(8, 0))

        self.info_path_var = tk.StringVar(value="-")
        self.info_size_var = tk.StringVar(value="-")
        self.info_modified_var = tk.StringVar(value="-")
        self.info_readonly_var = tk.StringVar(value="-")

        for label, var in (
            ("Full path:", self.info_path_var),
            ("Size:", self.info_size_var),
            ("Modified:", self.info_modified_var),
            ("Read-only:", self.info_readonly_var),
        ):
            row = ttk.Frame(info_frame)
            row.pack(fill=tk.X, padx=8, pady=4, anchor="w")
            ttk.Label(row, text=label, width=10, anchor="w").pack(side=tk.LEFT)
            ttk.Label(row, textvariable=var, wraplength=200, anchor="w").pack(
                side=tk.LEFT
            )

    # ------------------------------------------------------------ navigation

    def _populate(self, path):
        """List `path` into the tree. Reports PermissionError to the user."""
        try:
            entries = list(os.scandir(path))
        except (PermissionError, FileNotFoundError) as exc:
            messagebox.showerror("Cannot open folder", str(exc))
            return

        self.current_path = Path(path)
        self.path_var.set(str(self.current_path))

        self.tree.delete(*self.tree.get_children())

        folders = []
        files = []
        for entry in entries:
            try:
                is_dir = entry.is_dir()
                stat = entry.stat()
            except (PermissionError, FileNotFoundError, OSError):
                continue

            row = {
                "name": entry.name,
                "type": "Folder" if is_dir else "File",
                "size": "" if is_dir else _format_size(stat.st_size),
                "modified": _format_time(stat.st_mtime),
            }
            (folders if is_dir else files).append(row)

        folders.sort(key=lambda r: r["name"].lower())
        files.sort(key=lambda r: r["name"].lower())

        for row in folders + files:
            self.tree.insert(
                "", tk.END, iid=row["name"],
                values=(row["name"], row["type"], row["size"], row["modified"]),
            )

        if self.status_callback:
            self.status_callback(f"Listed {len(folders) + len(files)} entries.")

    def _on_refresh(self):
        self._populate(self.current_path)

    def _on_drive_selected(self, event=None):
        self._populate(Path(self.drive_var.get()))

    def _on_open(self, event=None):
        """Double-click: enter the selected folder (ignore files)."""
        path = self._selected_path()
        if path is not None and path.is_dir():
            self._populate(path)

    def _on_up(self):
        """Navigate to the parent directory, stopping at the drive root."""
        parent = self.current_path.parent
        if parent != self.current_path:
            self._populate(parent)

    def _selected_path(self):
        """Return the Path of the selected row, or None."""
        selection = self.tree.selection()
        if not selection:
            return None
        return self.current_path / selection[0]

    def _show_info(self, event=None):
        """Fill the information panel from the selected entry's os.stat()."""
        path = self._selected_path()
        if path is None:
            self.info_path_var.set("-")
            self.info_size_var.set("-")
            self.info_modified_var.set("-")
            self.info_readonly_var.set("-")
            return

        try:
            stat = path.stat()
        except (PermissionError, FileNotFoundError) as exc:
            messagebox.showerror("Cannot read info", str(exc))
            return

        self.info_path_var.set(str(path))
        self.info_size_var.set("-" if path.is_dir() else _format_size(stat.st_size))
        self.info_modified_var.set(_format_time(stat.st_mtime))
        is_readonly = not os.access(path, os.W_OK)
        self.info_readonly_var.set("Yes" if is_readonly else "No")

    # -------------------------------------------------------------- actions

    def _on_create_folder(self):
        """Prompt for a name, then os.mkdir() inside the current directory."""
        name = simpledialog.askstring("New Folder", "Folder name:")
        if not name:
            return

        new_path = self.current_path / name
        try:
            os.mkdir(new_path)
        except FileExistsError:
            messagebox.showerror("Cannot create folder", f"'{name}' already exists.")
            return
        except PermissionError as exc:
            messagebox.showerror("Cannot create folder", str(exc))
            return

        self._populate(self.current_path)
        if self.status_callback:
            self.status_callback(f"Created folder '{name}'.")

    def _on_rename(self):
        """Prompt for a new name, then os.rename() the selected entry."""
        path = self._selected_path()
        if path is None:
            return

        new_name = simpledialog.askstring(
            "Rename", "New name:", initialvalue=path.name
        )
        if not new_name or new_name == path.name:
            return

        new_path = path.with_name(new_name)
        try:
            os.rename(path, new_path)
        except FileExistsError:
            messagebox.showerror("Cannot rename", f"'{new_name}' already exists.")
            return
        except (PermissionError, FileNotFoundError) as exc:
            messagebox.showerror("Cannot rename", str(exc))
            return

        self._populate(self.current_path)
        if self.status_callback:
            self.status_callback(f"Renamed '{path.name}' to '{new_name}'.")

    def _on_delete(self):
        """Confirm, then os.remove() a file or shutil.rmtree() a folder."""
        path = self._selected_path()
        if path is None:
            return

        kind = "folder and all its contents" if path.is_dir() else "file"
        if not messagebox.askyesno(
            "Confirm Delete", f"Permanently delete this {kind}?\n\n{path}"
        ):
            return

        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                os.remove(path)
        except FileNotFoundError:
            messagebox.showerror("Cannot delete", "That item no longer exists.")
        except PermissionError as exc:
            messagebox.showerror("Cannot delete", str(exc))
        else:
            if self.status_callback:
                self.status_callback(f"Deleted '{path.name}'.")

        self._populate(self.current_path)

    # ------------------------------------------------------------ lifecycle

    def shutdown(self):
        """No worker threads to stop; present so main.py can treat tabs alike."""
        pass
