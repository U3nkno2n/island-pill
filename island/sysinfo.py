"""Pure system-information readers moved verbatim from island_pill.py
(Stage 2.1). Formatting helpers, /proc and /sys pollers, download helpers
and PARTIAL_EXT live here as the single source; island_pill re-imports the
names so every host-side consumer keeps working. stdlib only (os, time) --
no GTK/gi, so everything below is headless-testable.
"""

import os
import time

# browsers' unfinished files
PARTIAL_EXT = (".part", ".crdownload", ".opdownload", ".download")


def fmt_rate(bps):
    if bps >= 104857600:
        return "%d MB/s" % int(bps / 1048576.0)
    if bps >= 1048576:
        return "%.1f MB/s" % (bps / 1048576.0)
    return "%d KB/s" % int(bps / 1024)


def fmt_size(n):
    if n >= 1073741824:
        return "%.1f GB" % (n / 1073741824.0)
    if n >= 1048576:
        return "%d MB" % int(n / 1048576)
    return "%d KB" % int(n / 1024)


def read_cpu():
    with open("/proc/stat") as f:
        v = [int(x) for x in f.readline().split()[1:9]]
    return v[3] + v[4], sum(v)  # idle, total


def read_mem():
    total = avail = 0
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemTotal:"):
                total = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                avail = int(line.split()[1])
                break
    return (total - avail) / 1048576.0, total / 1048576.0  # GiB used, total


def find_temp_file():
    best = None
    try:
        for d in sorted(os.listdir("/sys/class/hwmon")):
            base = "/sys/class/hwmon/" + d
            try:
                with open(base + "/name") as f:
                    name = f.read().strip()
            except OSError:
                continue
            f = base + "/temp1_input"
            if name in ("k10temp", "coretemp", "zenpower") and os.path.exists(f):
                return f
            if name in ("acpitz", "cpu_thermal") and os.path.exists(f) and best is None:
                best = f
    except OSError:
        pass
    return best


def read_temp(path):
    if not path:
        return None
    try:
        with open(path) as f:
            return int(f.read()) / 1000.0
    except (OSError, ValueError):
        return None


def net_ifaces():
    """Physical network interfaces only. Loopback, bridges, docker and VPN tunnels are virtual
    (their traffic also crosses a physical interface, so counting them would double it)."""
    out = []
    try:
        for n in os.listdir("/sys/class/net"):
            if "/virtual/" not in os.path.realpath("/sys/class/net/" + n):
                out.append(n)
    except OSError:
        pass
    return out


def read_net_rx(names):
    """Bytes received so far on the given interfaces."""
    total = 0
    with open("/proc/net/dev") as f:
        for line in f.readlines()[2:]:
            name, _, rest = line.partition(":")
            if name.strip() in names:
                total += int(rest.split()[0])
    return total


def download_dir():
    home = os.path.expanduser("~")
    try:
        with open(os.path.join(home, ".config", "user-dirs.dirs")) as f:
            for line in f:
                if line.startswith("XDG_DOWNLOAD_DIR"):
                    p = line.split("=", 1)[1].strip().strip('"').replace("$HOME", home)
                    if p:
                        return p
    except OSError:
        pass
    return os.path.join(home, "Downloads")


def find_partial(dirpath):
    """Newest unfinished browser download (.part / .crdownload ...) touched in the last 8 s."""
    best = None
    now = time.time()
    try:
        with os.scandir(dirpath) as it:
            for e in it:
                if e.name.endswith(PARTIAL_EXT):
                    try:
                        mt = e.stat().st_mtime
                    except OSError:
                        continue
                    if now - mt < 8 and (best is None or mt > best[1]):
                        best = (e.name, mt)
    except OSError:
        return None
    return os.path.splitext(best[0])[0] if best else None
