#!/bin/bash
# Setup: Create + Attach + Mount a 1GB EBS volume for weblab app data
#
# This script:
#   1. Creates a 1GB gp3 EBS volume in the same AZ as the EC2 instance
#   2. Attaches it to the EC2 instance at /dev/xvdf
#   3. Formats as ext4 (default bytes-per-inode=16384 → ~65K inodes)
#   4. Mounts at /mnt/weblab-data
#   5. Moves gunicorn logs + creates audit log directory on the volume
#   6. Updates gunicorn to write logs to the EBS volume
#   7. Adds fstab entry for persistence
#
# After running this, the weblab app data layout is:
#   /mnt/weblab-data/
#   ├── logs/           ← gunicorn access.log + error.log
#   └── audit/          ← per-login audit log files (1 file per event)
#
# Inode budget: ~65,536 total, app uses ~20 → ~65,500 available for fault injection
#
# Usage: bash setup-ebs-volume.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

DEVICE_NAME="/dev/xvdf"
MOUNT_POINT="/mnt/weblab-data"
VOLUME_SIZE=1  # GB

log "=== Setting up 1GB EBS volume for weblab ==="

# Get EC2 instance AZ
AZ=$(aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --query 'Reservations[0].Instances[0].Placement.AvailabilityZone' \
    --output text)
log "Instance AZ: $AZ"

# Check if volume already exists (idempotent)
EXISTING_VOL=$(aws ec2 describe-volumes \
    --filters "Name=attachment.instance-id,Values=$INSTANCE_ID" \
              "Name=attachment.device,Values=$DEVICE_NAME" \
              "Name=status,Values=in-use" \
    --region "$REGION" \
    --query 'Volumes[0].VolumeId' --output text 2>/dev/null || echo "None")

if [ "$EXISTING_VOL" != "None" ] && [ -n "$EXISTING_VOL" ]; then
    log "EBS volume already attached: $EXISTING_VOL at $DEVICE_NAME"
    log "Checking if mounted..."
    ssm_run_wait "mountpoint -q $MOUNT_POINT && echo 'Already mounted' || echo 'Not mounted'"
    log "If already set up, no action needed. To recreate, detach first."
    exit 0
fi

# Step 1: Create volume
log "Creating ${VOLUME_SIZE}GB gp3 volume in $AZ..."
VOLUME_ID=$(aws ec2 create-volume \
    --size $VOLUME_SIZE \
    --volume-type gp3 \
    --availability-zone "$AZ" \
    --tag-specifications "ResourceType=volume,Tags=[{Key=Name,Value=weblab-data},{Key=Project,Value=weblab}]" \
    --region "$REGION" \
    --query 'VolumeId' --output text)
log "Volume created: $VOLUME_ID"

# Wait for available
log "Waiting for volume to be available..."
aws ec2 wait volume-available --volume-ids "$VOLUME_ID" --region "$REGION"
log "Volume ready."

# Step 2: Attach
log "Attaching $VOLUME_ID to $INSTANCE_ID at $DEVICE_NAME..."
aws ec2 attach-volume \
    --volume-id "$VOLUME_ID" \
    --instance-id "$INSTANCE_ID" \
    --device "$DEVICE_NAME" \
    --region "$REGION" > /dev/null

# Wait for attachment
log "Waiting for attachment..."
sleep 10
aws ec2 wait volume-in-use --volume-ids "$VOLUME_ID" --region "$REGION"
log "Volume attached."

# Step 3-7: Format, mount, configure on the EC2 instance
log "Formatting, mounting, and configuring on EC2..."
ssm_run_wait "
set -e

# Wait for device to appear (NVMe naming may differ)
DEVICE=''
for dev in /dev/xvdf /dev/nvme1n1; do
    if [ -b \$dev ]; then
        DEVICE=\$dev
        break
    fi
done

if [ -z \"\$DEVICE\" ]; then
    echo 'ERROR: No device found at /dev/xvdf or /dev/nvme1n1'
    lsblk
    exit 1
fi
echo \"Using device: \$DEVICE\"

# Format as ext4 (default bytes-per-inode=16384)
mkfs.ext4 -F \$DEVICE

# Create mount point and mount
mkdir -p $MOUNT_POINT
mount \$DEVICE $MOUNT_POINT

# Show inode info
echo ''
echo 'Volume info:'
df -h $MOUNT_POINT
echo ''
df -i $MOUNT_POINT

# Create app directories
mkdir -p $MOUNT_POINT/logs
mkdir -p $MOUNT_POINT/audit

# Move existing logs if any
cp /var/log/weblab-access.log $MOUNT_POINT/logs/access.log 2>/dev/null || touch $MOUNT_POINT/logs/access.log
cp /var/log/weblab-error.log $MOUNT_POINT/logs/error.log 2>/dev/null || touch $MOUNT_POINT/logs/error.log

# Add to fstab for persistence across reboots
UUID=\$(blkid -s UUID -o value \$DEVICE)
if ! grep -q \$UUID /etc/fstab 2>/dev/null; then
    echo \"UUID=\$UUID $MOUNT_POINT ext4 defaults,nofail 0 2\" >> /etc/fstab
    echo 'Added to fstab'
fi

echo ''
echo 'Mount point ready:'
ls -la $MOUNT_POINT/
echo ''
echo 'Inode summary:'
df -i $MOUNT_POINT | tail -1
"

# Step 6: Update gunicorn to use new log paths
log ""
log "Updating gunicorn log paths..."
ssm_run_wait "
# Update run.sh to use EBS volume for logs
sed -i 's|--access-logfile /var/log/weblab-access.log|--access-logfile $MOUNT_POINT/logs/access.log|' /opt/weblab/run.sh
sed -i 's|--error-logfile /var/log/weblab-error.log|--error-logfile $MOUNT_POINT/logs/error.log|' /opt/weblab/run.sh

# Add AUDIT_DIR env var to .env
if ! grep -q AUDIT_DIR /opt/weblab/.env 2>/dev/null; then
    echo 'AUDIT_DIR=$MOUNT_POINT/audit' >> /opt/weblab/.env
    echo 'Added AUDIT_DIR to .env'
fi

echo 'Updated run.sh:'
cat /opt/weblab/run.sh
"

# Restart service with new config
log ""
log "Restarting weblab with new log paths..."
ssm_run_wait 'systemctl restart weblab'
sleep 5

log ""
log "Verifying..."
health=$(check_health)
log "Health: $health"

log ""
log "=== EBS Setup Complete ==="
log "Volume: $VOLUME_ID (${VOLUME_SIZE}GB gp3)"
log "Mount: $MOUNT_POINT"
log "Logs: $MOUNT_POINT/logs/"
log "Audit: $MOUNT_POINT/audit/"
log ""
log "Inode budget: ~65,536 total"
log "Available for fault injection: ~65,500"
log ""
log "IMPORTANT: You also need to deploy the updated app.py with audit logging."
log "  1. Repackage app: cd infra/web-lab/app && tar czf /tmp/app.tar.gz ."
log "  2. Upload: aws s3 cp /tmp/app.tar.gz s3://agenticops-reports-533267047935/weblab/app.tar.gz"
log "  3. Deploy: bash deploy.sh (or ssm_run 'cd /opt/weblab && tar xzf ...')"
