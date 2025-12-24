#!/bin/bash
set -e

# === Configuration ===
REGION="eu-west-3"
INSTANCE_NAME="TurboRepo"
INSTANCE_TYPE="t3.small"
DOMAIN="turbo-wrap.com"
SECRET_NAME="agent-zero/global/api-keys"

echo "=== TurboRepo AWS Deployment ==="
echo "Region: $REGION"
echo "Domain: $DOMAIN"
echo ""

# === Step 1: Get VPC and Subnets ===
echo "1. Getting VPC and Subnet information..."

VPC_ID=$(aws ec2 describe-vpcs --region $REGION \
  --filters "Name=isDefault,Values=true" \
  --query 'Vpcs[0].VpcId' --output text)
echo "   VPC ID: $VPC_ID"

SUBNET_IDS=$(aws ec2 describe-subnets --region $REGION \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'Subnets[*].SubnetId' --output text | tr '\t' ',')
echo "   Subnets: $SUBNET_IDS"

# Get first two subnets for ALB (needs at least 2 AZs)
SUBNET_1=$(echo $SUBNET_IDS | cut -d',' -f1)
SUBNET_2=$(echo $SUBNET_IDS | cut -d',' -f2)

# Get latest Amazon Linux 2023 AMI
AMI_ID=$(aws ssm get-parameters --region $REGION \
  --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --query 'Parameters[0].Value' --output text)
echo "   AMI ID: $AMI_ID"

# === Step 2: Create Security Groups ===
echo ""
echo "2. Creating Security Groups..."

# Check if ALB SG exists
ALB_SG_ID=$(aws ec2 describe-security-groups --region $REGION \
  --filters "Name=group-name,Values=turborepo-alb-sg" "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")

if [ "$ALB_SG_ID" == "None" ] || [ -z "$ALB_SG_ID" ]; then
  ALB_SG_ID=$(aws ec2 create-security-group --region $REGION \
    --group-name turborepo-alb-sg \
    --description "TurboRepo ALB Security Group" \
    --vpc-id $VPC_ID \
    --query 'GroupId' --output text)

  # Allow HTTP and HTTPS from anywhere
  aws ec2 authorize-security-group-ingress --region $REGION \
    --group-id $ALB_SG_ID \
    --protocol tcp --port 80 --cidr 0.0.0.0/0
  aws ec2 authorize-security-group-ingress --region $REGION \
    --group-id $ALB_SG_ID \
    --protocol tcp --port 443 --cidr 0.0.0.0/0
  echo "   Created ALB SG: $ALB_SG_ID"
else
  echo "   ALB SG exists: $ALB_SG_ID"
fi

# Check if EC2 SG exists
EC2_SG_ID=$(aws ec2 describe-security-groups --region $REGION \
  --filters "Name=group-name,Values=turborepo-ec2-sg" "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")

if [ "$EC2_SG_ID" == "None" ] || [ -z "$EC2_SG_ID" ]; then
  EC2_SG_ID=$(aws ec2 create-security-group --region $REGION \
    --group-name turborepo-ec2-sg \
    --description "TurboRepo EC2 Security Group" \
    --vpc-id $VPC_ID \
    --query 'GroupId' --output text)

  # Allow port 8000 from ALB only
  aws ec2 authorize-security-group-ingress --region $REGION \
    --group-id $EC2_SG_ID \
    --protocol tcp --port 8000 --source-group $ALB_SG_ID
  echo "   Created EC2 SG: $EC2_SG_ID"
else
  echo "   EC2 SG exists: $EC2_SG_ID"
fi

# === Step 3: Create IAM Role ===
echo ""
echo "3. Creating IAM Role..."

ROLE_NAME="TurboRepoEC2Role"
INSTANCE_PROFILE_NAME="TurboRepoEC2Profile"

# Check if role exists
if ! aws iam get-role --role-name $ROLE_NAME 2>/dev/null; then
  # Create trust policy
  cat > /tmp/trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

  aws iam create-role --role-name $ROLE_NAME \
    --assume-role-policy-document file:///tmp/trust-policy.json

  # Attach SSM policy for Session Manager
  aws iam attach-role-policy --role-name $ROLE_NAME \
    --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore

  # Create and attach Secrets Manager policy
  cat > /tmp/secrets-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:$REGION:*:secret:$SECRET_NAME*"
    }
  ]
}
EOF

  aws iam put-role-policy --role-name $ROLE_NAME \
    --policy-name TurboRepoSecretsAccess \
    --policy-document file:///tmp/secrets-policy.json

  # Create instance profile
  aws iam create-instance-profile --instance-profile-name $INSTANCE_PROFILE_NAME
  aws iam add-role-to-instance-profile \
    --instance-profile-name $INSTANCE_PROFILE_NAME \
    --role-name $ROLE_NAME

  echo "   Created IAM Role: $ROLE_NAME"
  echo "   Waiting for instance profile to be available..."
  sleep 10
else
  echo "   IAM Role exists: $ROLE_NAME"
fi

# === Step 4: Request ACM Certificate ===
echo ""
echo "4. Requesting ACM Certificate..."

# Check if certificate exists
CERT_ARN=$(aws acm list-certificates --region $REGION \
  --query "CertificateSummaryList[?DomainName=='$DOMAIN'].CertificateArn" \
  --output text 2>/dev/null)

if [ -z "$CERT_ARN" ] || [ "$CERT_ARN" == "None" ]; then
  CERT_ARN=$(aws acm request-certificate --region $REGION \
    --domain-name $DOMAIN \
    --subject-alternative-names "*.$DOMAIN" \
    --validation-method DNS \
    --query 'CertificateArn' --output text)
  echo "   Requested certificate: $CERT_ARN"

  echo ""
  echo "   *** IMPORTANT: You need to validate the certificate! ***"
  echo "   Run the following to create DNS validation records:"
  echo ""
  echo "   aws acm describe-certificate --certificate-arn $CERT_ARN --region $REGION"
  echo ""
  echo "   Then create CNAME records in Route53 for validation."
  echo "   Press Enter once the certificate is validated..."
  read -p ""
else
  echo "   Certificate exists: $CERT_ARN"
fi

# Wait for certificate to be issued
echo "   Waiting for certificate validation..."
aws acm wait certificate-validated --certificate-arn $CERT_ARN --region $REGION || {
  echo "   Certificate not yet validated. Please validate and run script again."
  exit 1
}
echo "   Certificate validated!"

# === Step 5: Launch EC2 Instance ===
echo ""
echo "5. Launching EC2 Instance..."

# Check if instance already exists
INSTANCE_ID=$(aws ec2 describe-instances --region $REGION \
  --filters "Name=tag:Name,Values=$INSTANCE_NAME" "Name=instance-state-name,Values=running,pending" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null || echo "None")

if [ "$INSTANCE_ID" == "None" ] || [ -z "$INSTANCE_ID" ]; then
  # Read user-data script
  USER_DATA=$(base64 -i deploy/user-data.sh)

  INSTANCE_ID=$(aws ec2 run-instances --region $REGION \
    --image-id $AMI_ID \
    --instance-type $INSTANCE_TYPE \
    --security-group-ids $EC2_SG_ID \
    --subnet-id $SUBNET_1 \
    --iam-instance-profile Name=$INSTANCE_PROFILE_NAME \
    --user-data "$USER_DATA" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE_NAME}]" \
    --query 'Instances[0].InstanceId' --output text)

  echo "   Launched instance: $INSTANCE_ID"
  echo "   Waiting for instance to be running..."
  aws ec2 wait instance-running --instance-ids $INSTANCE_ID --region $REGION
else
  echo "   Instance exists: $INSTANCE_ID"
fi

# Get instance private IP
INSTANCE_IP=$(aws ec2 describe-instances --region $REGION \
  --instance-ids $INSTANCE_ID \
  --query 'Reservations[0].Instances[0].PrivateIpAddress' --output text)
echo "   Instance IP: $INSTANCE_IP"

# === Step 6: Create Target Group ===
echo ""
echo "6. Creating Target Group..."

TG_ARN=$(aws elbv2 describe-target-groups --region $REGION \
  --names turborepo-tg \
  --query 'TargetGroups[0].TargetGroupArn' --output text 2>/dev/null || echo "None")

if [ "$TG_ARN" == "None" ] || [ -z "$TG_ARN" ]; then
  TG_ARN=$(aws elbv2 create-target-group --region $REGION \
    --name turborepo-tg \
    --protocol HTTP \
    --port 8000 \
    --vpc-id $VPC_ID \
    --target-type instance \
    --health-check-path "/api/status" \
    --health-check-interval-seconds 30 \
    --health-check-timeout-seconds 5 \
    --healthy-threshold-count 2 \
    --unhealthy-threshold-count 3 \
    --query 'TargetGroups[0].TargetGroupArn' --output text)
  echo "   Created target group: $TG_ARN"
else
  echo "   Target group exists: $TG_ARN"
fi

# Register instance with target group
aws elbv2 register-targets --region $REGION \
  --target-group-arn $TG_ARN \
  --targets Id=$INSTANCE_ID
echo "   Registered instance with target group"

# === Step 7: Create Application Load Balancer ===
echo ""
echo "7. Creating Application Load Balancer..."

ALB_ARN=$(aws elbv2 describe-load-balancers --region $REGION \
  --names turborepo-alb \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || echo "None")

if [ "$ALB_ARN" == "None" ] || [ -z "$ALB_ARN" ]; then
  ALB_ARN=$(aws elbv2 create-load-balancer --region $REGION \
    --name turborepo-alb \
    --subnets $SUBNET_1 $SUBNET_2 \
    --security-groups $ALB_SG_ID \
    --scheme internet-facing \
    --type application \
    --query 'LoadBalancers[0].LoadBalancerArn' --output text)
  echo "   Created ALB: $ALB_ARN"

  echo "   Waiting for ALB to be active..."
  aws elbv2 wait load-balancer-available --load-balancer-arns $ALB_ARN --region $REGION
else
  echo "   ALB exists: $ALB_ARN"
fi

# Get ALB DNS name
ALB_DNS=$(aws elbv2 describe-load-balancers --region $REGION \
  --load-balancer-arns $ALB_ARN \
  --query 'LoadBalancers[0].DNSName' --output text)
ALB_ZONE=$(aws elbv2 describe-load-balancers --region $REGION \
  --load-balancer-arns $ALB_ARN \
  --query 'LoadBalancers[0].CanonicalHostedZoneId' --output text)
echo "   ALB DNS: $ALB_DNS"

# === Step 8: Create Listeners ===
echo ""
echo "8. Creating ALB Listeners..."

# Check if HTTPS listener exists
HTTPS_LISTENER=$(aws elbv2 describe-listeners --region $REGION \
  --load-balancer-arn $ALB_ARN \
  --query "Listeners[?Port==\`443\`].ListenerArn" --output text 2>/dev/null || echo "")

if [ -z "$HTTPS_LISTENER" ]; then
  # Create HTTPS listener
  aws elbv2 create-listener --region $REGION \
    --load-balancer-arn $ALB_ARN \
    --protocol HTTPS \
    --port 443 \
    --certificates CertificateArn=$CERT_ARN \
    --default-actions Type=forward,TargetGroupArn=$TG_ARN
  echo "   Created HTTPS listener"
else
  echo "   HTTPS listener exists"
fi

# Check if HTTP listener exists
HTTP_LISTENER=$(aws elbv2 describe-listeners --region $REGION \
  --load-balancer-arn $ALB_ARN \
  --query "Listeners[?Port==\`80\`].ListenerArn" --output text 2>/dev/null || echo "")

if [ -z "$HTTP_LISTENER" ]; then
  # Create HTTP listener (redirect to HTTPS)
  aws elbv2 create-listener --region $REGION \
    --load-balancer-arn $ALB_ARN \
    --protocol HTTP \
    --port 80 \
    --default-actions 'Type=redirect,RedirectConfig={Protocol=HTTPS,Port=443,StatusCode=HTTP_301}'
  echo "   Created HTTP -> HTTPS redirect listener"
else
  echo "   HTTP listener exists"
fi

# === Step 9: Create Route53 Record ===
echo ""
echo "9. Creating Route53 Record..."

# Get hosted zone ID
ZONE_ID=$(aws route53 list-hosted-zones \
  --query "HostedZones[?Name=='$DOMAIN.'].Id" --output text | sed 's|/hostedzone/||')

if [ -n "$ZONE_ID" ]; then
  cat > /tmp/route53-change.json << EOF
{
  "Changes": [
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "$DOMAIN",
        "Type": "A",
        "AliasTarget": {
          "HostedZoneId": "$ALB_ZONE",
          "DNSName": "$ALB_DNS",
          "EvaluateTargetHealth": true
        }
      }
    }
  ]
}
EOF

  aws route53 change-resource-record-sets \
    --hosted-zone-id $ZONE_ID \
    --change-batch file:///tmp/route53-change.json
  echo "   Created/Updated A record for $DOMAIN"
else
  echo "   WARNING: Could not find hosted zone for $DOMAIN"
fi

# === Summary ===
echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Resources created:"
echo "  - EC2 Instance: $INSTANCE_ID ($INSTANCE_NAME)"
echo "  - Target Group: turborepo-tg"
echo "  - ALB: turborepo-alb"
echo "  - Certificate: $CERT_ARN"
echo ""
echo "URLs:"
echo "  - https://$DOMAIN"
echo "  - http://$ALB_DNS (direct ALB)"
echo ""
echo "Access EC2 via SSM:"
echo "  aws ssm start-session --target $INSTANCE_ID --region $REGION"
echo ""
echo "View logs:"
echo "  aws ssm start-session --target $INSTANCE_ID --region $REGION"
echo "  # then: sudo tail -f /var/log/user-data.log"
echo ""
echo "Note: It may take 5-10 minutes for the application to fully start."
