#!/bin/bash
# Simple wrapper to execute natural language commands
# LLM decides which MCPs to use automatically
#
# Usage:
#   ./cli/run_command.sh "Create a Notion page titled 'Meeting Notes'"
#
# Environment variables:
#   KLIK_USER - Username (prompted if not set)
#   KLIK_PASS - Password (prompted if not set)

set -e

# Config
EXEC_API="http://localhost:9000/api/v1"      # Local KK_exec
AUTH_API="${EXEC_API}/auth"                   # Use local auth

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "========================================"
echo "  Natural Language Command Executor"
echo "========================================"
echo

# Get credentials (use KLIK_USER/KLIK_PASS to avoid conflicts with system vars)
if [ -z "$KLIK_USER" ]; then
    read -p "Username: " KLIK_USER
fi

if [ -z "$KLIK_PASS" ]; then
    read -sp "Password: " KLIK_PASS
    echo
fi

# Login
echo -e "${BLUE}→ Logging in...${NC}"
LOGIN_RESPONSE=$(curl -s -X POST "${AUTH_API}/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${KLIK_USER}\",\"password\":\"${KLIK_PASS}\"}")

TOKEN=$(echo "$LOGIN_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('access_token', ''))" 2>/dev/null)

if [ -z "$TOKEN" ]; then
    echo -e "${RED}✗ Login failed${NC}"
    echo "$LOGIN_RESPONSE" | python3 -m json.tool 2>/dev/null
    exit 1
fi

# Decode user_id from JWT (sub claim in payload)
USER_ID=$(echo "$TOKEN" | python3 -c "
import sys, json, base64
token = sys.stdin.read().strip()
payload = token.split('.')[1]
# Add padding if needed
payload += '=' * (4 - len(payload) % 4)
data = json.loads(base64.urlsafe_b64decode(payload))
print(data.get('sub', 'unknown'))
" 2>/dev/null)

echo -e "${GREEN}✓ Logged in as: ${USER_ID}${NC}"
echo

# Get command
if [ -z "$1" ]; then
    echo "What would you like to do?"
    echo "Examples:"
    echo "  - Create a Notion page titled 'Daily Standup'"
    echo "  - Send a Slack message to #general saying 'Hello team'"
    echo "  - Search GitHub for repos about 'machine learning'"
    echo
    read -p "Command: " COMMAND
else
    COMMAND="$*"
fi

echo
echo -e "${BLUE}→ Analyzing command and selecting MCPs...${NC}"
echo "  Command: $COMMAND"
echo

# Execute (get script directory and Python with dependencies)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PYTHON="/opt/homebrew/opt/python@3.12/bin/python3.12"

"$PYTHON" "$SCRIPT_DIR/execute_command.py" \
    "$COMMAND" \
    --user-id "$USER_ID" \
    --token "$TOKEN" \
    --api-url "$EXEC_API"
