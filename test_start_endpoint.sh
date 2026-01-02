#!/bin/bash

# Test script to debug the /start endpoint
# Run this script to test the Claude CLI chat /start endpoint

set -e

BASE_URL="${1:-http://localhost:8000}"
echo "Testing /start endpoint at $BASE_URL"
echo ""

# Step 1: List existing repositories
echo "=== STEP 1: List repositories ==="
REPOS=$(curl -s "$BASE_URL/api/repos")
echo "$REPOS" | jq '.[]' | head -5
echo ""

# Extract first repository ID
REPO_ID=$(echo "$REPOS" | jq -r '.[0].id' 2>/dev/null || echo "")
if [ -z "$REPO_ID" ] || [ "$REPO_ID" = "null" ]; then
    echo "ERROR: No repositories found. Create one first."
    exit 1
fi

echo "Using repository ID: $REPO_ID"
echo ""

# Step 2: Create a new chat session
echo "=== STEP 2: Create new chat session ==="
CREATE_SESSION=$(curl -s -X POST "$BASE_URL/api/cli-chat/sessions" \
  -H "Content-Type: application/json" \
  -d "{
    \"cli_type\": \"claude\",
    \"repository_id\": \"$REPO_ID\",
    \"model\": \"claude-opus-4-5-20251101\"
  }")

echo "$CREATE_SESSION" | jq '.'
echo ""

# Extract session ID
SESSION_ID=$(echo "$CREATE_SESSION" | jq -r '.id' 2>/dev/null || echo "")
if [ -z "$SESSION_ID" ] || [ "$SESSION_ID" = "null" ]; then
    echo "ERROR: Failed to create session"
    echo "Response: $CREATE_SESSION"
    exit 1
fi

echo "Created session ID: $SESSION_ID"
echo ""

# Step 3: Call /start endpoint
echo "=== STEP 3: Call /start endpoint (THIS IS THE KEY TEST) ==="
echo "Calling POST /api/cli-chat/sessions/$SESSION_ID/start"
echo ""

START_RESPONSE=$(curl -s -X POST "$BASE_URL/api/cli-chat/sessions/$SESSION_ID/start" \
  -H "Content-Type: application/json" \
  -w "\nHTTP_CODE:%{http_code}\n")

echo "$START_RESPONSE" | jq '.' 2>/dev/null || echo "$START_RESPONSE"
echo ""

# Step 4: Check /context endpoint
echo "=== STEP 4: Check /context endpoint (should work if /start succeeded) ==="
CONTEXT=$(curl -s "$BASE_URL/api/cli-chat/sessions/$SESSION_ID/context" \
  -w "\nHTTP_CODE:%{http_code}\n")

echo "$CONTEXT" | jq '.' 2>/dev/null || echo "$CONTEXT"
echo ""

# Step 5: Check /usage endpoint
echo "=== STEP 5: Check /usage endpoint (should work if /start succeeded) ==="
USAGE=$(curl -s "$BASE_URL/api/cli-chat/sessions/$SESSION_ID/usage" \
  -w "\nHTTP_CODE:%{http_code}\n")

echo "$USAGE" | jq '.' 2>/dev/null || echo "$USAGE"
echo ""

echo "=== TEST COMPLETE ==="
echo ""
echo "If you see HTTP 503 errors above, the process did not start."
echo "Check server logs (search for [START]) for detailed error messages."
echo ""
echo "Session ID for reference: $SESSION_ID"
echo ""
