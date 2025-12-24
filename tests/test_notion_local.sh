#!/bin/bash
# Test Notion OAuth locally using production auth

set -e

# Use production auth, local OAuth endpoints
AUTH_API="https://hiklik.ai/api/auth"
OAUTH_API="http://localhost:9000/api/v1/oauth"

echo "======================================"
echo "Notion OAuth - Local Test"
echo "======================================"
echo "Using:"
echo "  Auth: ${AUTH_API} (production)"
echo "  OAuth: ${OAUTH_API} (local)"
echo

# Step 1: Login to production auth
echo "Step 1: Login to Production Auth"
echo "----------------------------------"
read -p "Username or Email: " USERNAME_OR_EMAIL
read -sp "Password: " PASSWORD
echo

LOGIN_RESPONSE=$(curl -s -X POST "${AUTH_API}/login" \
  -H "Content-Type: application/json" \
  -d "{\"username_or_email\":\"${USERNAME_OR_EMAIL}\",\"password\":\"${PASSWORD}\",\"device_id\":\"test_client\"}")

TOKEN=$(echo "$LOGIN_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('access_token', ''))" 2>/dev/null)

if [ -z "$TOKEN" ]; then
  echo "✗ Login failed"
  echo "$LOGIN_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$LOGIN_RESPONSE"
  exit 1
fi

echo "✓ Token: ${TOKEN:0:20}..."
echo

# Step 2: Get Notion authorization URL (local server)
echo "Step 2: Get Authorization URL (Local)"
echo "--------------------------------------"

AUTH_RESPONSE=$(curl -s -X GET "${OAUTH_API}/notion/authorize" \
  -H "Authorization: Bearer $TOKEN")

AUTH_URL=$(echo "$AUTH_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('authorization_url', ''))" 2>/dev/null)
STATE=$(echo "$AUTH_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('state', ''))" 2>/dev/null)

if [ -z "$AUTH_URL" ]; then
  echo "✗ Failed to get authorization URL"
  echo "$AUTH_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$AUTH_RESPONSE"
  exit 1
fi

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
echo "3. Browser will redirect to: https://hiklik.ai/api/v1/oauth/notion/callback?code=...&state=..."
echo "4. Copy the FULL redirect URL from browser address bar"
echo

read -p "Paste the redirect URL here: " REDIRECT_URL

# Extract code from URL
CODE=$(echo "$REDIRECT_URL" | grep -o 'code=[^&]*' | cut -d'=' -f2)

if [ -z "$CODE" ]; then
  echo "✗ Could not extract code from URL"
  exit 1
fi

echo "✓ Code extracted: ${CODE:0:20}..."
echo

# Step 4: Call local callback endpoint
echo "Step 4: Exchange Code for Tokens (Local)"
echo "-----------------------------------------"

CALLBACK_RESPONSE=$(curl -s -i -X GET "http://localhost:9000/api/v1/oauth/notion/callback?code=$CODE&state=$STATE")

if echo "$CALLBACK_RESPONSE" | grep -q "success=true"; then
  echo "✓ OAuth flow completed successfully!"
  echo "$CALLBACK_RESPONSE" | grep -i "location:"
else
  echo "✗ OAuth flow failed"
  echo "$CALLBACK_RESPONSE"
  exit 1
fi

echo

# Step 5: Verify credential saved
echo "Step 5: Verify Credential Saved (Local)"
echo "----------------------------------------"

STATUS_RESPONSE=$(curl -s -X GET "http://localhost:9000/api/v1/oauth/notion/status" \
  -H "Authorization: Bearer $TOKEN")

echo "$STATUS_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$STATUS_RESPONSE"

echo
echo "======================================"
echo "Test Complete!"
echo "======================================"
