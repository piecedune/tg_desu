# Desu Manga Telegram Bot

A Telegram bot that searches Desu manga catalog, shows manga details, and lets users manage favorites.
The bot is built with **aiogram**.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a `.env` file (you can copy `.env.example`):

```bash
cp .env.example .env
```

Update `.env` with your Telegram token and (optional) Desu base URL:

```
TELEGRAM_TOKEN=your-telegram-token
DESU_BASE_URL=https://desu.me
```

## Run

```bash
python src/bot.py
```
