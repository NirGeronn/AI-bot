#!/bin/bash
# Deploy code updates to a specific bot instance (or all instances)
# Usage: ./deploy/deploy_update.sh <instance_name|all>

set -e
PROJECT="nir-ai-bot"
ZONE="us-central1-a"
ACCOUNT="geronir11@gmail.com"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

deploy_to() {
    local VM_NAME="$1"
    local REMOTE_DIR="/home/nir.geron/ai-bot"
    echo "=== Deploying to $VM_NAME ==="

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

    gcloud compute scp "$PROJECT_DIR/tools/"*.py \
        nir.geron@"$VM_NAME":"$REMOTE_DIR/tools/" \
        --project=$PROJECT --zone=$ZONE --account=$ACCOUNT

    gcloud compute scp "$PROJECT_DIR/skills/"*.md \
        nir.geron@"$VM_NAME":"$REMOTE_DIR/skills/" \
        --project=$PROJECT --zone=$ZONE --account=$ACCOUNT

    gcloud compute ssh nir.geron@"$VM_NAME" --project=$PROJECT --zone=$ZONE --account=$ACCOUNT \
        --command="cd $REMOTE_DIR && source venv/bin/activate && pip install -r requirements.txt -q && sudo systemctl restart ai-bot"

    echo "=== $VM_NAME updated and restarted ==="
}

if [ -z "$1" ]; then
    echo "Usage: $0 <instance_name|all>"
    echo "  instance_name: deploys to ai-bot-<name>"
    echo "  'main': deploys to ai-bot (your instance)"
    echo "  'all': deploys to all instances"
    exit 1
fi

if [ "$1" = "all" ]; then
    # Get all ai-bot VMs
    VMS=$(gcloud compute instances list --project=$PROJECT --filter="name~'^ai-bot'" --format="value(name)" --account=$ACCOUNT)
    for vm in $VMS; do
        deploy_to "$vm"
    done
elif [ "$1" = "main" ]; then
    deploy_to "ai-bot"
else
    deploy_to "ai-bot-${1}"
fi
