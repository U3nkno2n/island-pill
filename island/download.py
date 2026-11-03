# Pure download confirmation machine extracted from island_pill (Stage 8).
# The host keeps all filesystem and /proc reads (read_net_rx, find_partial,
# the every-30-polls net_ifaces refresh), the poll timer, the Unity
# LauncherEntry D-Bus handler and every show_peek / retarget / queue_draw /
# ensure_visual_tick effect. download_decide returns per-branch field
# updates in the original write order plus a single action; the untouched
# host methods dl_start/dl_stop are invoked at their original call sites.
# No state is ever bulk-applied.

from island.theme import BLUE, GREEN

# Consecutive low-evidence ticks allowed before a run ends, by the source
# that started it (original literals).
LOW_LIMITS = {"partial": 4, "reported": 6, "network": 6}


def download_sample(net_prev, dl_rate, now, rx):
    """Pure rate math for one valid poll sample; the host never calls this
    on a failed read (its own try/except returns early, exactly like the
    original code, so the error path never reaches this helper).

    Returns (net_prev', dl_rate', inst|None, delta|None, skip|None):
      skip = "gap"  — first sample ever (net_prev is None) or the sample gap
                      exceeds 30 s: the previous-value tuple becomes
                      (now, rx) and the rate resets to None; the host
                      assigns both and returns immediately.
      skip = None   — normal sample: delta clamps below-zero counter resets,
                      inst = delta / dt and the rate updates with the
                      original 0.5/0.5 blend (inst seeds the first EMA).
    """
    prev = net_prev
    if prev is None or now - prev[0] > 30:
        return (now, rx), None, None, None, "gap"
    dt = now - prev[0]
    delta = max(0, rx - prev[1])
    inst = delta / dt
    rate = inst if dl_rate is None else 0.5 * dl_rate + 0.5 * inst
    return (now, rx), rate, inst, delta, None


def download_decide(state, delta, inst, partial, reported,
                    fallback, min_kbps, confirm):
    """One machine step. `state` mirrors the host dl_* fields of this tick
    ("rate" is the already-updated value from download_sample). All settings
    inputs are explicit arguments per tick.

    Returns (updates, action):
      updates — list of (field, new_value) pairs, applied by the host in
                this exact order (setattr(self, "dl_" + field, value) over
                the machine vocabulary: hits, pending, bytes, peak, lows,
                name);
      action  — None | ("start", source) | ("stop",) | ("rename",);
                exactly one branch outcome per step, matching the original
                if/elif structure (name refresh and retarget go to the
                "rename" arm; dl_start/dl_stop bodies stay host-active).

    network_candidate = fallback and inst >= min_kbps * 1024.0, computed
    here exactly like the original thr comparison.
    """
    network_candidate = fallback and inst >= min_kbps * 1024.0
    if not state["active"]:
        candidate = bool(partial or reported or network_candidate)
        hits_new = state["hits"] + 1 if candidate else 0
        pending_new = state["pending"] + delta if candidate else 0
        updates = [("hits", hits_new), ("pending", pending_new)]
        if reported or hits_new >= confirm:
            source = ("reported" if reported else
                      "partial" if partial else "network")
            return updates, ("start", source)
        return updates, None
    bytes_new = state["bytes"] + delta
    peak_new = max(state["peak"], state["rate"] or 0.0)
    if state["source"] == "partial":
        evidence = bool(partial) or reported
        low_limit = LOW_LIMITS["partial"]
    elif state["source"] == "reported":
        evidence = reported
        low_limit = LOW_LIMITS["reported"]
    else:
        evidence = network_candidate
        low_limit = LOW_LIMITS["network"]
    lows_new = 0 if evidence else state["lows"] + 1
    updates = [("bytes", bytes_new), ("peak", peak_new), ("lows", lows_new)]
    if lows_new >= low_limit:
        return updates, ("stop",)
    if partial and partial != state["name"]:
        return updates + [("name", partial)], ("rename",)
    return updates, None


def progress_scan(progress, now):
    """Selection core of the host dl_fraction getter: iterates the mapping
    in dictionary order and returns the highest fraction among fresh
    entries (strictly-greater keeps the FIRST of equal fractions, matching
    the original `best is None or frac > best`). Entries older than 30 s
    are reported in stale_keys, in scan order; the host deletes them
    itself, keeping self.progress ownership and the original in-loop
    mutation effect. Nothing is written to the mapping here.
    """
    best = None
    stale = []
    for app, (frac, t) in progress.items():
        if now - t > 30:
            stale.append(app)
        elif best is None or frac > best:
            best = frac
    return best, stale


def dl_bar_pair(frac):
    """(fill 0..1, colour, real-percentage flag). Firefox exposes no
    reliable system-wide file total/progress signal here; a reported
    fraction wins and draws as a real GREEN progress bar, while anything
    else must never disguise network speed as a completion percentage —
    the host shows a moving indeterminate BLUE bar instead.
    """
    if frac is not None:
        return frac, GREEN, True
    return None, BLUE, False
