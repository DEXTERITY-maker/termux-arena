# SPDX-License-Identifier: MIT
# Copyright (c) 2026 — Termux Arena. См. LICENSE.

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ARENA: единый интерактивный чат двух моделей — Hermes ↔ OMP.
Один общий лог, ходы по очереди: [Hermes] → [OMP] → [Hermes] → ...
Стиль: рамки ╭─ ╮, [Hermes] голубым, [OMP] пурпурным, статус-бар.

Запуск UI:      python3 ~/.hermes/arena_chat.py
Запуск без UI:  python3 ~/.hermes/arena_chat.py --headless "тема" --turns 4 --task "задача"
Смоук-тест UI:  python3 ~/.hermes/arena_chat.py --smoke
Consensus:      python3 ~/.hermes/arena_chat.py --headless "тема" --consensus --task "задача"

Команды: /start <тема> · /stop · /turns N · /task <задача> · /consensus · /clear · /status · /quit

Режим «дискуссия → задачка»: задай задачу (/task или --task) — после завершения
диалога Hermes выполнит её с контекстом последних сообщений, результат — блок [EXEC].

Режим «до согласия» (/consensus или --consensus): диалог идёт не фиксированное
число ходов, а пока модель не зафиксирует согласованный вывод (маркеры: «итог»,
«договорились», «согласовано», «фиксирую», «резюмирую», «план такой»). Потолок —
30 ходов. /turns N — быстрый режим.

После завершения диалога в режимах /task и /consensus краткий итог доставляется
в основную сессию Hermes (#1, tmux hermes-chat) как
«[Arena → Hermes] Итог дискуссии: …» — Hermes в основном диалоге видит результат
и может его исполнить. Если сессии нет — доставка тихо пропускается.
"""

import argparse
import datetime as dt
import os
import queue
import re
import subprocess
import sys
import threading
import time

HOME = os.path.expanduser("~")
DEFAULT_MAX_TURNS = 10
TIMEOUT = 120          # защита от зависания, сек
PAUSE = 2.5            # пауза между ходами, сек
CTX_WINDOW = 6         # последние N сообщений уходят в контекст
MAX_MSG_CHARS = 1200   # обрезка длинных ответов в контексте
EXEC_TIMEOUT = 300     # таймаут выполнения задачи, сек
EXEC_CTX = 8           # последние N сообщений уходят в контекст задачи
CONSENSUS_MAX = 30     # потолок ходов в режиме «до согласия»

MAIN_SESSION = "hermes-chat"   # основная сессия Hermes (#1): сюда уходит итог
SUMMARY_MAX = 300              # максимальная длина сводки, символов

FINAL_MARKERS = ("итог", "договорились", "согласовано",
                 "фиксирую", "резюмирую", "план такой")

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
BOX_RE = re.compile(r"┌─.*?┐.*?└─.*?┘", re.S)  # блок рассуждений hermes


def now_ts():
    return dt.datetime.now().strftime("%H:%M:%S")


def call_model(kind, text, timeout, stop_event=None):
    """Программный вызов модели. Возвращает (ok, stdout, err).
    stop_event: при установке подпроцесс убивается (реагирует /stop мгновенно)."""
    if kind == "hermes":
        cmd = ["hermes", "chat", "-q", text, "-Q", "-t", "",
               "--reasoning", "none"]
    else:
        cmd = ["omp", "-p", "--allow-home",
               "--model", "deepseek/deepseek-v4-flash",
               "--system-prompt",
               "Ты — ИИ-агент OMP, участник автономной дискуссии с агентом "
               "Hermes. Отвечай кратко, по делу, без пояснений формата."]
    try:
        use_stdin = (kind == "omp")
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,
                             stdin=subprocess.PIPE if use_stdin else None,
                             text=True, cwd=HOME)
        if use_stdin:
            p.stdin.write(text + "\n")
            p.stdin.close()
    except Exception as e:
        return False, "", str(e)
    start = time.time()
    while True:
        if stop_event is not None and stop_event.is_set():
            p.kill()
            p.communicate()
            return False, "", "остановлено по /stop"
        rc = p.poll()
        if rc is not None:
            out, err = p.communicate()
            return rc == 0, out, err
        if time.time() - start > timeout:
            p.kill()
            p.communicate()
            return False, "", f"таймаут {timeout}с"
        time.sleep(0.2)


def clean(text):
    text = ANSI_RE.sub("", text)
    text = BOX_RE.sub("", text)
    return text.strip().strip("\n").strip()


def match_final_marker(text):
    """Возвращает маркер завершения из ответа или None (режим «до согласия»)."""
    low = text.lower()
    for m in FINAL_MARKERS:
        if m in low:
            return m
    return None


def tmux_session_alive(name=MAIN_SESSION):
    """True, если tmux-сессия name существует. Ошибки tmux — как «нет сессии»."""
    try:
        r = subprocess.run(["tmux", "has-session", "-t", name],
                           capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def send_to_main_session(text):
    """Отправляет text в основную сессию Hermes (#1) через tmux send-keys.
    Обёртка в одинарные кавычки, апострофы экранируются ('\''). Если сессии
    нет — тихо пропускает и возвращает False."""
    if not tmux_session_alive():
        return False
    safe = text.replace("'", "'\\''")
    cmd = f"tmux send-keys -t {MAIN_SESSION} '{safe}' Enter"
    try:
        subprocess.run(cmd, shell=True, timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def build_prompt(topic, history, model, consensus=False):
    lines = [f"Тема дискуссии: «{topic}».",
             "Это автономная беседа двух ИИ-агентов: Hermes и OMP.",
             "История диалога (последние сообщения):"]
    for m, t in history[-CTX_WINDOW:]:
        t = t if len(t) <= MAX_MSG_CHARS else t[:MAX_MSG_CHARS] + "…"
        lines.append(f"[{m.upper()}]: {t}")
    if model == "hermes" and not history:
        lines.append("Ты открываешь дискуссию. Начни: коротко обозначь свою позицию по теме.")
    elif consensus:
        lines.append("Режим «до согласия»: дискуссия идёт, пока вы не придёте к "
                     "согласованному выводу. Когда согласие достигнуто, начни "
                     "финальный ответ со слова «Итог:» или «Согласовано:». До этого "
                     "продолжай аргументированную дискуссию, реагируя на собеседника.")
    else:
        lines.append("Твой ход. Продолжи дискуссию: развивай тему, реагируй на аргументы собеседника.")
    lines.append("Отвечай по-русски, 3–6 предложений, без приветствий и служебных пояснений.")
    return "\n".join(lines)


def format_history(history, n=EXEC_CTX):
    lines = []
    for m, t in history[-n:]:
        t = t if len(t) <= MAX_MSG_CHARS else t[:MAX_MSG_CHARS] + "…"
        lines.append(f"[{m.upper()}]: {t}")
    return "\n".join(lines)


def normalize(t):
    return re.sub(r"\s+", " ", t).strip().lower()[:300]


class Dialogue:
    """Движок автодиалога. Работает в отдельном потоке, события — через on_event."""

    def __init__(self, topic, max_turns, on_event, stop_event, task=None,
                 consensus=False):
        self.topic = topic
        self.max_turns = max_turns
        self.on_event = on_event        # on_event(kind, title, text)
        self.stop = stop_event
        self.task = task                # задача для режима «дискуссия → задачка»
        self.consensus = consensus      # режим «до согласия» (маркеры, потолок 30)
        self.history = []
        self.exec_done = False          # задача реально выполнена ([EXEC] отдан)

    def run(self):
        turns = CONSENSUS_MAX if self.consensus else self.max_turns
        final_marker = None
        for i in range(turns):
            if self.stop.is_set():
                self.on_event("warn", "⏹", "Диалог остановлен по /stop")
                return
            model = "hermes" if i % 2 == 0 else "omp"
            self.on_event("status", None,
                          f"ход {i+1}/{turns} · {model} думает…")
            ok, out, err = call_model(model, build_prompt(self.topic, self.history, model, self.consensus), TIMEOUT, self.stop)
            if self.stop.is_set():
                self.on_event("warn", "⏹", "Диалог остановлен по /stop")
                return
            if not ok:
                self.on_event("warn", "⚠", f"[{model.upper()}] не ответил: {err}")
                return
            text = clean(out)
            if not text:
                self.on_event("warn", "⚠", f"[{model.upper()}] вернул пустой ответ")
                return
            # анти-зацикливание: тот же ответ, что в прошлый раз у этой модели
            if len(self.history) >= 2 and self.history[-2][0] == model \
               and normalize(text) == normalize(self.history[-2][1]):
                self.on_event("warn", "⟳", f"[{model.upper()}] дословно повторил свой прошлый ответ — диалог остановлен")
                return
            self.history.append((model, text))
            self.on_event("msg", model, text, turn=i + 1)
            if self.consensus:
                m = match_final_marker(text)
                if m:
                    final_marker = m
                    self.on_event("consensus", model, m, turn=i + 1)
                    break
            if i < turns - 1:
                time.sleep(PAUSE)
        if self.consensus:
            if final_marker:
                self.on_event("status", None,
                              f"диалог завершён: согласованный вывод (маркер «{final_marker}»)")
            else:
                self.on_event("status", None,
                              f"диалог завершён: потолок {CONSENSUS_MAX} ходов без маркера")
        else:
            self.on_event("status", None, "диалог завершён: лимит ходов")
        if self.task:
            self.run_task()
        # доставка итога в основную сессию Hermes (#1) — только после реального диалога
        if (self.task or self.consensus) and self.history:
            self.deliver_summary()

    def run_task(self):
        """Режим «дискуссия → задачка»: итог диалога + задача → Hermes, результат [EXEC]."""
        self.on_event("status", None, "задача: Hermes выполняет…")
        hist = format_history(self.history, EXEC_CTX)
        prompt = (f"Выполни задачу «{self.task}».\n"
                  f"Контекст дискуссии (итог обсуждения):\n{hist}\n"
                  "Дай практический результат по задаче, опираясь на контекст. "
                  "Отвечай по-русски, конкретно и по делу.")
        ok, out, err = call_model("hermes", prompt, EXEC_TIMEOUT, self.stop)
        if not ok:
            self.on_event("warn", "⚠", f"[EXEC] не выполнен: {err}")
            return
        text = clean(out)
        if not text:
            self.on_event("warn", "⚠", "[EXEC] вернул пустой ответ")
            return
        self.on_event("exec", None, text)
        self.exec_done = True

    def build_summary(self):
        """Краткая практичная сводка дискуссии (для основной сессии)."""
        parts = [f"тема «{self.topic}»", f"{len(self.history)} ходов"]
        if self.history:
            last = " ".join(self.history[-1][1].split())
            if len(last) > SUMMARY_MAX:
                last = last[:SUMMARY_MAX].rstrip() + "…"
            parts.append(f"итог: {last}")
        if self.exec_done:
            parts.append("задача выполнена ([EXEC])")
        return " · ".join(parts)

    def deliver_summary(self):
        """Итог дискуссии → основная сессия Hermes (#1), чтобы Hermes видел результат."""
        ok = send_to_main_session(
            f"[Arena → Hermes] Итог дискуссии: {self.build_summary()}")
        if ok:
            self.on_event("status", None,
                          "итог отправлен в основную сессию Hermes (#1)")


def run_headless(topic, turns, task=None, consensus=False):
    """Прогон без UI: печатает диалог в stdout. Возвращает код выхода."""
    stop = threading.Event()
    ev = queue.Queue()
    d = Dialogue(topic, turns, lambda k, t, x, turn=None: ev.put((k, t, x, turn)), stop, task, consensus)
    d.run()
    n = 0
    e = 0
    c_turn = None
    while not ev.empty():
        k, t, x, turn = ev.get()
        if k == "msg":
            n += 1
            who = "HERMES" if t == "hermes" else "OMP"
            print(f"\n[{who}] ход {turn} ({now_ts()}):\n{x}")
        elif k == "exec":
            e += 1
            print(f"\n[EXEC] ({now_ts()}):\n{x}")
        elif k == "consensus":
            c_turn = turn
            who = "HERMES" if t == "hermes" else "OMP"
            print(f"\n[ИТОГ] ({now_ts()}) ход {turn}: {who} зафиксировал(а) "
                  f"согласованный вывод (маркер «{x}»)")
        elif k == "warn":
            print(f"\n⚠ {x}")
    tail = ""
    if c_turn:
        tail += f", согласовано на ходе {c_turn}"
    if e:
        tail += f", {e} задача выполнена"
    print(f"\n--- итог: {n} ходов{tail} ---")
    return 0 if n >= 1 else 1


# ─────────────────────────── UI (urwid) ───────────────────────────

def make_ui(topic, turns, on_event, stop_event, smoke=False):
    import urwid

    palette = [
        ("hermes", "light cyan", "black"),
        ("omp", "light magenta", "black"),
        ("topic", "yellow", "black"),
        ("status", "white", "black"),
        ("warn", "light red", "black"),
        ("exec", "light green", "black"),
        ("consensus", "yellow,bold", "black"),
        ("sep", "dark gray", "black"),
        ("frame", "white", "black"),
        ("prompt", "yellow,bold", "black"),
    ]

    log_walker = urwid.SimpleListWalker([])
    log_box = urwid.ListBox(log_walker)

    def add_line(title, body, attr, boxed=True, divider=False):
        if divider:
            log_walker.append(urwid.Text(("sep", "─" * 46)))
        if boxed:
            w = urwid.LineBox(urwid.Text(body), title=title, title_attr=attr)
        else:
            w = urwid.Text((attr, body))
        log_walker.append(w)
        log_box.set_focus(len(log_walker) - 1)

    header_text = urwid.Text(("topic", f"ARENA  Hermes ↔ OMP    тема: «{topic}»    ходы: {turns}"))
    header = urwid.LineBox(header_text, title="╭─ ARENA ─╮", title_attr="frame")

    status_text = urwid.Text(("status", "готов · /start <тема> · /turns N · /stop · /clear · /quit"))
    edit = urwid.Edit(("prompt", "> "))

    def submit(ed):
        cmd = ed.edit_text.strip()
        ed.set_edit_text("")
        if not cmd:
            return
        handle_command(cmd)

    def on_key(key):
        if key == "enter":
            submit(edit)
        return key

    def handle_command(cmd):
        global engine_thread, current_turns, active_topic, active_task, arena_mode
        parts = cmd.split(None, 1)
        c = parts[0].lower()
        if c == "/start":
            if engine_thread and engine_thread.is_alive():
                status_text.set_text(("status", "диалог уже идёт — /stop сначала"))
                return
            topic_name = parts[1].strip() if len(parts) > 1 else "свободная беседа"
            active_topic = topic_name
            mode_s = "до согласия" if arena_mode == "consensus" else f"до {current_turns} ходов"
            header_text.set_text(("topic", f"ARENA  Hermes ↔ OMP    тема: «{topic_name}»    режим: {mode_s}"))
            note = f", задача: «{active_task}»" if active_task else ""
            add_line("▶", f"Диалог стартует: «{topic_name}», {mode_s}{note}", "topic", boxed=False)
            stop_event.clear()
            d = Dialogue(topic_name, current_turns, push_event, stop_event, active_task,
                         consensus=(arena_mode == "consensus"))
            engine_thread = threading.Thread(target=d.run, daemon=True)
            engine_thread.start()
        elif c == "/stop":
            stop_event.set()
            status_text.set_text(("status", "останавливаю…"))
        elif c == "/turns":
            arena_mode = "turns"
            try:
                current_turns = max(1, min(int(parts[1]), 50))
                status_text.set_text(("status", f"быстрый режим: лимит ходов {current_turns}"))
                add_line("⚙", f"быстрый режим: лимит ходов {current_turns}", "status", boxed=False)
            except (IndexError, ValueError):
                add_line("⚙", f"быстрый режим, лимит ходов сейчас: {current_turns} (пример: /turns 6)", "status", boxed=False)
        elif c == "/consensus":
            arena_mode = "consensus"
            status_text.set_text(("status", "режим «до согласия»: до согласованного вывода, потолок 30 ходов"))
            add_line("⚙", "режим «до согласия» включён: диалог идёт до согласованного вывода (маркеры «итог», «согласовано»…), потолок 30 ходов", "status", boxed=False)
        elif c == "/task":
            if len(parts) > 1 and parts[1].strip():
                active_task = parts[1].strip()
                status_text.set_text(("status", f"задача запомнена: «{active_task}»"))
                add_line("⚙", f"задача запомнена: «{active_task}» — выполнится после завершения диалога", "status", boxed=False)
            else:
                active_task = None
                add_line("⚙", "задача очищена", "status", boxed=False)
        elif c == "/clear":
            log_walker.clear()
        elif c == "/status":
            state = "идёт диалог" if (engine_thread and engine_thread.is_alive()) else "простой"
            task_s = f"«{active_task}»" if active_task else "—"
            mode_s = "до согласия" if arena_mode == "consensus" else f"до {current_turns} ходов"
            add_line("⚙", f"тема: «{active_topic}» · режим: {mode_s} · задача: {task_s} · состояние: {state} · {now_ts()}", "status", boxed=False)
        elif c == "/help":
            add_line("⚙", "/start <тема> · /stop · /turns N · /task <задача> · /consensus · /clear · /status · /quit", "status", boxed=False)
        elif c == "/quit":
            stop_event.set()
            raise urwid.ExitMainLoop()
        else:
            add_line("⚙", f"неизвестная команда: {cmd} (см. /help)", "warn", boxed=False)

    def push_event(kind, title, text, turn=None):
        ev_queue.put((kind, title, text, turn))

    ev_queue = queue.Queue()

    def poll_events(loop, user_data):
        try:
            while True:
                kind, title, text, turn = ev_queue.get_nowait()
                if kind == "msg":
                    who = "HERMES" if title == "hermes" else "OMP"
                    attr = "hermes" if title == "hermes" else "omp"
                    add_line(f" {who} · {now_ts()} · ход {turn} ", text, attr, divider=True)
                elif kind == "warn":
                    add_line(" ⚠ ", text, "warn", divider=True)
                elif kind == "exec":
                    add_line(f" EXEC · {now_ts()} ", text, "exec", divider=True)
                elif kind == "consensus":
                    who = "HERMES" if title == "hermes" else "OMP"
                    add_line(f" ИТОГ · {now_ts()} · ход {turn} ",
                             f"{who} зафиксировал(а) согласованный вывод (маркер «{text}»). Диалог завершён досрочно.",
                             "consensus", divider=True)
                elif kind == "status":
                    status_text.set_text(("status", text))
        except queue.Empty:
            pass
        if smoke and engine_thread is not None and not engine_thread.is_alive() and ev_queue.empty():
            raise urwid.ExitMainLoop()
        loop.set_alarm_in(0.15, poll_events)

    footer = urwid.Pile([status_text, edit])
    frame = urwid.Frame(urwid.LineBox(log_box, title="╭─ ЧАТ ─╮", title_attr="frame"),
                        header=header, footer=footer, focus_part="footer")

    # смоук: сам запускает короткий диалог и выходит
    def smoke_start(loop, user_data):
        handle_command("/turns 3")
        handle_command("/start Смоук-тест арены")
        loop.set_alarm_in(0.5, lambda l, u: None)

    loop = urwid.MainLoop(frame, palette, unhandled_input=on_key)
    if smoke:
        loop.set_alarm_in(1.0, smoke_start)
    loop.set_alarm_in(0.15, poll_events)
    return loop


def main():
    global engine_thread, current_turns, active_topic, active_task, arena_mode
    engine_thread = None
    current_turns = DEFAULT_MAX_TURNS
    active_topic = "—"
    active_task = None
    arena_mode = "turns"
    ap = argparse.ArgumentParser(description="Арена двух моделей: Hermes ↔ OMP")
    ap.add_argument("--headless", metavar="ТЕМА", help="прогон без UI (печать диалога)")
    ap.add_argument("--turns", type=int, default=DEFAULT_MAX_TURNS, help="лимит ходов")
    ap.add_argument("--task", metavar="ЗАДАЧА", default=None,
                    help="задача после диалога (режим «дискуссия → задачка»)")
    ap.add_argument("--consensus", action="store_true",
                    help="режим «до согласия»: до согласованного вывода, потолок 30 ходов")
    ap.add_argument("--smoke", action="store_true", help="смоук-тест UI (сам стартует и выходит)")
    args = ap.parse_args()

    if args.headless:
        sys.exit(run_headless(args.headless, args.turns, args.task, args.consensus))

    loop = make_ui("—", args.turns,
                   lambda k, t, x, turn=None: None,
                   threading.Event(), smoke=args.smoke)
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
