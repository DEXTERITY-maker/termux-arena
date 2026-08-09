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
Resume:         python3 ~/.hermes/arena_chat.py --headless "тема" --resume <session_id>
Тихий режим:    python3 ~/.hermes/arena_chat.py --headless "тема" --quiet --log-level debug
Метаданные:     python3 ~/.hermes/arena_chat.py --session-info <session_id>
Автотест:       python3 ~/.hermes/arena_chat.py --selftest-drop

Команды: /start <тема> · /stop · /turns N · /task <задача> · /consensus · /clear · /status · /quit

Протокол v1 (v0.0.7): каждая сессия сохраняется в ~/arena_sessions/<id>.json
(topic/participants/status/history) после каждого хода — восстановление по
session_id без потерь и дублей; машиночитаемые метаданные — --session-info.
Полный лог диалога: ~/arena_logs/<session_id>.log (ARENA_LOG_LEVEL=info|debug).
Вебхуки: события session_start/turn/exec/session_end/interrupt/resume
POST-ом на ARENA_WEBHOOK_URL (ретраи 1,2,4 с). Фолбэк-провайдер OMP:
ARENA_OMP_FALLBACK_MODEL — попытка после RETRIES=3 с задержкой 2,4,8 с.

Интернет (v0.0.8): доступен всегда, пассивно — модели сами решают, когда
обращаться к сети. Hermes вызывается с тулсетами browser,web (без
--reasoning none); OMP — с включёнными инструментами (по умолчанию).
Вебхуки (v0.0.8): отправка в daemon-потоке — ход диалога не блокируется.
Маркер согласия распознаётся только в начале ответа («Итог:», «Согласовано:»).
Сессия Hermes (v0.0.8): единая постоянная — создаётся при первом вызове,
session_id хранится в <ARENA_HOME>/arena_hermes_session, дальше все вызовы
идут через `hermes chat --resume <id>` (сессии не плодятся).

Режим «дискуссия → задачка»: задай задачу (/task или --task) — после завершения
диалога Hermes выполнит её с контекстом последних сообщений, результат — блок [EXEC].

Режим «до согласия» (/consensus или --consensus): диалог идёт не фиксированное
число ходов, а пока модель не зафиксирует согласованный вывод (маркеры: «итог»,
«договорились», «согласовано», «фиксирую», «резюмирую», «план такой»).
Детекция работает не раньше 4-го хода (обе модели высказываются дважды),
потолок — 30 ходов. /turns N — быстрый режим.

После завершения диалога в режимах /task и /consensus краткий итог доставляется
в основную сессию Hermes (#1, tmux hermes-chat) как
«[Arena → Hermes] Итог дискуссии: …» — Hermes в основном диалоге видит результат
и может его исполнить. Если сессии нет — доставка тихо пропускается.

Настройка через переменные окружения (токены/пути в коде не зашиваются,
везде безопасные дефолты):
  ARENA_HOME              — рабочая директория (по умолчанию ~)
  ARENA_MAIN_SESSION      — tmux-сессия для доставки итога (hermes-chat)
  ARENA_OMP_MODEL         — модель OMP (deepseek/deepseek-v4-flash)
  ARENA_OMP_FALLBACK_MODEL— фолбэк-модель OMP (пусто = нет фолбэка)
  ARENA_OMP_SYSTEM_PROMPT — системный промпт OMP
  ARENA_WEBHOOK_URL       — вебхук событий (пусто = выключен)
  ARENA_LOG_LEVEL         — уровень лог-файла: info | debug (info)
"""

import argparse
import datetime as dt
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

__version__ = "0.0.8"

PROTOCOL_NAME = "arena-protocol"
PROTOCOL_VERSION = 1

def env_str(name, default, maxlen=512):
    """Переменная окружения с санитизацией: strip, лимит длины; пустое или
    слишком длинное значение → безопасный дефолт. Токены/пути не зашиваются —
    всё настраиваемое читается из env."""
    v = os.environ.get(name, "")
    v = v.strip()
    if not v or len(v) > maxlen:
        return default
    return v


def env_session_name(name, default):
    """Имя tmux-сессии из env: только безопасные символы (без ведущего
    дефиса, чтобы не быть принятым за флаг), иначе дефолт."""
    v = env_str(name, default, maxlen=64)
    return v if re.fullmatch(r"[A-Za-z0-9._-]+", v) and not v.startswith("-") \
        else default


def env_dir(name, default):
    """Путь из env: должен существовать и быть директорией, иначе дефолт."""
    v = env_str(name, default)
    return v if os.path.isdir(v) else default


HOME = env_dir("ARENA_HOME", os.path.expanduser("~"))
DEFAULT_MAX_TURNS = 10
TIMEOUT = 300          # защита от зависания, сек
PAUSE = 2.5            # пауза между ходами, сек
CTX_WINDOW = 6         # последние N сообщений уходят в контекст
MAX_MSG_CHARS = 1200   # обрезка длинных ответов в контексте
EXEC_TIMEOUT = 300     # таймаут выполнения задачи, сек
EXEC_CTX = 8           # последние N сообщений уходят в контекст задачи
CONSENSUS_MAX = 30     # потолок ходов в режиме «до согласия»
CONSENSUS_MIN = 4      # детекция согласия не раньше 4-го хода (обе модели высказались дважды)

MAIN_SESSION = env_session_name("ARENA_MAIN_SESSION", "hermes-chat")
OMP_MODEL = env_str("ARENA_OMP_MODEL", "deepseek/deepseek-v4-flash", maxlen=128)
OMP_FALLBACK_MODEL = env_str("ARENA_OMP_FALLBACK_MODEL", "", maxlen=128)
WEBHOOK_URL = env_str("ARENA_WEBHOOK_URL", "", maxlen=2048)
LOG_LEVEL = env_str("ARENA_LOG_LEVEL", "info", maxlen=16).lower()
if LOG_LEVEL not in ("info", "debug"):
    LOG_LEVEL = "info"
RETRIES = 3            # попытки вызова модели (с экспоненциальной задержкой)
RETRY_BACKOFF = (2, 4, 8)   # задержки между попытками, сек
WEBHOOK_RETRIES = 3
WEBHOOK_TIMEOUT = 5    # сек; отправка в потоке — ход диалога не блокируется
OMP_SYSTEM_PROMPT = env_str(
    "ARENA_OMP_SYSTEM_PROMPT",
    "Ты — ИИ-агент OMP, участник автономной дискуссии с агентом Hermes. "
    "Отвечай кратко, по делу, без пояснений формата.",
    maxlen=2000)
SUMMARY_MAX = 300              # максимальная длина сводки, символов

FINAL_MARKERS = ("итог", "договорились", "согласовано",
                 "фиксирую", "резюмирую", "план такой")

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
BOX_RE = re.compile(r"┌─.*?┐.*?└─.*?┘", re.S)  # блок рассуждений hermes

SID_RE = re.compile(r"[0-9a-fA-F]{8}")   # session_id: ровно 8 hex-символов
HERMES_SID_RE = re.compile(r"[0-9]{8}_[0-9]{6}_[0-9a-fA-F]{6}")
HERMES_SESSION_FILE = os.path.join(HOME, "arena_hermes_session")


def now_ts():
    return dt.datetime.now().strftime("%H:%M:%S")


def hermes_session_read():
    """session_id постоянной сессии Hermes из файла арены (или None)."""
    try:
        with open(HERMES_SESSION_FILE, encoding="utf-8") as f:
            sid = f.read().strip()
        return sid if HERMES_SID_RE.fullmatch(sid) else None
    except OSError:
        return None


def hermes_session_write(sid):
    """Сохранить session_id постоянной сессии Hermes (атомарно tmp+rename)."""
    if not sid or not HERMES_SID_RE.fullmatch(sid):
        return
    tmp = HERMES_SESSION_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(sid + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, HERMES_SESSION_FILE)
    except OSError:
        pass


def hermes_session_clear():
    """Сброс session_id (сессия пропала — следующий вызов создаст новую)."""
    try:
        os.remove(HERMES_SESSION_FILE)
    except OSError:
        pass


def parse_hermes_session(out):
    """session_id из вывода `hermes chat -Q` (после первого запуска)."""
    m = re.search(r"session[:_\s]*([0-9]{8}_[0-9]{6}_[0-9a-fA-F]{6})",
                  out or "")
    if m:
        return m.group(1)
    m = re.search(r"([0-9]{8}_[0-9]{6}_[0-9a-fA-F]{6})", out or "")
    return m.group(1) if m else None


def _is_missing_session(err):
    low = (err or "").lower()
    return ("не найдена" in low or "not found" in low
            or "no such session" in low)


def call_model(kind, text, timeout, stop_event=None, session_id=None):
    """Программный вызов модели. Возвращает (ok, stdout, err).
    Ретраи с экспоненциальной задержкой (2,4,8 с); для omp при окончательном
    сбое — фолбэк-модель (ARENA_OMP_FALLBACK_MODEL), если задана.
    stop_event: при установке подпроцесс убивается (реагирует /stop мгновенно)."""
    attempts = list(range(RETRIES))
    if kind == "omp" and OMP_FALLBACK_MODEL:
        attempts.append("fallback")
    last_err = ""
    resume_sid = hermes_session_read() if kind == "hermes" else None
    for attempt in attempts:
        if stop_event is not None and stop_event.is_set():
            return False, "", "остановлено по /stop"
        if attempt == "fallback":
            cmd = ["omp", "-p", "--allow-home",
                   "--model", OMP_FALLBACK_MODEL,
                   "--system-prompt", OMP_SYSTEM_PROMPT]
        elif kind == "hermes":
            cmd = ["hermes", "chat", "-q", text, "-Q",
                   "-t", "browser,web"]
            if resume_sid:
                cmd += ["--resume", resume_sid]
        else:
            cmd = ["omp", "-p", "--allow-home",
                   "--model", OMP_MODEL,
                   "--system-prompt", OMP_SYSTEM_PROMPT]
        label = "omp-fallback" if attempt == "fallback" else kind
        log_write(session_id, "debug",
                  f"вызов {label} (попытка {attempts.index(attempt) + 1}/"
                  f"{len(attempts)})…")
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
            last_err = str(e)
            continue
        start = time.time()
        while True:
            if stop_event is not None and stop_event.is_set():
                p.kill()
                p.communicate()
                return False, "", "остановлено по /stop"
            rc = p.poll()
            if rc is not None:
                out, err = p.communicate()
                if rc == 0:
                    if kind == "hermes":
                        nsid = (parse_hermes_session(out)
                                or parse_hermes_session(err))
                        if nsid:
                            hermes_session_write(nsid)
                    return True, out, err
                last_err = err.strip() or f"exit {rc}"
                if kind == "hermes" and resume_sid \
                   and _is_missing_session(err):
                    hermes_session_clear()
                    resume_sid = None   # следующая попытка — новая сессия
                break
            if time.time() - start > timeout:
                p.kill()
                p.communicate()
                last_err = f"таймаут {timeout}с"
                break
            time.sleep(0.2)
        if attempt != attempts[-1]:
            delay = RETRY_BACKOFF[min(attempts.index(attempt),
                                      len(RETRY_BACKOFF) - 1)]
            log_write(session_id, "debug",
                      f"{label}: сбой ({last_err}), повтор через {delay}с")
            deadline = time.time() + delay
            while time.time() < deadline:
                if stop_event is not None and stop_event.is_set():
                    return False, "", "остановлено по /stop"
                time.sleep(0.2)
    return False, "", last_err


def clean(text):
    text = ANSI_RE.sub("", text)
    text = BOX_RE.sub("", text)
    return text.strip().strip("\n").strip()


def match_final_marker(text):
    """Маркер завершения, только если ответ НАЧИНАЕТСЯ с него.
    Подстроки («в итоге я считаю…», «не согласовано») согласием не считаются."""
    low = re.sub(r"^\W+", "", text.lower())
    for m in FINAL_MARKERS:
        if low.startswith(m):
            rest = low[len(m):]
            if not rest or rest[0] in ":!.,»)\"'…— ":
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
    shell=False: аргументы передаются списком, без shell-интерпретации —
    пробелы и спецсимволы в сессии/тексте безопасны. Если сессии нет —
    тихо пропускает и возвращает False."""
    if not tmux_session_alive():
        return False
    try:
        subprocess.run(["tmux", "send-keys", "-t", MAIN_SESSION,
                        "--", text, "Enter"],
                       timeout=10,
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
        lines.append(f"Режим «до согласия»: дискуссия идёт, пока вы не придёте к "
                     f"согласованному выводу. Минимум {CONSENSUS_MIN} хода (обе "
                     f"стороны высказываются дважды) — не фиксируй итог раньше. "
                     f"Когда согласие достигнуто, начни финальный ответ со слова "
                     f"«Итог:» или «Согласовано:». До этого продолжай "
                     f"аргументированную дискуссию, реагируя на собеседника.")
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


# ─────────────────── Протокол v1: сессии, лог, вебхуки ───────────────────

def sessions_dir():
    d = os.path.join(HOME, "arena_sessions")
    os.makedirs(d, exist_ok=True)
    return d


def logs_dir():
    d = os.path.join(HOME, "arena_logs")
    os.makedirs(d, exist_ok=True)
    return d


def session_path(session_id):
    return os.path.join(sessions_dir(), f"{session_id}.json")


def new_session_id():
    return uuid.uuid4().hex[:8]


def make_session(topic, mode, max_turns, task=None):
    """Новая сессия протокола v1. Возвращает dict-метаданные."""
    ts = dt.datetime.now().isoformat(timespec="seconds")
    return {
        "protocol": PROTOCOL_NAME,
        "protocol_version": PROTOCOL_VERSION,
        "session_id": new_session_id(),
        "topic": topic,
        "participants": ["hermes", "omp"],
        "status": "running",
        "mode": mode,                 # "turns" | "consensus"
        "max_turns": max_turns,
        "task": task,
        "final_marker": None,
        "exec_done": False,
        "turns": 0,
        "created_at": ts,
        "updated_at": ts,
        "history": [],
    }


def save_session(sess):
    """Атомарная запись сессии (tmp + rename). Никогда не теряет данные."""
    sess["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    p = session_path(sess["session_id"])
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sess, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def load_session(session_id):
    """Загрузка сессии протокола v1 или None."""
    p = session_path(session_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def history_from_sess(sess):
    """[(model, text), ...] из машиночитаемой истории сессии."""
    return [(h["model"], h["text"]) for h in sess.get("history", [])]


def log_write(session_id, level, text):
    """Полное логирование диалога в файл arena_logs/<session_id>.log.
    debug-строки пишутся только при LOG_LEVEL=debug."""
    if not session_id or (level == "debug" and LOG_LEVEL != "debug"):
        return
    try:
        with open(os.path.join(logs_dir(), f"{session_id}.log"),
                  "a", encoding="utf-8") as f:
            f.write(f"[{now_ts()}] [{level.upper()}] {text}\n")
    except OSError:
        pass


_WEBHOOK_THREADS = []


def _webhook_post(sess, event, model=None, turn=None, text=None, extra=None):
    """POST машиночитаемого события на ARENA_WEBHOOK_URL.
    Ретраи 1,2,4 с, тихий фейл. Вызывается в daemon-потоке — диалог
    не блокируется и не ломается."""
    if not WEBHOOK_URL:
        return
    payload = {
        "protocol": PROTOCOL_NAME,
        "protocol_version": PROTOCOL_VERSION,
        "session_id": sess["session_id"],
        "event": event,
        "status": sess.get("status"),
        "turn": turn,
        "model": model,
        "text": (text[:2000] if text else None),
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
    }
    if extra:
        payload.update(extra)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_err = ""
    for attempt in range(WEBHOOK_RETRIES):
        try:
            req = urllib.request.Request(WEBHOOK_URL, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=WEBHOOK_TIMEOUT) as r:
                r.read()
            return
        except Exception as e:
            last_err = str(e)
            if attempt < WEBHOOK_RETRIES - 1:
                time.sleep(2 ** attempt)   # 1, 2, 4 с
    log_write(sess["session_id"], "warn",
              f"вебхук {event} не доставлен ({WEBHOOK_RETRIES} попыток): {last_err}")


def send_webhook(sess, event, model=None, turn=None, text=None, extra=None):
    """Отправка события в daemon-потоке: ход диалога не блокируется даже при
    недоступном вебхуке. Headless дожидается потоков после диалога."""
    if not WEBHOOK_URL:
        return
    t = threading.Thread(target=_webhook_post,
                         args=(sess, event, model, turn, text, extra),
                         daemon=True)
    _WEBHOOK_THREADS.append(t)
    t.start()


class Dialogue:
    """Движок автодиалога. Работает в отдельном потоке, события — через on_event.
    Протокол v1: сессия (topic/participants/status/history) сохраняется после
    каждого хода; при session_id — восстанавливается без потерь и дублей."""

    def __init__(self, topic, max_turns, on_event, stop_event, task=None,
                 consensus=False, session_id=None, quiet=False,
                 crash_after=None, call_fn=None):
        self.topic = topic
        self.max_turns = max_turns
        self.on_event = on_event        # on_event(kind, title, text)
        self.stop = stop_event
        self.task = task                # задача для режима «дискуссия → задачка»
        self.consensus = consensus      # режим «до согласия» (маркеры, потолок 30)
        self.quiet = quiet              # компактный вывод в stdout
        self.crash_after = crash_after  # тест обрыва: «умереть» после N ходов
        self.call_fn = call_fn or call_model  # хук вызова модели (selftest мокает)
        self.sess = None                # метаданные протокола v1
        self.history = []
        self.exec_done = False          # задача реально выполнена ([EXEC] отдан)
        self.base_turns = 0             # ходов уже было до этого запуска (resume)
        if session_id:
            self._load(session_id)

    # ── протокол v1 ──

    def _load(self, session_id):
        if not SID_RE.fullmatch(session_id or ""):
            raise ValueError(f"некорректный session_id: {session_id!r}")
        sess = load_session(session_id)
        if sess is None:
            raise ValueError(f"сессия {session_id} не найдена в {sessions_dir()}")
        if sess.get("status") == "completed":
            raise ValueError(f"сессия {session_id} уже завершена — начните новую")
        if sess.get("protocol_version") != PROTOCOL_VERSION:
            raise ValueError(f"несовместимая версия протокола: "
                             f"{sess.get('protocol_version')} != {PROTOCOL_VERSION}")
        self.sess = sess
        self.topic = sess.get("topic", self.topic)
        self.task = sess.get("task")
        self.consensus = sess.get("mode") == "consensus"
        self.max_turns = sess.get("max_turns", self.max_turns)
        self.history = history_from_sess(sess)
        self.base_turns = len(self.history)
        self.sess["status"] = "running"   # обрыв → продолжаем

    def _save(self, final_marker=None):
        if self.sess is None:
            return
        self.sess["history"] = [
            {"turn": i + 1, "model": m, "ts": now_ts(), "text": t}
            for i, (m, t) in enumerate(self.history)
        ]
        self.sess["turns"] = len(self.history)
        if final_marker:
            self.sess["final_marker"] = final_marker
        self.sess["exec_done"] = self.exec_done
        save_session(self.sess)

    def _interrupt(self, reason):
        if self.sess is None:
            return
        self.sess["status"] = "interrupted"
        self._save()
        log_write(self.sess["session_id"], "warn", f"прервано: {reason}")
        send_webhook(self.sess, "session_interrupt", extra={"reason": reason})

    # ── основной цикл ──

    def run(self):
        try:
            if self.sess is None:
                mode = "consensus" if self.consensus else "turns"
                self.sess = make_session(self.topic, mode, self.max_turns,
                                         self.task)
                self._save()
                log_write(self.sess["session_id"], "info",
                          f"сессия {self.sess['session_id']}: тема «{self.topic}»")
                send_webhook(self.sess, "session_start")
                self.on_event("status", None,
                              f"сессия {self.sess['session_id']} · {mode}")
            elif self.base_turns:
                log_write(self.sess["session_id"], "info",
                          f"возобновление: {self.base_turns} ходов восстановлено")
                send_webhook(self.sess, "session_resume",
                             extra={"resumed_turns": self.base_turns})
                self.on_event("status", None,
                              f"возобновлено: {self.base_turns} ходов из "
                              f"сессии {self.sess['session_id']}")
            turns = CONSENSUS_MAX if self.consensus else self.max_turns
            final_marker = None
            for i in range(self.base_turns, turns):
                if self.stop.is_set():
                    self.on_event("warn", "⏹", "Диалог остановлен по /stop")
                    self._interrupt("остановлен по /stop")
                    return
                model = "hermes" if i % 2 == 0 else "omp"
                turn_no = i + 1
                self.on_event("status", None,
                              f"ход {turn_no}/{turns} · {model} думает…")
                ok, out, err = self.call_fn(
                    model, build_prompt(self.topic, self.history, model,
                                        self.consensus),
                    TIMEOUT, self.stop, self.sess["session_id"])
                if self.stop.is_set():
                    self.on_event("warn", "⏹", "Диалог остановлен по /stop")
                    self._interrupt("остановлен по /stop")
                    return
                if not ok:
                    self.on_event("warn", "⚠", f"[{model.upper()}] не ответил: {err}")
                    self._interrupt(f"{model} не ответил: {err}")
                    return
                text = clean(out)
                if not text:
                    self.on_event("warn", "⚠", f"[{model.upper()}] вернул пустой ответ")
                    self._interrupt(f"{model} пустой ответ")
                    return
                # анти-зацикливание: тот же ответ, что в прошлый раз у этой модели
                if len(self.history) >= 2 and self.history[-2][0] == model \
                   and normalize(text) == normalize(self.history[-2][1]):
                    self.on_event("warn", "⟳", f"[{model.upper()}] дословно повторил свой прошлый ответ — диалог остановлен")
                    self._interrupt("анти-зацикливание")
                    return
                self.history.append((model, text))
                self._save()
                log_write(self.sess["session_id"], "info",
                          f"ход {turn_no} [{model.upper()}]: {text[:200]}")
                self.on_event("msg", model, text, turn=turn_no)
                send_webhook(self.sess, "turn", model=model, turn=turn_no,
                             text=text)
                if self.consensus and i >= CONSENSUS_MIN - 1:
                    m = match_final_marker(text)
                    if m:
                        final_marker = m
                        self._save(final_marker)
                        self.on_event("consensus", model, m, turn=turn_no)
                        break
                if self.crash_after and turn_no >= self.crash_after:
                    # имитация обрыва: статус остаётся running, история цела
                    self.on_event("warn", "💥",
                                  f"имитация обрыва после хода {turn_no}")
                    return
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
            self.sess["status"] = "completed"
            self._save(final_marker)
            log_write(self.sess["session_id"], "info",
                      f"завершено: {len(self.history)} ходов, "
                      f"status=completed")
            if self.task:
                self.run_task()
            send_webhook(self.sess, "session_end",
                         extra={"turns": len(self.history)})
            # доставка итога в основную сессию Hermes (#1) — только после реального диалога
            if (self.task or self.consensus) and self.history:
                self.deliver_summary()
        except Exception as e:
            # любой сбой — сессия помечается interrupted, данные не теряются
            if self.sess is not None:
                try:
                    self._interrupt(f"исключение: {e}")
                except Exception:
                    pass   # не маскировать исходное исключение
            raise

    def run_task(self):
        """Режим «дискуссия → задачка»: итог диалога + задача → Hermes, результат [EXEC]."""
        self.on_event("status", None, "задача: Hermes выполняет…")
        hist = format_history(self.history, EXEC_CTX)
        prompt = (f"Выполни задачу «{self.task}».\n"
                  f"Контекст дискуссии (итог обсуждения):\n{hist}\n"
                  "Дай практический результат по задаче, опираясь на контекст. "
                  "Отвечай по-русски, конкретно и по делу.")
        ok, out, err = self.call_fn("hermes", prompt, EXEC_TIMEOUT, self.stop,
                                    self.sess["session_id"] if self.sess else None)
        if not ok:
            self.on_event("warn", "⚠", f"[EXEC] не выполнен: {err}")
            return
        text = clean(out)
        if not text:
            self.on_event("warn", "⚠", "[EXEC] вернул пустой ответ")
            return
        self.on_event("exec", None, text)
        self.exec_done = True
        self._save()
        if self.sess:
            log_write(self.sess["session_id"], "info",
                      f"[EXEC]: {text[:200]}")
            send_webhook(self.sess, "exec", text=text)

    def build_summary(self):
        """Краткая практичная сводка дискуссии (для основной сессии)."""
        parts = [f"сессия {self.sess['session_id']}" if self.sess else "",
                 f"тема «{self.topic}»", f"{len(self.history)} ходов"]
        if self.history:
            last = " ".join(self.history[-1][1].split())
            if len(last) > SUMMARY_MAX:
                last = last[:SUMMARY_MAX].rstrip() + "…"
            parts.append(f"итог: {last}")
        if self.exec_done:
            parts.append("задача выполнена ([EXEC])")
        return " · ".join(p for p in parts if p)

    def deliver_summary(self):
        """Итог дискуссии → основная сессия Hermes (#1), чтобы Hermes видел результат."""
        ok = send_to_main_session(
            f"[Arena → Hermes] Итог дискуссии: {self.build_summary()}")
        if ok:
            self.on_event("status", None,
                          "итог отправлен в основную сессию Hermes (#1)")


def run_headless(topic, turns, task=None, consensus=False, session_id=None,
                 quiet=False):
    """Прогон без UI: печатает диалог в stdout. Возвращает код выхода."""
    print(f"arena_chat {__version__} · тема «{topic}»"
          f" · режим: {'до согласия' if consensus else f'до {turns} ходов'}"
          + (f" · resume {session_id}" if session_id else ""))
    stop = threading.Event()
    ev = queue.Queue()
    try:
        d = Dialogue(topic, turns,
                     lambda k, t, x, turn=None: ev.put((k, t, x, turn)),
                     stop, task, consensus, session_id=session_id,
                     quiet=quiet)
    except ValueError as e:
        print(f"⚠ {e}")
        return 2
    d.run()
    # дождаться daemon-потоков вебхуков (иначе процесс выйдет раньше них)
    for t in list(_WEBHOOK_THREADS):
        t.join(timeout=25)
        if t in _WEBHOOK_THREADS:
            _WEBHOOK_THREADS.remove(t)
    n = 0
    e = 0
    c_turn = None
    while not ev.empty():
        k, t, x, turn = ev.get()
        if k == "msg":
            n += 1
            who = "HERMES" if t == "hermes" else "OMP"
            if quiet:
                one = " ".join(x.split())
                print(f"{turn:>3} {who:<6} {now_ts()} | {one[:100]}")
            else:
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


def selftest_drop():
    """АВТОТЕСТ ОБРЫВА СЕССИИ (критерий приёмки v0.0.7):
    1) диалог на 2 хода с имитацией обрыва (статус остаётся running);
    2) resume по session_id — продолжение без потерь и дублей контекста;
    3) проверка: 4 хода, номера уникальны, тексты ходов 1–2 сохранены.
    Вызовы моделей замоканы (проверяется протокол, а не модели)."""
    print(f"arena_chat {__version__} · selftest-drop (обрыв сессии)")
    sid = None
    try:
        def fake_call_model(kind, text, timeout, stop_event=None,
                            session_id=None):
            """Мок вызова модели: детерминированные ответы без реальных CLI
            (selftest проверяет протокол сохранения/резюма, а не модели)."""
            n = fake_call_model.n
            fake_call_model.n += 1
            return True, f"ход {n}: ответ модели {kind} (тест)", ""
        fake_call_model.n = 0
        stop = threading.Event()
        ev = queue.Queue()
        d1 = Dialogue("Самопроверка обрыва сессии", 4,
                      lambda k, t, x, turn=None: ev.put((k, t, x, turn)),
                      stop, None, False, crash_after=2,
                      call_fn=fake_call_model)
        d1.run()
        sid = d1.sess["session_id"] if d1.sess else None
        if not sid:
            print("FAIL: сессия не создана")
            return 1
        sess = load_session(sid)
        if sess.get("status") != "running":
            print(f"FAIL: статус после обрыва = {sess.get('status')}, "
                  f"ожидался running")
            return 1
        if sess.get("turns") != 2 or len(sess.get("history", [])) != 2:
            print(f"FAIL: после обрыва {sess.get('turns')} ходов, "
                  f"ожидалось 2")
            return 1
        saved_first = [h["text"] for h in sess["history"]]
        print(f"обрыв имитирован: сессия {sid}, 2 хода, status=running")

        stop2 = threading.Event()
        ev2 = queue.Queue()
        d2 = Dialogue("", 4,
                      lambda k, t, x, turn=None: ev2.put((k, t, x, turn)),
                      stop2, None, False, session_id=sid,
                      call_fn=fake_call_model)
        d2.run()
        sess2 = load_session(sid)
        if sess2.get("status") != "completed":
            print(f"FAIL: после resume статус = {sess2.get('status')}, "
                  f"ожидался completed")
            return 1
        turns_n = [h["turn"] for h in sess2.get("history", [])]
        texts = [h["text"] for h in sess2.get("history", [])]
        if turns_n != [1, 2, 3, 4]:
            print(f"FAIL: номера ходов {turns_n}, ожидались [1,2,3,4]")
            return 1
        if len(set(texts)) != 4:
            print("FAIL: есть дубли текстов (контекст задублирован)")
            return 1
        if texts[:2] != saved_first:
            print("FAIL: тексты ходов 1–2 не совпадают с сохранёнными "
                  "(потеря контекста)")
            return 1
        print(f"resume OK: {sid} → 4 хода [1..4], без потерь и дублей")
        print("SELFTEST DROP: PASS")
        return 0
    except Exception as e:
        print(f"SELFTEST DROP: FAIL ({e})")
        return 1


def session_info(session_id):
    """Машиночитаемые метаданные сессии (протокол v1) в stdout."""
    if not SID_RE.fullmatch(session_id or ""):
        print(f"некорректный session_id: {session_id!r}")
        return 1
    p = session_path(session_id)
    if not os.path.exists(p):
        print(f"сессия {session_id} не найдена в {sessions_dir()}")
        return 1
    try:
        with open(p, encoding="utf-8") as f:
            sess = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"сессия {session_id}: повреждён файл ({e})")
        return 1
    print(json.dumps(sess, ensure_ascii=False, indent=2))
    return 0


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

    header_text = urwid.Text(("topic", f"ARENA v{__version__}  Hermes ↔ OMP    тема: «{topic}»    ходы: {turns}"))
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
    ap.add_argument("--version", action="version",
                    version=f"arena_chat {__version__}")
    ap.add_argument("--headless", metavar="ТЕМА", help="прогон без UI (печать диалога)")
    ap.add_argument("--turns", type=int, default=DEFAULT_MAX_TURNS, help="лимит ходов")
    ap.add_argument("--task", metavar="ЗАДАЧА", default=None,
                    help="задача после диалога (режим «дискуссия → задачка»)")
    ap.add_argument("--consensus", action="store_true",
                    help="режим «до согласия»: до согласованного вывода, потолок 30 ходов")
    ap.add_argument("--resume", metavar="SESSION_ID", default=None,
                    help="восстановить сессию по session_id (протокол v1)")
    ap.add_argument("--quiet", action="store_true",
                    help="компактный вывод в stdout (полный текст — в лог-файл)")
    ap.add_argument("--log-level", choices=["info", "debug"], default=None,
                    help="уровень лог-файла (по умолчанию ARENA_LOG_LEVEL=info)")
    ap.add_argument("--webhook", metavar="URL", default=None,
                    help="вебхук событий (перекрывает ARENA_WEBHOOK_URL)")
    ap.add_argument("--session-info", metavar="SESSION_ID", default=None,
                    help="машиночитаемые метаданные сессии (JSON) и выход")
    ap.add_argument("--selftest-drop", action="store_true",
                    help="автотест обрыва сессии: 2 хода → обрыв → resume → проверка")
    ap.add_argument("--smoke", action="store_true", help="смоук-тест UI (сам стартует и выходит)")
    args = ap.parse_args()

    global LOG_LEVEL, WEBHOOK_URL
    if args.log_level:
        LOG_LEVEL = args.log_level
    if args.webhook:
        WEBHOOK_URL = args.webhook

    if args.session_info:
        sys.exit(session_info(args.session_info))
    if args.selftest_drop:
        sys.exit(selftest_drop())
    if args.headless:
        sys.exit(run_headless(args.headless, args.turns, args.task,
                              args.consensus, args.resume, args.quiet))

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
