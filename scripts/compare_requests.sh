#!/bin/bash

# Direct comparison test between bot and test script
# This shows exactly what the bot is sending vs what works

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}🔍 Bot vs Test Script Comparison${NC}"
echo "================================="

echo -e "${YELLOW}1. Testing with external script (working):${NC}"
./scripts/test_llm.sh

echo ""
echo -e "${YELLOW}2. Testing same token with curl (working):${NC}"
TOKEN=$(cat secrets/open_webui_token.txt)
URL=$(grep OPEN_WEB_UI_URL .env | cut -d'=' -f2)
MODEL=$(grep OPEN_WEB_UI_MODEL .env | cut -d'=' -f2)

echo "Token: ${TOKEN:0:10}..."
echo "URL: $URL"
echo "Model: $MODEL"

# Test basic auth with curl from same Docker network
docker run --rm --network intranet --env-file .env \
    -e TEST_TOKEN="$TOKEN" \
    agora-bot:latest \
    bash -c '
    curl -s -w "\nHTTP_CODE:%{http_code}\n" \
         -H "Authorization: Bearer $TEST_TOKEN" \
         -H "Content-Type: application/json" \
         -d "{\"model\":\"$OPEN_WEB_UI_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"test\"}],\"max_tokens\":5}" \
         "$OPEN_WEB_UI_URL"
    '

echo ""
echo -e "${YELLOW}3. Check bot logs for comparison:${NC}"
echo "Now trigger a channel proposal and compare the bot logs with the working requests above."
echo ""
echo -e "${GREEN}Look for differences in:${NC}"
echo "- Token format/length"
echo "- URL endpoints"
echo "- Request headers"
echo "- Model names"