#!/usr/bin/env python3
"""agent-view-filters picker: curses TUI that mirrors the Agents sidebar.

Rows: a space header with a checkbox; under it every root agent with a
checkbox; a root with children keeps its own row ("tab · space", checkbox, status
glyph) followed by a non-selectable "├ label" row and the children ("└ label"),
without checkbox; mirroring the `picked`-mode sidebar (layout D).
Checked = shown. A space unchecked hides the whole space (its roots render
unchecked/dim and do not count in the header); a root unchecked hides it and its
children. Rows that share one "tab:<id>" entry (lone panes of a tab) toggle
together. Enter saves `excluded` ("space:<id>", "tab:<id>" for tab-fallback
groups and lone panes in an excluded tab, root pane ids) to state.json and
applies the `picked` view; q/Esc cancels without saving. With no agents it shows
a message until any key. Order is fixed: space order, tab order, root, children
(see agent_view.layout_sequence).
"""
import curses
import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_view as av  # noqa: E402

GLYPH = "●"
BOLD_STATUS = {"working", "blocked"}
STATUS_PAIR = {"working": 1, "done": 2, "blocked": 3, "idle": 4}
STATUS_FG = {1: curses.COLOR_YELLOW, 2: curses.COLOR_BLUE,
             3: curses.COLOR_RED, 4: curses.COLOR_GREEN}
LEGEND = ("working", "done", "blocked", "idle")
IGNORED = -2


def make_rows(agents, ctx, ws, ws_idx, excluded, tree):
    """Pure-ish. Rows mirroring the layout B sidebar, in display order.

    kind "space": {kind, id, label, count, checked, selectable}
    kind "root":  {kind, pane_id, entry, status, label ("tab - space"), checked,
                   selectable, header}; `entry` = "tab:<id>" for tab-fallback
                   groups, else the pane id (what collect_excluded stores);
                   header True = group header of a root with children
    kind "item":  {kind, label ("├ repo" of a root with children), selectable False}
    kind "child": {kind, pane_id, status, label ("├ repo"/"└ repo"), selectable False}
    """
    ex = set(excluded)
    by_id = {a.get("pane_id"): a for a in agents if a.get("pane_id")}
    panes = list(ctx[1].values())
    seq, space_key = av.layout_sequence(agents, panes, ctx[0], ws_idx, tree)
    marks, parents = av.group_marks(seq, tree)
    tab_roots = av.tab_fallback_roots(agents, panes, tree)
    rows = []
    last = None
    for pid in seq:
        a = by_id[pid]
        key = space_key[pid]
        wid = key[1]
        if key != last:
            last = key
            n = sum(1 for p in seq if space_key[p] == key)
            rows.append({"kind": "space", "id": wid, "label": ws.get(wid, wid) or "-",
                         "count": n, "checked": av.space_entry(wid) not in ex,
                         "selectable": True})
        status = a.get("agent_status") or "unknown"
        if pid in tree:
            title, _, _ = av.row_texts(a, ctx, ws, marks.get(pid))
            rows.append({"kind": "child", "pane_id": pid, "status": status,
                         "label": title or pid, "selectable": False})
        else:
            title, space, sub = av.row_texts(a, ctx, ws, None, pid in parents)
            tab = a.get("tab_id")
            # A "tab:<id>" entry hides every agent of the tab, so a lone pane in an
            # excluded tab is represented by that entry (toggling it removes it).
            if pid in tab_roots:
                entry = av.tab_entry(tab_roots[pid])
            elif tab and av.tab_entry(tab) in ex:
                entry = av.tab_entry(tab)
            else:
                entry = pid
            header = pid in parents
            rows.append({"kind": "root", "pane_id": pid, "entry": entry, "status": status,
                         "label": " \u00b7 ".join(x for x in (title or pid, space) if x),
                         "checked": entry not in ex and pid not in ex,
                         "selectable": True, "header": header})
            if header and sub:
                rows.append({"kind": "item", "label": sub, "selectable": False})
    return rows


def build_rows():
    snap = av.take_snapshot()
    agents = snap["agents"]
    if agents is None:
        sys.stderr.write("agent-view-filters: cannot list agents\n")
        sys.exit(1)
    ctx = av.name_context(snap)
    tree = av.current_tree(agents, snap["panes"], snap["group_by_tab"])
    excluded = av.read_excluded()
    rows = make_rows(agents, ctx, snap["ws"], snap["ws_idx"], excluded, tree)
    return rows, excluded


def collect_excluded(rows, existing=()):
    """Pure. `excluded` entries from the rows: unchecked spaces + unchecked roots
    ("tab:<id>" for tab-fallback groups, else the pane id). `existing` space:/tab:
    entries with no row in the picker (e.g. an empty space) are kept."""
    shown = set()
    checked_roots = set()  # entries with at least one checked root row
    for r in rows:
        if r["kind"] == "space":
            shown.add(av.space_entry(r["id"]))
        elif r["kind"] == "root":
            entry = r.get("entry") or r["pane_id"]
            shown.add(entry)
            if r["checked"]:
                checked_roots.add(entry)
    out = [e for e in existing
           if e.startswith((av.SPACE_PREFIX, av.TAB_PREFIX)) and e not in shown]
    for r in rows:
        if r["kind"] == "space" and not r["checked"]:
            out.append(av.space_entry(r["id"]))
        elif r["kind"] == "root" and not r["checked"]:
            # A shared entry ("tab:<id>" of several lone roots) is emitted only when
            # none of its rows is checked; one checked row reveals the group.
            entry = r.get("entry") or r["pane_id"]
            if entry not in checked_roots and entry not in out:
                out.append(entry)
    return out


def merge_excluded(rows, old, fresh):
    """Pure. `excluded` to save: the picker's rows over the `fresh` stored list.
    Entries added to state after the picker opened (in `fresh`, not in `old`) and
    without a row are kept, so concurrent syncs are not clobbered."""
    shown = {av.space_entry(r["id"]) for r in rows if r["kind"] == "space"}
    shown |= {r.get("entry") or r["pane_id"] for r in rows if r["kind"] == "root"}
    out = collect_excluded(rows, fresh)
    out += [e for e in fresh if e not in old and e not in shown and e not in out]
    return out


def move_cursor(rows, cur, delta):
    """Pure. Next selectable row index from cur in direction delta (+/-1); stays if none."""
    i = cur + delta
    while 0 <= i < len(rows):
        if rows[i]["selectable"]:
            return i
        i += delta
    return cur


def getkey(stdscr):
    """getch() that tells a lone Esc from other escape sequences (IGNORED)."""
    k = stdscr.getch()
    if k != 27:
        return k
    stdscr.timeout(25)
    seq = []
    try:
        while len(seq) < 8:
            c = stdscr.getch()
            if c == -1:
                break
            seq.append(c)
            if c not in (91, 79, 59) and not 48 <= c <= 57:
                break
    finally:
        stdscr.timeout(-1)
    return 27 if not seq else IGNORED


def init_colors():
    """Set up status color pairs. Returns False (glyph-only mode) on any failure."""
    try:
        if not curses.has_colors():
            return False
        curses.start_color()
        try:
            curses.use_default_colors()
            bg = -1
        except curses.error:
            bg = curses.COLOR_BLACK
        for pid, fg in STATUS_FG.items():
            curses.init_pair(pid, fg, bg)
        return True
    except curses.error:
        return False


def status_attr(status, colors):
    """Attr for the status glyph. Colorless terminals get no attr."""
    if not colors:
        return 0
    pid = STATUS_PAIR.get(status)
    if pid is None:
        return curses.A_DIM  # unknown: default dim
    return curses.color_pair(pid) | (curses.A_BOLD if status in BOLD_STATUS else 0)


def char_width(ch):
    """Terminal columns of one character: 0 combining, 2 wide/fullwidth/emoji."""
    if unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F") or ord(ch) >= 0x1F000:
        return 2
    return 1


def text_width(text):
    return sum(char_width(c) for c in text)


def clip(text, cols):
    """text cut to at most `cols` terminal columns (never splits a wide char)."""
    out, used = [], 0
    for c in text:
        cw = char_width(c)
        if used + cw > cols:
            break
        out.append(c)
        used += cw
    return "".join(out)


def put(stdscr, y, x, text, attr, w):
    """Clipped addnstr (by display width) that never raises on the screen edge;
    returns next x."""
    if text and x < w - 1:
        part = clip(text, w - 1 - x)
        if part:
            stdscr.addnstr(y, x, part, len(part), attr)
    return x + text_width(text)


def draw_row(stdscr, y, r, rev, space_on, colors, w):
    put(stdscr, y, 0, " " * w, rev, w)
    if r["kind"] == "space":
        mark = "[x]" if r["checked"] else "[ ]"
        attr = rev | (curses.A_BOLD if r["checked"] else curses.A_DIM)
        put(stdscr, y, 0, f" {mark} {r['label']}  ({r['count']})", attr, w)
        return
    dim = 0 if space_on else curses.A_DIM
    if r["kind"] == "item":
        put(stdscr, y, 0, "           " + r["label"], rev | curses.A_DIM, w)
        return
    # Com cor, o glifo não herda o reverso da linha selecionada (senão perde a cor);
    # sem cor, segue o realce da linha.
    sattr = status_attr(r["status"], colors) | (0 if colors else rev)
    if r["kind"] == "root":
        on = r["checked"] and space_on  # root under an unchecked space is derived-off
        mark = "[x]" if on else "[ ]"
        attr = rev | dim | (curses.A_BOLD if on else curses.A_DIM)
        x = put(stdscr, y, 0, f"     {mark} ", attr, w)
        x = put(stdscr, y, x, GLYPH, sattr, w)
        put(stdscr, y, x, f" {r['label']}", attr, w)
    else:
        attr = rev | curses.A_DIM
        x = put(stdscr, y, 0, "           ", attr, w)
        x = put(stdscr, y, x, GLYPH, sattr, w)
        put(stdscr, y, x, f" {r['label']}", attr, w)


def toggle(rows, cur):
    """Flip row `cur`; root rows sharing its "tab:<id>"/pane entry follow it so
    every row of one entry always renders the same state."""
    r = rows[cur]
    new = not r["checked"]
    r["checked"] = new
    if r["kind"] == "root":
        entry = r.get("entry") or r["pane_id"]
        for o in rows:
            if o["kind"] == "root" and (o.get("entry") or o["pane_id"]) == entry:
                o["checked"] = new


def show_empty(stdscr):
    """No agents: show a message until any key."""
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.erase()
    try:
        stdscr.addnstr(0, 1, "no agents", 40, curses.A_BOLD)
        stdscr.addnstr(2, 1, "press any key", 40, curses.A_DIM)
    except curses.error:
        pass
    stdscr.refresh()
    stdscr.getch()


def run(stdscr, rows):
    """Returns True to save (rows hold the checkbox state)."""
    try:
        curses.curs_set(0)  # terminais como vt100 não suportam
    except curses.error:
        pass
    stdscr.keypad(True)
    colors = init_colors()
    cur = move_cursor(rows, -1, 1)
    top = 0
    while True:
        h, w = stdscr.getmaxyx()
        body = max(1, h - 3)
        cur = max(0, min(cur, len(rows) - 1))
        if cur < top:
            top = cur
        if cur >= top + body:
            top = cur - body + 1
        stdscr.erase()
        n_on = n_all = 0
        space_on = True
        for r in rows:
            if r["kind"] == "space":
                space_on = r["checked"]
            elif r["kind"] == "root":
                n_all += 1
                n_on += 1 if (r["checked"] and space_on) else 0
        head = f" agents shown: {n_on}/{n_all} roots"
        try:
            stdscr.addnstr(0, 0, clip(head.ljust(w), w - 1), w - 1, curses.A_BOLD)
            legend = []
            for j, s in enumerate(LEGEND):
                if j:
                    legend.append(("  ", 0))
                legend.append((GLYPH, status_attr(s, colors)))
                legend.append((f" {s}", curses.A_DIM))
            lx = w - 1 - sum(text_width(t) for t, _ in legend)
            if lx > len(head) + 2:
                for t, a in legend:
                    lx = put(stdscr, 0, lx, t, a, w)
        except curses.error:
            pass
        space_on = True
        for i, r in enumerate(rows):
            if r["kind"] == "space":
                space_on = r["checked"]
            if top <= i < top + body:
                try:  # one bad row must not abort the rest of the screen
                    draw_row(stdscr, 2 + i - top, r, curses.A_REVERSE if i == cur else 0,
                             space_on, colors, w)
                except curses.error:
                    pass
        try:
            stdscr.addnstr(h - 1, 0, " up/down nav  space toggle  enter save  esc cancel",
                           w - 1, curses.A_DIM)
        except curses.error:
            pass
        stdscr.refresh()

        k = getkey(stdscr)
        if k == IGNORED:
            continue
        if k in (ord("q"), 27):
            return False
        if k in (curses.KEY_UP, ord("k")):
            cur = move_cursor(rows, cur, -1)
        elif k in (curses.KEY_DOWN, ord("j")):
            cur = move_cursor(rows, cur, 1)
        elif k in (curses.KEY_HOME, ord("g")):
            cur = move_cursor(rows, -1, 1)
        elif k in (curses.KEY_END, ord("G")):
            cur = move_cursor(rows, len(rows), -1)
        elif k == ord(" "):
            toggle(rows, cur)
        elif k in (10, 13, curses.KEY_ENTER):
            return True


def main():
    rows, old_excluded = build_rows()
    os.environ.setdefault("ESCDELAY", "25")  # lone Esc cancels fast (keypad waits 1s)
    if not rows:
        curses.wrapper(show_empty)
        return
    if not curses.wrapper(run, rows):
        return
    with av.state_lock():
        # Re-read under the lock: only `excluded` changes, the rest of the state
        # (seen / first_seen / tab_roots / parents) is merged, never clobbered.
        excluded = merge_excluded(rows, old_excluded, av.read_excluded())
        av.write_state("picked", excluded)
        av.apply_mode("picked", excluded)


if __name__ == "__main__":
    main()
