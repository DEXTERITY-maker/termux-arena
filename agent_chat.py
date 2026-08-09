# SPDX-License-Identifier: MIT
# Copyright (c) 2026 — Termux Arena. См. LICENSE.

#!/data/data/com.termux/files/usr/bin/python3
# agent_chat.py — AGENT ARENA: Пользователь | Hermes | OMP | Dao
# Каналы:
#   → Hermes : tmux send-keys в hermes-chat
#   → OMP    : tmux send-keys в rk_omp_chat_8e939621 (или omp-chat)
#   → Dao    : append в dao_inbox.md + флаг
# Команды: @h (Hermes) | @o (OMP) | @d (Dao) | @auto (автодиалог Hermes↔OMP) | @quit
# Обычный текст = Hermes'у.

import urwid
import subprocess
import os
import time

HERMES_SESSION = "hermes-chat"
OMP_SESSION    = "rk_omp_chat_efb690b2"
DAO_INBOX      = os.path.expanduser("~/.hermes/dao_inbox.md")
DAO_FLAG       = os.path.expanduser("~/.hermes/hermes_inbox.flag")
AUTO_STATE     = os.path.expanduser("~/.hermes/agent_auto.state")

def sh(cmd, timeout=8):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception as e:
        return f"<err: {e}>"

def tmux_capture(session, n=30):
    return sh(f"tmux capture-pane -t {session} -p | tail -{n}")

def tail_file(path, n=15):
    if not os.path.exists(path):
        return "(файла нет)"
    out = sh(f"tail -{n} '{path}'")
    return out if out.strip() else "(пусто)"

def ts():
    return time.strftime("%H:%M:%S")

def find_omp_session():
    """Автопоиск tmux-сессии OMP по процессу (устойчиво к падениям tmux)."""
    try:
        out = sh("for p in $(pgrep -f 'oh-my-pi/omp'); do t=$(readlink /proc/$p/fd/0 2>/dev/null); case \"$t\" in /dev/pts/*) echo \"$t\"; break;; esac; done")
        tty = out.strip()
        if tty:
            ses = sh(f"tmux list-panes -a -F '#{{session_name}} {{pane_tty}}' 2>/dev/null | awk -v t='{tty}' '{{ if ($2 == t) print $1 }}'").strip()
            if ses:
                return ses.split("\n")[0]
    except Exception:
        pass
    return None

def send_to(session, text):
    safe = text.replace("'", "'\\''")
    sh(f"tmux send-keys -t {session} '{safe}' Enter")

def send_dao(text):
    line = f"\n**[{ts()}] [User → Dao]** {text}\n"
    with open(DAO_INBOX, "a", encoding="utf-8") as f:
        f.write(line)
    open(DAO_FLAG, "a").close()

# ---------- Палитра ----------
palette = [
    ("bar",       "white", "dark blue"),
    ("prompt",    "light cyan", "black"),
    ("h_border",  "light cyan", "black"),
    ("o_border",  "light magenta", "black"),
    ("d_border",  "light green", "black"),
    ("head",      "white", "dark blue"),
    ("input",     "white", "black"),
    ("status",    "yellow", "black"),
]

head = urwid.Text("⚡ AGENT ARENA — Пользователь | Hermes | OMP", align="center")
head = urwid.AttrMap(urwid.Padding(head, left=1, right=1), "head")

hermes_txt = urwid.Text("(загрузка Hermes...)", wrap="clip")
omp_txt    = urwid.Text("(загрузка OMP...)", wrap="clip")

def panel(txt, title, border):
    w = urwid.LineBox(urwid.Filler(txt, valign="bottom"),
                      title=f" {title}  {ts()} ", title_align="left",
                      tlcorner="╭", tline="─", trcorner="╮",
                      blcorner="╰", rline="│", brcorner="╯", lline="│")
    return urwid.AttrMap(w, border)

columns = urwid.Columns([
    ("weight", 50, panel(hermes_txt, "⚕ Hermes", "h_border")),
    ("weight", 50, panel(omp_txt, "π OMP", "o_border")),
])

status_txt = urwid.Text("автодиалог Hermes↔OMP: ВЫКЛ", align="center")
status_bar = urwid.AttrMap(status_txt, "status")

class EnterEdit(urwid.Edit):
    def keypress(self, size, key):
        if key == "enter":
            on_input(self, self.get_edit_text())
            return None
        return super().keypress(size, key)

input_edit = urwid.AttrMap(EnterEdit(("prompt", "⚕ ❯ "), ""), "input")
footer = urwid.Pile([status_bar, input_edit])
frame = urwid.Frame(header=head, body=columns, footer=footer, focus_part="footer")

# ---------- Логика ----------
auto_mode = False
auto_busy = False
last_h_snap = ""
last_o_snap = ""

def refresh_ui(loop=None, data=None):
    global last_h_snap, last_o_snap, last_d_snap
    last_h_snap = tmux_capture(HERMES_SESSION)
    hermes_txt.set_text(last_h_snap[-2500:] if len(last_h_snap) > 2500 else last_h_snap)
    global OMP_SESSION
    last_o_snap = tmux_capture(OMP_SESSION)
    if not last_o_snap.strip():
        found = find_omp_session()
        if found:
            OMP_SESSION = found
            last_o_snap = tmux_capture(OMP_SESSION)
    omp_txt.set_text(last_o_snap[-2500:] if len(last_o_snap) > 2500 else last_o_snap)
    columns.contents[0] = (panel(hermes_txt, "⚕ Hermes", "h_border"), columns.options("weight", 50))
    columns.contents[1] = (panel(omp_txt, "π OMP", "o_border"), columns.options("weight", 50))
    status_txt.set_text(f"⚕ arena │ авто Hermes↔OMP: {'ВКЛ' if auto_mode else 'ВЫКЛ'} │ ⏱ {ts()}")
    if auto_mode:
        step_auto()
    if loop:
        loop.set_alarm_in(3, refresh_ui)

def is_junk_line(s):
    bad = ("<err:", "(файла нет)", "(пусто)", "(загрузка", "[Process completed",
           "⚕ ❯", "автодиалог:", "arena │", ">>>", "π  >", "⚕ deepseek",
           "[Arena #", "─")
    return s.startswith(bad) or len(s) < 4

MAX_TURNS = 20
IDLE_TIMEOUT = 900

def last_block(snap, marker):
    """Многострочный ответ ПОСЛЕ последнего маркера #[N] в панели."""
    lines = snap.splitlines()
    idx = -1
    for i, l in enumerate(lines):
        if marker in l:
            idx = i
    if idx < 0:
        return ""
    block = [l.strip() for l in lines[idx + 1:] if l.strip() and not is_junk_line(l)]
    text = " ".join(block)
    return text[:400]

def step_auto():
    """Автодиалог Hermes ↔ OMP: ответ одной модели передаётся другой по маркерам #[N]."""
    global auto_busy, auto_mode
    if auto_busy:
        return
    auto_busy = True
    try:
        state = {}
        if os.path.exists(AUTO_STATE):
            for kv in open(AUTO_STATE).read().splitlines():
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    state[k] = v
        turns = int(state.get("turns", "0") or 0)
        if turns >= MAX_TURNS:
            auto_mode = False
            status_txt.set_text(f"⚕ автостоп (лимит {MAX_TURNS} ходов, {ts()})")
            return
        last_turn = float(state.get("last_turn_ts", "0") or 0)
        if last_turn and time.time() - last_turn > IDLE_TIMEOUT:
            auto_mode = False
            status_txt.set_text(f"⚕ автостоп (пауза >{IDLE_TIMEOUT//60} мин, {ts()})")
            return

        n = int(state.get("n", "0") or 0)
        moved = False
        if state.get("turn") == "o":
            # ждём ответ OMP на [Arena #n → OMP], стабильность 1 цикл
            block = last_block(last_o_snap, f"[Arena #{n} → OMP]")
            if block and block == state.get("o_prev", "") and block != state.get("o_sent", ""):
                send_to(HERMES_SESSION, f"[Arena #{n} → Hermes] {block}")
                state["o_sent"] = block
                state["turn"] = "h"
                status_txt.set_text(f"⚕ ход #{n}: OMP → Hermes ({ts()})")
                moved = True
            state["o_prev"] = block
        else:
            # ждём ответ Hermes на [Arena #n → Hermes]
            block = last_block(last_h_snap, f"[Arena #{n} → Hermes]")
            if block and block == state.get("h_prev", "") and block != state.get("h_sent", ""):
                n += 1
                send_to(OMP_SESSION, f"[Arena #{n} → OMP] {block}")
                state["h_sent"] = block
                state["n"] = str(n)
                state["turn"] = "o"
                status_txt.set_text(f"⚕ ход #{n}: Hermes → OMP ({ts()})")
                moved = True
            state["h_prev"] = block
        if moved:
            state["turns"] = str(turns + 1)
            state["last_turn_ts"] = str(time.time())
        with open(AUTO_STATE, "w") as f:
            for k, v in state.items():
                f.write(f"{k}={v}\n")
    finally:
        auto_busy = False

def on_input(edit_widget, text):
    global auto_mode
    text = text.strip()
    if not text:
        return
    edit_widget.set_edit_text("")
    if text == "@quit":
        raise urwid.ExitMainLoop()
    if text == "@auto":
        auto_mode = not auto_mode
        if auto_mode:
            state = {}
            if os.path.exists(AUTO_STATE):
                for kv in open(AUTO_STATE).read().splitlines():
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        state[k] = v
            if not state.get("n"):
                send_to(OMP_SESSION, "[Arena #1 → OMP] Привет! Старт арены. Предложи 3 идеи контента для канала @termux_tracex (Termux: гайды, инструменты, автоматизация, безопасность). Ответь кратко.")
                state["n"] = "1"
                state["turn"] = "o"
                with open(AUTO_STATE, "w") as f:
                    for k, v in state.items():
                        f.write(f"{k}={v}\n")
                status_txt.set_text(f"⚕ автодиалог ВКЛ: стартовый ход → OMP ({ts()})")
            else:
                status_txt.set_text(f"⚕ автодиалог ВКЛ (продолжаем, {ts()})")
        else:
            status_txt.set_text(f"⚕ автодиалог ВЫКЛ ({ts()})")
        return
    if text == "@status":
        status_txt.set_text(f"⚕ hermes:{'ok' if last_h_snap.strip() else 'нет'} omp:{'ok' if last_o_snap.strip() else 'нет'} dao:{'есть' if os.path.exists(DAO_INBOX) else 'нет'} ({ts()})")
        return
    if text.startswith("@o "):
        send_to(OMP_SESSION, text[3:].strip())
        status_txt.set_text(f"⚕ → OMP отправлено ({ts()})")
        return
    if text.startswith("@d "):
        send_dao(text[3:].strip())
        status_txt.set_text(f"⚕ → Dao отправлено ({ts()})")
        return
    if text.startswith("@h "):
        send_to(HERMES_SESSION, text[3:].strip())
        status_txt.set_text(f"⚕ → Hermes отправлено ({ts()})")
        return
    send_to(HERMES_SESSION, text)
    status_txt.set_text(f"⚕ → Hermes отправлено ({ts()})")

loop = urwid.MainLoop(frame, palette, unhandled_input=lambda key: None)
loop.set_alarm_in(1, refresh_ui)
loop.run()
