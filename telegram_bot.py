#!/usr/bin/env python3
"""
Telegram-бот для экспорта чатов ChatGPT прямо с мобильного телефона.
Работает полностью на стандартной библиотеке Python 3 (без сторонних библиотек).

Как запустить:
  1. Создайте бота в Telegram через @BotFather и получите токен.
  2. Запустите:
       BOT_TOKEN="ВАШ_ТОКЕН" python3 telegram_bot.py
     или введите токен при запросе в консоли.
  3. Отправьте боту в Telegram ссылку на чат ChatGPT — в ответ придет готовый .txt файл!
"""

import datetime
import json
import mimetypes
import os
import sys
import time
import urllib.parse
import urllib.request
import ssl

from chat_exporter import export_chat, normalize_chat_url


def send_telegram_request(token: str, method: str, data: dict = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    if data:
        json_data = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=json_data,
            headers={"Content-Type": "application/json"},
        )
    else:
        req = urllib.request.Request(url)

    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_document(token: str, chat_id: int, file_path: str, caption: str = ""):
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    boundary = f"----WebKitFormBoundary{int(time.time()*1000)}"
    filename = os.path.basename(file_path)

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    body = bytearray()

    # Поле chat_id
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'.encode("utf-8"))
    body.extend(f"{chat_id}\r\n".encode("utf-8"))

    # Поле caption
    if caption:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="caption"\r\n\r\n'.encode("utf-8"))
        body.extend(f"{caption}\r\n".encode("utf-8"))

    # Файл document
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode("utf-8")
    )
    body.extend(b"Content-Type: text/plain; charset=utf-8\r\n\r\n")
    body.extend(file_bytes)
    body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_bot(token: str):
    print("=" * 60)
    print("🤖 Telegram-бот для экспорта чатов запущен!")
    print("Отправьте ссылку на чат ChatGPT вашему боту в Telegram.")
    print("Для остановки нажмите Ctrl + C")
    print("=" * 60)

    offset = 0
    while True:
        try:
            updates = send_telegram_request(token, "getUpdates", {"offset": offset, "timeout": 20})
            for u in updates.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message")
                if not msg:
                    continue

                chat_id = msg["chat"]["id"]
                text = msg.get("text", "").strip()

                if text == "/start":
                    send_telegram_request(
                        token,
                        "sendMessage",
                        {
                            "chat_id": chat_id,
                            "text": (
                                "👋 Привет! Я бот для экспорта чатов из ChatGPT.\n\n"
                                "Просто отправь мне публичную ссылку на чат ChatGPT (Share link), "
                                "и я пришлю тебе готовый .txt файл!"
                            ),
                        },
                    )
                    continue

                if "chatgpt.com" in text or "openai.com" in text or len(text) == 36:
                    send_telegram_request(
                        token,
                        "sendMessage",
                        {"chat_id": chat_id, "text": "⏳ Загружаю и конвертирую чат..."},
                    )
                    try:
                        saved_path, parsed = export_chat(text)
                        caption = (
                            f"✅ {parsed.get('title')}\n"
                            f"💬 Сообщений: {len(parsed.get('messages', []))}\n"
                            f"🤖 Модель: {parsed.get('model_name', 'ChatGPT')}"
                        )
                        send_document(token, chat_id, saved_path, caption=caption)
                    except Exception as e:
                        send_telegram_request(
                            token,
                            "sendMessage",
                            {"chat_id": chat_id, "text": f"❌ Ошибка экспорта: {e}"},
                        )
                else:
                    send_telegram_request(
                        token,
                        "sendMessage",
                        {
                            "chat_id": chat_id,
                            "text": "Отправьте корректную ссылку вида https://chatgpt.com/share/...",
                        },
                    )
        except KeyboardInterrupt:
            print("\nБот остановлен.")
            break
        except Exception as e:
            time.sleep(2)


if __name__ == "__main__":
    bot_token = os.environ.get("BOT_TOKEN")
    if not bot_token:
        if len(sys.argv) > 1:
            bot_token = sys.argv[1]
        else:
            bot_token = input("Введите токен Telegram-бота (от @BotFather): ").strip()

    if not bot_token:
        print("Ошибка: токен не указан.")
        sys.exit(1)

    run_bot(bot_token)
