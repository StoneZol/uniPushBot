# uniPushBot

Dumb Telegram bot: accepts an HTTP push and broadcasts it to all subscribers (`/start`).

Privacy / who can talk to the bot is configured in **BotFather** (Telegram), not in this app. Restrict the bot there if you want it private.

## Env

```env
BOT_TOKEN=123456:token
API_SECRET=long_random_secret
```

Copy `.env.example` → `.env`.

## Run

```bash
docker compose up -d --build
sudo ufw allow 6666/tcp   # if ufw is enabled
```

Port: **6666**. Subscribers are stored in `./data/subscribers.json`.

In Telegram: `/start` to subscribe, `/stop` to unsubscribe.

## Push (curl / batch)

```bat
curl -s -X POST "http://VPS_IP:6666/v1/create" ^
  -H "Authorization: Bearer YOUR_SECRET" ^
  -H "Content-Type: application/json" ^
  -d "{\"title\":\"Login\",\"body\":\"PC: %COMPUTERNAME%\nUser: %USERNAME%\nTime: %DATE% %TIME%\"}"
```

Or `{"text":"hello"}`.

Startup example: `examples/boot.bat`.

HTTPS is optional — put nginx/Caddy (or similar) in front if you want TLS; the app itself stays HTTP on 6666.

## API

| Method | Path | Auth |
|--------|------|------|
| `POST` | `/v1/create` | `Authorization: Bearer <API_SECRET>` |
| `GET`  | `/healthz`   | — |
