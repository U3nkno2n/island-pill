"""Island visual mode decision matrix and lazy size mapping (Stage 3).

Pure logic: no imports, no gi, no island_pill access. The host resolves
vertical state flags and passes callables; invocation ORDER of the
activity callable exactly matches the original Island.target() branch
order (island_pill.py, pre-Stage 3):

    1. open            -> "open"    (activity never consulted; open_h only)
    2. peek_on         -> "peek"    (nothing consulted)
    3. HOVER_ONLY AND pointer-out AND not activity_visible()
                       -> "hidden"  (1, 1; the ONLY consult path,
                                     evaluated once, after both short
                                     circuits)
    4. HOVER_ONLY AND pointer-out (activity visible)  -> "idle"
    5. otherwise (not HOVER_ONLY, or hovering)        -> "idle"
"""

def decide_mode(is_open, peek_on, pointer_inside, activity_fn, hover_only):
    """Symbolic visual mode. activity_fn is called at most once per
    decision, and only on the hover-only/pointer-out path."""
    if is_open:
        return "open"
    if peek_on:
        return "peek"
    if hover_only and not pointer_inside and not activity_fn():
        return "hidden"
    return "idle"


def size_for(mode, *, open_dims, idle_dims, peek_dims):
    """mode -> (w, h). Every *_dims argument is a zero-argument callable,
    dereferenced at most once and only when that mode is selected, so the
    host's geometry getters (open_h(), idle_target_w/h()) run exactly when
    the original branch structure ran them. 'hidden' dereferences none of
    them and always returns (1, 1)."""
    if mode == "open":
        return open_dims()
    if mode == "peek":
        return peek_dims()
    if mode == "hidden":
        return (1, 1)
    return idle_dims()
