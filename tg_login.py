#!/data/data/com.termux/files/usr/bin/python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 — Termux Arena. См. LICENSE.
#
# tg_login.py — вход в Telegram через MTProto (telethon) без пароля.
# Использование: python3 ~/.hermes/tg_login.py <номер_телефона>
# Ввод кода — интерактивный; сессия сохраняется в ~/.hermes/tg_session.session
import asyncio, sys, os
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

def load_env():
    env = {}
    p = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

async def main():
    if len(sys.argv) < 2:
        print("Использование: python3 tg_login.py <номер_телефона>")
        sys.exit(1)
    phone = sys.argv[1].strip()
    env = load_env()
    api_id = env.get("TG_API_ID") or input("api_id: ").strip()
    api_hash = env.get("TG_API_HASH") or input("api_hash: ").strip()

    session = os.path.expanduser("~/.hermes/tg_session")
    client = TelegramClient(session, int(api_id), api_hash)
    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"УЖЕ ВОШЁЛ: {me.first_name} (@{me.username}) — сессия активна")
        return
    await client.send_code_request(phone)
    print(f"Код отправлен на {phone}. Введи код из Telegram:")
    code = input("code: ").strip()
    try:
        await client.sign_in(phone, code)
    except SessionPasswordNeededError:
        # только реальный 2FA; неверный код/номер — падают с понятной ошибкой,
        # а не уводят в запрос пароля
        print("Включена двухфакторная защита — нужен облачный пароль.")
        pwd = input("password: ").strip()
        await client.sign_in(password=pwd)
    me = await client.get_me()
    print(f"ВХОД ВЫПОЛНЕН: {me.first_name} (@{me.username})")
    print("Сессия сохранена: ~/.hermes/tg_session.session")

asyncio.run(main())
