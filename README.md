# Nehoray — Personal Telegram AI Bot

[![Telegram](https://img.shields.io/badge/Telegram-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)](https://core.telegram.org/bots)
[![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Anthropic](https://img.shields.io/badge/Anthropic_Claude-191919?style=for-the-badge&logo=anthropic&logoColor=white)](https://www.anthropic.com/)
[![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=for-the-badge&logo=openai&logoColor=white)](https://openai.com/)
[![Google Gemini](https://img.shields.io/badge/Google_Gemini-8E75B2?style=for-the-badge&logo=googlegemini&logoColor=white)](https://ai.google.dev/)
[![Gmail](https://img.shields.io/badge/Gmail-EA4335?style=for-the-badge&logo=gmail&logoColor=white)](https://developers.google.com/gmail/api)
[![Google Calendar](https://img.shields.io/badge/Google_Calendar-4285F4?style=for-the-badge&logo=googlecalendar&logoColor=white)](https://developers.google.com/calendar)
[![Google Cloud](https://img.shields.io/badge/Google_Cloud-4285F4?style=for-the-badge&logo=googlecloud&logoColor=white)](https://cloud.google.com/)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![Playwright](https://img.shields.io/badge/Playwright-2EAD33?style=for-the-badge&logo=playwright&logoColor=white)](https://playwright.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)

A self-hosted, personal AI assistant on Telegram, powered by Anthropic Claude. Built around a skills-based architecture (each capability is a markdown file), persistent memory, proactive scheduling, and a growing library of tools — Gmail, Calendar, web search, browser automation, image generation, voice replies, and more.

This bot is designed for **a single owner** — you. Authorization is locked to your Telegram chat ID.

---

## What you can do with it

Just message the bot in plain language — it figures out which tool to call. Some real examples:

### 📅 Daily life
- _"What's on my calendar today?"_
- _"Remind me to call mom tomorrow at 6pm"_
- _"Every Sunday at 9am, send me a list of this week's meetings"_
- _"Add milk and eggs to my shopping list"_
- _"What's the weather like in Tel Aviv this weekend?"_

### 📧 Email & comms
- _"Any important emails from this morning?"_
- _"Summarize the thread from Dana about the budget"_
- _"Draft a reply saying I'll get back to him on Monday"_

### 🌐 Research & information
- _"What's the latest on the Fed rate decision?"_
- _"Compare the iPhone 16 Pro and Pixel 9 Pro — battery, camera, price"_
- _"Read https://example.com/long-article and give me the key points"_
- _"Summarize this YouTube video: &lt;link&gt;"_

### 🎨 Creative
- _"Generate an image of a corgi astronaut on Mars"_
- _"Take this photo I sent and make it look like an oil painting"_
- _(send a voice message and get a voice reply back)_

### 🧠 Memory & personalization
- _"Remember that my wife's birthday is March 14"_
- _"What do you know about me?"_
- _"I prefer concise answers — don't write long replies unless I ask"_

### ⚙️ Utility
- _"Is github.com down?"_
- _"Run a speed test"_
- _"Was my email in any data breach?"_
- _"What's trending on GitHub for Rust this week?"_

### 📰 Proactive (no prompt needed)
- Wakes up each morning with a personalized news digest based on your interests
- Heartbeat checks (inbox, calendar, todos) on a schedule
- Pulse: occasional smart unsolicited messages (a heads-up, a question, a nudge)

---

## Features

### Core
- 💬 **Conversational** — natural chat with full history, memory, and personality (`skills/soul.md`)
- 🧠 **Active memory** — remembers facts about you and surfaces them when relevant
- 🌍 **Multi-language** — replies in any language via `BOT_LANGUAGE`; per-feature overrides (e.g. `NEWS_DIGEST_LANGUAGE`)
- 🔐 **Owner-only** — locked to your Telegram chat ID; ignores everyone else
- 💸 **Cost tracking** — per-message token usage and running cost via `/usage`

### AI providers
- 🤖 **Anthropic Claude** — default, with prompt caching
- 🟢 **OpenAI** — drop-in alternative via `AI_PROVIDER=openai`
- ✨ **Google Gemini** — image generation (`gemini-2.5-flash-image`) + voice replies (TTS)

### Skills & tools
- 🧩 **Skills system** — drop a markdown file in `skills/` to teach the bot a new capability
- 🛠️ **Add your own tools** — Anthropic-format schema + an async function (auto-converted to OpenAI format)
- 🌐 **Web search & research** — DuckDuckGo + multi-page deep research
- 🕸️ **Browser automation** — Playwright/Chromium for JS-heavy pages
- 📧 **Gmail** — read, search, send, draft
- 📅 **Calendar** — Google Calendar or iCloud (CalDAV)
- ⏰ **Reminders & schedules** — one-shot + recurring weekly, persisted in SQLite (survive restarts)
- ✅ **Todo lists** — named lists, add/complete/remove
- 🌤️ **Weather** — current + 7-day forecast for any city
- 🎨 **Image generation** — generate or edit images (uses your sent photo if `use_user_photo=true`)
- 🎙️ **Voice in / voice out** — transcribes voice messages, replies with TTS
- 🎬 **Video summarization** — YouTube and other video URLs
- 📄 **PDF reading** — extract and summarize PDF content
- 📈 **GitHub trends** — trending repos by language and timeframe
- 🔎 **Misc utilities** — breach lookup, is-it-down, speed test, and more

### Proactive
- ❤️ **Heartbeat** — standing orders (inbox check, calendar check, todo review)
- 📡 **Pulse** — smart unsolicited outreach
- 📰 **Daily news digest** — morning briefing tailored to your interests

### Ops
- 💾 **SQLite storage** — conversations, memories, profile, usage, scheduled jobs
- 🐧 **VM-ready** — included `deploy/` scripts for GCP + a generic systemd recipe
- 🧪 **Test suite** — `pytest` covers tools, scheduler, memory, agent behavior

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

## Contributing

Pull requests welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, the tool/skill pattern, and coding conventions.

---

## License

MIT — see [LICENSE](LICENSE).
