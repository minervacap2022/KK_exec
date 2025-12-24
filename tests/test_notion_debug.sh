#!/bin/bash
# Debug version - shows all responses

set -e

AUTH_API="http://localhost:18000/api/auth"  # Via SSH tunnel
OAUTH_API="http://localhost:9000/api/v1/oauth"

echo "======================================"
echo "Notion OAuth - Debug Test"
echo "======================================"
echo

# Test login directly
echo "Testing login with yaodong / yaodong123..."
LOGIN_RESPONSE=$(curl -s -X POST "${AUTH_API}/login" \
  -H "Content-Type: application/json" \
  -d '{"username_or_email":"yaodong","password":"yaodong123","device_id":"test_client"}')

echo "Login Response:"
echo "$LOGIN_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$LOGIN_RESPONSE"
echo

# Extract token and user_id
TOKEN=$(echo "$LOGIN_RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('access_token', ''))" 2>/dev/null)
USER_ID=$(echo "$LOGIN_RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('user_id', ''))" 2>/dev/null)

echo "Extracted:"
echo "  Token: ${TOKEN:0:30}..."
echo "  User ID: $USER_ID"
echo

if [ -z "$TOKEN" ]; then
  echo "✗ No token received"
  exit 1
fi

# Get authorization URL
echo "Getting Notion auth URL..."
AUTH_RESPONSE=$(curl -s -X GET "${OAUTH_API}/notion/authorize" \
  -H "Authorization: Bearer $TOKEN")

echo "Auth URL Response:"
echo "$AUTH_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$AUTH_RESPONSE"
echo
