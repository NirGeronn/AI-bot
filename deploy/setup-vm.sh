#!/bin/bash
# Run this ON the GCP VM after SSH-ing in
# It sets up everything needed to run the bot

set -e

echo "=== Setting up AI Bot on GCP VM ==="

# Install Python 3.11 and pip
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git

# Create app directory
sudo mkdir -p /opt/ai-bot
sudo chown $USER:$USER /opt/ai-bot

# Copy code (assumes you've already scp'd or cloned the files)
cd /opt/ai-bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "=== Creating .env file ==="
echo "Enter your Telegram bot token:"
read -r TELEGRAM_TOKEN
echo "Enter your OpenAI API key:"
read -r OPENAI_API_KEY
echo "Enter your Telegram chat ID (owner, use /whoami to find it):"
read -r OWNER_CHAT_ID

cat > /opt/ai-bot/.env << EOF
TELEGRAM_TOKEN=$TELEGRAM_TOKEN
OPENAI_API_KEY=$OPENAI_API_KEY
OWNER_CHAT_ID=$OWNER_CHAT_ID

# Personalization (optional - defaults shown)
# BOT_OWNER_NAME=YourName
# BOT_LANGUAGE=English
# USER_TIMEZONE=UTC
# MODEL=gpt-4o

# Google integrations (optional)
# GOOGLE_CLIENT_ID=
# GOOGLE_CLIENT_SECRET=
EOF

chmod 600 /opt/ai-bot/.env

# Create systemd service
sudo tee /etc/systemd/system/ai-bot.service > /dev/null << 'EOF'
[Unit]
Description=Telegram AI Bot Agent
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/opt/ai-bot
ExecStart=/opt/ai-bot/venv/bin/python bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Fix the $USER in service file
sudo sed -i "s/\$USER/$USER/g" /etc/systemd/system/ai-bot.service

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable ai-bot
sudo systemctl start ai-bot

echo ""
echo "=== Done! Bot is running ==="
echo "Check status:  sudo systemctl status ai-bot"
echo "View logs:     sudo journalctl -u ai-bot -f"
echo "Restart:       sudo systemctl restart ai-bot"
