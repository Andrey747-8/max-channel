#!/usr/bin/env python3
"""Автопостинг в канал MAX от имени бота.

Очередь: queue/ГГГГ-ММ-ДД_ЧЧММ.md (время московское). Когда время наступило,
пост публикуется, а имя файла записывается в published.txt (повторно не уйдёт). Первая строка поста может быть
'button: Текст кнопки' — тогда под постом будет кнопка-ссылка BUTTON_URL.

  python3 poster.py check        — проверить токен и найти канал
  python3 poster.py run          — опубликовать все посты, чьё время наступило
  python3 poster.py list         — показать очередь
Только стандартная библиотека Python 3.9+.
"""
import json, sys, re, urllib.request, urllib.error, urllib.parse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
MSK = ZoneInfo("Europe/Moscow")
NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})(?:_.*)?\.md$")


def load_env():
    env = {}
    p = ROOT / "config.env"
    if not p.exists():
        sys.exit("Нет config.env — скопируйте config.env.example и заполните")
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


ENV = load_env()
API = ENV.get("MAX_API", "https://platform-api.max.ru").rstrip("/")
TOKEN = ENV.get("MAX_TOKEN", "")


def api(method, path, params=None, body=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path}: HTTP {e.code} {e.read()[:300]!r}")


def log(msg):
    line = f"{datetime.now(MSK):%Y-%m-%d %H:%M} {msg}"
    print(line)
    with open(ROOT / "poster.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def channel_id():
    ch = ENV.get("CHANNEL_ID", "")
    if ch.lstrip("-").isdigit():
        return int(ch)
    sys.exit("В config.env не указан CHANNEL_ID — запустите: python3 poster.py check")


def due_time(name):
    m = NAME_RE.match(name)
    if not m:
        return None
    return datetime.strptime(f"{m[1]} {m[2]}{m[3]}", "%Y-%m-%d %H%M").replace(tzinfo=MSK)


def build(text):
    body = {"text": text, "format": "markdown", "attachments": []}
    lines = text.splitlines()
    if lines and lines[0].lower().startswith("button:"):
        label = lines[0].split(":", 1)[1].strip()
        body["text"] = "\n".join(lines[1:]).strip()
        url = ENV.get("BUTTON_URL", "")
        if not url:
            sys.exit("В посте есть кнопка, но в config.env не задан BUTTON_URL")
        body["attachments"].append({"type": "inline_keyboard", "payload": {
            "buttons": [[{"type": "link", "text": label, "url": url}]]}})
    if len(body["text"]) > 4000:
        raise RuntimeError("Пост длиннее 4000 символов")
    return body


def cmd_check():
    me = api("GET", "/me")
    print(f"Бот: {me.get('name')} (@{me.get('username')}), id {me.get('user_id')}")
    link = ENV.get("CHANNEL_LINK", "").rstrip("/").split("/")[-1].lstrip("@")
    if link:
        try:
            ch = api("GET", f"/chats/{link}")
            print(f"Канал: {ch.get('title')} — CHANNEL_ID={ch.get('chat_id')}")
            print("Впишите это число в config.env, строка CHANNEL_ID=")
        except RuntimeError as e:
            print("Не нашёл канал по ссылке:", e)
    try:
        chats = api("GET", "/chats", {"count": 50}).get("chats", [])
        for c in chats:
            print(f"  в чате: {c.get('title')} ({c.get('type')}) CHANNEL_ID={c.get('chat_id')}")
    except RuntimeError as e:
        print("Список чатов недоступен:", e)


def cmd_list():
    for f in sorted((ROOT / "queue").glob("*.md")):
        t = due_time(f.name)
        mark = "✓ вышел " if f.name in published() else "  ждёт   "
        print(f"{mark}{t:%d.%m %H:%M} {f.name}" if t else f"?? неверное имя {f.name}")


PUB = ROOT / "published.txt"


def published():
    return set(PUB.read_text(encoding="utf-8").split()) if PUB.exists() else set()


def cmd_run():
    cid = channel_id()
    done = published()
    now = datetime.now(MSK)
    for f in sorted((ROOT / "queue").glob("*.md")):
        t = due_time(f.name)
        if t is None:
            log(f"ПРОПУСК неверное имя файла: {f.name}")
            continue
        if f.name in done or t > now:
            continue
        if (now - t).total_seconds() > 6 * 3600:
            log(f"ПРОПУСК опоздал больше чем на 6 часов, не публикую: {f.name}")
            continue
        try:
            res = api("POST", "/messages", {"chat_id": cid}, build(f.read_text(encoding="utf-8")))
            mid = (res.get("message") or {}).get("body", {}).get("mid", "?")
            with open(PUB, "a", encoding="utf-8") as fh:
                fh.write(f.name + "\n")
            log(f"ОПУБЛИКОВАН {f.name} mid={mid}")
        except Exception as e:
            log(f"ОШИБКА {f.name}: {e}")


if __name__ == "__main__":
    {"check": cmd_check, "run": cmd_run, "list": cmd_list}.get(
        sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
