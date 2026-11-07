#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具助手 · 通用代理（Python 3.9+，只用标准库）

与 Cloudflare Worker 行为一致：POST /chat，接收 {messages:[...]}，
用服务端环境变量里的 Key 调用 OpenAI 兼容接口，返回 {answer}。

用法：
    set LLM_API_KEY=sk-xxxx                     # Windows
    set ALLOWED_ORIGINS=https://tool.acheng9616.com
    python rag/proxy/server.py

    # 部署到公网服务器时：
    set HOST=0.0.0.0
    set PORT=8787
    python rag/proxy/server.py

可选环境变量：
    LLM_BASE_URL   默认 https://api.deepseek.com/v1
    LLM_MODEL      默认 deepseek-chat
    MAX_TOKENS     默认 700
    DAILY_LIMIT    每 IP 每日次数，默认 30
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API_KEY = os.environ.get("LLM_API_KEY", "").strip()
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
ALLOWED = [
    s.strip()
    for s in os.environ.get(
        "ALLOWED_ORIGINS",
        "https://tool.acheng9616.com,http://127.0.0.1:8000,http://localhost:8000",
    ).split(",")
    if s.strip()
]
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "700"))
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "30"))
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8787"))

_quota = {}
_quota_lock = threading.Lock()


def clean_messages(value):
    if not isinstance(value, list):
        return None
    out = []
    for item in value[:12]:
        if not isinstance(item, dict) or not isinstance(item.get("content"), str):
            continue
        role = item.get("role")
        role = role if role in ("system", "assistant", "user") else "user"
        content = item["content"][:8000]
        if not content.strip():
            continue
        out.append({"role": role, "content": content})
    if not out:
        return None
    if sum(len(m["content"]) for m in out) > 24000:
        return None
    if not any(m["role"] == "system" for m in out):
        out.insert(
            0,
            {
                "role": "system",
                "content": "你是「项目工具盒」的站内助手，用简体中文简洁回答访客关于本站工具的问题；不确定时请让访客联系 @AChengLinus。",
            },
        )
    return out


def take_quota(ip):
    day = time.strftime("%Y-%m-%d", time.gmtime())
    with _quota_lock:
        stored_day, used = _quota.get(ip, (day, 0))
        if stored_day != day:
            used = 0
        if used >= DAILY_LIMIT:
            return False, 0
        _quota[ip] = (day, used + 1)
        return True, DAILY_LIMIT - used - 1


class Handler(BaseHTTPRequestHandler):
    server_version = "ToolRagProxy/1.0"

    def log_message(self, fmt, *args):
        print("[%s] %s" % (time.strftime("%H:%M:%S"), fmt % args))

    def _send(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        origin = self.headers.get("Origin", "")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        origin = self.headers.get("Origin", "")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/health":
            self._send(200, {"ok": True, "model": MODEL})
        else:
            self._send(404, {"error": "not_found"})

    def do_POST(self):
        if self.path.split("?")[0] != "/chat":
            self._send(404, {"error": "not_found"})
            return

        origin = self.headers.get("Origin", "")
        if origin and origin not in ALLOWED:
            self._send(403, {"error": "origin_not_allowed"})
            return

        if not API_KEY:
            self._send(500, {"error": "server_not_configured"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 64 * 1024:
            self._send(400, {"error": "invalid_body"})
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send(400, {"error": "invalid_json"})
            return

        messages = clean_messages(payload.get("messages") if isinstance(payload, dict) else None)
        if not messages:
            self._send(400, {"error": "invalid_messages"})
            return

        ip = self.client_address[0]
        allowed, remaining = take_quota(ip)
        if not allowed:
            self._send(429, {"error": "quota_exceeded"})
            return

        body = json.dumps(
            {
                "model": MODEL,
                "messages": messages,
                "max_tokens": min(MAX_TOKENS, 1200),
                "temperature": 0.2,
                "stream": False,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            BASE_URL + "/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + API_KEY,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            print("upstream HTTP %s: %s" % (exc.code, exc.read()[:200]))
            self._send(429 if exc.code == 429 else 502, {"error": "upstream_error"})
            return
        except Exception as exc:  # noqa: BLE001
            print("upstream failed: %s" % exc)
            self._send(502, {"error": "upstream_unreachable"})
            return

        try:
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            answer = ""

        if not answer or not str(answer).strip():
            self._send(502, {"error": "empty_answer"})
            return

        self._send(200, {"answer": str(answer).strip(), "remaining": remaining})


def main():
    if not API_KEY:
        print("警告：未设置 LLM_API_KEY，/chat 会返回 server_not_configured")
    print("工具助手代理已启动：http://%s:%d/chat" % (HOST, PORT))
    print("允许的站点：%s" % ", ".join(ALLOWED))
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
