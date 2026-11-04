import asyncio
import html
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("uniPushBot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_SECRET = os.getenv("API_SECRET", "").strip()
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
SUBSCRIBERS_FILE = DATA_DIR / "subscribers.json"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
POLL_TIMEOUT = 30

if not BOT_TOKEN or not API_SECRET:
    raise SystemExit("BOT_TOKEN and API_SECRET are required")


class SubscriberStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self._ids: set[int] = set()

    async def load(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            await self._save_unlocked()
            return
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return
        data = json.loads(raw)
        self._ids = {int(x) for x in data}

    async def _save_unlocked(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(sorted(self._ids), indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    async def add(self, chat_id: int) -> None:
        async with self._lock:
            self._ids.add(chat_id)
            await self._save_unlocked()

    async def remove(self, chat_id: int) -> None:
        async with self._lock:
            self._ids.discard(chat_id)
            await self._save_unlocked()

    async def all(self) -> list[int]:
        async with self._lock:
            return list(self._ids)


store = SubscriberStore(SUBSCRIBERS_FILE)
http: httpx.AsyncClient | None = None
poll_task: asyncio.Task | None = None


async def tg(method: str, payload: dict[str, Any] | None = None, timeout: float = 15.0) -> Any:
    assert http is not None
    r = await http.post(f"{TELEGRAM_API}/{method}", json=payload or {}, timeout=timeout)
    r.raise_for_status()
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(f"telegram {method}: {body.get('description', body)}")
    return body.get("result")


async def send_message(chat_id: int, text: str) -> None:
    await tg("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})


def command_name(text: str) -> str:
    first = (text or "").strip().split()[0] if text else ""
    return first.split("@", 1)[0]


async def handle_update(update: dict[str, Any]) -> None:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    cmd = command_name(message.get("text", ""))
    if cmd == "/start":
        await store.add(int(chat_id))
        await send_message(chat_id, "Подписка активна. Буду слать пуши сюда.")
    elif cmd == "/stop":
        await store.remove(int(chat_id))
        await send_message(chat_id, "Отписался.")
    elif cmd == "/help":
        await send_message(chat_id, "Команды:\n/start — подписаться\n/stop — отписаться")


async def poll_updates() -> None:
    offset = 0
    while True:
        try:
            updates = await tg(
                "getUpdates",
                {"offset": offset, "timeout": POLL_TIMEOUT},
                timeout=POLL_TIMEOUT + 10,
            )
            for update in updates or []:
                update_id = int(update["update_id"])
                if update_id >= offset:
                    offset = update_id + 1
                try:
                    await handle_update(update)
                except Exception:
                    log.exception("update failed")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("getUpdates failed")
            await asyncio.sleep(3)


def build_message(payload: dict[str, Any]) -> str:
    text = str(payload.get("text") or "").strip()
    if text:
        return text
    title = str(payload.get("title") or "").strip()
    body = str(payload.get("body") or "").strip()
    if title and body:
        return f"<b>{html.escape(title)}</b>\n{html.escape(body)}"
    if title:
        return html.escape(title)
    if body:
        return html.escape(body)
    return ""


def check_auth(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthorized")
    token = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(token, API_SECRET):
        raise HTTPException(status_code=401, detail="unauthorized")


@asynccontextmanager
async def lifespan(_: FastAPI):
    global http, poll_task
    await store.load()
    http = httpx.AsyncClient()
    poll_task = asyncio.create_task(poll_updates())
    log.info("bot started, listening for pushes and telegram updates")
    try:
        yield
    finally:
        if poll_task:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass
        if http:
            await http.aclose()


app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.post("/v1/create")
async def create(
    request: Request,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    check_auth(authorization)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid json")

    msg = build_message(payload)
    if not msg:
        raise HTTPException(status_code=400, detail='need "text" or "title"/"body"')

    ids = await store.all()
    sent = 0
    failed = 0
    for chat_id in ids:
        try:
            await send_message(chat_id, msg)
            sent += 1
        except Exception:
            log.exception("send to %s failed", chat_id)
            failed += 1

    return JSONResponse({"ok": True, "sent": sent, "failed": failed, "targets": len(ids)})
