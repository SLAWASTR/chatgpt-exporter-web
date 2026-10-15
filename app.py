#!/usr/bin/env python3
"""
Автономный веб-сервер для ChatGPT Chat Exporter v2.
Поддерживает экспорт в PDF, HTML, TXT, галерею изображений и вложений.
Работает локально или на любом облачном хостинге.
"""

import json
import mimetypes
import os
import socket
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

from chat_exporter import (
    extract_conversation_from_html,
    fetch_chat_html,
    format_chat_to_html,
    format_chat_to_text,
    normalize_chat_url,
    parse_conversation_data,
    sanitize_filename,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")


class StandaloneAppHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        if len(args) > 1 and str(args[1]).startswith(("4", "5")):
            super().log_message(format, *args)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.lstrip("/")

        if not path or path == "index.html":
            filepath = os.path.join(PUBLIC_DIR, "index.html")
        else:
            filepath = os.path.join(PUBLIC_DIR, path)

        if not os.path.abspath(filepath).startswith(PUBLIC_DIR):
            self.send_error(403, "Forbidden")
            return

        if os.path.exists(filepath) and os.path.isfile(filepath):
            mime_type, _ = mimetypes.guess_type(filepath)
            mime_type = mime_type or "application/octet-stream"
            if mime_type.startswith("text/") or mime_type in (
                "application/javascript",
                "application/json",
            ):
                mime_type += "; charset=utf-8"

            with open(filepath, "rb") as f:
                content = f.read()

            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404, "File Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/api", "/api/", "/api/export", "/api/parse"):
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length).decode("utf-8")

            try:
                payload = json.loads(raw_body)
                url = payload.get("url", "").strip()
                include_header = payload.get("include_header", True)
                include_timestamps = payload.get("include_timestamps", True)

                if not url:
                    raise ValueError("Пожалуйста, вставьте ссылку на чат ChatGPT.")

                clean_url, share_id = normalize_chat_url(url)
                html = fetch_chat_html(clean_url)
                conv_data = extract_conversation_from_html(html)
                parsed_data = parse_conversation_data(conv_data)

                txt_content = format_chat_to_text(
                    parsed_data,
                    source_url=clean_url,
                    include_header=include_header,
                    include_timestamps=include_timestamps,
                )

                html_content = format_chat_to_html(
                    parsed_data,
                    source_url=clean_url,
                )

                title = parsed_data.get("title") or f"chat_{share_id}"
                clean_title = sanitize_filename(title)

                response_data = {
                    "success": True,
                    "title": parsed_data.get("title"),
                    "model_name": parsed_data.get("model_name"),
                    "messages": parsed_data.get("messages", []),
                    "filename": f"{clean_title}.txt",
                    "filename_html": f"{clean_title}.html",
                    "filename_pdf": f"{clean_title}.pdf",
                    "txt_content": txt_content,
                    "html_content": html_content,
                }
                self._send_json(200, response_data)

            except Exception as e:
                self._send_json(400, {"success": False, "error": str(e)})
        else:
            self.send_error(404, "Not Found")

    def _send_json(self, status_code: int, data: dict):
        response_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)


def find_free_port(start_port: int = 8080) -> int:
    port = start_port
    while port < 65535:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
        port += 1
    return start_port


def run_server(port: Optional[int] = None, auto_open: bool = False):
    env_port = os.environ.get("PORT")
    final_port = int(env_port) if env_port else (port or find_free_port(8080))

    server_address = ("0.0.0.0", final_port)
    httpd = HTTPServer(server_address, StandaloneAppHandler)
    url = f"http://localhost:{final_port}"

    print(f"\n=======================================================")
    print(f"🚀 Веб-сервер запущен на порту {final_port}")
    print(f"Локальный адрес: {url}")
    print(f"=======================================================\n")

    if auto_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановка сервера...")
        httpd.server_close()


if __name__ == "__main__":
    auto_browser = "--open" in sys.argv
    run_server(auto_open=auto_browser)
