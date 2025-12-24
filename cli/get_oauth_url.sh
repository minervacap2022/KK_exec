#!/bin/bash
# Get OAuth URL for a user
#
# Usage:
#   ./cli/get_oauth_url.sh <provider> <username> <password>
#
# Example:
#   ./cli/get_oauth_url.sh notion yaodong2 yaodong333

set -e

PROVIDER=${1:-notion}
USERNAME=$2
PASSWORD=$3

API_URL="http://localhost:9000/api/v1"

if [ -z "$USERNAME" ] || [ -z "$PASSWORD" ]; then
    echo "Usage: $0 <provider> <username> <password>"
    echo "Example: $0 notion yaodong2 yaodong333"
    exit 1
fi

# Login
TOKEN=$(curl -s -X POST "$API_URL/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)

if [ -z "$TOKEN" ]; then
    echo "Error: Login failed for user '$USERNAME'"
    exit 1
fi

# Get OAuth URL
OAUTH_URL=$(curl -s -H "Authorization: Bearer $TOKEN" \
    "$API_URL/oauth/$PROVIDER/authorize" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('authorization_url',''))" 2>/dev/null)

if [ -z "$OAUTH_URL" ]; then
    echo "Error: Failed to get OAuth URL for provider '$PROVIDER'"
    exit 1
fi

echo ""
echo "Open this URL to authorize $PROVIDER for user '$USERNAME':"
echo ""
echo "$OAUTH_URL"
echo ""
