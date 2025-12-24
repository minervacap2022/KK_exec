#!/bin/bash
# Test Notion OAuth using curl commands

set -e

API="http://localhost:8000/api/v1"

echo "=============================="
echo "Notion OAuth - curl Test"
echo "=============================="
echo

# Step 1: Register user
echo "Step 1: Register User"
echo "----------------------"
read -p "Email: " EMAIL
read -sp "Password: " PASSWORD
echo

REGISTER_RESPONSE=$(curl -s -X POST "$API/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"full_name\":\"Test User\"}")

# Try to extract token from register, if fails try login
TOKEN=$(echo "$REGISTER_RESPONSE" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)

if [ -z "$TOKEN" ]; then
  echo "Registration failed, trying login..."
  LOGIN_RESPONSE=$(curl -s -X POST "$API/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")

  TOKEN=$(echo "$LOGIN_RESPONSE" | grep -o '"access_token":"[^"]*' | cut -d'"' -f4)
fi

if [ -z "$TOKEN" ]; then
  echo "✗ Failed to get token"
  exit 1
fi

echo "✓ Token: ${TOKEN:0:20}..."
echo

# Step 2: Get authorization URL
echo "Step 2: Get Authorization URL"
echo "------------------------------"

AUTH_RESPONSE=$(curl -s -X GET "$API/oauth/notion/authorize" \
  -H "Authorization: Bearer $TOKEN")

AUTH_URL=$(echo "$AUTH_RESPONSE" | grep -o '"authorization_url":"[^"]*' | cut -d'"' -f4 | sed 's/\\//g')
STATE=$(echo "$AUTH_RESPONSE" | grep -o '"state":"[^"]*' | cut -d'"' -f4)

echo "✓ Authorization URL:"
echo "$AUTH_URL"
echo
echo "State: $STATE"
echo

# Step 3: Open in browser
echo "Step 3: Authorize in Browser"
echo "-----------------------------"
echo "1. Open the URL above in your browser"
echo "2. Authorize the Klik app in Notion"
echo "3. After redirect, copy the FULL URL from browser"
echo "   (will look like: https://hiklik.ai/api/v1/oauth/notion/callback?code=...&state=...)"
echo

read -p "Paste the redirect URL here: " REDIRECT_URL

# Extract code from URL
CODE=$(echo "$REDIRECT_URL" | grep -o 'code=[^&]*' | cut -d'=' -f2)

if [ -z "$CODE" ]; then
  echo "✗ Could not extract code from URL"
  exit 1
fi

echo "✓ Code: ${CODE:0:20}..."
echo

# Step 4: Call callback endpoint
echo "Step 4: Exchange Code for Tokens"
echo "---------------------------------"

CALLBACK_RESPONSE=$(curl -s -i -X GET "$API/oauth/notion/callback?code=$CODE&state=$STATE")

if echo "$CALLBACK_RESPONSE" | grep -q "success=true"; then
  echo "✓ OAuth flow completed successfully!"
else
  echo "✗ OAuth flow failed"
  echo "$CALLBACK_RESPONSE"
  exit 1
fi

echo

# Step 5: Check status
echo "Step 5: Verify Connection"
echo "-------------------------"

STATUS_RESPONSE=$(curl -s -X GET "$API/oauth/notion/status" \
  -H "Authorization: Bearer $TOKEN")

echo "$STATUS_RESPONSE" | python3 -m json.tool

echo
echo "=============================="
echo "Test Complete!"
echo "=============================="
