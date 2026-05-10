#!/bin/bash
# Creates a new bot instance on a fresh GCP VM.
# Run from the project root directory on your Mac.
#
# Usage:
#   ./deploy/create_instance.sh <instance_name> <telegram_token> <owner_name> <language> <timezone> [calendar_provider]
#
# Example:
#   ./deploy/create_instance.sh nehoray 7123456:AAHxxx Nehoray English Europe/Brussels icloud
#
# After creation:
#   1. User messages the bot and sends /whoami to get their chat_id
#   2. Run: ./deploy/set_owner.sh <instance_name> <chat_id>
#   3. For Gmail: python3 auth_gmail.py <instance_name>_token
#      Then: ./deploy/upload_token.sh <instance_name>
#   4. For iCloud calendar: ./deploy/set_icloud.sh <instance_name> <email> <app_password>

set -e

PROJECT="nir-ai-bot"
ZONE="us-central1-a"
ACCOUNT="geronir11@gmail.com"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

INSTANCE_NAME="$1"
TELEGRAM_TOKEN="$2"
OWNER_NAME="$3"
LANGUAGE="${4:-English}"
TIMEZONE="${5:-UTC}"
CALENDAR_PROVIDER="${6:-google}"

if [ -z "$INSTANCE_NAME" ] || [ -z "$TELEGRAM_TOKEN" ] || [ -z "$OWNER_NAME" ]; then
    echo "Usage: $0 <instance_name> <telegram_token> <owner_name> [language] [timezone] [calendar_provider]"
    echo ""
    echo "  instance_name     Short name (e.g. 'nehoray', 'david'). Used for VM name: ai-bot-<name>"
    echo "  telegram_token    Bot token from @BotFather"
    echo "  owner_name        User's display name"
    echo "  language          Bot language (default: English)"
    echo "  timezone          IANA timezone (default: UTC)"
    echo "  calendar_provider 'google' or 'icloud' (default: google)"
    exit 1
fi

VM_NAME="ai-bot-${INSTANCE_NAME}"
REMOTE_DIR="/home/nir.geron/ai-bot"

# Get shared API keys from the main bot
echo "=== Fetching shared API keys from main bot ==="
ANTHROPIC_KEY=$(gcloud compute ssh nir.geron@ai-bot --project=$PROJECT --zone=$ZONE --account=$ACCOUNT --command="grep ANTHROPIC_API_KEY /home/nir.geron/ai-bot/.env | cut -d= -f2-" 2>/dev/null)

if [ -z "$ANTHROPIC_KEY" ]; then
    echo "ERROR: Could not fetch ANTHROPIC_API_KEY from main bot"
    exit 1
fi

# Step 1: Create VM
echo "=== Creating VM: $VM_NAME ==="
gcloud compute instances create "$VM_NAME" \
    --project=$PROJECT \
    --zone=$ZONE \
    --machine-type=e2-small \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --boot-disk-size=20GB \
    --account=$ACCOUNT

echo "=== Waiting for VM to be ready ==="
sleep 15

# Step 2: Create remote directories
echo "=== Setting up directories ==="
gcloud compute ssh nir.geron@"$VM_NAME" --project=$PROJECT --zone=$ZONE --account=$ACCOUNT \
    --command="mkdir -p $REMOTE_DIR/tools $REMOTE_DIR/skills $REMOTE_DIR/deploy"

# Step 3: Copy project files
echo "=== Copying project files ==="
# Main files
gcloud compute scp \
    "$PROJECT_DIR/bot.py" \
    "$PROJECT_DIR/agent.py" \
    "$PROJECT_DIR/config.py" \
    "$PROJECT_DIR/memory.py" \
    "$PROJECT_DIR/active_memory.py" \
    "$PROJECT_DIR/heartbeat.py" \
    "$PROJECT_DIR/pulse.py" \
    "$PROJECT_DIR/mood.py" \
    "$PROJECT_DIR/habits.py" \
    "$PROJECT_DIR/skills_loader.py" \
    "$PROJECT_DIR/auth_gmail.py" \
    "$PROJECT_DIR/requirements.txt" \
    nir.geron@"$VM_NAME":"$REMOTE_DIR/" \
    --project=$PROJECT --zone=$ZONE --account=$ACCOUNT

# Tools
gcloud compute scp "$PROJECT_DIR/tools/"*.py \
    nir.geron@"$VM_NAME":"$REMOTE_DIR/tools/" \
    --project=$PROJECT --zone=$ZONE --account=$ACCOUNT

# Skills
gcloud compute scp "$PROJECT_DIR/skills/"*.md \
    nir.geron@"$VM_NAME":"$REMOTE_DIR/skills/" \
    --project=$PROJECT --zone=$ZONE --account=$ACCOUNT

# Client secret for Gmail OAuth
if [ -f "$PROJECT_DIR/client_secret.json" ]; then
    gcloud compute scp "$PROJECT_DIR/client_secret.json" \
        nir.geron@"$VM_NAME":"$REMOTE_DIR/" \
        --project=$PROJECT --zone=$ZONE --account=$ACCOUNT
fi

# Step 4: Install dependencies and create .env
echo "=== Installing dependencies ==="
gcloud compute ssh nir.geron@"$VM_NAME" --project=$PROJECT --zone=$ZONE --account=$ACCOUNT --command="
cd $REMOTE_DIR
sudo apt update -qq && sudo apt install -y -qq python3 python3-venv python3-pip > /dev/null 2>&1
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
python -m playwright install --with-deps chromium > /dev/null 2>&1
echo '=== Dependencies installed ==='
"

# Step 5: Create .env
echo "=== Creating .env ==="
gcloud compute ssh nir.geron@"$VM_NAME" --project=$PROJECT --zone=$ZONE --account=$ACCOUNT --command="
cat > $REMOTE_DIR/.env << ENVEOF
TELEGRAM_TOKEN=$TELEGRAM_TOKEN
ANTHROPIC_API_KEY=$ANTHROPIC_KEY
OWNER_CHAT_ID=
BOT_OWNER_NAME=$OWNER_NAME
BOT_LANGUAGE=$LANGUAGE
USER_TIMEZONE=$TIMEZONE
CALENDAR_PROVIDER=$CALENDAR_PROVIDER
ENVEOF
chmod 600 $REMOTE_DIR/.env
"

# Step 6: Create systemd service
echo "=== Creating systemd service ==="
gcloud compute ssh nir.geron@"$VM_NAME" --project=$PROJECT --zone=$ZONE --account=$ACCOUNT --command="
sudo tee /etc/systemd/system/ai-bot.service > /dev/null << 'SVCEOF'
[Unit]
Description=Telegram AI Bot Agent ($OWNER_NAME)
After=network.target

[Service]
Type=simple
User=nir.geron
WorkingDirectory=$REMOTE_DIR
ExecStart=$REMOTE_DIR/venv/bin/python bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF

sudo systemctl daemon-reload
sudo systemctl enable ai-bot
sudo systemctl start ai-bot
"

sleep 3

echo ""
echo "============================================"
echo "  Bot instance '$VM_NAME' is RUNNING!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. User messages the bot on Telegram and sends /whoami"
echo "  2. Set owner:    ./deploy/set_owner.sh $INSTANCE_NAME <chat_id>"
echo "  3. Gmail setup:  python3 auth_gmail.py ${INSTANCE_NAME}_token"
echo "                   ./deploy/upload_token.sh $INSTANCE_NAME"
if [ "$CALENDAR_PROVIDER" = "icloud" ]; then
echo "  4. iCloud cal:   ./deploy/set_icloud.sh $INSTANCE_NAME <email> <app_password>"
fi
echo ""
echo "Management:"
echo "  Status:  gcloud compute ssh nir.geron@$VM_NAME --project=$PROJECT --zone=$ZONE --command='sudo systemctl status ai-bot'"
echo "  Logs:    gcloud compute ssh nir.geron@$VM_NAME --project=$PROJECT --zone=$ZONE --command='sudo journalctl -u ai-bot -f'"
echo "  Restart: gcloud compute ssh nir.geron@$VM_NAME --project=$PROJECT --zone=$ZONE --command='sudo systemctl restart ai-bot'"
