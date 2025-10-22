"""
Core Bot Commands

This cog contains essential bot commands including health checks and basic utilities.
"""

import logging
import platform
import sys
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

class CoreCog(commands.Cog):
    """Core bot functionality and health checks."""
    
    def __init__(self, bot):
        """Initialize the Core cog."""
        self.bot = bot
        self.logger = logging.getLogger('cogs.core')
        self.start_time = datetime.utcnow()
        
        self.logger.info("[core.__init__] Core cog initialized")
    
    @app_commands.command(name="status", description="Check bot and database health status")
    async def status(self, interaction: discord.Interaction):
        """
        Health check command for Docker and admin monitoring.
        Returns comprehensive bot and server statistics.
        """
        try:
            self.logger.info(f"[core.status] Status check requested by {interaction.user.id}")
            
            # Test database connections
            db_status = {'postgresql': False, 'redis': False, 'redis_stats': False}
            if self.bot.db_manager:
                db_status = await self.bot.db_manager.test_connections()
            
            # Calculate uptime
            uptime = datetime.utcnow() - self.start_time
            uptime_str = f"{uptime.days}d {uptime.seconds//3600}h {(uptime.seconds//60)%60}m {uptime.seconds%60}s"
            
            # Get system information
            import psutil
            import discord as discord_lib
            
            # Calculate member count across all guilds
            total_members = sum(guild.member_count for guild in self.bot.guilds)
            total_channels = sum(len(guild.channels) for guild in self.bot.guilds)
            
            # Memory and CPU usage
            process = psutil.Process()
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            memory_percent = process.memory_percent()
            cpu_percent = psutil.cpu_percent()
            
            # Create status embed
            embed = discord.Embed(
                title="🤖 Agora Bot Status",
                description="Current bot and server statistics",
                color=0x00ff00 if all(db_status.values()) else 0xff9900,
                timestamp=datetime.utcnow()
            )
            
            # Bot Info
            bot_status = "🟢 Online" if not self.bot.is_closed() else "🔴 Offline"
            embed.add_field(
                name="🤖 Bot Info",
                value=f"**Status:** {bot_status}\n"
                      f"**Uptime:** {uptime_str}\n"
                      f"**Discord.py:** {discord_lib.__version__}",
                inline=True
            )
            
            # Server Info
            embed.add_field(
                name="🌐 Server Info",
                value=f"**Guilds:** {len(self.bot.guilds)}\n"
                      f"**Total Members:** {total_members:,}\n"
                      f"**Channels:** {total_channels}",
                inline=True
            )
            
            # System Resources
            embed.add_field(
                name="💻 System Resources",
                value=f"**CPU Usage:** {cpu_percent:.1f}%\n"
                      f"**Memory:** {memory_percent:.1f}% ({memory_mb:.0f} MB)",
                inline=True
            )
            
            # Database Stats
            embed.add_field(
                name="🗄️ Database Stats",
                value=f"**Events:** 3\n"  # Placeholder - could be dynamic
                      f"**Announcements:** 7\n"  # Placeholder - could be dynamic
                      f"**Users:** 1",  # Placeholder - could be dynamic
                inline=True
            )
            
            # Connections
            pg_status = "🟢 Connected" if db_status.get('postgresql') else "🔴 Disconnected"
            redis_status = "🟢 Connected" if db_status.get('redis') else "🔴 Disconnected"
            
            embed.add_field(
                name="🔌 Connections",
                value=f"**Database:** {pg_status}\n"
                      f"**Health Check:** Port 8080\n"
                      f"**Latency:** {round(self.bot.latency * 1000)}ms",
                inline=True
            )
            
            # Footer with requester
            embed.set_footer(text=f"Requested by {interaction.user.display_name}")
            
            await interaction.response.send_message(embed=embed)
            self.logger.info(f"[core.status] Status response sent to {interaction.user.id}")
            
            # Log the status check result
            status_msg = "OK" if all(db_status.values()) else "DEGRADED"
            self.logger.info(f"[core.status] Status: {status_msg}, PostgreSQL: {db_status.get('postgresql')}, Redis: {db_status.get('redis')}")
            
        except Exception as e:
            self.logger.error(f"[core.status] Error in status command: {e}", exc_info=True)
            error_embed = discord.Embed(
                title="❌ Status Check Failed",
                description=f"An error occurred while checking status: {str(e)}",
                color=0xff0000,
                timestamp=datetime.utcnow()
            )
            
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(embed=error_embed, ephemeral=True)
                else:
                    await interaction.followup.send(embed=error_embed, ephemeral=True)
            except Exception as send_error:
                self.logger.error(f"[core.status] Failed to send error message: {send_error}")
    
    @app_commands.command(name="info", description="Get bot information and statistics")
    async def info(self, interaction: discord.Interaction):
        """Display bot information and basic statistics."""
        try:
            self.logger.info(f"[core.info] Info requested by {interaction.user.id}")
            
            # Calculate uptime
            uptime = datetime.utcnow() - self.start_time
            uptime_str = f"{uptime.days}d {uptime.seconds//3600}h {(uptime.seconds//60)%60}m"
            
            embed = discord.Embed(
                title="🎯 Agora Discord Bot",
                description="Multi-functional Discord bot for community management",
                color=0x5865f2,
                timestamp=datetime.utcnow()
            )
            
            embed.add_field(
                name="Version",
                value="1.0.0",
                inline=True
            )
            
            embed.add_field(
                name="Uptime",
                value=uptime_str,
                inline=True
            )
            
            embed.add_field(
                name="Servers",
                value=str(len(self.bot.guilds)),
                inline=True
            )
            
            embed.add_field(
                name="Features",
                value="• Channel & Emoji Proposals\n• Activity Tracking\n• User Reporting\n• Admin Management",
                inline=False
            )
            
            embed.add_field(
                name="Technology",
                value="Python • discord.py • PostgreSQL • Redis",
                inline=False
            )
            
            embed.set_footer(text="Use /status for health information")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            self.logger.error(f"[core.info] Error in info command: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while retrieving bot information.",
                ephemeral=True
            )
    
    @commands.Cog.listener()
    async def on_ready(self):
        """Called when the cog is ready."""
        self.logger.info("[core.on_ready] Core cog is ready")
    
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Handle errors in app commands."""
        self.logger.error(f"[core.cog_app_command_error] Command error: {error}", exc_info=True)
        
        error_message = "An unexpected error occurred. Please try again later."
        
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ {error_message}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ {error_message}", ephemeral=True)
        except Exception as e:
            self.logger.error(f"[core.cog_app_command_error] Failed to send error message: {e}")

async def setup(bot):
    """Setup function for loading the cog."""
    await bot.add_cog(CoreCog(bot))
    logging.getLogger('cogs.core').info("[core.setup] Core cog loaded successfully")