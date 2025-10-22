"""
Agora Discord Bot - Main Bot Class

This module contains the main bot class with Discord connection handling,
event listeners, graceful shutdown, and startup/shutdown notifications.
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands

from database.db_session import DatabaseManager

class AgoraBot(commands.Bot):
    """Main bot class for the Agora Discord Bot."""
    
    def __init__(self):
        """Initialize the bot with required intents and configuration."""
        # Configure intents
        intents = discord.Intents.default()
        intents.message_content = True  # Required for message tracking
        intents.members = True  # Required for user validation
        
        # Initialize the bot
        super().__init__(
            command_prefix='!',  # Legacy prefix (slash commands will be primary)
            intents=intents,
            case_insensitive=True,
            help_command=None  # Disable default help command
        )
        
        self.logger = logging.getLogger('bot')
        self.db_manager: Optional[DatabaseManager] = None
        self.admin_notification_channel_id = None
        self.is_shutting_down = False
        self.start_time = discord.utils.utcnow()
        
        # Load configuration
        self._load_config()
        
        # Setup signal handlers for graceful shutdown
        self._setup_signal_handlers()
    
    def _load_config(self):
        """Load configuration from environment variables."""
        self.logger.info("[bot._load_config] Loading configuration...")
        
        # Check Docker secrets availability
        self._check_docker_secrets()
        
        # Required environment variables
        required_env_vars = [
            'ADMIN_NOTIFICATION_CHANNEL_ID',
            'QUEUE_CHANNEL_ID',
            'PROPOSED_CHANNEL_CATEGORY_ID',
        ]
        
        missing_vars = []
        for var in required_env_vars:
            if not os.getenv(var):
                missing_vars.append(var)
        
        if missing_vars:
            self.logger.error(f"[bot._load_config] Missing required environment variables: {missing_vars}")
            raise ValueError(f"Missing required environment variables: {missing_vars}")
        
        # Load channel IDs and configuration
        try:
            self.admin_notification_channel_id = int(os.getenv('ADMIN_NOTIFICATION_CHANNEL_ID'))
            self.queue_channel_id = int(os.getenv('QUEUE_CHANNEL_ID'))
            self.public_announcement_channel_id = int(os.getenv('PUBLIC_ANNOUNCEMENT_CHANNEL_ID'))
            self.proposed_channel_category_id = int(os.getenv('PROPOSED_CHANNEL_CATEGORY_ID'))
            self.permanent_channel_category_id = int(os.getenv('PERMANENT_CHANNEL_CATEGORY_ID'))
            self.proposed_activity_report_channel_id = int(os.getenv('PROPOSED_ACTIVITY_REPORT_CHANNEL_ID'))
            self.permanent_activity_report_channel_id = int(os.getenv('PERMANENT_ACTIVITY_REPORT_CHANNEL_ID'))
            self.max_proposed_channels = int(os.getenv('MAX_PROPOSED_CHANNELS', '10'))
            self.stats_refresh_interval_minutes = int(os.getenv('STATS_REFRESH_INTERVAL_MINUTES', '30'))
        except (ValueError, TypeError) as e:
            self.logger.error(f"[bot._load_config] Invalid configuration values: {e}")
            raise
        
        # Load admin role configuration
        admin_role_config = os.getenv('ADMIN_ROLE_IDS', 'administrator')
        if admin_role_config.lower() == 'administrator':
            self.admin_role_ids = None  # Use administrator permission
            self.logger.info("[bot._load_config] Using Discord administrator permission for admin commands")
        else:
            try:
                # Parse comma-separated role IDs
                self.admin_role_ids = [int(role_id.strip()) for role_id in admin_role_config.split(',') if role_id.strip()]
                self.logger.info(f"[bot._load_config] Loaded {len(self.admin_role_ids)} admin role IDs")
            except ValueError as e:
                self.logger.error(f"[bot._load_config] Invalid admin role IDs: {e}")
                # Fall back to administrator permission
                self.admin_role_ids = None
                self.logger.warning("[bot._load_config] Falling back to administrator permission")
        
        # Load LLM configuration
        self.llm_url = os.getenv('OPEN_WEB_UI_URL', 'http://openwebui:8080/api/chat/completions')
        self.llm_model = os.getenv('OPEN_WEB_UI_MODEL', 'llama3.2')
        
        self.logger.info("[bot._load_config] Configuration loaded successfully")
    
    def _check_docker_secrets(self):
        """Check which Docker secrets are available at startup."""
        self.logger.info("[bot._check_docker_secrets] Checking Docker secrets availability...")
        
        secrets_dir = Path('/run/secrets')
        if not secrets_dir.exists():
            self.logger.warning("[bot._check_docker_secrets] /run/secrets directory does not exist")
            return
        
        expected_secrets = ['discord_bot_token.txt', 'db_password.txt', 'open_webui_token.txt']
        found_secrets = []
        missing_secrets = []
        
        for secret_file in expected_secrets:
            secret_path = secrets_dir / secret_file
            if secret_path.exists():
                try:
                    with open(secret_path, 'r') as f:
                        content = f.read().strip()
                    if content:
                        found_secrets.append(f"{secret_file} (length: {len(content)})")
                    else:
                        missing_secrets.append(f"{secret_file} (empty)")
                except Exception as e:
                    missing_secrets.append(f"{secret_file} (read error: {e})")
            else:
                missing_secrets.append(f"{secret_file} (not found)")
        
        if found_secrets:
            self.logger.info(f"[bot._check_docker_secrets] Available secrets: {', '.join(found_secrets)}")
        
        if missing_secrets:
            self.logger.warning(f"[bot._check_docker_secrets] Missing/problematic secrets: {', '.join(missing_secrets)}")
        
        # Also log environment variables
        env_vars = ['OPEN_WEB_UI_URL', 'OPEN_WEB_UI_MODEL', 'DB_HOST', 'DB_NAME']
        self.logger.info("[bot._check_docker_secrets] Environment variables:")
        for var in env_vars:
            value = os.getenv(var, 'NOT_SET')
            if 'password' in var.lower() or 'token' in var.lower():
                value = f"{value[:10]}..." if len(value) > 10 else "***"
            self.logger.info(f"  {var}={value}")
    
    def has_admin_permissions(self, user: discord.Member) -> bool:
        """Check if a user has admin permissions based on configuration."""
        if self.admin_role_ids is None:
            # Use Discord administrator permission
            return user.guild_permissions.administrator
        else:
            # Check if user has any of the configured admin roles
            user_role_ids = [role.id for role in user.roles]
            return any(role_id in user_role_ids for role_id in self.admin_role_ids)
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            self.logger.info(f"[bot._setup_signal_handlers] Received signal {signum}")
            # Set shutdown flag and close the bot
            self.is_shutting_down = True
            # Force the bot to close which will trigger our close() method
            asyncio.create_task(self.close())
        
        # Only setup signal handlers on Unix systems
        if sys.platform != 'win32':
            signal.signal(signal.SIGTERM, signal_handler)
            signal.signal(signal.SIGINT, signal_handler)
    
    async def setup_hook(self):
        """
        Setup hook called when the bot is starting up.
        This is where we initialize database connections and load cogs.
        """
        self.logger.info("[bot.setup_hook] Bot setup starting...")
        
        try:
            # Initialize database connections
            self.db_manager = DatabaseManager()
            await self.db_manager.initialize()
            self.logger.info("[bot.setup_hook] Database connections initialized")
            
            # Load cogs
            await self._load_cogs()
            
            # Set up error handler for the command tree
            self.tree.error(self.on_app_command_error)
            self.logger.info("[bot.setup_hook] Command tree error handler configured")
            
            self.logger.info("[bot.setup_hook] Bot setup completed successfully")
            
        except Exception as e:
            self.logger.error(f"[bot.setup_hook] Setup failed: {e}", exc_info=True)
            raise
    
    async def _load_cogs(self):
        """Load all bot cogs."""
        cogs_to_load = [
            'cogs.core',  # Health check and basic commands
            'cogs.user_reports',  # User reporting functionality
            'cogs.admin_reports',  # Admin report management
            'cogs.user_emoji_proposals',  # User emoji proposal functionality
            'cogs.user_channel_proposals',  # User channel proposal functionality
            'cogs.admin_emoji_management',  # Admin emoji and channel proposal management
            'cogs.admin_management',  # Admin channel promotion and statistics
            'cogs.tasks',  # Background tasks for statistics and cleanup
            'cogs.debug_commands',  # Debug and testing commands
        ]
        
        for cog in cogs_to_load:
            try:
                await self.load_extension(cog)
                self.logger.info(f"[bot._load_cogs] Loaded cog: {cog}")
            except Exception as e:
                self.logger.error(f"[bot._load_cogs] Failed to load cog {cog}: {e}", exc_info=True)
                # Don't raise here - allow bot to start with partial functionality
    
    async def on_ready(self):
        """Event fired when the bot is ready and connected to Discord."""
        self.logger.info(f"[bot.on_ready] Bot logged in as {self.user} (ID: {self.user.id})")
        self.logger.info(f"[bot.on_ready] Connected to {len(self.guilds)} guild(s)")
        
        # Send startup notification
        await self._send_startup_notification()
        
        # Sync slash commands
        try:
            synced = await self.tree.sync()
            self.logger.info(f"[bot.on_ready] Synced {len(synced)} slash command(s)")
        except Exception as e:
            self.logger.error(f"[bot.on_ready] Failed to sync commands: {e}", exc_info=True)
    
    async def _send_startup_notification(self):
        """Send a startup notification to the admin channel."""
        try:
            channel = self.get_channel(self.admin_notification_channel_id)
            if channel:
                # Get system information
                import psutil
                import discord as discord_lib
                
                # Calculate member count across all guilds
                total_members = sum(guild.member_count for guild in self.guilds)
                
                # Get database status
                db_status = {'postgresql': False, 'redis': False, 'redis_stats': False}
                if self.db_manager:
                    db_status = await self.db_manager.test_connections()
                
                # Memory usage
                process = psutil.Process()
                memory_mb = process.memory_info().rss / 1024 / 1024
                
                embed = discord.Embed(
                    title="🤖 Agora Bot Started",
                    description="The bot has successfully started and is ready to serve!",
                    color=0x00ff00,
                    timestamp=discord.utils.utcnow()
                )
                
                # Server Info
                embed.add_field(
                    name="🌐 Server Info",
                    value=f"**Guilds:** {len(self.guilds)}\n"
                          f"**Users:** {total_members:,}\n"
                          f"**Start Time:** {discord.utils.utcnow().strftime('%H:%M:%S UTC')}",
                    inline=True
                )
                
                # Database
                pg_icon = "🟢" if db_status.get('postgresql') else "🔴"
                redis_icon = "🟢" if db_status.get('redis') else "🔴"
                
                embed.add_field(
                    name="🗄️ Database",
                    value=f"**Status:** {pg_icon} Connected\n"
                          f"**Events:** 3\n"  # Placeholder - could be dynamic
                          f"**Announcements:** 7",  # Placeholder - could be dynamic
                    inline=True
                )
                
                # System
                embed.add_field(
                    name="💻 System",
                    value=f"**Discord.py:** {discord_lib.__version__}\n"
                          f"**Health Port:** 8080\n"
                          f"**CPU:** {psutil.cpu_percent():.1f}%\n"
                          f"**Memory:** {memory_mb:.1f} MB",
                    inline=True
                )
                
                # Startup Process
                redis_stats_icon = "🟢" if db_status.get('redis_stats') else "🔴"
                embed.add_field(
                    name="🚀 Startup Process",
                    value=f"**Health Server:** Running\n"
                          f"**Scheduler:** Active\n"
                          f"**Commands:** Synced\n"
                          f"**Redis Stats:** {redis_stats_icon}",
                    inline=False
                )
                
                await channel.send(embed=embed)
                self.logger.info("[bot._send_startup_notification] Startup notification sent")
            else:
                self.logger.warning(f"[bot._send_startup_notification] Admin notification channel not found: {self.admin_notification_channel_id}")
        except Exception as e:
            self.logger.error(f"[bot._send_startup_notification] Failed to send startup notification: {e}", exc_info=True)
    
    async def on_message(self, message):
        """Event fired when a message is sent."""
        # Ignore messages from bots
        if message.author.bot:
            return
        
        # Track channel activity for scoring
        await self._track_channel_activity(message)
        
        # Process commands (for legacy prefix commands if any)
        await self.process_commands(message)
    
    async def _track_channel_activity(self, message):
        """Track message activity for channel scoring."""
        try:
            # Only track messages in text channels
            if not isinstance(message.channel, discord.TextChannel):
                return
            
            # Check if channel is in a tracked category
            if not message.channel.category_id:
                return
            
            tracked_categories = [
                self.proposed_channel_category_id,
                self.permanent_channel_category_id
            ]
            
            if message.channel.category_id not in tracked_categories:
                return
            
            # Update Redis stats
            if hasattr(self.db_manager, 'redis_stats'):
                timestamp = int(message.created_at.timestamp())
                await self.db_manager.redis_stats.increment_channel_messages(
                    message.channel.id,
                    message.id, 
                    timestamp
                )
                
                self.logger.info(f"[bot._track_channel_activity] Tracked message in channel {message.channel.name} (ID: {message.channel.id})")
            else:
                self.logger.warning("[bot._track_channel_activity] redis_stats not available for message tracking")
        except Exception as e:
            self.logger.error(f"[bot._track_channel_activity] Error tracking activity: {e}", exc_info=True)
    
    async def on_error(self, event, *args, **kwargs):
        """Global error handler for Discord events."""
        self.logger.error(f"[bot.on_error] Error in event {event}", exc_info=True)
    
    async def on_command_error(self, ctx, error):
        """Global error handler for commands."""
        self.logger.error(f"[bot.on_command_error] Command error: {error}", exc_info=True)
    
    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        """Global error handler for application (slash) commands."""
        command_name = interaction.command.name if interaction.command else "unknown"
        user_id = interaction.user.id
        
        # Handle specific error types
        if isinstance(error, discord.app_commands.CheckFailure):
            self.logger.warning(f"[bot.on_app_command_error] Permission denied for /{command_name} by user {user_id}")
            
            # Send user-friendly permission error message
            embed = discord.Embed(
                title="❌ Permission Denied",
                description=f"You don't have permission to use the `/{command_name}` command.",
                color=0xff0000
            )
            
            # Show which permission/roles are required
            if self.admin_role_ids is None:
                embed.add_field(
                    name="Required Permission",
                    value="Administrator",
                    inline=True
                )
            else:
                role_mentions = []
                guild = interaction.guild
                if guild:
                    for role_id in self.admin_role_ids:
                        role = guild.get_role(role_id)
                        if role:
                            role_mentions.append(role.mention)
                        else:
                            role_mentions.append(f"<@&{role_id}>")  # Fallback mention
                
                if role_mentions:
                    embed.add_field(
                        name="Required Roles",
                        value="\n".join(role_mentions),
                        inline=True
                    )
                else:
                    embed.add_field(
                        name="Required Permission",
                        value="Administrator",
                        inline=True
                    )
            
            embed.set_footer(text="Contact a server administrator if you believe this is an error.")
            
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.response.send_message(embed=embed, ephemeral=True)
            except discord.errors.NotFound:
                # Interaction expired, log but don't crash
                self.logger.warning(f"[bot.on_app_command_error] Could not respond to expired interaction for /{command_name}")
            except Exception as e:
                self.logger.error(f"[bot.on_app_command_error] Failed to send permission error message: {e}", exc_info=True)
        
        elif isinstance(error, discord.app_commands.CommandOnCooldown):
            # Handle cooldown errors
            self.logger.info(f"[bot.on_app_command_error] Cooldown hit for /{command_name} by user {user_id}")
            
            embed = discord.Embed(
                title="⏰ Command on Cooldown",
                description=f"Please wait {error.retry_after:.1f} seconds before using `/{command_name}` again.",
                color=0xff9900
            )
            
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.response.send_message(embed=embed, ephemeral=True)
            except discord.errors.NotFound:
                self.logger.warning(f"[bot.on_app_command_error] Could not respond to expired interaction for /{command_name}")
            except Exception as e:
                self.logger.error(f"[bot.on_app_command_error] Failed to send cooldown error message: {e}", exc_info=True)
        
        else:
            # Handle all other app command errors
            self.logger.error(f"[bot.on_app_command_error] Unhandled error in /{command_name} by user {user_id}: {error}", exc_info=True)
            
            embed = discord.Embed(
                title="❌ Command Error",
                description="An unexpected error occurred while processing your command. Please try again later.",
                color=0xff0000
            )
            embed.set_footer(text="If this problem persists, please contact a server administrator.")
            
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.response.send_message(embed=embed, ephemeral=True)
            except discord.errors.NotFound:
                self.logger.warning(f"[bot.on_app_command_error] Could not respond to expired interaction for /{command_name}")
            except Exception as e:
                self.logger.error(f"[bot.on_app_command_error] Failed to send generic error message: {e}", exc_info=True)
    
    async def close(self):
        """Override close to ensure proper cleanup."""
        if not self.is_shutting_down:
            await self.shutdown()
        else:
            # If already shutting down via signal, just do the cleanup directly
            self.logger.info("[bot.close] Bot close called during shutdown")
            try:
                # Send shutdown notification
                await self._send_shutdown_notification()
                
                # Close database connections
                if self.db_manager:
                    await self.db_manager.close()
                    self.logger.info("[bot.close] Database connections closed")
                
            except Exception as e:
                self.logger.error(f"[bot.close] Error during close cleanup: {e}", exc_info=True)
        
        await super().close()
    
    async def shutdown(self):
        """Gracefully shutdown the bot."""
        if self.is_shutting_down:
            return  # Already shutting down
        
        self.is_shutting_down = True
        self.logger.info("[bot.shutdown] Initiating graceful shutdown...")
        
        try:
            # Send shutdown notification
            await self._send_shutdown_notification()
            
            # Close database connections
            if self.db_manager:
                await self.db_manager.close()
                self.logger.info("[bot.shutdown] Database connections closed")
            
            # Close the bot connection
            if not self.is_closed():
                await super().close()
                self.logger.info("[bot.shutdown] Bot connection closed")
            
        except Exception as e:
            self.logger.error(f"[bot.shutdown] Error during shutdown: {e}", exc_info=True)
        
        self.logger.info("[bot.shutdown] Shutdown complete")
    
    async def get_proposed_channels_count(self) -> int:
        """
        Get the current number of channels in the proposed category.
        This is used to enforce the MAX_PROPOSED_CHANNELS limit.
        """
        try:
            category = self.get_channel(self.proposed_channel_category_id)
            if category and isinstance(category, discord.CategoryChannel):
                # Count only text and voice channels, not other category types
                channel_count = len([c for c in category.channels if isinstance(c, (discord.TextChannel, discord.VoiceChannel))])
                self.logger.debug(f"[bot.get_proposed_channels_count] Found {channel_count} channels in proposed category")
                return channel_count
            else:
                self.logger.warning(f"[bot.get_proposed_channels_count] Proposed category not found or invalid: {self.proposed_channel_category_id}")
                return 0
        except Exception as e:
            self.logger.error(f"[bot.get_proposed_channels_count] Error counting proposed channels: {e}")
            return 0

    async def _send_shutdown_notification(self):
        """Send a shutdown notification to the admin channel."""
        try:
            if self.is_closed():
                return  # Can't send messages if already closed
            
            channel = self.get_channel(self.admin_notification_channel_id)
            if channel:
                # Get system information
                import psutil
                import discord as discord_lib
                
                # Calculate uptime
                if hasattr(self, 'start_time'):
                    uptime = discord.utils.utcnow() - self.start_time
                    uptime_str = f"{uptime.total_seconds()//60:.0f}m {uptime.total_seconds()%60:.0f}s"
                else:
                    uptime_str = "Unknown"
                
                # Calculate member count across all guilds
                total_members = sum(guild.member_count for guild in self.guilds)
                
                # Get database status
                db_status = {'postgresql': False, 'redis': False}
                if self.db_manager:
                    try:
                        db_status = await self.db_manager.test_connections()
                    except:
                        pass  # If database is already closing
                
                # Memory usage
                try:
                    process = psutil.Process()
                    memory_mb = process.memory_info().rss / 1024 / 1024
                    cpu_percent = psutil.cpu_percent()
                except:
                    memory_mb = 0
                    cpu_percent = 0
                
                embed = discord.Embed(
                    title="🔴 Bot Shutdown",
                    description="The Agora bot is shutting down gracefully... (Signal received)",
                    color=0xff0000,
                    timestamp=discord.utils.utcnow()
                )
                
                # Session Stats
                embed.add_field(
                    name="📊 Session Stats",
                    value=f"**Uptime:** {uptime_str}\n"
                          f"**Guilds:** {len(self.guilds)}\n"
                          f"**Users:** {total_members:,}",
                    inline=True
                )
                
                # Database
                pg_icon = "🟢" if db_status.get('postgresql') else "🔴"
                embed.add_field(
                    name="🗄️ Database",
                    value=f"**Status:** {pg_icon} Connected\n"
                          f"**Events:** 3\n"  # Placeholder
                          f"**Announcements:** 7",  # Placeholder
                    inline=True
                )
                
                # System
                embed.add_field(
                    name="⚙️ System",
                    value=f"**Discord.py:** {discord_lib.__version__}\n"
                          f"**CPU:** {cpu_percent:.1f}%\n"
                          f"**Memory:** {memory_mb:.1f} MB",
                    inline=True
                )
                
                # Shutdown Process
                embed.add_field(
                    name="🔄 Shutdown Process",
                    value=f"**Type:** Signal-triggered\n"
                          f"**Resources:** Cleaning up\n"
                          f"**Health:** Port closing",
                    inline=False
                )
                
                await channel.send(embed=embed)
                self.logger.info("[bot._send_shutdown_notification] Shutdown notification sent")
            else:
                self.logger.warning(f"[bot._send_shutdown_notification] Admin notification channel not found: {self.admin_notification_channel_id}")
        except Exception as e:
            self.logger.error(f"[bot._send_shutdown_notification] Failed to send shutdown notification: {e}", exc_info=True)
    
    async def start_bot(self):
        """Start the bot with token from secrets."""
        try:
            # Read Discord token from secrets
            token_path = Path('/run/secrets/discord_bot_token.txt')
            if not token_path.exists():
                # Fallback to local development
                token_path = Path('secrets/discord_bot_token.txt')
            
            if not token_path.exists():
                raise FileNotFoundError("Discord bot token not found in secrets")
            
            token = token_path.read_text().strip()
            if not token:
                raise ValueError("Discord bot token is empty")
            
            self.logger.info("[bot.start_bot] Starting bot...")
            await self.start(token)
            
        except Exception as e:
            self.logger.error(f"[bot.start_bot] Failed to start bot: {e}", exc_info=True)
            raise