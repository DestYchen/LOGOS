# Feedback Telegram Bot Helper

This helper sends locally stored feedback tickets to a Telegram group.

## Environment
- `SUPPLYHUB_TELEGRAM_BOT_TOKEN`
- `SUPPLYHUB_TELEGRAM_CHAT_ID`
- Optional: `SUPPLYHUB_BASE_DIR` (defaults to `/srv/supplyhub`)
- Optional: `SUPPLYHUB_FEEDBACK_ROOT` / `FEEDBACK_ROOT` to override feedback directory

## Setup
```
.\deploy.ps1
```

## Commands
Send all pending tickets:
```
.\.venv\Scripts\python.exe .\main.py drain
```

Watch for new tickets continuously:
```
.\.venv\Scripts\python.exe .\main.py watch
```

Send a specific ticket:
```
.\.venv\Scripts\python.exe .\main.py send <path-to-ticket-dir>
```
