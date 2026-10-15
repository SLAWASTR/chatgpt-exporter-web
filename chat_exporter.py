"""
Модуль для выгрузки и парсинга публичных чатов ChatGPT (по ссылке 'Share')
в текстовый формат (.txt).

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

    Поддерживает:
      - https://chatgpt.com/share/6acfb93c-4640-83eb-9934-045ecac95d7d?ogimg=plain
      - https://chatgpt.com/share/6acfb93c-4640-83eb-9934-045ecac95d7d/
      - https://chat.openai.com/share/6acfb93c-4640-83eb-9934-045ecac95d7d
      - 6acfb93c-4640-83eb-9934-045ecac95d7d
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
    Использует SSL-контекст с защитой от сбоев сертификатов на macOS.
    """
    # Создаем контекст, совместимый с macOS Python
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
    Преобразует плоский массив с индексами в иерархический Python dict/list/value.
    """
    memo: Dict[int, Any] = {}
    visited = set()

    def resolve(idx: Any) -> Any:
        if idx == -5:
            # -5 в turbo-stream означает undefined
            return None
        if not isinstance(idx, int) or isinstance(idx, bool):
            return idx
        if idx < 0 or idx >= len(flat_data):
            return None
        if idx in memo:
            return memo[idx]
        if idx in visited:
            return None  # защита от циклических ссылок

        visited.add(idx)
        val = flat_data[idx]

        if isinstance(val, (str, float, bool)) or val is None or isinstance(val, int):
            memo[idx] = val
            return val
        elif isinstance(val, list):
            # Проверка специальных тегов TurboStream (например, ['P', 644] - Promise)
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
    Ищет словарь, содержащий 'linear_conversation' или 'mapping' с 'title'.
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
    Поддерживает:
      1) streamController.enqueue(...) (React Router / Remix TurboStream)
      2) window.__remixContext / window.__reactRouterContext
      3) <script id="__NEXT_DATA__">
      4) Прямой поиск JSON-объектов с serverResponse
    """
    # 1. Поиск вызовов streamController.enqueue(...)
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

    # 2. Поиск __reactRouterContext / __remixContext
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

    # 3. Поиск __NEXT_DATA__
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

    # 4. Fallback: поиск фрагментов JSON с conversation_id / mapping
    json_blocks = re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL)
    for block in json_blocks:
        try:
            parsed = json.loads(block)
            conv = find_conversation_in_tree(parsed)
            if conv:
                return conv
        except Exception:
            pass

    raise RuntimeError(
        "Не удалось извлечь данные диалога из страницы. "
        "Возможно, структура страницы ChatGPT обновилась или ссылка недоступна."
    )


def extract_message_text(content: Optional[Dict[str, Any]]) -> str:
    """
    Извлекает текст из структуры content сообщения.
    Корректно обрабатывает текстовые блоки, изображения и служебные структуры.
    """
    if not content:
        return ""

    parts = content.get("parts", [])
    text_chunks: List[str] = []

    for p in parts:
        if isinstance(p, str):
            text_chunks.append(p)
        elif isinstance(p, dict):
            if "text" in p and isinstance(p["text"], str):
                text_chunks.append(p["text"])
            elif p.get("content_type") == "image_asset_pointer":
                text_chunks.append("[Изображение]")
            elif p.get("content_type") == "audio_asset_pointer":
                text_chunks.append("[Аудиозапись]")
            elif "asset_pointer" in p:
                text_chunks.append("[Вложение]")
            else:
                # Если неизвестная структура со словарем
                val_text = p.get("val") or p.get("value")
                if val_text and isinstance(val_text, str):
                    text_chunks.append(val_text)
        elif isinstance(p, list):
            text_chunks.extend(str(item) for item in p)

    return "\n".join(text_chunks)


def parse_conversation_data(conv_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Приводит сырые данные диалога к структурированному виду:
      - title: название чата
      - create_time: время создания
      - update_time: время обновления
      - model_name: название модели (GPT-4, GPT-6 и т.д.)
      - messages: список сообщений [{'role', 'role_label', 'text', 'timestamp', 'datetime_str'}]
    """
    title = conv_data.get("title") or "Чат ChatGPT"
    create_time = conv_data.get("create_time")
    update_time = conv_data.get("update_time")

    model_info = conv_data.get("model") or {}
    model_name = model_info.get("title") or model_info.get("slug") or conv_data.get("default_model_slug") or ""

    # Извлечение узлов диалога
    raw_nodes: List[Dict[str, Any]] = []

    if conv_data.get("linear_conversation"):
        raw_nodes = conv_data["linear_conversation"]
    elif conv_data.get("mapping"):
        mapping = conv_data["mapping"]
        # Восстанавливаем цепочку сообщений от current_node к корню
        curr = conv_data.get("current_node")
        if not curr or curr not in mapping:
            # Ищем лист без детей
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
        content = msg.get("content") or {}
        text = extract_message_text(content).strip()

        # Фильтрация пустых системных сообщений и заглушек
        if not text:
            continue
        if role == "user" and text == "Original custom instructions no longer available":
            continue
        if role == "system" and not text:
            continue

        role_label = {
            "user": "Пользователь",
            "assistant": "ChatGPT",
            "system": "Система",
            "tool": "Инструмент",
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
            "text": text,
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
    Форматирует распарсенный чат в красивый текстовый документ (.txt).
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

        lines.append(m["text"])

        # Разделитель между сообщениями (кроме последнего)
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


def sanitize_filename(name: str) -> str:
    """
    Очищает строку для безопасного использования в качестве имени файла.
    """
    clean = re.sub(r'[\\/*?:"<>|]', "", name)
    clean = re.sub(r"\s+", " ", clean).strip()
    clean = clean.strip(" .")
    if not clean:
        clean = "chatgpt_export"
    # Ограничиваем длину имени файла
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

    Возвращает:
      (абсолютный_путь_к_сохраненному_файлу, словарь_с_данными_чата)
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

    # Определяем имя и путь к файлу
    if output_path:
        final_path = os.path.abspath(output_path)
    else:
        title = parsed.get("title") or f"chat_{share_id}"
        filename = f"{sanitize_filename(title)}.txt"
        target_dir = os.path.abspath(output_dir or os.getcwd())
        final_path = os.path.join(target_dir, filename)

    # Создаем директорию, если не существует
    os.makedirs(os.path.dirname(final_path), exist_ok=True)

    with open(final_path, "w", encoding="utf-8") as f:
        f.write(txt_content)

    return final_path, parsed
