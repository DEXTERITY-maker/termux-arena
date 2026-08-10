# Changelog

Все заметные изменения проекта Termux Arena.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
проект придерживается [Semantic Versioning](https://semver.org/lang/ru/).


## [0.0.11] — 2026-08-10

### Added
- P0.1: обрезка ответов при записи в сессию (MAX_MSG_CHARS + «…»), полный текст в arena_logs
- P0.2: персистентная очередь вебхуков (файловый спилл + replay при старте)
- P0.3: пиннинг зависимостей (urwid==4.0.8, telethon==1.44.0) + проверка при старте
- P1.4: команды /resume и /sessions в UI
- P1.5: экспорт сессии в Markdown (/export <sid|last>, --export CLI)
- P1.6: спиннер-индикатор ожидания модели в статус-баре
- P2.7: network healthcheck (curl) перед стартом диалога
- P2.8: авто-prune старых сессий и логов (ARENA_PRUNE_DAYS, дефолт 30)

### Changed
- Версия 0.0.10 → 0.0.11
- requirements.txt: пиннинг точных версий

## [0.0.10] — 2026-08-10

### Changed
- Арена полностью на русском (промпты Hermes и OMP, включая рассуждения)

## [0.0.9] — 2026-08-10

### Fixed
- Маркер согласия: точное совпадение в начале ответа
- Повреждённый JSON сессии: явная диагностика
- Regex сессии: валидация 8 hex
- Webhook-потоки: корректный drain перед выходом

### Added
- Субагенты в видимых tmux-сессиях (subagent_tmux.sh)
- Keep-alive панели штурма

## [0.0.8] — 2026-08-10

### Added
- Пассивный интернет: Hermes всегда с тулсетами browser,web, OMP — с инструментами по умолчанию
- Единая постоянная сессия Hermes: создаётся один раз, session_id в `~/arena_hermes_session`, далее `hermes chat --resume <id>`
- Видимый мозговой штурм: `scripts/arena_sturm.sh` — headless в отдельной tmux-сессии `arena-shurm` (не в фоне)

### Changed
- Вебхуки отправляются в daemon-потоке: ход диалога не блокируется
- Маркер согласия распознаётся только в начале ответа («Итог:», «Согласовано:»)
- `session_end` вебхук отправляется после `[EXEC]`
- `--selftest-drop` использует мок моделей вместо реальных вызовов
- Валидация `session_id` в `--resume`/`--session-info` (ровно 8 hex)

### Fixed
- Сессии Hermes больше не плодятся: все вызовы идут в единую сессию
- Ложные срабатывания consensus на подстроках («в итоге я считаю…»)
- Мусорный `~/arena_logs/-.log` при вызове модели без сессии
- `/stop` прерывает паузу между ретраями
- Потеря данных при сбое записи: fsync перед rename
- Сбой `_interrupt` в обработчике больше не маскирует исходное исключение
- Повреждённый JSON сессии сообщается явно, а не как «не найдена»

## [0.0.7] — 2026-08-10

### Added
- Протокол v1: сессии в `~/arena_sessions/<id>.json`, атомарная запись после каждого хода
- `--resume <session_id>` — продолжение прерванной сессии
- `--selftest-drop` — автотест обрыва (обрыв → resume → проверка целостности)
- `--session-info <session_id>` — метаданные сессии в JSON
- Лог диалога: `~/arena_logs/<session_id>.log` (`ARENA_LOG_LEVEL=info|debug`)
- Вебхуки событий (start/turn/exec/end/interrupt/resume) на `ARENA_WEBHOOK_URL`, ретраи 1,2,4 с
- Фолбэк-модель OMP: `ARENA_OMP_FALLBACK_MODEL` после 3 ретраев
- `--quiet` — компактный вывод headless

## [0.0.5] — 2026-08-09

### Added
- Единый чат-лог: ходы `[HERMES]` → `[OMP]` → `[HERMES]` в одном потоке
- Автодиалог двух моделей (Hermes ↔ OMP) через CLI-бэкенды
- `/consensus` — диалог до согласия (маркеры с 4-го хода, потолок 30)
- `/task` — дискуссия → исполнение задачи Hermes (`[EXEC]`)
- Доставка итога в основную сессию Hermes (#1) через tmux
- `shell=False` во всех subprocess-вызовах, `--` перед текстом
- Env-конфиг с санитизацией: `ARENA_HOME`, `ARENA_MAIN_SESSION`, `ARENA_OMP_MODEL`, `ARENA_OMP_SYSTEM_PROMPT`
- Версионирование: `--version`, шапка UI и headless-запуска
