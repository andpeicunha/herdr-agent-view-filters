#!/usr/bin/env python3
"""Inspect or change the Herdr labels used by the picked agent view.

The picked group title comes from the root pane's tab label. This command
changes real Herdr labels only when --apply is supplied; normal filter syncs
remain read-only with respect to tab and pane names.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_view  # noqa: E402


def snapshot():
    """Read Herdr through its CLI; this command also works outside plugin hooks."""
    data = {}
    for kind, key in (("pane", "panes"), ("agent", "agents"),
                      ("tab", "tabs")):
        result = subprocess.run(["herdr", kind, "list"], check=True,
                                capture_output=True, text=True, timeout=5)
        data[key] = json.loads(result.stdout)["result"][key]
    data["group_by_tab"] = agent_view.read_group_by_tab()
    return data


def label(value):
    if value is None:
        return None
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    name = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    if not name or len(name) > 80:
        raise ValueError("name must become 1-80 kebab-case characters")
    return name


def plan(snap, pane_id, group=None, tab=None, pane=None):
    panes = {item.get("pane_id"): item for item in snap["panes"]}
    target = panes.get(pane_id)
    if target is None:
        raise ValueError(f"pane not found: {pane_id}")
    group, tab, pane = label(group), label(tab), label(pane)
    if group is None and tab is None and pane is None:
        raise ValueError("provide --group, --tab, or --pane-label")

    operations = []
    if group is not None:
        tree = agent_view.current_tree(snap["agents"] or [], snap["panes"],
                                       snap["group_by_tab"])
        root = panes.get(tree.get(pane_id, pane_id), target)
        root_tab = root.get("tab_id")
        if not root_tab:
            raise ValueError("group root has no tab")
        operations.append(("tab", root_tab, group))
    if tab is not None:
        target_tab = target.get("tab_id")
        if not target_tab:
            raise ValueError("pane has no tab")
        if operations and operations[0][1] == target_tab:
            if operations[0][2] != tab:
                raise ValueError("--group and --tab name the same tab differently")
        else:
            operations.append(("tab", target_tab, tab))
    if pane is not None:
        operations.append(("pane", pane_id, pane))
    return operations


def apply(operations):
    for kind, target, name in operations:
        subprocess.run(["herdr", kind, "rename", target, name], check=True,
                       capture_output=True, text=True)
    # A tab rename emits a sync event, but a pane rename does not. Refresh the
    # display tokens immediately without changing the selected filter mode.
    subprocess.run(["herdr", "plugin", "action", "invoke", "sync",
                    "--plugin", "andpeicunha.agent-view-filters"], check=True,
                   capture_output=True, text=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pane", default=os.environ.get("HERDR_PANE_ID"),
                        help="target pane id (default: HERDR_PANE_ID)")
    parser.add_argument("--group", help="picked group (root tab); normalized to kebab-case")
    parser.add_argument("--tab", help="target tab; normalized to kebab-case")
    parser.add_argument("--pane-label", help="target pane; normalized to kebab-case")
    parser.add_argument("--apply", action="store_true", help="apply the preview")
    args = parser.parse_args(argv)
    if not args.pane:
        parser.error("--pane or HERDR_PANE_ID is required")
    try:
        snap = snapshot()
        operations = plan(snap, args.pane, args.group,
                          args.tab, args.pane_label)
    except ValueError as error:
        parser.error(str(error))
    old_names = {
        "pane": {item["pane_id"]: item.get("label") or "(sem nome)"
                 for item in snap["panes"]},
        "tab": {item["tab_id"]: item.get("label") or "(sem nome)"
                for item in snap["tabs"]},
    }
    for kind, target, name in operations:
        print(f"{kind} {target}: {old_names[kind].get(target, '(sem nome)')} -> {name}")
    if args.apply:
        try:
            apply(operations)
        except subprocess.CalledProcessError as error:
            print(f"rename failed after a partial update: {error.stderr or error}",
                  file=sys.stderr)
            return 1
    else:
        print("preview only; add --apply to rename")
    return 0


if __name__ == "__main__":
    sys.exit(main())
