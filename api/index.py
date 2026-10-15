import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# Добавляем родительскую директорию в sys.path для импорта chat_exporter
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chat_exporter import (
    extract_conversation_from_html,
    fetch_chat_html,
    format_chat_to_html,
    format_chat_to_text,
    normalize_chat_url,
    parse_conversation_data,
    sanitize_filename,
)


class handler(BaseHTTPRequestHandler):
    """Serverless обработчик для Vercel."""

    def log_message(self, format, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(
            json.dumps({"status": "ok", "service": "ChatGPT Chat Exporter API v2"}).encode("utf-8")
        )

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length).decode("utf-8")

        try:
            payload = json.loads(raw_body)
            url = payload.get("url", "").strip()
            include_header = payload.get("include_header", True)
            include_timestamps = payload.get("include_timestamps", True)

            if not url:
                raise ValueError("Пожалуйста, укажите ссылку на чат ChatGPT.")

            clean_url, share_id = normalize_chat_url(url)
            html = fetch_chat_html(clean_url)
            conv_data = extract_conversation_from_html(html)
            parsed = parse_conversation_data(conv_data)

            txt_content = format_chat_to_text(
                parsed,
                source_url=clean_url,
                include_header=include_header,
                include_timestamps=include_timestamps,
            )

            html_content = format_chat_to_html(
                parsed,
                source_url=clean_url,
            )

            title = parsed.get("title") or f"chat_{share_id}"
            clean_title = sanitize_filename(title)
            filename_txt = f"{clean_title}.txt"
            filename_html = f"{clean_title}.html"
            filename_pdf = f"{clean_title}.pdf"

            response_data = {
                "success": True,
                "title": parsed.get("title"),
                "model_name": parsed.get("model_name"),
                "messages": parsed.get("messages", []),
                "filename": filename_txt,
                "filename_html": filename_html,
                "filename_pdf": filename_pdf,
                "txt_content": txt_content,
                "html_content": html_content,
            }

            self._send_json(200, response_data)

        except Exception as e:
            self._send_json(400, {"success": False, "error": str(e)})

    def _send_json(self, status_code: int, data: dict):
        response_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)
