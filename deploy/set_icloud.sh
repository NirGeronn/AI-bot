#!/bin/bash
# Configure iCloud Calendar credentials for a bot instance
# Usage: ./deploy/set_icloud.sh <instance_name> <icloud_email> <app_password>

set -e
PROJECT="nir-ai-bot"
ZONE="us-central1-a"
ACCOUNT="geronir11@gmail.com"

INSTANCE_NAME="$1"
ICLOUD_EMAIL="$2"
ICLOUD_PASSWORD="$3"
VM_NAME="ai-bot-${INSTANCE_NAME}"

if [ -z "$INSTANCE_NAME" ] || [ -z "$ICLOUD_EMAIL" ] || [ -z "$ICLOUD_PASSWORD" ]; then
    echo "Usage: $0 <instance_name> <icloud_email> <app_password>"
    echo ""
    echo "Generate an app-specific password at https://appleid.apple.com/account/manage"
    exit 1
fi

gcloud compute ssh nir.geron@"$VM_NAME" --project=$PROJECT --zone=$ZONE --account=$ACCOUNT --command="
cd /home/nir.geron/ai-bot
# Remove old iCloud lines if they exist
sed -i '/ICLOUD_EMAIL/d' .env
sed -i '/ICLOUD_APP_PASSWORD/d' .env
sed -i 's/CALENDAR_PROVIDER=.*/CALENDAR_PROVIDER=icloud/' .env
# Add new ones
echo 'ICLOUD_EMAIL=$ICLOUD_EMAIL' >> .env
echo 'ICLOUD_APP_PASSWORD=$ICLOUD_PASSWORD' >> .env
sudo systemctl restart ai-bot
sleep 2
sudo systemctl status ai-bot --no-pager
"

echo "=== iCloud Calendar configured for $VM_NAME ==="
