#!/usr/bin/env python3
"""name_hint: agent hook that asks the agent to give its Herdr pane a short name.

Reads $HERDR_PANE_ID (stdin is NOT read). When the pane label is auto (empty /
cwd basename / "<basename> #N") it emits an instruction; a manual label, a
missing pane id, an unreachable socket or a non-interactive run (env
CLAUDE_CODE_ENTRYPOINT starting with "sdk", i.e. `claude -p` / SDK / subagents
spawned by them; interactive Claude Code sets "cli", other agents leave it unset)
emit nothing. Never blocks: always exits 0, socket timeout < 1s.

  --format claude (default)  Claude Code UserPromptSubmit hook JSON
  --format text              raw instruction text
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agent_view  # noqa: E402

SOCKET_TIMEOUT = 0.8
FORMATS = ("claude", "text")


def build_instruction(pane_id):
    return (
        "Nome do pane Herdr ainda automático. Se o assunto deste pane já estiver "
        "claro pela conversa, rode uma única vez "
        f'`herdr pane rename {pane_id} "<nome>"` com um nome de 2 a 4 palavras, '
        "kebab-case minúsculo, descrevendo a demanda (sem emoji). Se ainda não "
        "estiver claro, não faça nada: isso será perguntado de novo no próximo prompt."
    )


def non_interactive(env=None):
    """True for SDK / headless Claude Code runs (CLAUDE_CODE_ENTRYPOINT "sdk-*")."""
    entry = (os.environ if env is None else env).get("CLAUDE_CODE_ENTRYPOINT") or ""
    return entry.startswith("sdk")


def hint_for(pane_id):
    """Instruction text, or None (no pane id, non-interactive run, pane not
    found/unreachable, manual label)."""
    if not pane_id or non_interactive():
        return None
    try:
        panes = agent_view.list_panes(SOCKET_TIMEOUT)
    except SystemExit:  # HERDR_SOCKET_PATH unset
        return None
    pane = next((p for p in panes if p.get("pane_id") == pane_id), None)
    if pane is None:
        return None
    cwd = pane.get("foreground_cwd") or pane.get("cwd") or ""
    if not agent_view.is_auto_label(pane.get("label"), cwd):
        return None
    return build_instruction(pane_id)


def claude_output(text):
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit", "additionalContext": text}},
        ensure_ascii=False)


def main(argv):
    fmt = "claude"
    for i, arg in enumerate(argv):
        if arg == "--format":
            fmt = argv[i + 1] if i + 1 < len(argv) else None
        elif arg.startswith("--format="):
            fmt = arg.split("=", 1)[1]
    if fmt not in FORMATS:  # hook safety: unknown format -> silent, exit 0
        return 0
    try:
        text = hint_for(os.environ.get("HERDR_PANE_ID"))
    except Exception:  # never block the agent
        text = None
    if text:
        print(text if fmt == "text" else claude_output(text))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
