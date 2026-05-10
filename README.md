# Nehoray — Personal Telegram AI Bot

A self-hosted, personal AI assistant on Telegram, powered by Anthropic Claude. Built around a skills-based architecture (each capability is a markdown file), persistent memory, proactive scheduling, and a growing library of tools — Gmail, Calendar, web search, browser automation, image generation, voice replies, and more.

This bot is designed for **a single owner** — you. Authorization is locked to your Telegram chat ID.

---

## Features

- **Conversational** — natural chat with full history, memory, and personality (skills/soul.md)
- **Multi-provider** — Anthropic Claude (default), OpenAI, or Google Gemini via `AI_PROVIDER` env var
- **Skills system** — drop a markdown file in `skills/` to teach the bot a new capability
- **Tools** — Gmail, Google Calendar (or iCloud via CalDAV), web search, web research, browser automation (Playwright), weather, todo lists, scheduled reminders, GitHub trends, image generation (Gemini), voice replies (TTS), YouTube/video summarization, breach lookup, speed test, PDF reading, and more
- **Active memory** — remembers facts about you and surfaces them when relevant
- **Proactive features** — heartbeat (standing orders like inbox/calendar checks), pulse (smart outreach), and a daily news digest tailored to your interests
- **Persistent scheduling** — one-shot reminders + recurring weekly schedules survive restarts (SQLite-backed)
- **Cost tracking** — per-message token usage and running cost via `/usage`

---

## Quick Start (Local)

### 1. Prerequisites

- Python 3.11+
- A Telegram account
- An Anthropic API key (or OpenAI / Google AI key)

### 2. Create your Telegram bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts:
   - Pick a **name** (e.g. "Nehoray")
   - Pick a **username** ending in `bot` (e.g. `my_nehoray_bot`)
3. BotFather replies with a **token** like `1234567890:ABCdef...` — save it
4. Optional but recommended — send BotFather these commands to polish your bot:
   - `/setdescription` → short blurb
   - `/setuserpic` → profile picture
   - `/setcommands` → paste:
     ```
     start - Welcome message
     new - Archive current chat and start fresh
     clear - Wipe all conversation history
     memories - List what I remember about you
     usage - Show token usage and cost
     whoami - Show your Telegram chat ID
     errors - Recent errors (debug)
     ```

### 3. Find your Telegram chat ID

After creating the bot, message it once (anything — `hi`), then:

```bash
curl "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates"
```

Look for `"chat":{"id":<NUMBER>` — that's your `OWNER_CHAT_ID`. Or run the bot and use `/whoami`.

### 4. Get an AI API key

- **Anthropic Claude (default):** [console.anthropic.com](https://console.anthropic.com/) → API Keys
- **OpenAI:** [platform.openai.com](https://platform.openai.com/api-keys)
- **Google AI (for image gen + voice):** [aistudio.google.com](https://aistudio.google.com/app/apikey)

### 5. Clone and install

```bash
git clone https://github.com/NirGeronn/AI-bot.git
cd AI-bot

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# For browser automation (web tool's browse_url uses Playwright for JS-heavy pages)
playwright install chromium
```

### 6. Configure

```bash
cp .env.example .env
```

Edit `.env`:

```env
TELEGRAM_TOKEN=1234567890:ABCdef...
ANTHROPIC_API_KEY=sk-ant-...
OWNER_CHAT_ID=123456789

# Optional personalization
BOT_OWNER_NAME=YourName
BOT_LANGUAGE=English
USER_TIMEZONE=America/New_York

# Optional: override news digest language independently
# NEWS_DIGEST_LANGUAGE=English
```

See [Configuration reference](#configuration-reference) below for all options.

### 7. Run

```bash
python bot.py
```

Open Telegram, message your bot, and say hi. If it doesn't respond, check the terminal logs.

---

## Optional integrations

These are off by default — enable each one if you want it.

### Gmail + Google Calendar (Google OAuth)

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create a project
2. **APIs & Services → Library** → enable **Gmail API** and **Google Calendar API**
3. **APIs & Services → Credentials** → Create Credentials → **OAuth client ID** → Desktop app
4. Download the JSON and save it as `client_secret.json` in the project root
5. Run the OAuth flow once:
   ```bash
   python auth_gmail.py google_token
   ```
   This opens a browser, asks you to log in to your Google account, and saves `google_token.json`.
6. Set in `.env`: `CALENDAR_PROVIDER=google` (or omit — it's the default)

### iCloud Calendar (alternative to Google)

1. Generate an [app-specific password](https://appleid.apple.com/account/manage) for iCloud
2. In `.env`:
   ```env
   CALENDAR_PROVIDER=icloud
   ICLOUD_EMAIL=you@icloud.com
   ICLOUD_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
   ```

### Image generation + voice replies (Google Gemini)

```env
GOOGLE_AI_API_KEY=AIza...
```

When the user sends a voice message, the bot transcribes (Whisper-equivalent) and replies with voice (Gemini TTS). Image gen uses `gemini-2.5-flash-image`.

---

## Deploy to a VM (production)

The included `deploy/` scripts target Google Cloud Platform but the pattern works on any Linux VM.

### Option A: GCP (with the included scripts)

```bash
# Edit deploy/create_instance.sh first — set PROJECT, ZONE, ACCOUNT to yours
./deploy/create_instance.sh ai-bot
./deploy/upload_token.sh ai-bot          # uploads google_token.json
./deploy/set_owner.sh ai-bot <CHAT_ID>   # sets OWNER_CHAT_ID on the VM
```

After the first deploy, push code updates with:

```bash
./deploy/deploy_update.sh ai-bot
```

### Option B: Any Linux VM

```bash
# On the VM
sudo apt update && sudo apt install -y python3 python3-venv git
git clone https://github.com/NirGeronn/AI-bot.git /opt/ai-bot
cd /opt/ai-bot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
playwright install-deps      # install OS-level deps for Chromium

# Create .env (see Configure step above)
nano .env

# Create a systemd unit
sudo tee /etc/systemd/system/ai-bot.service > /dev/null <<'EOF'
[Unit]
Description=AI Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/ai-bot
ExecStart=/opt/ai-bot/venv/bin/python /opt/ai-bot/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ai-bot
sudo systemctl status ai-bot
```

Logs: `sudo journalctl -u ai-bot -f`

---

## Configuration reference

All settings live in `.env`. Only the first three are required.

| Variable | Required | Default | Notes |
|---|---|---|---|
| `TELEGRAM_TOKEN` | yes | — | From @BotFather |
| `OWNER_CHAT_ID` | yes | — | Your Telegram chat ID — bot ignores everyone else |
| `ANTHROPIC_API_KEY` | yes\* | — | \*if `AI_PROVIDER=anthropic` (default) |
| `OPENAI_API_KEY` | yes\* | — | \*if `AI_PROVIDER=openai` |
| `AI_PROVIDER` | no | `anthropic` | `anthropic`, `openai`, or `gemini` |
| `MODEL` | no | `claude-haiku-4-5-20251001` | Override model |
| `MODEL_PRO` | no | same as `MODEL` | Heavier model for complex tasks |
| `BOT_OWNER_NAME` | no | `Nir` | How the bot addresses you |
| `BOT_LANGUAGE` | no | `English` | Language for replies |
| `NEWS_DIGEST_LANGUAGE` | no | `BOT_LANGUAGE` | Override language for the daily news digest only |
| `USER_TIMEZONE` | no | `Asia/Jerusalem` | IANA tz name (e.g. `America/New_York`) |
| `GOOGLE_AI_API_KEY` | no | — | Enables image gen + voice replies |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | no | — | For Gmail + Calendar |
| `CALENDAR_PROVIDER` | no | `google` | Or `icloud` |
| `ICLOUD_EMAIL` / `ICLOUD_APP_PASSWORD` | no | — | If using iCloud calendar |
| `PRICE_INPUT_PER_M` / `PRICE_OUTPUT_PER_M` | no | model defaults | $/M tokens for `/usage` cost calc |

---

## Architecture

```
bot.py              Telegram entry point — handlers, scheduler, lifecycle
agent.py            LLM agent loop — assembles prompt, calls model, runs tools
ai_client.py        Provider abstraction (Anthropic / OpenAI / Gemini)
config.py           Env-var loading + constants
memory.py           SQLite: conversations, memories, profile, usage
active_memory.py    Pre-reply memory search — surfaces relevant context
skills_loader.py    Loads skills/*.md into the system prompt
heartbeat.py        Standing orders (recurring background checks)
pulse.py            Proactive outreach (smart unsolicited messages)
news_digest.py      Daily AI/news briefing
profile_builder.py  Builds an owner profile from conversation history
mood.py / habits.py Lifestyle tracking
error_log.py        Centralized error log surfaced via /errors

skills/             Markdown skill files — system prompt is composed from these
tools/              Each tool: Anthropic-format schema + async execute fn
tests/              pytest suite
deploy/             VM provisioning + update scripts (GCP-flavored)
```

### Adding a new tool

1. Create `tools/your_tool.py`:
   ```python
   YOUR_TOOLS = [{
       "name": "your_action",
       "description": "What it does — be explicit, the model relies on this",
       "input_schema": {
           "type": "object",
           "properties": {"arg": {"type": "string"}},
           "required": ["arg"],
       },
   }]

   async def execute_your_tool(name, input_data, chat_id) -> str:
       return f"result for {input_data['arg']}"
   ```
2. Register it in `tools/__init__.py`
3. Create `skills/your_tool.md` describing when the bot should use it (the model reads this)

See `CONTRIBUTING.md` for more.

---

## Useful commands

In Telegram (authorized owner only):

| Command | Purpose |
|---|---|
| `/start` | Welcome |
| `/new` | Archive current conversation, start fresh |
| `/clear` | Wipe all conversation history |
| `/memories` | List facts the bot has remembered |
| `/usage` | Token usage + running cost |
| `/whoami` | Show your chat ID |
| `/errors` | Recent errors |

---

## Tests

```bash
source venv/bin/activate
pytest -q
```

---

## Troubleshooting

- **Bot doesn't reply** — confirm `OWNER_CHAT_ID` matches yours (`/whoami` after sending any message; check `getUpdates` if not running yet)
- **"not authorized"** — same as above; `OWNER_CHAT_ID` mismatch
- **Gmail/Calendar errors** — re-run `python auth_gmail.py google_token` to refresh OAuth tokens
- **Playwright errors** — run `playwright install chromium` and on Linux `playwright install-deps`
- **High costs** — switch to a cheaper model via `MODEL=` in `.env`; check `/usage` regularly

---

## License

MIT — see [LICENSE](LICENSE).
