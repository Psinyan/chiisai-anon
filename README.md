# Anonymous Telegram Bot (Simple)

This bot lets people send you anonymous messages in Telegram.

You can:
- receive text, images, and stickers
- reply to users anonymously
- silently ban users (`/ban`) so their messages stop reaching you
- receive notifications when users react to your replies

## 1) Create your bot in Telegram

1. Open Telegram and find `@BotFather`.
2. Run `/newbot`.
3. Choose a name and username.
4. Copy the bot token (looks like `123456:ABC...`).

## 2) Find your admin chat ID

1. In Telegram, send any message to `@userinfobot`.
2. Copy your numeric `Id` value.

## 3) Install Python

Install Python 3.10+ from [python.org](https://www.python.org/downloads/).

## 4) Project setup

In this project folder:

1. Copy `.env.example` to `.env`.
2. Edit `.env`:
   - `BOT_TOKEN` = your token from BotFather
   - `ADMIN_CHAT_ID` = your Telegram numeric ID
   - keep `DB_PATH=bot_data.db`

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

## 5) Run the bot

```powershell
python bot.py
```

If everything is correct, bot starts and waits for messages.

## 6) Run with Docker (optional, simple)

If you already have Docker Desktop installed, you can run the bot in a container.

1. Make sure `.env` is filled (`BOT_TOKEN`, `ADMIN_CHAT_ID`, `DB_PATH=bot_data.db`).
2. Run:

```powershell
docker compose up -d --build
```

Useful commands:

```powershell
docker compose logs -f
docker compose restart
docker compose down
```

The database file is saved on your host as `bot_data.db`, so data stays after container restarts.

After you change code, update/redeploy with one command:

```powershell
docker compose up -d --build
```

## How to use

- Users open your bot and send messages/media.
- You receive messages with anonymous IDs like `[A1B2C3D]`.
- To reply, **reply in Telegram** to that forwarded message with text/photo/sticker.
- Ban a user:
  - `/ban A1B2C3D`
- Unban a user:
  - `/unban A1B2C3D`
- View stats:
  - `/stats`
- Admin help:
  - `/help_admin`

## Silent ban behavior

When banned, user can still send messages to bot and sees no ban warning.
But you no longer receive those messages.

## Run automatically on server reboot (Windows Task Scheduler)

1. Open Task Scheduler.
2. Create Task.
3. Trigger: `At startup`.
4. Action: `Start a program`
   - Program/script: `python`
   - Add arguments: `bot.py`
   - Start in: your project folder path
5. Save task.

## Troubleshooting

- `BOT_TOKEN is missing`
  - `.env` is missing or field is empty.
- `ADMIN_CHAT_ID must be a number`
  - Use only digits (no `@username`).
- Bot does not answer
  - Make sure `python bot.py` is running.
  - Make sure you started chat with your bot and clicked Start.
- Reaction notifications missing
  - Telegram reactions depend on app/client support and message types.
