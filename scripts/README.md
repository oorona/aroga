# Database Cleanup Tool

Simple shell script to clean Agora bot database using Docker.

## Quick Start

1. **Clean up old Docker images** (if needed):
   ```bash
   docker rmi agora-agora-bot:latest && docker image prune -a
   ```

2. **Build/rebuild the image**:
   ```bash
   docker-compose build
   ```

3. **Clean database**:
   ```bash
   ./scripts/clean_db.sh
   ```

## What it does

1. **Lists all tables** with record counts
2. **Shows sample records** from any table (first 5 records)
3. **Deletes specific table** data with confirmation
4. **Deletes all data** (PostgreSQL + Redis) with confirmation

## Example Session

```
🗃️  Agora Database Cleanup Tool
================================

🔧 Options:
1. List all tables
2. Show records from a table
3. Delete records from a table
4. Delete ALL data (PostgreSQL + Redis)
5. Exit

Enter choice (1-5): 1

📊 Loading database info...
📋 Database Tables:
  1. proposals (3 records)
  2. reports (1 record) 
  3. tracked_channels (2 records)
  4. persistent_embeds (4 records)

📡 Redis: 15 keys

Enter choice (1-5): 2

Enter table number or name: 1

📋 Loading records from 'proposals'...

📋 Sample records from 'proposals':
============================================================

Record #1:
  proposal_id: 1
  user_id: 123456789012345678
  proposal_type: channel
  status: pending
  original_text: Discussion channel for React development
  llm_suggestion: ⚛️・react-dev
  final_name: NULL
  created_at: 2024-10-20 15:30:45.123456+00:00

... and 2 more records
```

## Requirements

- Docker and Docker Compose
- Image name: `agora-bot:latest` (built by docker-compose)
- `.env` file with database config
- `dbnet` Docker network

## Docker Commands

**Remove old images:**
```bash
docker rmi agora-agora-bot:latest && docker image prune -a
```

**Build image:**
```bash
docker-compose build
```

**Check images:**
```bash
docker images | grep agora
```