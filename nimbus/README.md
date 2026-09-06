# ☁ Nimbus AI

Веб-чат с моделями **DeepSeek**. Без зависимостей — только Python 3 (стандартная библиотека).
Работает в Termux, на Linux, macOS.

## Запуск
```bash
echo "DEEPSEEK_API_KEY=sk-..." > ../.env   # ключ лежит в .env в корне репо (в .gitignore)
python3 nimbus/server.py 8080
# открыть http://localhost:8080
```
Или `bash nimbus/run.sh 8080`.

## Возможности
- Выбор модели: список тянется из `GET /models` DeepSeek (deepseek-chat, deepseek-reasoner, …)
- Потоковый ответ (SSE), кнопка «стоп»
- Отдельный блок «Рассуждения» для reasoner-моделей
- История чатов в localStorage, системный промпт, температура
- Адаптивный тёмный интерфейс (телефон/десктоп)

## Переменные окружения
| Имя | По умолчанию |
|---|---|
| `DEEPSEEK_API_KEY` | — (обязателен) |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` |
| `PORT` / `HOST` | `8080` / `0.0.0.0` |

⚠️ Ключ никогда не попадает в браузер — все запросы идут через локальный сервер.
