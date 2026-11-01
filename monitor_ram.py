#!/usr/bin/env python3
"""Lightweight RAM monitor for the Island Pill process.

Continuously samples /proc/<PID>/smaps_rollup for the running
island_pill.py process and appends timestamped measurements to
ram_log.csv. Uses only the Python standard library. Does not modify
the Island Pill application or its installer.

Usage:
    python3 monitor_ram.py start [-i SECONDS]   # start background monitoring
    python3 monitor_ram.py stop                 # stop background monitoring
    python3 monitor_ram.py status               # show monitoring status
"""

import argparse
import csv
import datetime
import os
import signal
import subprocess
import sys
import time

SCRIPT_NAME = "island_pill.py"
LOG_FILE = "ram_log.csv"
PID_FILE = "monitor_ram.pid"
LOG_FILE_MONITOR = "monitor_ram.log"
DEFAULT_INTERVAL = 5.0
STOP_HOUR = 20
STOP_MINUTE = 0

FIELDS = (
    "Rss",
    "Pss",
    "Private_Clean",
    "Private_Dirty",
    "Shared_Clean",
    "Shared_Dirty",
)

CSV_HEADER = [
    "timestamp",
    "pid",
    "status",
    "rss_kb",
    "pss_kb",
    "private_clean_kb",
    "private_dirty_kb",
    "shared_clean_kb",
    "shared_dirty_kb",
]


def find_island_pill_pid():
    """Return the PID of the running island_pill.py process, or None.

    Identifies the process by scanning /proc/*/cmdline for the
    island_pill.py script path, so no assumed PID is required.
    """
    own_pid = os.getpid()
    try:
        entries = os.listdir("/proc")
    except OSError:
        return None
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == own_pid:
            continue
        cmdline_path = os.path.join("/proc", entry, "cmdline")
        try:
            with open(cmdline_path, "rb") as f:
                cmdline = f.read()
        except OSError:
            continue
        if not cmdline:
            continue
        parts = [
            p.decode("utf-8", "replace")
            for p in cmdline.split(b"\0")
            if p
        ]
        if any("island_pill.py" in p for p in parts):
            return pid
    return None


def read_smaps(pid):
    """Read the tracked fields from /proc/<pid>/smaps_rollup.

    Returns a dict mapping field name to kilobytes, or None if the
    file is unavailable or incomplete.
    """
    path = os.path.join("/proc", str(pid), "smaps_rollup")
    values = {}
    try:
        with open(path, "r") as f:
            for line in f:
                for field in FIELDS:
                    prefix = field + ":"
                    if line.startswith(prefix):
                        rest = line[len(prefix):].strip()
                        if rest:
                            values[field] = int(rest.split()[0])
                        break
    except OSError:
        return None
    if len(values) != len(FIELDS):
        return None
    return values


def init_log():
    """Create the log file with a CSV header if it does not exist."""
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADER)


def append_row(row):
    """Append one row to the CSV log (append-only, never overwrite)."""
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(row)


def read_pid_file():
    """Return the PID stored in the pid file, or None."""
    try:
        with open(PID_FILE, "r") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def write_pid_file(pid):
    with open(PID_FILE, "w") as f:
        f.write(str(pid) + "\n")


def remove_pid_file():
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def is_process_alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def is_monitor_process(pid):
    """Return True if /proc/<pid>/cmdline references monitor_ram.py."""
    try:
        with open(os.path.join("/proc", str(pid), "cmdline"), "rb") as f:
            cmdline = f.read()
    except OSError:
        return False
    parts = [p.decode("utf-8", "replace") for p in cmdline.split(b"\0") if p]
    return any("monitor_ram.py" in p for p in parts)


def today_stop_time(now):
    """Return the datetime of today's 20:00 (local time)."""
    return now.replace(hour=STOP_HOUR, minute=STOP_MINUTE, second=0, microsecond=0)


def run_monitoring(interval):
    """Main monitoring loop (runs as the detached background process)."""
    stop_flag = {"flag": False}

    def handle_signal(signum, frame):
        stop_flag["flag"] = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    init_log()
    running = False
    last_pid = None
    sys.stderr.write(
        "monitor_ram started (pid %d), interval %.1fs, stop at 20:00 local\n"
        % (os.getpid(), interval)
    )
    sys.stderr.flush()

    while not stop_flag["flag"]:
        now = datetime.datetime.now()
        # Automatic daily stop at 20:00 local time. Also stops as soon as the
        # machine resumes if it slept through 20:00.
        if now >= today_stop_time(now):
            sys.stderr.write("reached automatic stop time 20:00; shutting down\n")
            break

        pid = find_island_pill_pid()
        ts = datetime.datetime.now().isoformat(timespec="seconds")

        if pid is None:
            if running:
                sys.stderr.write("island_pill.py stopped (was pid %d)\n" % last_pid)
                running = False
                last_pid = None
            row = [ts, "", "not_running"] + [""] * 6
            append_row(row)
            sys.stderr.write("  %s  island_pill.py not running\n" % ts)
        else:
            smaps = read_smaps(pid)
            if smaps is None:
                row = [ts, pid, "smaps_unavailable"] + [""] * 6
                append_row(row)
                sys.stderr.write("  %s  pid=%d  smaps_rollup unavailable\n" % (ts, pid))
            else:
                if not running or pid != last_pid:
                    if running:
                        sys.stderr.write(
                            "island_pill.py pid changed %d -> %d\n"
                            % (last_pid, pid)
                        )
                    else:
                        sys.stderr.write(
                            "island_pill.py running as pid %d\n" % pid
                        )
                    running = True
                    last_pid = pid
                row = [
                    ts,
                    pid,
                    "running",
                    smaps["Rss"],
                    smaps["Pss"],
                    smaps["Private_Clean"],
                    smaps["Private_Dirty"],
                    smaps["Shared_Clean"],
                    smaps["Shared_Dirty"],
                ]
                append_row(row)
                sys.stderr.write(
                    "  %s  pid=%d  RSS=%skB  PSS=%skB  PrivD=%skB  ShrD=%skB\n"
                    % (
                        ts,
                        pid,
                        smaps["Rss"],
                        smaps["Pss"],
                        smaps["Private_Dirty"],
                        smaps["Shared_Dirty"],
                    )
                )

        # Sleep in small increments so signals and the 20:00 stop are handled
        # promptly without busy-waiting.
        deadline = time.monotonic() + interval
        while time.monotonic() < deadline and not stop_flag["flag"]:
            time.sleep(min(0.2, deadline - time.monotonic()))

    sys.stderr.write("monitor_ram shutting down\n")
    sys.stderr.flush()


def cmd_start(interval):
    """Start background monitoring."""
    pid = read_pid_file()
    if pid:
        if is_process_alive(pid) and is_monitor_process(pid):
            print("monitor_ram is already running (pid %d)" % pid)
            return 1
        # Stale pid file.
        remove_pid_file()

    now = datetime.datetime.now()
    today_stop = today_stop_time(now)
    if now >= today_stop:
        print(
            "Refusing to start: current time %s is at or after the "
            "automatic stop time 20:00 local time." % now.strftime("%H:%M")
        )
        return 1

    log_path = os.path.abspath(LOG_FILE_MONITOR)
    with open(log_path, "ab") as log_f:
        proc = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), "_run", str(interval)],
            stdin=subprocess.DEVNULL,
            stdout=log_f,
            stderr=log_f,
            start_new_session=True,
        )
    write_pid_file(proc.pid)
    print(
        "Started monitor_ram (pid %d), interval %.1fs, log %s, CSV %s"
        % (proc.pid, interval, log_path, os.path.abspath(LOG_FILE))
    )
    print("Automatic stop at 20:00 local time each day.")
    return 0


def cmd_stop():
    """Stop background monitoring."""
    pid = read_pid_file()
    if not pid:
        print("monitor_ram is not running (no pid file)")
        return 1
    if not is_process_alive(pid):
        print("monitor_ram pid file is stale; removing")
        remove_pid_file()
        return 1
    if not is_monitor_process(pid):
        print("pid %d is not a monitor_ram process; not stopping" % pid)
        return 1
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as e:
        print("failed to signal pid %d: %s" % (pid, e))
        remove_pid_file()
        return 1
    for _ in range(50):
        if not is_process_alive(pid):
            break
        time.sleep(0.1)
    if is_process_alive(pid):
        print("pid %d did not exit; sending SIGKILL" % pid)
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    remove_pid_file()
    print("Stopped monitor_ram (pid %d)" % pid)
    return 0


def cmd_status():
    """Show monitoring status."""
    pid = read_pid_file()
    now = datetime.datetime.now()
    print("monitor_ram status")
    print("  automatic stop time: daily 20:00 local time")
    print("  next stop: %s" % today_stop_time(now).strftime("%Y-%m-%d %H:%M:%S"))
    print("  csv log: %s" % os.path.abspath(LOG_FILE))
    print("  pid file: %s" % os.path.abspath(PID_FILE))
    print("  monitor log: %s" % os.path.abspath(LOG_FILE_MONITOR))
    if not pid:
        print("  status: not running")
        return 0
    if is_process_alive(pid) and is_monitor_process(pid):
        print("  status: running (pid %d)" % pid)
        return 0
    print("  status: not running (stale pid file %d)" % pid)
    return 1


def main():
    parser = argparse.ArgumentParser(
        description="Monitor Island Pill process RAM usage and log to ram_log.csv.",
    )
    sub = parser.add_subparsers(dest="command")

    p_start = sub.add_parser("start", help="start background monitoring")
    p_start.add_argument(
        "-i",
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help="sampling interval in seconds (default: %(default)s)",
    )

    sub.add_parser("stop", help="stop background monitoring")
    sub.add_parser("status", help="show monitoring status")

    p_run = sub.add_parser("_run", help=argparse.SUPPRESS)
    p_run.add_argument("interval_arg", nargs="?", default=str(DEFAULT_INTERVAL))

    args = parser.parse_args()

    if args.command == "start":
        return cmd_start(args.interval)
    if args.command == "stop":
        return cmd_stop()
    if args.command == "status":
        return cmd_status()
    if args.command == "_run":
        try:
            interval = float(args.interval_arg)
        except ValueError:
            interval = DEFAULT_INTERVAL
        run_monitoring(interval)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
