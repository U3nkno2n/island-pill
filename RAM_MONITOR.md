# Island Pill RAM Monitor (`monitor_ram.py`)

Standalone development utility that continuously measures the actual memory
consumption of the running Island Pill process and appends timestamped
readings to `ram_log.csv`.

This is **not** part of the GTK application. It does not modify
`island_pill.py`, `install.sh`, or any other application file, and it adds no
runtime overhead to Island Pill itself.

## What it measures

For the running `island_pill.py` process, it reads `/proc/<PID>/smaps_rollup`
and records:

- **Rss** — Resident Set Size
- **Pss** — Proportional Set Size
- **Private_Clean**
- **Private_Dirty**
- **Shared_Clean**
- **Shared_Dirty**

All values are in kilobytes (kB), matching `/proc` units.

Each log row also records the timestamp (ISO 8601), the PID, and a status
(`running`, `not_running`, or `smaps_unavailable`).

## Commands

### Start monitoring (background)

```bash
python3 monitor_ram.py start
```

Launches the monitor in the background, returns control to the terminal
immediately, and keeps running after the terminal is closed. A pid file
(`monitor_ram.pid`) is written so only one instance runs at a time. Output
goes to `monitor_ram.log`.

### Start with a custom interval

```bash
python3 monitor_ram.py start --interval 2
python3 monitor_ram.py start -i 10
```

The interval must be a positive number (fractional seconds allowed).

### Stop monitoring

```bash
python3 monitor_ram.py stop
```

Stops only the monitor process (not Island Pill), cleans up the pid file,
and preserves all existing CSV records.

### Show status

```bash
python3 monitor_ram.py status
```

Shows whether monitoring is active, the monitor PID, logging interval,
automatic stop time, and CSV location.

## Automatic stop at 8:00 PM

Monitoring stops automatically every day at 20:00 (8 PM) local time. The
time is checked on every sample, so if the computer sleeps through 20:00,
monitoring stops as soon as it resumes. The CSV file is flushed cleanly on
shutdown.

If you attempt to `start` at or after 20:00, the monitor refuses to start
and explains why. Wait until after midnight (when the next 20:00 target
rolls to the following day) or start before 20:00.

## Output: `ram_log.csv`

- Created automatically on first run if it does not exist.
- New records are **appended** — existing logs are never overwritten.
- Comma-separated values with a header row, compatible with LibreOffice Calc.
- Columns: `timestamp,pid,status,rss_kb,pss_kb,private_clean_kb,private_dirty_kb,shared_clean_kb,shared_dirty_kb`
- When Island Pill is not running, `pid` and the measurement columns are blank and `status` is `not_running`.

### Example CSV

```
timestamp,pid,status,rss_kb,pss_kb,private_clean_kb,private_dirty_kb,shared_clean_kb,shared_dirty_kb
2026-10-30T10:15:00,2316,running,60296,24710,1848,19860,38660,0
2026-10-30T10:15:05,2316,running,60300,24714,1780,19860,38660,0
2026-10-30T10:15:10,,not_running,,,,,,
```

### Inspecting the results

Open in LibreOffice Calc:

```bash
libreoffice --calc ram_log.csv
```

Or inspect with command-line tools:

```bash
# View the whole log
cat ram_log.csv

# Show only running samples
grep ',running,' ram_log.csv

# Show peak RSS
awk -F, 'NR>1 && $4!="" {if(max==""||$4>max)max=$4} END{print "peak RSS kB:", max}' ram_log.csv
```

## Behavior notes

- **Process identification:** The monitor scans `/proc/*/cmdline` for `island_pill.py` on every sample, so it finds the process by path rather than an assumed PID. It skips its own PID to avoid self-matching.
- **PID changes:** If the Island Pill process restarts under a new PID, the monitor detects the change and continues logging.
- **Not running:** If Island Pill is not running, a `not_running` row is recorded each interval instead of crashing.
- **Process termination:** If the process disappears between detection and reading `smaps_rollup`, an `smaps_unavailable` row is recorded.
- **Overhead:** One `/proc` scan and one `smaps_rollup` read per interval; sleeps the rest of the time. CPU/RAM impact is negligible.
- **Standard library only:** No external dependencies.
- **No root required:** Runs as the current user.
- **No system services:** Nothing is installed system-wide.

## Files

- `monitor_ram.py` — the monitor utility
- `monitor_ram.log` — background process stdout/stderr (created at runtime)
- `monitor_ram.pid` — background process pid file (created at runtime)
- `ram_log.csv` — the append-only measurement log (created at runtime)
- `RAM_MONITOR.md` — this document
