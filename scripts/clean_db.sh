#!/bin/bash

# Agora Discord Bot Database Cleanup Tool
# Simple interactive database cleanup using Docker

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}🗃️  Agora Database Cleanup Tool${NC}"
echo "================================"

# Check requirements
if [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}❌ Run this from the project root directory${NC}"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo -e "${RED}❌ .env file not found${NC}"
    exit 1
fi

# Check if Docker image exists
if ! docker image inspect agora-bot:latest >/dev/null 2>&1; then
    echo -e "${RED}❌ Docker image 'agora-bot:latest' not found${NC}"
    echo -e "${YELLOW}💡 Build it first with: docker-compose build${NC}"
    exit 1
fi

# Check if secrets directory exists
if [ ! -d "secrets" ]; then
    echo -e "${RED}❌ secrets/ directory not found${NC}"
    echo -e "${YELLOW}💡 Create secrets directory with db_password.txt${NC}"
    exit 1
fi

# Check if db password secret exists  
if [ ! -f "secrets/db_password.txt" ]; then
    echo -e "${RED}❌ secrets/db_password.txt not found${NC}"
    echo -e "${YELLOW}💡 Create this file with your database password${NC}"
    exit 1
fi

# Create temporary Python script for database operations
cat > /tmp/db_cleanup.py << 'EOF'
import asyncio
import asyncpg
import redis
import os
import sys

DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'port': int(os.getenv('DB_PORT')),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD')
}

REDIS_CONFIG = {
    'host': os.getenv('REDIS_HOST'),
    'port': int(os.getenv('REDIS_PORT')),
    'db': int(os.getenv('REDIS_DB'))
}

async def main():
    action = sys.argv[1] if len(sys.argv) > 1 else 'list'
    
    try:
        conn = await asyncpg.connect(**DB_CONFIG)
        r = redis.Redis(**REDIS_CONFIG, decode_responses=True)
        r.ping()
        
        if action == 'list':
            # Get all tables with record counts
            tables_query = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name;
            """
            tables = await conn.fetch(tables_query)
            
            print("📋 Database Tables:")
            for i, table in enumerate(tables, 1):
                count = await conn.fetchval(f"SELECT COUNT(*) FROM {table['table_name']}")
                print(f"  {i}. {table['table_name']} ({count} records)")
            
            # Redis info
            keys = r.keys('*')
            print(f"\n📡 Redis: {len(keys)} keys")
            
        elif action == 'show':
            table_name = sys.argv[2]
            
            # Show sample records
            records = await conn.fetch(f"SELECT * FROM {table_name} LIMIT 5")
            
            if not records:
                print(f"📄 Table '{table_name}' is empty")
                return
            
            print(f"\n📋 Sample records from '{table_name}':")
            print("=" * 60)
            
            # Get column names
            columns = list(records[0].keys())
            
            for i, record in enumerate(records, 1):
                print(f"\nRecord #{i}:")
                for col in columns:
                    value = record[col]
                    if value is None:
                        value_str = "NULL"
                    else:
                        value_str = str(value)
                        if len(value_str) > 80:
                            value_str = value_str[:77] + "..."
                    print(f"  {col}: {value_str}")
            
            total = await conn.fetchval(f"SELECT COUNT(*) FROM {table_name}")
            if total > 5:
                print(f"\n... and {total - 5} more records")
        
        elif action == 'delete':
            table_name = sys.argv[2]
            result = await conn.execute(f"DELETE FROM {table_name}")
            count = int(result.split()[-1]) if result.split()[-1].isdigit() else 0
            print(f"✅ Deleted {count} records from '{table_name}'")
        
        elif action == 'delete_all':
            # Get all tables
            tables = await conn.fetch("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """)
            
            total_deleted = 0
            for table in tables:
                result = await conn.execute(f"DELETE FROM {table['table_name']}")
                count = int(result.split()[-1]) if result.split()[-1].isdigit() else 0
                total_deleted += count
                print(f"  ✅ {table['table_name']}: {count} records")
            
            # Clear Redis
            r.flushall()
            redis_keys = len(r.keys('*'))
            
            print(f"\n✅ Total PostgreSQL records deleted: {total_deleted}")
            print(f"✅ Redis cache cleared")
    
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    finally:
        if 'conn' in locals():
            await conn.close()
        if 'r' in locals():
            r.close()

if __name__ == "__main__":
    asyncio.run(main())
EOF

# Main menu function
show_menu() {
    echo ""
    echo -e "${BLUE}🔧 Options:${NC}"
    echo "1. List all tables"
    echo "2. Show records from a table"
    echo "3. Delete records from a table" 
    echo "4. Delete ALL data (PostgreSQL + Redis)"
    echo "5. Exit"
    echo ""
}

# Docker run function
run_docker() {
    # Read the database password from secrets file
    DB_PASSWORD=$(cat secrets/db_password.txt)
    
    docker run --rm -i \
        --network dbnet \
        --env-file .env \
        -e DB_PASSWORD="$DB_PASSWORD" \
        --mount type=bind,source=/tmp/db_cleanup.py,target=/app/cleanup.py \
        agora-bot:latest \
        python /app/cleanup.py "$@"
}

# Main loop
while true; do
    show_menu
    read -p "Enter choice (1-5): " choice
    
    case $choice in
        1)
            echo -e "\n${YELLOW}📊 Loading database info...${NC}"
            run_docker list
            ;;
        2)
            echo ""
            run_docker list
            echo ""
            read -p "Enter table number or name: " table_input
            
            # If it's a number, get table name
            if [[ "$table_input" =~ ^[0-9]+$ ]]; then
                table_name=$(run_docker list | grep "^  $table_input\." | cut -d' ' -f4)
                if [ -z "$table_name" ]; then
                    echo -e "${RED}❌ Invalid table number${NC}"
                    continue
                fi
            else
                table_name="$table_input"
            fi
            
            echo -e "\n${YELLOW}📋 Loading records from '$table_name'...${NC}"
            run_docker show "$table_name"
            ;;
        3)
            echo ""
            run_docker list
            echo ""
            read -p "Enter table number or name: " table_input
            
            # If it's a number, get table name
            if [[ "$table_input" =~ ^[0-9]+$ ]]; then
                table_name=$(run_docker list | grep "^  $table_input\." | cut -d' ' -f4)
                if [ -z "$table_name" ]; then
                    echo -e "${RED}❌ Invalid table number${NC}"
                    continue
                fi
            else
                table_name="$table_input"
            fi
            
            echo -e "\n${YELLOW}📋 Records in '$table_name':${NC}"
            run_docker show "$table_name"
            
            echo ""
            read -p "⚠️  Delete all records from '$table_name'? (yes/no): " confirm
            if [ "$confirm" = "yes" ]; then
                echo -e "${YELLOW}🗑️  Deleting records...${NC}"
                run_docker delete "$table_name"
            else
                echo -e "${RED}❌ Cancelled${NC}"
            fi
            ;;
        4)
            echo -e "\n${RED}⚠️  WARNING: This will delete ALL data!${NC}"
            read -p "Type 'DELETE ALL' to confirm: " confirm
            if [ "$confirm" = "DELETE ALL" ]; then
                echo -e "${YELLOW}🗑️  Deleting all data...${NC}"
                run_docker delete_all
            else
                echo -e "${RED}❌ Cancelled${NC}"
            fi
            ;;
        5)
            echo -e "${GREEN}👋 Goodbye!${NC}"
            break
            ;;
        *)
            echo -e "${RED}❌ Invalid choice${NC}"
            ;;
    esac
done

# Cleanup
rm -f /tmp/db_cleanup.py
echo -e "${GREEN}✅ Cleanup completed${NC}"