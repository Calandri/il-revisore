#!/bin/bash
set -e

# Log everything
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1

echo "=== TurboRepo EC2 Bootstrap ==="

# Configuration
REGION="eu-west-3"
SECRET_NAME="agent-zero/global/api-keys"
ECR_REPO="198584570682.dkr.ecr.eu-west-3.amazonaws.com/turbowrap:latest"

# Update system
yum update -y

# Install Docker and AWS CLI
yum install -y docker jq
systemctl start docker
systemctl enable docker

# Login to ECR
echo "Logging in to ECR..."
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin 198584570682.dkr.ecr.$REGION.amazonaws.com

# Create app directory with correct permissions for appuser (uid 1000)
mkdir -p /opt/turbowrap/data
chown -R 1000:1000 /opt/turbowrap/data

# Mount EBS volume for repos (if attached)
REPOS_DEVICE="/dev/xvdf"
REPOS_MOUNT="/mnt/repos"

if [ -b "$REPOS_DEVICE" ]; then
  echo "Found repos EBS volume at $REPOS_DEVICE"

  # Format if not already formatted
  if ! blkid "$REPOS_DEVICE" | grep -q ext4; then
    echo "Formatting volume as ext4..."
    mkfs.ext4 "$REPOS_DEVICE"
  fi

  # Create mount point and mount
  mkdir -p "$REPOS_MOUNT"
  mount "$REPOS_DEVICE" "$REPOS_MOUNT"

  # Ensure correct permissions for appuser (uid 1000)
  chown -R 1000:1000 "$REPOS_MOUNT"

  # Add to fstab for persistence across reboots
  if ! grep -q "$REPOS_DEVICE" /etc/fstab; then
    echo "$REPOS_DEVICE $REPOS_MOUNT ext4 defaults,nofail 0 2" >> /etc/fstab
  fi

  echo "Repos volume mounted at $REPOS_MOUNT"
else
  echo "No repos EBS volume found, using local storage"
  REPOS_MOUNT="/opt/turbowrap/data/repos"
  mkdir -p "$REPOS_MOUNT"
  chown -R 1000:1000 "$REPOS_MOUNT"
fi

# Get secrets from AWS Secrets Manager
echo "Fetching secrets from Secrets Manager..."
SECRETS=$(aws secretsmanager get-secret-value --secret-id "$SECRET_NAME" --region "$REGION" --query SecretString --output text)

# Parse secrets and create .env file
echo "Creating environment file..."

# Extract API keys
ANTHROPIC_KEY=$(echo $SECRETS | jq -r '.ANTHROPIC_API_KEY // empty')
GOOGLE_KEY=$(echo $SECRETS | jq -r '.GOOGLE_API_KEY // empty')
GEMINI_KEY=$(echo $SECRETS | jq -r '.GEMINI_API_KEY // empty')
GITHUB_KEY=$(echo $SECRETS | jq -r '.GITHUB_TOKEN // empty')
LINEAR_KEY=$(echo $SECRETS | jq -r '.LINEAR_API_KEY // empty')

# If GEMINI_API_KEY is not set, use GOOGLE_API_KEY (they're the same)
if [ -z "$GEMINI_KEY" ]; then
  GEMINI_KEY="$GOOGLE_KEY"
fi

cat > /opt/turbowrap/.env << EOF
# API Keys from Secrets Manager
ANTHROPIC_API_KEY=$ANTHROPIC_KEY
GOOGLE_API_KEY=$GOOGLE_KEY
GEMINI_API_KEY=$GEMINI_KEY
GITHUB_TOKEN=$GITHUB_KEY
LINEAR_API_KEY=$LINEAR_KEY

# Server config
TURBOWRAP_SERVER_HOST=0.0.0.0
TURBOWRAP_SERVER_PORT=8000
TURBOWRAP_DB_URL=sqlite:////data/turbowrap.db
TURBOWRAP_REPOS_DIR=/data/repos
EOF

# Pull Docker image from ECR
echo "Pulling Docker image from ECR..."
docker pull $ECR_REPO

# Run container
echo "Starting container..."
docker run -d \
  --name turbowrap \
  --restart always \
  -p 8000:8000 \
  -v /opt/turbowrap/data:/data \
  --env-file /opt/turbowrap/.env \
  $ECR_REPO

# Wait for container to be healthy
echo "Waiting for application to start..."
sleep 10

# Check status
docker ps
curl -s http://localhost:8000/api/status || echo "Warning: Health check failed"

echo "=== TurboRepo Bootstrap Complete ==="
