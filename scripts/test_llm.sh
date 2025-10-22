#!/bin/bash

# Test LLM connectivity from Docker container
# This runs on the same networks as your bot

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}🔬 Testing LLM Connection from Docker${NC}"
echo "===================================="

# Check requirements
if [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}❌ Run this from the project root directory${NC}"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo -e "${RED}❌ .env file not found${NC}"
    exit 1
fi

if [ ! -f "secrets/open_webui_token.txt" ]; then
    echo -e "${RED}❌ secrets/open_webui_token.txt not found${NC}"
    exit 1
fi

# Check if Docker image exists
if ! docker image inspect agora-bot:latest >/dev/null 2>&1; then
    echo -e "${RED}❌ Docker image 'agora-bot:latest' not found${NC}"
    echo -e "${YELLOW}💡 Build it first with: docker-compose build${NC}"
    exit 1
fi

echo -e "${YELLOW}📡 Testing network connectivity...${NC}"

# Test basic connectivity to openwebui
echo "Testing ping to openwebui..."
docker run --rm --network intranet agora-bot:latest ping -c 2 openwebui || echo "Ping failed (normal if ping is disabled)"

echo ""
echo -e "${YELLOW}🔑 Testing LLM API with your token...${NC}"

# Read token and URL from files
TOKEN=$(cat secrets/open_webui_token.txt)
URL=$(grep OPEN_WEB_UI_URL .env | cut -d'=' -f2)
MODEL=$(grep OPEN_WEB_UI_MODEL .env | cut -d'=' -f2)

echo "URL: $URL"
echo "Model: $MODEL"
echo "Token: ${TOKEN:0:10}..." # Show first 10 chars only

# Test the actual API call from within Docker
docker run --rm -i \
    --network intranet \
    --env-file .env \
    -e OPEN_WEB_UI_TOKEN="$TOKEN" \
    agora-bot:latest \
    python -c "
import asyncio
import aiohttp
import os
import json

async def test_llm():
    url = os.getenv('OPEN_WEB_UI_URL')
    token = os.getenv('OPEN_WEB_UI_TOKEN')
    model = os.getenv('OPEN_WEB_UI_MODEL')
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}'
    }
    
    payload = {
        'model': model,
        'messages': [
            {'role': 'user', 'content': 'Hello, just testing the connection'}
        ],
        'max_tokens': 10
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as response:
                print(f'Status: {response.status}')
                if response.status == 200:
                    data = await response.json()
                    print('✅ LLM API connection successful!')
                    print(f'Response: {json.dumps(data, indent=2)}')
                else:
                    text = await response.text()
                    print(f'❌ API Error: {response.status}')
                    print(f'Response: {text}')
    except Exception as e:
        print(f'❌ Connection Error: {e}')

asyncio.run(test_llm())
"

echo ""
echo -e "${GREEN}✅ LLM test completed${NC}"