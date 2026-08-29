# RubyOS System Manager

🎥 **Video Presentation:** [Watch the Project Demonstration]((https://youtu.be/57MwhS7SuYA))

## Overview

**RubyOS System Manager** is a Python-based desktop system management application developed to demonstrate practical Operating System concepts using **real processes, real system resources, real filesystem operations, multithreading, and process scheduling controls**.

Unlike an OS simulator, RubyOS interacts directly with the host operating system. CPU and memory statistics are collected from the actual machine, processes shown in the Process Manager are real running processes, process-control operations affect real PIDs, and file operations modify the real filesystem.

The application provides four main modules:

* System Monitor
* Process Manager
* File Explorer
* Adaptive Process Optimizer

The graphical interface is built using **Tkinter**, while **psutil** provides access to operating-system process and resource information.

---

## Features

### 1. Live System Monitor

The System Monitor provides real-time information about the computer's current resource usage.

**Features:**

* Live overall CPU utilization
* Individual CPU core utilization
* Real-time RAM usage
* Used and total memory display
* Real-time disk usage
* Used and total disk-space display
* Progress-bar based resource visualization
* Automatic periodic resource updates
* Background resource sampling to keep the GUI responsive

Resource information is collected directly from the operating system using `psutil`.

---

### 2. Process Manager

The Process Manager provides information about processes currently running on the operating system and allows the user to perform real process-control operations.

**Process information displayed:**

* Process ID (PID)
* Parent Process ID (PPID)
* Process name
* CPU usage
* Memory usage
* Process status
* Number of threads

**Process management features:**

* Search processes by name, PID, or Parent PID
* Sort processes by different columns
* Terminate a selected process
* Suspend a running process
* Resume a suspended process
* Change process scheduling priority
* Launch a new process from the application
* Automatically locate and highlight newly launched processes
* View real parent-child process relationships through PID and PPID
* Automatic process-list refresh

The module also handles common real-world process conditions such as inaccessible processes, terminated processes, and zombie processes.

---

### 3. File Explorer

The File Explorer provides direct access to the computer's actual filesystem.

**Features:**

* Browse files and directories
* Select available disk/drive roots
* Navigate into folders
* Navigate to parent directories
* Refresh directory contents
* View file and folder names
* View file type
* View file size
* View modification time
* View detailed file information
* Create new folders
* Rename files and folders
* Permanently delete files
* Permanently delete directories and their contents
* Confirmation before destructive delete operations
* Error handling for inaccessible or protected filesystem objects

All operations are performed against real paths on the host computer using Python filesystem APIs.

---

### 4. Adaptive Process Optimizer

The Adaptive Process Optimizer analyzes running processes and provides resource-management recommendations based on their current behavior.

It operates using live process information rather than simulated workloads.

The optimizer can identify:

* **CPU Heavy Processes** — processes consuming more than the configured CPU threshold
* **Memory Heavy Processes** — processes consuming a significant percentage of system memory
* **Long-Idle Processes** — processes remaining below the CPU utilization threshold for an extended period

Two operating modes are available:

#### Recommendation Mode

The optimizer analyzes processes and recommends whether their scheduling priority should be reduced without modifying the process.

#### Auto Optimization Mode

When enabled, the optimizer can perform a real scheduling-priority modification using:

`psutil.Process(pid).nice()`

For eligible CPU-heavy or long-idle processes, the optimizer can reduce the process priority from **Normal** to **Below Normal**, allowing the operating-system scheduler to favor other competing processes.

Additional optimizer features include:

* Manual **Analyze Now** option
* Continuous background process analysis
* Current CPU and RAM overview
* Optimization recommendations
* Current process priority display
* Optimization action status
* Optimization event log
* Protection of important Windows processes
* Protection of RubyOS's own process
* Memory-heavy process warnings without automatic termination
* No automatic process termination

This design allows RubyOS to perform meaningful resource optimization while avoiding unnecessarily dangerous actions.

---

# Operating System Concepts Used

## 1. Process Management

RubyOS interacts with the operating system's actual process table.

Using `psutil.process_iter()`, the application retrieves information about currently executing processes including their PID, PPID, resource utilization, status, and thread count.

The Process Manager can also perform real operations such as:

* Process creation
* Process termination
* Process suspension
* Process resumption

---

## 2. Process Creation and Parent-Child Relationships

Processes can be launched using Python's `subprocess.Popen()`.

When a program such as `notepad.exe` is launched, the operating system creates a real process and assigns it a PID.

RubyOS also displays the process's **Parent PID**, demonstrating the parent-child relationship maintained by the operating system.

---

## 3. CPU Scheduling and Process Priority

RubyOS demonstrates process scheduling concepts through priority management.

Process priority can be changed using:

`psutil.Process(pid).nice()`

On Windows, this corresponds to real Windows scheduling priority classes such as:

* Idle
* Below Normal
* Normal
* Above Normal
* High
* Realtime

Changing process priority influences how favorably the operating-system scheduler treats the process when multiple processes compete for CPU time.

The Adaptive Optimizer uses this mechanism to perform real priority-based resource optimization.

---

## 4. Multithreading

Background worker threads are used for operations that continuously collect system information.

Examples include:

* System-resource monitoring thread
* Process-table refresh thread
* Adaptive optimizer analysis thread

These workers execute separately from Tkinter's main GUI thread, preventing continuous OS queries from freezing the user interface.

---

## 5. Thread Synchronization and Communication

RubyOS uses:

* `threading.Event`
* `queue.Queue`
* Tkinter `after()`

Worker threads collect data but do not directly update Tkinter widgets.

Instead, data is placed into a thread-safe `queue.Queue`. The main GUI thread periodically retrieves the data and updates the interface.

This avoids unsafe concurrent access to GUI components.

`threading.Event` is also used for:

* Graceful worker-thread termination
* Triggering immediate process scans
* Enabling and disabling Auto Optimization Mode

---

## 6. Resource Management

RubyOS monitors actual operating-system resources including:

* CPU utilization
* Per-core CPU utilization
* Physical memory usage
* Disk-space usage
* Per-process CPU consumption
* Per-process memory consumption

The Adaptive Optimizer uses these measurements to classify processes and make resource-management decisions.

---

## 7. File System Management

The File Explorer demonstrates direct interaction with the operating system's filesystem.

Operations include:

* Directory traversal
* Directory creation
* File and directory renaming
* File deletion
* Recursive directory deletion
* Reading file metadata
* Accessing disk partitions

These operations are performed using real filesystem APIs rather than a virtual or simulated filesystem.

---

## 8. System Calls and OS-Level Interaction

RubyOS communicates with operating-system facilities through Python libraries such as `psutil`, `os`, `subprocess`, `pathlib`, and `shutil`.

Examples include:

* Querying running processes
* Reading CPU and memory statistics
* Changing process priority
* Suspending and resuming processes
* Terminating processes
* Creating new processes
* Reading filesystem metadata
* Creating, renaming, and deleting filesystem objects

Although Python provides high-level interfaces, these operations ultimately interact with underlying operating-system services.

---

## 9. Graceful Thread and Application Shutdown

Each background-enabled module provides a shutdown mechanism.

When the RubyOS window is closed:

1. Worker threads receive a stop signal.
2. Active periodic GUI callbacks are cancelled.
3. Worker threads are joined.
4. The Tkinter root window is destroyed.

This prevents background threads from keeping the Python process alive after the GUI has been closed.

---

# Technologies Used

| Technology      | Purpose                                                  |
| --------------- | -------------------------------------------------------- |
| **Python**      | Main programming language                                |
| **Tkinter**     | Desktop graphical user interface                         |
| **ttk**         | Modern Tkinter widgets, tables, tabs and progress bars   |
| **psutil**      | Real system monitoring and process management            |
| **threading**   | Background resource and process monitoring               |
| **queue.Queue** | Thread-safe communication between worker and GUI threads |
| **subprocess**  | Creation of real operating-system processes              |
| **os**          | Process and filesystem operations                        |
| **pathlib**     | Filesystem path handling and metadata access             |
| **shutil**      | Directory deletion and filesystem operations             |
| **time**        | Optimizer timing and event timestamps                    |

---

# Project Architecture

```text
RubyOS_System_Monitor/
│
├── main.py
├── monitor.py
├── process_manager.py
├── file_explorer.py
├── optimizer.py
└── requirements.txt
```

### `main.py`

Application entry point. Creates the main Tkinter window, notebook tabs, shared status bar, and manages graceful application shutdown.

### `monitor.py`

Implements live CPU, per-core CPU, RAM, and disk monitoring using a background sampling thread.

### `process_manager.py`

Implements process listing, searching, sorting, process creation, termination, suspension, resumption, and scheduling-priority control.

### `file_explorer.py`

Implements real filesystem browsing, metadata viewing, folder creation, rename, and deletion operations.

### `optimizer.py`

Implements continuous process analysis, resource classification, optimization recommendations, and optional automatic process-priority adjustment.

---

# Why This Is Not a Simulator

RubyOS System Manager does **not simulate an operating system, process scheduler, filesystem, or resource workload**.

It operates on the actual host operating system:

* CPU values come from the real processor.
* RAM values come from actual physical-memory statistics.
* Disk information comes from the real filesystem.
* Listed PIDs are real operating-system processes.
* Launched applications become real processes.
* Parent PIDs come from the real process hierarchy.
* Suspend and resume affect real processes.
* Termination ends real processes.
* Priority changes modify real scheduling priorities.
* File creation, renaming, and deletion modify the actual filesystem.
* The Adaptive Optimizer analyzes and can modify real running processes.



