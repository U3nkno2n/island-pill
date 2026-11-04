"""Island Pill user-configurable settings.

Extracted verbatim from island_pill.py's "settings you may want to change"
block (Stage 2, Phase 2 restructure). This is now the file hand-editors
modify on an installed copy; island_pill.py re-imports these names so its
own host-side readers keep a live alias (runtime hand-mutation of
island_pill.<name> keeps affecting island_pill code).

Layout constants (NOTCH, geometry) stay in island_pill.py and depend on
STYLE here. Stdlib only (`os` for the env-backed STYLE): import-safe
headless by rule.
"""
import os

HOUR24 = False            # False: 10:24 PM    True: 22:24
STYLE = os.environ.get("ISLAND_PILL_STYLE", "notch")
#   "pill":  a detached, floating pill with a gap above it (default)
#   "notch": hangs from the very top edge with flared corners
FONT = "Sans"
TIMER_PRESETS = (5, 10, 25)   # minutes, shown as buttons in the open view
PEEK_SECONDS = 4          # how long a peek stays out
HOVER_OPEN_DELAY_MS = 300 # hover this long before opening the full controls; click opens instantly
SHOW_NOTIFICATIONS = True # peek on desktop notifications
LOW_BATTERY = (20, 10)    # warn when the battery falls below these percentages
SHOW_DOWNLOADS = True     # speed + progress bar while something downloads (False: no polling at all)
DOWNLOAD_MIN_KBPS = 1200  # fallback threshold, KB/s; used only if network fallback is enabled
DOWNLOAD_NETWORK_FALLBACK = False  # avoids mistaking video/music streaming for file downloads
DOWNLOAD_DONE_PEEK = True # peek "Download finished" when a download of 20 MB or more ends
SHOW_WIFI = True          # Wi-Fi button in the open card, peek on connect / disconnect
HOVER_ONLY = True         # keep the island visually quiet; reveal/expand content only on hover
HOVER_ONLY_PEEKS = True   # allow brief peeks (battery, downloads, Wi-Fi, etc.) even in quiet mode
