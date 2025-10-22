# Agora Discord Bot

A multi-functional Discord bot for community management featuring channel/emoji proposals, user reporting, and activity tracking with dual-database architecture.

## Features

- **Channel & Emoji Proposals**: Users can propose new channels and emojis through interactive slash commands
- **Admin Approval System**: Interactive approval workflow with LLM-assisted name suggestions and modal overrides
- **Activity Tracking**: Real-time channel activity scoring and ranking system
- **User Reporting**: Confidential reporting system for community issues
- **Channel Lifecycle Management**: Automated promotion of active channels from proposed to permanent categories

## Architecture

- **Discord.py v2.x** with Cogs-based modular structure
- **Dual Database**: PostgreSQL for persistent data, Redis for high-frequency statistics
- **Docker Containerized** with health monitoring and graceful shutdown
- **LLM Integration** via Open Web UI API with function calling for structured responses
- **Event-driven Statistics** with real-time message tracking

## Prerequisites

### Discord Application Setup

1. Create a Discord Application at https://discord.com/developers/applications
2. Create a bot user and obtain the bot token
3. Configure the following **Bot Permissions**:
   - `Send Messages`
   - `Use Slash Commands`
   - `Manage Channels` (for creating/moving channels)
   - `Manage Emojis and Stickers` (for creating custom emojis)
   - `Read Message History` (for statistics recalculation)
   - `Embed Links` (for rich embeds)
   - `Attach Files` (for handling file uploads)
   - `Manage Messages` (for editing persistent embeds)

4. Configure **Privileged Gateway Intents**:
   - `Message Content Intent` (for message tracking)
   - `Server Members Intent` (for user validation)

5. **OAuth2 Scopes**:
   - `bot`
   - `applications.commands`

### Infrastructure Requirements

- **PostgreSQL Database** (existing instance on `dbnet` Docker network)
- **Redis Instance** (for statistics caching)
- **Docker & Docker Compose**
- **Open Web UI Instance** (for LLM integration)

### Discord Server Setup

Create the following channels and categories in your Discord server:

#### Required Categories
- **Proposed Channels Category** (for new channel proposals)
- **Permanent Channels Category** (for promoted channels)

#### Required Channels
- **Admin Notification Channel** (for all bot notifications)
- **Queue Management Channel** (for interactive approval embeds)
- **Public Announcement Channel** (for new/promoted channel announcements)
- **Proposed Activity Report Channel** (for proposed channel statistics)
- **Permanent Activity Report Channel** (for permanent channel statistics)

## Installation & Deployment

### 1. Clone the Repository

```bash
git clone <repository-url>
cd agora
```

### 2. Environment Configuration

Create a `.env` file with the following variables:

```env
# Logging
LOG_LEVEL=INFO

# Discord Channel IDs (obtain from Discord Developer Mode)
ADMIN_NOTIFICATION_CHANNEL_ID=123456789012345678
QUEUE_CHANNEL_ID=123456789012345678
PUBLIC_ANNOUNCEMENT_CHANNEL_ID=123456789012345678
PROPOSED_CHANNEL_CATEGORY_ID=123456789012345678
PERMANENT_CHANNEL_CATEGORY_ID=123456789012345678
PROPOSED_ACTIVITY_REPORT_CHANNEL_ID=123456789012345678
PERMANENT_ACTIVITY_REPORT_CHANNEL_ID=123456789012345678

# Bot Configuration
STATS_REFRESH_INTERVAL_MINUTES=30
MAX_PROPOSED_CHANNELS=10
STATS_RECALCULATION_MONTH_LIMIT=6

# External Services
OPEN_WEB_UI_URL=http://your-llm-api-endpoint
OPEN_WEB_UI_MODEL=llama3.2

# Database Configuration
DB_HOST=postgres
DB_PORT=5432
DB_NAME=discord
DB_USER=discord
REDIS_HOST=redis
```

### 3. Secrets Configuration

The bot uses Docker secrets for secure credential management. Create a `secrets/` directory with the following files:

```bash
mkdir secrets
echo "your_discord_bot_token" > secrets/discord_bot_token.txt
echo "your_db_password" > secrets/db_password.txt
echo "your_open_webui_token" > secrets/open_webui_token.txt
```

**Note**: These files are referenced as Docker secrets in `docker-compose.yml` and will be mounted at `/run/secrets/` inside the container.

### 4. LLM Prompt Templates

Create prompt templates in the `prompts/` directory:

```bash
mkdir prompts
```

Create `prompts/channel_name_suggestion.txt`:
```
Based on the following channel idea, suggest a concise, descriptive channel name that follows Discord naming conventions (lowercase, hyphens for spaces, no special characters):

Channel Idea: {idea_text}

Provide only the suggested channel name, nothing else.
```

### 5. Announcement Templates

Create markdown templates in the `templates/` directory:

```bash
mkdir templates
```

Create `templates/new_channel_announcement.md`:
```markdown
🎉 **New Channel Created!**

**{channel_name}** has been added to the server!

💡 *Proposed by:* {user_mention}
📝 *Original idea:* {original_text}
```

Create `templates/promoted_channel_announcement.md`:
```markdown
⭐ **Channel Promoted!**

**{channel_name}** has been promoted to permanent status due to high activity!

🔥 Keep the conversations going!
```

### 6. Docker Deployment

Ensure your PostgreSQL and Redis services are running on the `dbnet` Docker network, then deploy:

```bash
# Build and start the bot
docker-compose up -d

# View logs
docker-compose logs -f agora-bot

# Check health status
docker-compose exec agora-bot python -c "from bot import status_check; status_check()"
```

### 7. Database Initialization

The bot will automatically create the required database tables on first startup using SQLAlchemy.

Required PostgreSQL tables:
- `proposals` - Channel and emoji proposals
- `reports` - User reports
- `tracked_channels` - Channel activity tracking
- `persistent_embeds` - Bot message state management

## Usage

### User Commands

- `/propose_channel <idea_text>` - Submit a channel proposal
- `/propose_emoji <name> <image_file>` - Submit an emoji proposal with image
- `/report <description> [image_file]` - Submit a confidential report

### Admin Commands

- `/approve_proposal <proposal_id>` - Interactive approval with LLM suggestions
- `/reject_proposal <proposal_id> <reason>` - Reject a proposal with reason
- `/view_report <report_id>` - Mark report as investigating
- `/resolve_report <report_id> <explanation>` - Close a report
- `/promote_channel <channel>` - Move channel to permanent category
- `/recalculate_stats <months_limit>` - Rebuild activity statistics
- `/refresh_channels` - Rescan channel categories
- `/status` - Check bot and database health

## File Validation

### Emoji Requirements
- **Formats**: PNG, JPG, JPEG, GIF (animated supported)
- **Size**: Maximum 256 KB
- **Dimensions**: 32x32px to 256x256px (square ratio required)
- **Name**: 2-32 characters, alphanumeric and underscores only
- **Security**: Files processed in memory only, never saved to filesystem

## Activity Scoring

Channels are scored using the algorithm:
```
Score = (total_messages × 0.4) + (recent_7day_messages × 0.6)
```

Statistics refresh every `STATS_REFRESH_INTERVAL_MINUTES` and are displayed in activity report channels.

## Monitoring & Health

- **Health Checks**: `/status` command provides database connectivity status
- **Docker Health**: Container includes built-in health monitoring
- **Logging**: Console-based logging with `[module.command]` pattern for traceability via Docker logs
- **Graceful Shutdown**: Bot notifies admins during planned restarts

## Security Features

- **Input Validation**: Comprehensive validation for all user inputs
- **File Security**: Uploaded files never executed or saved to disk
- **Exception Safety**: All errors caught and logged without crashing
- **Secrets Management**: Sensitive tokens stored separately from configuration

## Development

### Project Structure
```
agora/
├── main.py                 # Bot entry point
├── bot.py                  # Main bot class and event listeners
├── cogs/                   # Command modules
│   ├── proposals.py        # User proposal commands
│   ├── admin_queue.py      # Admin approval workflow
│   ├── admin_reports.py    # Report management
│   ├── admin_manage.py     # Channel management
│   ├── user_reports.py     # User reporting
│   ├── core.py            # Health checks
│   └── tasks.py           # Background tasks
├── database/              # Database layer
│   ├── db_models.py       # SQLAlchemy models
│   ├── db_session.py      # Connection management
│   └── redis_client.py    # Redis operations
├── templates/             # Announcement templates
├── prompts/              # LLM interaction templates
└── requirements.txt      # Python dependencies
```

### Contributing

1. Follow the established logging pattern: `logger.info(f"[{module}.{command}] Message")`
2. All exceptions must be caught and logged without crashing
3. No hardcoded values - use environment variables for all configuration
4. Use interactive buttons/modals for admin commands
5. Process uploaded files in memory only

## Troubleshooting

### Common Issues

**Bot not responding to commands:**
- Verify bot permissions and intents are correctly configured
- Check that slash commands are registered with Discord
- Ensure bot has access to the channels it needs to operate in

**Database connection errors:**
- Verify PostgreSQL is running and accessible on the `dbnet` network
- Check database credentials in secrets files
- Ensure database user has necessary permissions to create tables

**LLM integration not working:**
- Verify Open Web UI endpoint is accessible
- Check API token in secrets
- Review prompt templates in `/prompts/` directory
- Ensure model supports function/instruction calling for structured responses

**Activity statistics not updating:**
- Check Redis connection and accessibility
- Verify message content intent is enabled
- Review background task logs for errors

For additional support, check the application logs using `docker-compose logs agora-bot`.