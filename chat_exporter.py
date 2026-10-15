"""
Модуль для выгрузки и парсинга публичных чатов ChatGPT (по ссылке 'Share')
в текстовый формат (.txt) и HTML (.html) с полной поддержкой изображений и вложений.

Не требует внешних зависимостей — работает на стандартной библиотеке Python 3.
"""

import datetime
import http.cookiejar
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


def create_http_session() -> urllib.request.OpenerDirector:
    """
    Создает urllib opener с сохранением Cookie и отключенной строгой проверкой SSL
    (необходимо для стабильной работы на macOS и серверах без предустановленных корневых сертификатов).
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPSHandler(context=ctx),
    )
    return opener


def is_image_file(name: str = "", mime_type: str = "") -> bool:
    """Определяет, является ли файл изображением (по MIME или расширению)."""
    if mime_type and mime_type.startswith("image/"):
        return True
    ext = os.path.splitext((name or "").lower())[1]
    return ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".svg", ".heic", ".ico"]


def get_file_icon(name: str = "", mime_type: str = "") -> str:
    """Возвращает наглядный эмодзи-значок в зависимости от формата файла."""
    ext = os.path.splitext((name or "").lower())[1]
    mime = (mime_type or "").lower()
    if ext == ".pdf" or "pdf" in mime:
        return "📕"
    elif ext in [".xls", ".xlsx", ".csv", ".tsv"] or "spreadsheet" in mime or "excel" in mime:
        return "📊"
    elif ext in [".doc", ".docx"] or "word" in mime or "document" in mime:
        return "📄"
    elif ext in [".zip", ".rar", ".7z", ".tar", ".gz"]:
        return "📦"
    elif ext in [".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".sql", ".sh", ".c", ".cpp"]:
        return "💻"
    elif is_image_file(name, mime_type):
        return "📷"
    elif ext in [".mp3", ".wav", ".ogg", ".m4a"]:
        return "🎵"
    elif ext in [".mp4", ".mov", ".avi", ".mkv", ".webm"]:
        return "🎬"
    return "📎"


def resolve_shared_file_download_url(
    file_id: str,
    shared_id: str,
    session: Optional[urllib.request.OpenerDirector] = None,
    timeout: int = 8,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Получает прямую временную ссылку на скачивание/просмотр пользовательского файла (фото, pdf, xlsx и т.д.)
    из расшаренного чата ChatGPT через официальный анонимный эндпоинт.
    Возвращает (download_url, error_code).
    """
    if not file_id or not shared_id:
        return None, None

    clean_file_id = file_id.strip()
    if clean_file_id.startswith("sediment://"):
        clean_file_id = clean_file_id[len("sediment://"):]
    if "?" in clean_file_id:
        clean_file_id = clean_file_id.split("?")[0]

    api_url = f"https://chatgpt.com/backend-anon/files/download/{clean_file_id}?shared_conversation_id={shared_id}"
    req = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": f"https://chatgpt.com/share/{shared_id}",
            "Accept": "application/json",
        },
    )

    try:
        if session:
            resp = session.open(req, timeout=timeout)
        else:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
        data = json.loads(resp.read().decode("utf-8"))
        if data.get("status") == "success" and data.get("download_url"):
            return data["download_url"], None
        elif data.get("error_code") == "safety_check_failed":
            return None, "safety_check_failed"
        elif data.get("error_code"):
            return None, data["error_code"]
    except Exception as e:
        return None, str(e)
    return None, None


def fetch_chat_html(
    url: str,
    timeout: int = 20,
    session: Optional[urllib.request.OpenerDirector] = None,
) -> str:
    """
    Загружает HTML-код публичной страницы чата ChatGPT с сохранением cookie сессии.
    """
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
        if session:
            response = session.open(req, timeout=timeout)
        else:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            response = urllib.request.urlopen(req, timeout=timeout, context=ctx)

        with response:
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


def parse_conversation_data(
    conv_data: Dict[str, Any],
    shared_id: Optional[str] = None,
    session: Optional[urllib.request.OpenerDirector] = None,
) -> Dict[str, Any]:
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

    # Если shared_id не был передан явно, ищем его в метаданных сообщений
    if not shared_id:
        for item in raw_nodes:
            m_obj = item.get("message")
            if m_obj and m_obj.get("metadata", {}).get("shared_conversation_id"):
                shared_id = m_obj["metadata"]["shared_conversation_id"]
                break

    messages: List[Dict[str, Any]] = []

    # Кеш для избежания повторных запросов одного и того же файла
    resolved_file_cache: Dict[str, str] = {}

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
        images: List[str] = []

        for att in meta.get("attachments", []):
            name = att.get("name") or "Вложенный файл"
            sz_bytes = att.get("size") or 0
            sz_kb = sz_bytes // 1024
            w = att.get("width")
            h = att.get("height")
            dim = f"{w}x{h}" if w and h else ""
            att_id = att.get("id", "")
            mime = att.get("mime_type", "")
            is_img = is_image_file(name, mime)

            # Пытаемся получить живую ссылку на файл пользователя через OpenAI API
            att_url = None
            err_code = None
            if att_id and shared_id and session:
                if att_id not in resolved_file_cache:
                    resolved_file_cache[att_id] = resolve_shared_file_download_url(att_id, shared_id, session)
                att_url, err_code = resolved_file_cache[att_id]

            attachments.append({
                "name": name,
                "size_kb": sz_kb,
                "dimensions": dim,
                "mime_type": mime,
                "id": att_id,
                "url": att_url,
                "is_image": is_img,
                "icon": get_file_icon(name, mime),
                "error": err_code,
            })

            # В галерею картинок и PDF добавляем ТОЛЬКО настоящие изображения (не PDF, не Excel и т.д.)
            if is_img and att_url and att_url not in images:
                images.append(att_url)

        # 2. Извлекаем текст и ссылки на изображения
        parts = content.get("parts", [])
        text_parts: List[str] = []

        for p in parts:
            if isinstance(p, str):
                text_parts.append(p)
                # Ищем картинки в Markdown ![alt](url)
                for img_match in re.finditer(r"!\[(.*?)\]\((https?://[^\s\)]+)\)", p):
                    img_url = img_match.group(2)
                    if img_url not in images:
                        images.append(img_url)
            elif isinstance(p, dict):
                # Внутренние структуры ChatGPT/DALL-E или картинки
                content_type = p.get("content_type", "")
                if content_type == "image_asset_pointer":
                    ap = p.get("asset_pointer", "")
                    fid_m = re.search(r"file_[a-zA-Z0-9]+", ap)
                    if fid_m and shared_id and session:
                        fid = fid_m.group(0)
                        if fid not in resolved_file_cache:
                            resolved_file_cache[fid] = resolve_shared_file_download_url(fid, shared_id, session)
                        resolved_img, _ = resolved_file_cache[fid]
                        if resolved_img and resolved_img not in images:
                            images.append(resolved_img)
                elif "image_url" in p and p["image_url"] not in images:
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
            icon = att.get("icon") or "📎"
            dim_str = f", {att['dimensions']}" if att.get("dimensions") else ""
            if att.get("url"):
                lines.append(f"{icon} [Прикрепленный файл: {att['name']} ({att.get('size_kb', 0)} КБ{dim_str}) -> {att['url']}]")
            elif att.get("error") == "safety_check_failed":
                lines.append(f"{icon} [Прикрепленный файл: {att['name']} ({att.get('size_kb', 0)} КБ{dim_str}) — заблокировано фильтром безопасности OpenAI]")
            else:
                lines.append(f"{icon} [Прикрепленный файл: {att['name']} ({att.get('size_kb', 0)} КБ{dim_str})]")

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
        "      display: flex;",
        "      align-items: center;",
        "      gap: 12px;",
        "      padding: 10px 14px;",
        "      background: #f8fafc;",
        "      border: 1px solid #cbd5e1;",
        "      border-radius: 8px;",
        "      font-size: 13px;",
        "      margin-bottom: 12px;",
        "      color: #334155;",
        "    }",
        "    .att-icon { font-size: 20px; line-height: 1; flex-shrink: 0; }",
        "    .att-info { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }",
        "    .att-name { font-weight: 600; color: #1e293b; text-decoration: none; word-break: break-all; }",
        "    .att-name:hover { text-decoration: underline; color: #2563eb; }",
        "    .att-meta { font-size: 11px; color: #64748b; }",
        "    .att-btn {",
        "      display: inline-flex;",
        "      align-items: center;",
        "      gap: 4px;",
        "      padding: 6px 12px;",
        "      background: #3b82f6;",
        "      color: #ffffff !important;",
        "      border-radius: 6px;",
        "      text-decoration: none !important;",
        "      font-size: 12px;",
        "      font-weight: 600;",
        "      white-space: nowrap;",
        "      flex-shrink: 0;",
        "      transition: background 0.15s;",
        "    }",
        "    .att-btn:hover { background: #2563eb; }",
        "    .att-warning { background: #fffbeb; border-color: #fde68a; }",
        "    .att-warn-text { font-size: 11px; color: #b45309; font-weight: 500; margin-top: 2px; }",
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
        "      .att-btn { display: none; }",
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
            icon = att.get("icon") or "📎"
            dim_str = f" • {att['dimensions']}" if att.get("dimensions") else ""
            size_str = f"{att.get('size_kb', 0)} КБ{dim_str}"
            name_esc = att["name"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            is_img = att.get("is_image", False)
            btn_text = "Открыть фото" if is_img else "Скачать файл"

            if att.get("url"):
                safe_att_url = att["url"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "%27")
                html_parts.append(
                    f"      <div class='attachment-box'>"
                    f"        <span class='att-icon'>{icon}</span>"
                    f"        <div class='att-info'>"
                    f"          <a href='{safe_att_url}' target='_blank' rel='noopener' class='att-name'>{name_esc}</a>"
                    f"          <span class='att-meta'>{size_str}</span>"
                    f"        </div>"
                    f"        <a href='{safe_att_url}' target='_blank' rel='noopener' class='att-btn'>⬇️ {btn_text}</a>"
                    f"      </div>"
                )
            elif att.get("error") == "safety_check_failed":
                html_parts.append(
                    f"      <div class='attachment-box att-warning'>"
                    f"        <span class='att-icon'>{icon}</span>"
                    f"        <div class='att-info'>"
                    f"          <span class='att-name'>{name_esc}</span>"
                    f"          <span class='att-meta'>{size_str}</span>"
                    f"          <div class='att-warn-text'>⚠️ Заблокировано фильтром безопасности OpenAI (safety check)</div>"
                    f"        </div>"
                    f"      </div>"
                )
            else:
                html_parts.append(
                    f"      <div class='attachment-box'>"
                    f"        <span class='att-icon'>{icon}</span>"
                    f"        <div class='att-info'>"
                    f"          <span class='att-name'>{name_esc}</span>"
                    f"          <span class='att-meta'>{size_str}</span>"
                    f"        </div>"
                    f"      </div>"
                )

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
    session = create_http_session()
    html = fetch_chat_html(clean_url, session=session)
    conv_data = extract_conversation_from_html(html)
    parsed = parse_conversation_data(conv_data, shared_id=share_id, session=session)
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
