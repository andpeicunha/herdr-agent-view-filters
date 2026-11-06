#!/usr/bin/env python3
"""agent-view-filters picker: curses TUI to untick agents hidden from the sidebar.

Checked = visible (not excluded). Enter saves `excluded` to state.json and
applies the `picked` view; q/Esc cancels without saving.

Manual order (picked view only): spaces always follow the live sidebar order;
Shift+Up/Down (or K/J) move the item under the cursor only inside its own space,
`r` goes back to the default order. Enter also saves `order` (the displayed
list) when a manual order is active, or clears it after `r`.
"""
import curses
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_view as av  # noqa: E402

GLYPH = "●"
BOLD_STATUS = {"working", "blocked"}
STATUS_PAIR = {"working": 1, "done": 2, "blocked": 3, "idle": 4}
REPO_PAIR = 5  # repo na linha 1 quando marcado: ciano claro (sem DIM)
STATUS_FG = {1: curses.COLOR_YELLOW, 2: curses.COLOR_BLUE,
             3: curses.COLOR_RED, 4: curses.COLOR_GREEN}
LEGEND = ("working", "done", "blocked", "idle")


def build_rows():
    agents = av.list_agents()
    if agents is None:
        sys.stderr.write("agent-view-filters: cannot list agents\n")
        sys.exit(1)
    ws = av.list_workspaces()
    ws_idx = av.workspace_index()
    # Labels são opcionais: falha aqui cai no comportamento anterior (título).
    ctx = av.name_context()
    excluded = set(av.read_excluded())
    rows = []
    for a in agents:
        cwd = a.get("foreground_cwd") or a.get("cwd") or ""
        title = a.get("terminal_title_stripped") or a.get("terminal_title") or ""
        name = av.agent_name(a, ctx)
        rows.append({
            "pane_id": a.get("pane_id", ""),
            "repo": os.path.basename(cwd.rstrip("/")) or cwd or "-",
            "name": name,
            "title": title,
            "status": a.get("agent_status") or "unknown",
            "ws": ws.get(a.get("workspace_id"), a.get("workspace_id", "")),
            "agent": a.get("agent") or "",
            "ws_idx": ws_idx.get(a.get("workspace_id"), len(ws_idx)),
            "checked": a.get("pane_id") not in excluded,
        })
    return rows, excluded, av.read_order()


def resort(rows, order=None):
    """Spaces in live sidebar order; inside each, saved order first, then new
    agents by repo/name."""
    by_id = {r["pane_id"]: r for r in rows}
    seq = av.space_sequence(
        [(r["pane_id"], r["ws_idx"], r["repo"], r["name"]) for r in rows], order or [])
    rows[:] = [by_id[p] for p in seq]


SHIFT_UP = getattr(curses, "KEY_SR", 337)
SHIFT_DOWN = getattr(curses, "KEY_SF", 336)
MOVE_UP = {SHIFT_UP, getattr(curses, "KEY_SUP", -99), ord("K")}
MOVE_DOWN = {SHIFT_DOWN, getattr(curses, "KEY_SDOWN", -99), ord("J")}
RAW_SHIFT_UP = [91, 49, 59, 50, 65]    # ESC [ 1 ; 2 A
RAW_SHIFT_DOWN = [91, 49, 59, 50, 66]  # ESC [ 1 ; 2 B
IGNORED = -2


def getkey(stdscr):
    """getch() that decodes raw shift+arrows and tells a lone Esc from other
    escape sequences (returned as IGNORED, never as cancel)."""
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
    if not seq:
        return 27
    if seq == RAW_SHIFT_UP:
        return SHIFT_UP
    if seq == RAW_SHIFT_DOWN:
        return SHIFT_DOWN
    return IGNORED


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
        curses.init_pair(REPO_PAIR, curses.COLOR_CYAN, bg)
        return True
    except curses.error:
        return False


def status_attr(status, colors):
    """Attr for the status glyph/text. Colorless terminals get no attr."""
    if not colors:
        return 0
    pid = STATUS_PAIR.get(status)
    if pid is None:
        return curses.A_DIM  # unknown: default dim
    return curses.color_pair(pid) | (curses.A_BOLD if status in BOLD_STATUS else 0)


def put(stdscr, y, x, text, attr, w):
    """Clipped addnstr that never raises on the screen edge; returns next x."""
    if text and x < w - 1:
        stdscr.addnstr(y, x, text, w - 1 - x, attr)
    return x + len(text)


def run(stdscr, rows, order, result):
    """Returns True to save. result["manual"] tells whether to store `order`."""
    try:
        curses.curs_set(0)  # terminais como vt100 não suportam
    except curses.error:
        pass
    stdscr.keypad(True)
    colors = init_colors()
    query = ""
    searching = False
    cur = 0
    top = 0
    # Sort once at start; do not reshuffle while toggling (avoids jumping rows).
    manual = bool(order)
    notice = ""
    resort(rows, order)

    def visible():
        q = query.lower()
        if not q:
            return rows
        return [r for r in rows if q in " ".join(
            [r["repo"], r["name"], r["title"], r["status"], r["ws"], r["agent"]]).lower()]

    while True:
        vis = visible()
        cur = max(0, min(cur, len(vis) - 1)) if vis else 0
        h, w = stdscr.getmaxyx()
        # Itens visíveis: cada item ocupa 3 linhas (repo, detalhe, separador).
        # Layout: linha 0 header, linha 1 em branco, lista a partir da linha 2.
        body = max(1, (h - 4) // 3)
        if cur < top:
            top = cur
        if cur >= top + body:
            top = cur - body + 1
        stdscr.erase()
        n_on = sum(1 for r in rows if r["checked"])
        head = f" agents shown: {n_on}/{len(rows)}   order: " + (
            "manual (per space)" if manual else "follows spaces")
        if query or searching:
            head += f"   /{query}{'_' if searching else ''}"
        try:
            stdscr.addnstr(0, 0, head.ljust(w), w - 1, curses.A_BOLD)
            # Legenda no canto direito do header; omitida se não couber.
            legend = []
            for j, s in enumerate(LEGEND):
                if j:
                    legend.append(("  ", 0))
                legend.append((GLYPH, status_attr(s, colors)))
                legend.append((f" {s}", curses.A_DIM))
            lw = sum(len(t) for t, _ in legend)
            lx = w - 1 - lw
            if lx > len(head) + 2:
                for t, a in legend:
                    lx = put(stdscr, 0, lx, t, a, w)
            for i, r in enumerate(vis[top:top + body]):
                idx = top + i
                y = 2 + 3 * i
                mark = "[x]" if r["checked"] else "[ ]"
                rev = curses.A_REVERSE if idx == cur else 0
                attr1 = rev | (curses.A_BOLD if r["checked"] else curses.A_DIM)
                attr2 = rev | curses.A_DIM
                sattr = status_attr(r["status"], colors) | rev
                # Repo claro quando marcado; desmarcado segue DIM como o resto.
                if not r["checked"]:
                    repo_attr = rev | curses.A_DIM
                elif colors:
                    repo_attr = rev | curses.color_pair(REPO_PAIR)
                else:
                    repo_attr = rev | curses.A_NORMAL
                # Linha 1: fundo, "  [x] ", bolinha, " <space>", "  <repo>".
                # Sem space: o repo ocupa a posição do space, sem repetir.
                put(stdscr, y, 0, " " * w, attr1, w)
                x = put(stdscr, y, 0, f"  {mark} ", attr1, w)
                x = put(stdscr, y, x, GLYPH, sattr, w)
                if r["ws"]:
                    x = put(stdscr, y, x, f" {r['ws']}", attr1, w)
                    x = put(stdscr, y, x, "  ", attr1, w)
                    put(stdscr, y, x, r["repo"], repo_attr, w)
                else:
                    put(stdscr, y, x, f" {r['repo']}", attr1, w)
                # Linha 2: nome [· título em DIM]. Space já está na linha 1.
                # O título só aparece como nome se não houver nome, ou como
                # sufixo dim quando não está contido no nome.
                put(stdscr, y + 1, 0, " " * w, attr2, w)
                shown = r["name"] or r["title"]
                x = put(stdscr, y + 1, 0, f"      {shown}", attr2, w)
                if r["name"] and r["title"] and r["title"].lower() not in r["name"].lower():
                    put(stdscr, y + 1, x, f"  ·  {r['title']}", attr2, w)
            foot = (" j/k nav  S-up/dn|J/K reorder  space toggle  / find  a all  n none"
                    "  r reset order  enter save  q cancel")
            if notice:
                stdscr.addnstr(h - 1, 0, " " + notice, w - 1, curses.A_BOLD)
            else:
                stdscr.addnstr(h - 1, 0, foot, w - 1, curses.A_DIM)
        except curses.error:
            pass
        stdscr.refresh()

        k = getkey(stdscr)
        notice = ""
        if k == IGNORED:
            continue
        if searching:
            if k in (27,):
                searching = False
                query = ""
            elif k in (10, 13, curses.KEY_ENTER):
                searching = False
            elif k in (curses.KEY_BACKSPACE, 127, 8):
                query = query[:-1]
            elif k in (curses.KEY_UP,):
                cur -= 1
            elif k in (curses.KEY_DOWN,):
                cur += 1
            elif 32 <= k < 127:
                query += chr(k)
                cur = 0
            continue
        if k in (ord("q"), 27):
            if k == 27 and query:
                query = ""
                continue
            return False
        if k in (curses.KEY_UP, ord("k")):
            cur -= 1
        elif k in (curses.KEY_DOWN, ord("j")):
            cur += 1
        elif k == curses.KEY_PPAGE:
            cur -= body
        elif k == curses.KEY_NPAGE:
            cur += body
        elif k in (curses.KEY_HOME, ord("g")):
            cur = 0
        elif k in (curses.KEY_END, ord("G")):
            cur = len(vis) - 1
        elif k == ord(" ") and vis:
            vis[cur]["checked"] = not vis[cur]["checked"]
        elif k in MOVE_UP or k in MOVE_DOWN:
            if query:
                notice = "clear search (Esc) to reorder"
            elif vis:
                by_id = {r["pane_id"]: r for r in rows}
                ids, cur, moved = av.move_in_space(
                    [r["pane_id"] for r in rows], cur, -1 if k in MOVE_UP else 1,
                    lambda p: by_id[p]["ws_idx"])
                if moved:
                    rows[:] = [by_id[p] for p in ids]
                    manual = True
                else:
                    notice = "space boundary: can only reorder within a space"
        elif k == ord("r"):
            manual = False
            resort(rows)
            cur = 0
            top = 0
        elif k == ord("/"):
            searching = True
        elif k == ord("a"):
            for r in vis:
                r["checked"] = True
        elif k == ord("n"):
            for r in vis:
                r["checked"] = False
        elif k in (10, 13, curses.KEY_ENTER):
            result["manual"] = manual
            return True


def main():
    rows, old_excluded, order = build_rows()
    if not rows:
        print("no agents")
        return
    result = {"manual": False}
    os.environ.setdefault("ESCDELAY", "25")  # lone Esc cancels fast (keypad waits 1s)
    save = curses.wrapper(run, rows, order, result)
    if not save:
        return
    live = {r["pane_id"] for r in rows}
    # Keep exclusions of panes not listed (none after prune, but be safe).
    excluded = [r["pane_id"] for r in rows if not r["checked"]]
    excluded += [p for p in old_excluded if p not in live]
    new_order = [r["pane_id"] for r in rows] if result["manual"] else []
    av.write_state("picked", excluded, new_order)
    av.apply_mode("picked", excluded)


if __name__ == "__main__":
    main()
