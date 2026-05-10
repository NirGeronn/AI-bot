#!/bin/bash
# Set the OWNER_CHAT_ID for a bot instance (locks it to one Telegram user)
# Usage: ./deploy/set_owner.sh <instance_name> <chat_id>

set -e
PROJECT="nir-ai-bot"
ZONE="us-central1-a"
ACCOUNT="geronir11@gmail.com"

INSTANCE_NAME="$1"
CHAT_ID="$2"
VM_NAME="ai-bot-${INSTANCE_NAME}"

if [ -z "$INSTANCE_NAME" ] || [ -z "$CHAT_ID" ]; then
    echo "Usage: $0 <instance_name> <chat_id>"
    exit 1
fi

gcloud compute ssh nir.geron@"$VM_NAME" --project=$PROJECT --zone=$ZONE --account=$ACCOUNT --command="
sed -i 's/OWNER_CHAT_ID=.*/OWNER_CHAT_ID=$CHAT_ID/' /home/nir.geron/ai-bot/.env
sudo systemctl restart ai-bot
sleep 2
sudo systemctl status ai-bot --no-pager
"

echo "=== Owner set to $CHAT_ID for $VM_NAME ==="
