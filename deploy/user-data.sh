#!/bin/bash
set -e

# Log everything
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1

echo "=== TurboRepo EC2 Bootstrap ==="

# Update system
yum update -y

# Install Docker
yum install -y docker git jq
systemctl start docker
systemctl enable docker

# Install AWS CLI v2 (for Secrets Manager)
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
yum install -y unzip
unzip awscliv2.zip
./aws/install
rm -rf aws awscliv2.zip

# Create app directory
mkdir -p /opt/turbowrap
cd /opt/turbowrap

# Clone repository
git clone https://github.com/3bee/ultraWrap.git .
# Or if private: use deploy key or CodeCommit

# Get secrets from AWS Secrets Manager
REGION="eu-west-3"
SECRET_NAME="agent-zero/global/api-keys"

echo "Fetching secrets from Secrets Manager..."
SECRETS=$(aws secretsmanager get-secret-value --secret-id "$SECRET_NAME" --region "$REGION" --query SecretString --output text)

# Parse secrets and create .env file
echo "Creating environment file..."
cat > /opt/turbowrap/.env << EOF
# API Keys from Secrets Manager
ANTHROPIC_API_KEY=$(echo $SECRETS | jq -r '.ANTHROPIC_API_KEY // empty')
GOOGLE_API_KEY=$(echo $SECRETS | jq -r '.GOOGLE_API_KEY // empty')
GEMINI_API_KEY=$(echo $SECRETS | jq -r '.GEMINI_API_KEY // empty')
GITHUB_TOKEN=$(echo $SECRETS | jq -r '.GITHUB_TOKEN // empty')
LINEAR_API_KEY=$(echo $SECRETS | jq -r '.LINEAR_API_KEY // empty')

# Server config
TURBOWRAP_SERVER_HOST=0.0.0.0
TURBOWRAP_SERVER_PORT=8000
TURBOWRAP_DB_URL=sqlite:////data/turbowrap.db
TURBOWRAP_REPOS_DIR=/data/repos
EOF

# Create data directory
mkdir -p /opt/turbowrap/data

# Build Docker image
echo "Building Docker image..."
docker build -t turbowrap:latest .

# Run container
echo "Starting container..."
docker run -d \
  --name turbowrap \
  --restart always \
  -p 8000:8000 \
  -v /opt/turbowrap/data:/data \
  --env-file /opt/turbowrap/.env \
  turbowrap:latest

# Wait for container to be healthy
echo "Waiting for application to start..."
sleep 10

# Check status
docker ps
curl -s http://localhost:8000/api/status || echo "Warning: Health check failed"

echo "=== TurboRepo Bootstrap Complete ==="
