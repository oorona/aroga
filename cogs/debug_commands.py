"""
Debug Commands Cog - Testing and debugging utilities

This cog provides admin commands for testing and debugging the activity scoring system.
"""

import logging
import os
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands


class DebugCommandsCog(commands.Cog):
    """Cog for debug and testing commands."""
    
    def __init__(self, bot):
        """Initialize the debug commands cog."""
        self.bot = bot
        self.logger = logging.getLogger('debug_commands')
    
    @app_commands.command(name="debug_activity", description="Debug activity scoring system")
    @app_commands.default_permissions(administrator=True)
    async def debug_activity(self, interaction: discord.Interaction):
        """Debug the activity scoring system."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            if not hasattr(self.bot.db_manager, 'redis_stats'):
                await interaction.followup.send("❌ Redis stats not available")
                return
            
            # Get proposed category
            proposed_category = self.bot.get_channel(self.bot.proposed_channel_category_id)
            if not proposed_category:
                await interaction.followup.send("❌ Proposed category not found")
                return
            
            # Get report channel IDs to exclude
            proposed_report_channel_id = int(os.getenv('PROPOSED_ACTIVITY_REPORT_CHANNEL_ID', '0'))
            permanent_report_channel_id = int(os.getenv('PERMANENT_ACTIVITY_REPORT_CHANNEL_ID', '0'))
            
            debug_info = []
            debug_info.append(f"**Debug Activity Scoring System**")
            debug_info.append(f"Proposed Category: {proposed_category.name} (ID: {proposed_category.id})")
            debug_info.append(f"Total text channels: {len(proposed_category.text_channels)}")
            debug_info.append(f"Excluding report channels: {proposed_report_channel_id}, {permanent_report_channel_id}")
            debug_info.append("")
            
            for channel in proposed_category.text_channels:
                if channel.id in [proposed_report_channel_id, permanent_report_channel_id]:
                    debug_info.append(f"🚫 **{channel.name}** (ID: {channel.id}) - EXCLUDED (report channel)")
                    continue
                
                # Get stats
                stats = await self.bot.db_manager.redis_stats.get_channel_stats(channel.id)
                recent_count = await self.bot.db_manager.redis_stats.get_recent_message_count(channel.id, 7)
                score = await self.bot.db_manager.redis_stats.calculate_channel_score(channel.id)
                
                debug_info.append(f"📊 **{channel.name}** (ID: {channel.id})")
                debug_info.append(f"   Total messages: {stats['total_messages']}")
                debug_info.append(f"   Recent (7d): {recent_count}")
                debug_info.append(f"   Score: {score:.2f}")
                debug_info.append("")
            
            # Split message if too long
            message_content = "\n".join(debug_info)
            if len(message_content) > 2000:
                # Send in chunks
                chunks = []
                current_chunk = ""
                for line in debug_info:
                    if len(current_chunk + line + "\n") > 2000:
                        if current_chunk:
                            chunks.append(current_chunk)
                        current_chunk = line + "\n"
                    else:
                        current_chunk += line + "\n"
                if current_chunk:
                    chunks.append(current_chunk)
                
                await interaction.followup.send(chunks[0])
                for chunk in chunks[1:]:
                    await interaction.followup.send(chunk)
            else:
                await interaction.followup.send(message_content)
        
        except Exception as e:
            self.logger.error(f"[debug_commands.debug_activity] Error: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error debugging activity: {e}")
    
    @app_commands.command(name="test_message_tracking", description="Add test message data to Redis")
    @app_commands.default_permissions(administrator=True)
    async def test_message_tracking(self, interaction: discord.Interaction, channel: discord.TextChannel, message_count: int = 5):
        """Add test message data to Redis for a channel."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            if not hasattr(self.bot.db_manager, 'redis_stats'):
                await interaction.followup.send("❌ Redis stats not available")
                return
            
            if message_count > 50:
                await interaction.followup.send("❌ Maximum 50 test messages allowed")
                return
            
            # Add test message data
            base_timestamp = int(datetime.now().timestamp())
            for i in range(message_count):
                fake_message_id = 1000000000000000000 + i  # Fake message ID
                timestamp = base_timestamp - (i * 3600)  # Spread over hours
                
                await self.bot.db_manager.redis_stats.increment_channel_messages(
                    channel.id, fake_message_id, timestamp
                )
            
            # Get updated stats
            stats = await self.bot.db_manager.redis_stats.get_channel_stats(channel.id)
            recent_count = await self.bot.db_manager.redis_stats.get_recent_message_count(channel.id, 7)
            score = await self.bot.db_manager.redis_stats.calculate_channel_score(channel.id)
            
            await interaction.followup.send(
                f"✅ Added {message_count} test messages to {channel.mention}\n"
                f"📊 Total messages: {stats['total_messages']}\n"
                f"📊 Recent (7d): {recent_count}\n"
                f"📊 Score: {score:.2f}"
            )
        
        except Exception as e:
            self.logger.error(f"[debug_commands.test_message_tracking] Error: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error adding test data: {e}")
    
    @app_commands.command(name="backfill_stats", description="Backfill message statistics from recent history")
    @app_commands.default_permissions(administrator=True)
    async def backfill_stats(self, interaction: discord.Interaction, channel: discord.TextChannel = None, days: int = 7):
        """Backfill message statistics from recent channel history."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            if not hasattr(self.bot.db_manager, 'redis_stats'):
                await interaction.followup.send("❌ Redis stats not available")
                return
            
            if days > 30:
                await interaction.followup.send("❌ Maximum 30 days allowed for backfill")
                return
            
            # If no channel specified, backfill all tracked channels
            channels_to_process = []
            
            if channel:
                channels_to_process = [channel]
            else:
                # Get all channels in tracked categories
                proposed_category = self.bot.get_channel(self.bot.proposed_channel_category_id)
                permanent_category = self.bot.get_channel(self.bot.permanent_channel_category_id)
                
                if proposed_category:
                    channels_to_process.extend(proposed_category.text_channels)
                if permanent_category:
                    channels_to_process.extend(permanent_category.text_channels)
                
                # Exclude report channels
                proposed_report_channel_id = int(os.getenv('PROPOSED_ACTIVITY_REPORT_CHANNEL_ID', '0'))
                permanent_report_channel_id = int(os.getenv('PERMANENT_ACTIVITY_REPORT_CHANNEL_ID', '0'))
                
                channels_to_process = [ch for ch in channels_to_process 
                                     if ch.id not in [proposed_report_channel_id, permanent_report_channel_id]]
            
            if not channels_to_process:
                await interaction.followup.send("❌ No channels to process")
                return
            
            await interaction.followup.send(f"🔄 Starting backfill for {len(channels_to_process)} channel(s) over {days} days...")
            
            total_messages = 0
            
            for ch in channels_to_process:
                try:
                    self.logger.info(f"[debug_commands.backfill_stats] Processing channel: {ch.name}")
                    
                    # Get message history
                    cutoff_date = datetime.now() - timedelta(days=days)
                    
                    message_count = 0
                    async for message in ch.history(limit=None, after=cutoff_date):
                        if not message.author.bot:  # Skip bot messages
                            timestamp = int(message.created_at.timestamp())
                            await self.bot.db_manager.redis_stats.increment_channel_messages(
                                ch.id, message.id, timestamp
                            )
                            message_count += 1
                    
                    total_messages += message_count
                    self.logger.info(f"[debug_commands.backfill_stats] Processed {message_count} messages from {ch.name}")
                    
                except Exception as e:
                    self.logger.error(f"[debug_commands.backfill_stats] Error processing {ch.name}: {e}")
            
            await interaction.followup.send(f"✅ Backfill complete! Processed {total_messages} historical messages.")
            
            # Trigger activity report update
            tasks_cog = self.bot.get_cog('BackgroundTasksCog')
            if tasks_cog:
                await tasks_cog._update_proposed_activity_report()
                await tasks_cog._update_permanent_activity_report()
                await interaction.followup.send("📊 Activity reports updated with new data.")
        
        except Exception as e:
            self.logger.error(f"[debug_commands.backfill_stats] Error: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error during backfill: {e}")

    @app_commands.command(name="inspect_redis", description="Inspect Redis data for a channel")
    @app_commands.default_permissions(administrator=True)
    async def inspect_redis(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Inspect Redis data for a specific channel."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            if not hasattr(self.bot.db_manager, 'redis_stats'):
                await interaction.followup.send("❌ Redis stats not available")
                return
            
            redis_client = self.bot.db_manager.redis_client
            channel_id = channel.id
            
            # Get raw Redis data
            hash_key = f"channel_stats:{channel_id}"
            zset_key = f"channel_activity:{channel_id}"
            
            # Get hash data
            hash_data = await redis_client.hgetall(hash_key)
            
            # Get sorted set size and recent entries
            zset_size = await redis_client.zcard(zset_key)
            
            # Get recent entries (last 10)
            recent_entries = await redis_client.zrevrange(zset_key, 0, 9, withscores=True)
            
            # Get stats using the manager
            stats = await self.bot.db_manager.redis_stats.get_channel_stats(channel_id)
            recent_count = await self.bot.db_manager.redis_stats.get_recent_message_count(channel_id, 7)
            score = await self.bot.db_manager.redis_stats.calculate_channel_score(channel_id)
            
            info = [
                f"**Redis Data Inspection for {channel.name}**",
                f"Channel ID: {channel_id}",
                "",
                f"**Raw Redis Hash ({hash_key}):**",
                f"```json",
                f"{dict(hash_data) if hash_data else 'No data'}",
                f"```",
                "",
                f"**Raw Redis Sorted Set ({zset_key}):**",
                f"Total entries: {zset_size}",
                f"Recent entries (last 10):",
                f"```json",
                f"{recent_entries if recent_entries else 'No entries'}",
                f"```",
                "",
                f"**Calculated Stats:**",
                f"Total messages: {stats['total_messages']}",
                f"Recent (7d): {recent_count}",
                f"Score: {score:.2f}",
            ]
            
            message_content = "\n".join(info)
            
            # Split if too long
            if len(message_content) > 2000:
                chunks = []
                current_chunk = ""
                for line in info:
                    if len(current_chunk + line + "\n") > 1900:  # Leave room for formatting
                        if current_chunk:
                            chunks.append(current_chunk)
                        current_chunk = line + "\n"
                    else:
                        current_chunk += line + "\n"
                if current_chunk:
                    chunks.append(current_chunk)
                
                await interaction.followup.send(chunks[0])
                for chunk in chunks[1:]:
                    await interaction.followup.send(chunk)
            else:
                await interaction.followup.send(message_content)
        
        except Exception as e:
            self.logger.error(f"[debug_commands.inspect_redis] Error: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error inspecting Redis: {e}")

    @app_commands.command(name="trigger_activity_report", description="Manually trigger activity report update")
    @app_commands.default_permissions(administrator=True)
    async def trigger_activity_report(self, interaction: discord.Interaction):
        """Manually trigger activity report update."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get the background tasks cog
            tasks_cog = self.bot.get_cog('BackgroundTasksCog')
            if not tasks_cog:
                await interaction.followup.send("❌ Background tasks cog not found")
                return
            
            # Trigger the reports
            await tasks_cog._update_proposed_activity_report()
            await tasks_cog._update_permanent_activity_report()
            
            await interaction.followup.send("✅ Activity reports updated")
        
        except Exception as e:
            self.logger.error(f"[debug_commands.trigger_activity_report] Error: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error triggering reports: {e}")


async def setup(bot):
    """Add cog to bot."""
    await bot.add_cog(DebugCommandsCog(bot))