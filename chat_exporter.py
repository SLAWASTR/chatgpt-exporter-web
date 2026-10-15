"""
Модуль для выгрузки и парсинга публичных чатов ChatGPT (по ссылке 'Share')
в текстовый формат (.txt) и HTML (.html) с полной поддержкой изображений и вложений.

Не требует внешних зависимостей — работает на стандартной библиотеке Python 3.
"""

import datetime
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


def normalize_chat_url(url_or_id: str) -> Tuple[str, str]:
    """
    Принимает ссылку на чат ChatGPT (или UUID) и возвращает нормализованный URL
    и идентификатор шаринга (share_id).
    """
    raw = url_or_id.strip()
    if not raw:
        raise ValueError("Введена пустая ссылка.")

    # 1. Поиск share/<id>
    match_share = re.search(r"share/([a-zA-Z0-9_-]+)", raw)
    if match_share:
        share_id = match_share.group(1)
        return f"https://chatgpt.com/share/{share_id}", share_id

    # 2. Поиск UUID
    match_uuid = re.search(
        r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        raw,
    )
    if match_uuid:
        share_id = match_uuid.group(1)
        return f"https://chatgpt.com/share/{share_id}", share_id

    # 3. Общий HTTP URL
    if raw.startswith(("http://", "https://")):
        clean = re.sub(r"[?#].*$", "", raw).rstrip("/")
        share_id = clean.split("/")[-1]
        return clean, share_id

    raise ValueError(
        f"Не удалось распознать ссылку на чат ChatGPT: '{raw}'.\n"
        "Ожидается ссылка вида https://chatgpt.com/share/..."
    )


def fetch_chat_html(url: str, timeout: int = 20) -> str:
    """
    Загружает HTML-код публичной страницы чата ChatGPT.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            html_bytes = response.read()
            return html_bytes.decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError(
                "Чат не найден (ошибка 404). Возможно, ссылка устарела или автор закрыл к ней доступ."
            ) from e
        elif e.code == 403:
            raise RuntimeError(
                "Доступ ограничен (ошибка 403 Cloudflare/ChatGPT). Попробуйте позже."
            ) from e
        else:
            raise RuntimeError(f"Сетевая ошибка при загрузке страницы: HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Не удалось подключиться к серверу: {e.reason}") from e


def decode_turbo_stream(flat_data: List[Any]) -> Any:
    """
    Десериализует массив TurboJSON / React Router / Remix stream.
    """
    memo: Dict[int, Any] = {}
    visited = set()

    def resolve(idx: Any) -> Any:
        if idx == -5:
            return None
        if not isinstance(idx, int) or isinstance(idx, bool):
            return idx
        if idx < 0 or idx >= len(flat_data):
            return None
        if idx in memo:
            return memo[idx]
        if idx in visited:
            return None

        visited.add(idx)
        val = flat_data[idx]

        if isinstance(val, (str, float, bool)) or val is None or isinstance(val, int):
            memo[idx] = val
            return val
        elif isinstance(val, list):
            if len(val) == 2 and val[0] in ("P", "D", "B", "S", "E"):
                memo[idx] = val
                return val
            res_list: List[Any] = []
            memo[idx] = res_list
            for item in val:
                if isinstance(item, int) and (item >= 0 or item == -5):
                    res_list.append(resolve(item))
                else:
                    res_list.append(item)
            return res_list
        elif isinstance(val, dict):
            res_dict: Dict[str, Any] = {}
            memo[idx] = res_dict
            for k, v in val.items():
                if k.startswith("_"):
                    try:
                        k_idx = int(k[1:])
                        resolved_k = resolve(k_idx)
                        key_str = str(resolved_k) if resolved_k is not None else k
                    except ValueError:
                        key_str = k
                else:
                    key_str = k

                if isinstance(v, int) and (v >= 0 or v == -5):
                    res_dict[key_str] = resolve(v)
                else:
                    res_dict[key_str] = v
            return res_dict
        else:
            memo[idx] = val
            return val

    return resolve(0)


def find_conversation_in_tree(obj: Any) -> Optional[Dict[str, Any]]:
    """
    Рекурсивно находит объект диалога в распарсенном дереве состояний.
    """
    if isinstance(obj, dict):
        if "linear_conversation" in obj and isinstance(obj["linear_conversation"], list):
            return obj
        if "mapping" in obj and isinstance(obj["mapping"], dict) and "title" in obj:
            return obj
        for v in obj.values():
            found = find_conversation_in_tree(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_conversation_in_tree(item)
            if found:
                return found
    return None


def extract_conversation_from_html(html: str) -> Dict[str, Any]:
    """
    Извлекает данные чата из HTML-кода страницы.
    """
    marker = "streamController.enqueue("
    pos = 0
    while True:
        pos = html.find(marker, pos)
        if pos == -1:
            break
        start = pos + len(marker)
        script_end = html.find("</script>", start)
        snippet = html[start:script_end if script_end != -1 else len(html)].strip()

        if snippet.endswith(";"):
            snippet = snippet[:-1].rstrip()
        if snippet.endswith(")"):
            snippet = snippet[:-1].rstrip()

        try:
            raw_parsed = json.loads(snippet)
            if isinstance(raw_parsed, str):
                raw_parsed = json.loads(raw_parsed.rstrip("\n"))
            if isinstance(raw_parsed, list):
                tree = decode_turbo_stream(raw_parsed)
                conv = find_conversation_in_tree(tree)
                if conv:
                    return conv
        except Exception:
            pass

        pos = script_end if script_end != -1 else start + 1

    for ctx_pattern in [
        r"window\.__reactRouterContext\s*=\s*(\{.*?\});",
        r"window\.__remixContext\s*=\s*(\{.*?\});",
    ]:
        match = re.search(ctx_pattern, html, re.DOTALL)
        if match:
            try:
                tree = json.loads(match.group(1))
                conv = find_conversation_in_tree(tree)
                if conv:
                    return conv
            except Exception:
                pass

    next_match = re.search(
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    if next_match:
        try:
            tree = json.loads(next_match.group(1))
            conv = find_conversation_in_tree(tree)
            if conv:
                return conv
        except Exception:
            pass

    raise RuntimeError(
        "Не удалось извлечь данные диалога из страницы. "
        "Возможно, структура страницы ChatGPT обновилась или ссылка недоступна."
    )


def clean_chatgpt_text(text: str) -> str:
    """
    Очищает внутренние служебные токены ChatGPT Search, карт и цитат.
    Превращает \\ue200map\\ue201 в читаемый блок 📍 [Карта мест].
    """
    if not text:
        return ""
    # Заменяем служебные теги карты
    text = re.sub(r"[\ue200\ue201]map[\ue200\ue201]?", "📍 [Карта мест / Магазины]", text)
    # Убираем внутренние служебные цитаты вида citeturn0search3
    text = re.sub(r"[\ue200\ue201]cite[^\ue200\ue201]*[\ue200\ue201]?", "", text)
    # Убираем служебные сущности вида entity...
    text = re.sub(r"[\ue200\ue201]entity[^\ue200\ue201]*[\ue200\ue201]?", "", text)
    # Удаляем любые оставшиеся непечатаемые спецсимволы Private Use Area
    text = re.sub(r"[\ue200-\ue205]", "", text)
    return text.strip()


def parse_conversation_data(conv_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Приводит сырые данные диалога к структурированному виду с извлечением:
      - title: название чата
      - create_time: время создания
      - update_time: время обновления
      - model_name: название модели (GPT-4, GPT-6 и т.д.)
      - messages: список сообщений с текстом, вложениями (attachments) и картинками (images)
    """
    title = conv_data.get("title") or "Чат ChatGPT"
    create_time = conv_data.get("create_time")
    update_time = conv_data.get("update_time")

    model_info = conv_data.get("model") or {}
    model_name = model_info.get("title") or model_info.get("slug") or conv_data.get("default_model_slug") or ""

    raw_nodes: List[Dict[str, Any]] = []

    if conv_data.get("linear_conversation"):
        raw_nodes = conv_data["linear_conversation"]
    elif conv_data.get("mapping"):
        mapping = conv_data["mapping"]
        curr = conv_data.get("current_node")
        if not curr or curr not in mapping:
            leaves = [nid for nid, node in mapping.items() if not node.get("children")]
            curr = leaves[0] if leaves else None

        chain: List[Dict[str, Any]] = []
        visited = set()
        while curr and curr in mapping and curr not in visited:
            visited.add(curr)
            node = mapping[curr]
            chain.append(node)
            curr = node.get("parent")

        chain.reverse()
        raw_nodes = chain

    messages: List[Dict[str, Any]] = []

    for item in raw_nodes:
        msg = item.get("message")
        if not msg:
            continue

        author = msg.get("author") or {}
        role = author.get("role", "")
        # Игнорируем внутренние скрытые плагины/инструменты (The output of this plugin was redacted)
        if role in ("tool", "system"):
            continue

        meta = msg.get("metadata") or {}
        content = msg.get("content") or {}

        # 1. Извлекаем прикрепленные пользователем файлы/фото
        attachments: List[Dict[str, Any]] = []
        for att in meta.get("attachments", []):
            name = att.get("name") or "Прикрепленное фото"
            sz_bytes = att.get("size") or 0
            sz_kb = sz_bytes // 1024
            w = att.get("width")
            h = att.get("height")
            dim = f"{w}x{h}" if w and h else ""
            attachments.append({
                "name": name,
                "size_kb": sz_kb,
                "dimensions": dim,
                "mime_type": att.get("mime_type", ""),
                "id": att.get("id", ""),
            })

        # 2. Извлекаем текст и ссылки на изображения
        parts = content.get("parts", [])
        text_parts: List[str] = []
        images: List[str] = []

        for p in parts:
            if isinstance(p, str):
                text_parts.append(p)
                # Ищем картинки в Markdown ![alt](url)
                for img_match in re.finditer(r"!\[(.*?)\]\((https?://[^\s\)]+)\)", p):
                    img_url = img_match.group(2)
                    if img_url not in images:
                        images.append(img_url)
            elif isinstance(p, dict):
                # Внутренние структуры DALL-E или картинки
                if "image_url" in p and p["image_url"] not in images:
                    images.append(p["image_url"])
                elif "url" in p and p["url"] not in images:
                    images.append(p["url"])
                elif "text" in p and isinstance(p["text"], str):
                    text_parts.append(p["text"])

        # 3. Извлекаем картинки из поиска/карт (content_references safe_urls)
        for cr in meta.get("content_references", []):
            for u in cr.get("safe_urls", []):
                if u and ("images.openai.com" in u or any(u.lower().endswith(ext) for ext in [".jpg", ".png", ".webp", ".jpeg"])):
                    if u not in images:
                        images.append(u)

        raw_text = "\n".join(text_parts).strip()
        clean_text = clean_chatgpt_text(raw_text)

        # Пропускаем технические заглушки
        if clean_text == "Original custom instructions no longer available":
            continue
        if not clean_text and not attachments and not images:
            continue

        role_label = {
            "user": "Пользователь",
            "assistant": "ChatGPT",
        }.get(role, role.capitalize() if role else "Сообщение")

        ts = msg.get("create_time")
        dt_str = ""
        if ts:
            try:
                dt_str = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                dt_str = ""

        messages.append({
            "role": role,
            "role_label": role_label,
            "text": clean_text,
            "attachments": attachments,
            "images": images,
            "timestamp": ts,
            "datetime_str": dt_str,
        })

    return {
        "title": title,
        "create_time": create_time,
        "update_time": update_time,
        "model_name": model_name,
        "messages": messages,
    }


def format_chat_to_text(
    parsed: Dict[str, Any],
    source_url: Optional[str] = None,
    include_header: bool = True,
    include_timestamps: bool = True,
) -> str:
    """
    Форматирует распарсенный чат в текстовый документ (.txt).
    Включает информацию о прикрепленных файлах и ссылки на изображения.
    """
    lines: List[str] = []
    separator_major = "=" * 80
    separator_minor = "-" * 80

    if include_header:
        lines.append(separator_major)
        lines.append(f"Название: {parsed.get('title', 'Чат ChatGPT')}")
        if parsed.get("model_name"):
            lines.append(f"Модель: {parsed['model_name']}")

        create_ts = parsed.get("create_time")
        if create_ts:
            try:
                dt = datetime.datetime.fromtimestamp(create_ts).strftime("%Y-%m-%d %H:%M:%S")
                lines.append(f"Дата создания: {dt}")
            except Exception:
                pass

        if source_url:
            lines.append(f"Ссылка: {source_url}")

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"Дата выгрузки: {now_str}")
        lines.append(separator_major)
        lines.append("")

    messages = parsed.get("messages", [])
    for i, m in enumerate(messages):
        role_label = m["role_label"]
        dt_str = m.get("datetime_str")

        if include_timestamps and dt_str:
            lines.append(f"[{role_label}] • {dt_str}")
        else:
            lines.append(f"[{role_label}]")

        # Выводим инфо о прикрепленных фото/файлах
        for att in m.get("attachments", []):
            dim_str = f", {att['dimensions']}" if att.get("dimensions") else ""
            lines.append(f"📷 [Прикрепленный файл: {att['name']} ({att.get('size_kb', 0)} КБ{dim_str})]")

        if m["text"]:
            lines.append(m["text"])

        # Выводим ссылки на изображения
        images = m.get("images", [])
        if images:
            lines.append("")
            lines.append(f"🖼️ [Изображения / Карточки поиска ({len(images)} шт.):]")
            for img_idx, img_url in enumerate(images, 1):
                lines.append(f"   {img_idx}. {img_url}")

        if i < len(messages) - 1:
            lines.append("")
            lines.append(separator_minor)
            lines.append("")

    if include_header:
        lines.append("")
        lines.append(separator_major)
        lines.append(f"Конец чата (всего сообщений: {len(messages)})")
        lines.append(separator_major)

    return "\n".join(lines)


def format_chat_to_html(
    parsed: Dict[str, Any],
    source_url: Optional[str] = None,
) -> str:
    """
    Генерирует автономный HTML-документ (.html) с красивой версткой,
    полной поддержкой изображений и оптимизацией под печать/сохранение в PDF (A4).
    """
    title = parsed.get("title", "Чат ChatGPT")
    model_name = parsed.get("model_name", "ChatGPT")

    create_ts = parsed.get("create_time")
    date_str = ""
    if create_ts:
        try:
            date_str = datetime.datetime.fromtimestamp(create_ts).strftime("%d.%m.%Y %H:%M")
        except Exception:
            date_str = ""

    html_parts = [
        "<!DOCTYPE html>",
        "<html lang='ru'>",
        "<head>",
        "  <meta charset='UTF-8'>",
        "  <meta name='viewport' content='width=device-width, initial-scale=1.0'>",
        f"  <title>{title} — Экспорт ChatGPT</title>",
        "  <style>",
        "    :root {",
        "      --bg: #f8fafc;",
        "      --text: #0f172a;",
        "      --user-bg: #e0e7ff;",
        "      --user-border: #6366f1;",
        "      --assistant-bg: #ffffff;",
        "      --assistant-border: #cbd5e1;",
        "    }",
        "    * { box-sizing: border-box; margin: 0; padding: 0; }",
        "    body {",
        "      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;",
        "      background: var(--bg);",
        "      color: var(--text);",
        "      line-height: 1.6;",
        "      padding: 30px 20px;",
        "    }",
        "    .container { max-width: 860px; margin: 0 auto; }",
        "    .header {",
        "      background: #ffffff;",
        "      border: 1px solid #e2e8f0;",
        "      border-radius: 12px;",
        "      padding: 20px;",
        "      margin-bottom: 24px;",
        "      box-shadow: 0 2px 4px rgba(0,0,0,0.05);",
        "    }",
        "    .header h1 { font-size: 22px; font-weight: 700; margin-bottom: 6px; }",
        "    .header-meta { font-size: 13px; color: #64748b; }",
        "    .instruction-badge {",
        "      margin-top: 12px;",
        "      padding: 10px 14px;",
        "      background: #eff6ff;",
        "      border-left: 4px solid #3b82f6;",
        "      border-radius: 4px;",
        "      font-size: 13px;",
        "      color: #1e40af;",
        "    }",
        "    .chat-flow { display: flex; flex-direction: column; gap: 20px; }",
        "    .message {",
        "      border-radius: 12px;",
        "      padding: 18px;",
        "      background: #ffffff;",
        "      border: 1px solid #e2e8f0;",
        "      page-break-inside: avoid;",
        "    }",
        "    .message.user {",
        "      background: var(--user-bg);",
        "      border: 1px solid var(--user-border);",
        "    }",
        "    .message.assistant {",
        "      background: var(--assistant-bg);",
        "      border: 1px solid var(--assistant-border);",
        "    }",
        "    .msg-header {",
        "      display: flex;",
        "      justify-content: space-between;",
        "      font-size: 12px;",
        "      font-weight: 700;",
        "      text-transform: uppercase;",
        "      letter-spacing: 0.5px;",
        "      margin-bottom: 10px;",
        "      color: #475569;",
        "    }",
        "    .msg-body { font-size: 15px; white-space: pre-wrap; word-break: break-word; }",
        "    .attachment-box {",
        "      display: inline-flex;",
        "      align-items: center;",
        "      gap: 8px;",
        "      padding: 8px 12px;",
        "      background: #f1f5f9;",
        "      border: 1px solid #cbd5e1;",
        "      border-radius: 8px;",
        "      font-size: 13px;",
        "      font-weight: 600;",
        "      margin-bottom: 12px;",
        "      color: #334155;",
        "    }",
        "    .image-grid {",
        "      display: grid;",
        "      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));",
        "      gap: 12px;",
        "      margin-top: 14px;",
        "    }",
        "    .image-card {",
        "      border-radius: 8px;",
        "      overflow: hidden;",
        "      border: 1px solid #e2e8f0;",
        "      background: #f8fafc;",
        "    }",
        "    .image-card img {",
        "      width: 100%;",
        "      height: 180px;",
        "      object-fit: cover;",
        "      display: block;",
        "    }",
        "    @media print {",
        "      body { background: #ffffff; padding: 0; }",
        "      .container { max-width: 100%; }",
        "      .header { box-shadow: none; border-color: #cbd5e1; }",
        "      .message { box-shadow: none; border: 1px solid #cbd5e1; }",
        "      .image-card img { height: 140px; }",
        "    }",
        "  </style>",
        "</head>",
        "<body>",
        "  <div class='container'>",
        "    <header class='header'>",
        f"      <h1>💬 {title}</h1>",
        f"      <div class='header-meta'>Модель: <strong>{model_name}</strong> • Дата: {date_str}</div>",
        "      <div class='instruction-badge'>💡 <strong>Для продолжения контекста в новом чате ChatGPT:</strong> Прикрепите этот файл через скрепку 📎 в новый чат, и ChatGPT продолжит диалог с полным пониманием всей истории и картинок.</div>",
        "    </header>",
        "    <div class='chat-flow'>",
    ]

    for m in parsed.get("messages", []):
        role_class = "user" if m["role"] == "user" else "assistant"
        role_label = m["role_label"]
        dt_str = m.get("datetime_str", "")

        html_parts.append(f"    <div class='message {role_class}'>")
        html_parts.append(f"      <div class='msg-header'><span>{role_label}</span><span>{dt_str}</span></div>")

        for att in m.get("attachments", []):
            dim_str = f" • {att['dimensions']}" if att.get("dimensions") else ""
            html_parts.append(f"      <div class='attachment-box'>📷 {att['name']} ({att.get('size_kb', 0)} КБ{dim_str})</div>")

        # Экранируем текст для безопасного вывода в HTML
        safe_text = m["text"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        html_parts.append(f"      <div class='msg-body'>{safe_text}</div>")

        images = m.get("images", [])
        if images:
            html_parts.append("      <div class='image-grid'>")
            for img_url in images:
                html_parts.append(f"        <div class='image-card'><a href='{img_url}' target='_blank'><img src='{img_url}' loading='lazy' alt='Изображение из чата' /></a></div>")
            html_parts.append("      </div>")

        html_parts.append("    </div>")

    html_parts.extend([
        "    </div>",
        "  </div>",
        "</body>",
        "</html>",
    ])

    return "\n".join(html_parts)


def sanitize_filename(name: str) -> str:
    """
    Очищает строку для безопасного использования в качестве имени файла.
    """
    clean = re.sub(r'[\\/*?:"<>|]', "", name)
    clean = re.sub(r"\s+", " ", clean).strip()
    clean = clean.strip(" .")
    if not clean:
        clean = "chatgpt_export"
    return clean[:120]


def export_chat(
    url_or_id: str,
    output_path: Optional[str] = None,
    output_dir: Optional[str] = None,
    include_header: bool = True,
    include_timestamps: bool = True,
) -> Tuple[str, Dict[str, Any]]:
    """
    Основная функция: скачивает, парсит и сохраняет чат в файл .txt.
    """
    clean_url, share_id = normalize_chat_url(url_or_id)
    html = fetch_chat_html(clean_url)
    conv_data = extract_conversation_from_html(html)
    parsed = parse_conversation_data(conv_data)
    txt_content = format_chat_to_text(
        parsed,
        source_url=clean_url,
        include_header=include_header,
        include_timestamps=include_timestamps,
    )

    if output_path:
        final_path = os.path.abspath(output_path)
    else:
        title = parsed.get("title") or f"chat_{share_id}"
        filename = f"{sanitize_filename(title)}.txt"
        target_dir = os.path.abspath(output_dir or os.getcwd())
        final_path = os.path.join(target_dir, filename)

    os.makedirs(os.path.dirname(final_path), exist_ok=True)

    with open(final_path, "w", encoding="utf-8") as f:
        f.write(txt_content)

    return final_path, parsed
