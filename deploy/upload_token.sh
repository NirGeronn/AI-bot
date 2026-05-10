#!/bin/bash
# Upload a Gmail OAuth token to a bot instance
# Run auth_gmail.py first: python3 auth_gmail.py <instance_name>_token
# Then run this script to upload it.
# Usage: ./deploy/upload_token.sh <instance_name>

set -e
PROJECT="nir-ai-bot"
ZONE="us-central1-a"
ACCOUNT="geronir11@gmail.com"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

INSTANCE_NAME="$1"
VM_NAME="ai-bot-${INSTANCE_NAME}"
TOKEN_FILE="$PROJECT_DIR/${INSTANCE_NAME}_token.json"

if [ -z "$INSTANCE_NAME" ]; then
    echo "Usage: $0 <instance_name>"
    exit 1
fi

if [ ! -f "$TOKEN_FILE" ]; then
    echo "Token file not found: $TOKEN_FILE"
    echo "Run first: python3 auth_gmail.py ${INSTANCE_NAME}_token"
    exit 1
fi

gcloud compute scp "$TOKEN_FILE" \
    nir.geron@"$VM_NAME":/home/nir.geron/ai-bot/google_token.json \
    --project=$PROJECT --zone=$ZONE --account=$ACCOUNT

gcloud compute ssh nir.geron@"$VM_NAME" --project=$PROJECT --zone=$ZONE --account=$ACCOUNT \
    --command="sudo systemctl restart ai-bot && sleep 2 && sudo systemctl status ai-bot --no-pager"

echo "=== Gmail token uploaded and bot restarted for $VM_NAME ==="
