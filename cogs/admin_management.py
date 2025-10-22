"""
Admin Management Cog - Commands for channel promotion and statistics management

This cog handles administrative functions for managing channels, including
promoting channels from proposed to permanent and recalculating statistics.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from database.db_models import TrackedChannel


class AdminManagementCog(commands.Cog):
    """Cog for administrative channel management functionality."""
    
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('cogs.admin_management')
    
    def cog_check(self, ctx):
        """Check if user has admin permissions."""
        return self.bot.has_admin_permissions(ctx.author)
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if user has admin permissions for slash commands."""
        return self.bot.has_admin_permissions(interaction.user)
    
    @app_commands.command(name="promote_channel", description="Promote a channel from proposed to permanent category")
    @app_commands.describe(channel="Channel to promote to permanent status")
    async def promote_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Command to promote a channel from proposed to permanent category."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            self.logger.info(f"[admin_management.promote_channel] Channel {channel.id} promotion requested by {interaction.user.id}")
            
            # Verify channel is in proposed category
            if channel.category_id != self.bot.proposed_channel_category_id:
                await interaction.followup.send(
                    f"❌ **Error**: {channel.mention} is not in the proposed channels category.",
                    ephemeral=True
                )
                return
            
            # Get permanent category
            permanent_category = self.bot.get_channel(self.bot.permanent_channel_category_id)
            if not permanent_category:
                await interaction.followup.send(
                    "❌ **Error**: Permanent channels category not found.",
                    ephemeral=True
                )
                return
            
            # Move channel to permanent category
            old_category_name = channel.category.name if channel.category else "No Category"
            await channel.edit(category=permanent_category, reason=f"Promoted by {interaction.user}")
            
            # Update tracked channels in database
            await self._update_channel_tracking(channel.id, 'proposed', 'permanent')
            
            # Send confirmation to admin
            embed = discord.Embed(
                title="✅ Channel Promoted",
                description=f"{channel.mention} has been promoted to permanent status!",
                color=0x00ff00,
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(name="Channel", value=channel.mention, inline=True)
            embed.add_field(name="Promoted by", value=interaction.user.mention, inline=True)
            embed.add_field(name="Previous Category", value=old_category_name, inline=True)
            
            # Get channel statistics
            if hasattr(self.bot.db_manager, 'redis_stats'):
                stats = await self.bot.db_manager.redis_stats.get_channel_stats(channel.id)
                score = await self.bot.db_manager.redis_stats.calculate_channel_score(channel.id)
                recent_count = await self.bot.db_manager.redis_stats.get_recent_message_count(channel.id, 7)
                
                embed.add_field(name="Total Messages", value=f"{stats['total_messages']:,}", inline=True)
                embed.add_field(name="Recent Messages (7d)", value=f"{recent_count:,}", inline=True)
                embed.add_field(name="Activity Score", value=f"{score:.1f}", inline=True)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            # Send public announcement
            await self._send_promotion_announcement(channel, interaction.user)
            
            # Send admin log
            await self._send_admin_log(channel, interaction.user, "promoted")
            
            self.logger.info(f"[admin_management.promote_channel] Channel {channel.id} promoted by {interaction.user.id}")
            
        except Exception as e:
            self.logger.error(f"[admin_management.promote_channel] Error promoting channel {channel.id}: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ **Error**: Failed to promote channel. Please try again later.",
                ephemeral=True
            )
    
    @app_commands.command(name="recalculate_stats", description="Recalculate activity statistics for tracked channels")
    @app_commands.describe(
        months_back="Number of months to look back for recalculation (default: 1, max from config)"
    )
    async def recalculate_stats(self, interaction: discord.Interaction, months_back: int = 1):
        """Command to recalculate channel activity statistics."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Validate months_back parameter
            max_months = getattr(self.bot, 'stats_recalculation_month_limit', 6)
            if months_back > max_months:
                months_back = max_months
            elif months_back < 1:
                months_back = 1
            
            self.logger.info(f"[admin_management.recalculate_stats] Stats recalculation requested by {interaction.user.id} for {months_back} months")
            
            # Get all tracked channels
            tracked_channels = []
            
            # Get channels from both categories
            proposed_category = self.bot.get_channel(self.bot.proposed_channel_category_id)
            permanent_category = self.bot.get_channel(self.bot.permanent_channel_category_id)
            
            if proposed_category:
                tracked_channels.extend(proposed_category.text_channels)
            
            if permanent_category:
                tracked_channels.extend(permanent_category.text_channels)
            
            # Exclude report channels
            proposed_report_channel_id = int(os.getenv('PROPOSED_ACTIVITY_REPORT_CHANNEL_ID', '0'))
            permanent_report_channel_id = int(os.getenv('PERMANENT_ACTIVITY_REPORT_CHANNEL_ID', '0'))
            
            original_count = len(tracked_channels)
            tracked_channels = [ch for ch in tracked_channels 
                              if ch.id not in [proposed_report_channel_id, permanent_report_channel_id]]
            excluded_count = original_count - len(tracked_channels)
            
            self.logger.info(f"[admin_management.recalculate_stats] Found {original_count} channels, excluded {excluded_count} report channels, processing {len(tracked_channels)}")
            
            if not tracked_channels:
                await interaction.followup.send(
                    "❌ **Error**: No tracked channels found.",
                    ephemeral=True
                )
                return
            
            # Send initial response
            embed = discord.Embed(
                title="🔄 Recalculating Statistics",
                description=f"Processing {len(tracked_channels)} channels from tracked categories (excluding report channels)...",
                color=0xff9900,
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Lookback Period", value=f"{months_back} month(s)", inline=True)
            embed.add_field(name="Status", value="In Progress...", inline=True)
            embed.add_field(name="Excluded", value=f"{excluded_count} report channels", inline=True)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            # Calculate cutoff date
            cutoff_date = datetime.utcnow() - timedelta(days=30 * months_back)
            
            # Process each channel
            processed_count = 0
            error_count = 0
            
            for channel in tracked_channels:
                try:
                    await self._recalculate_channel_stats(channel, cutoff_date)
                    processed_count += 1
                except Exception as e:
                    self.logger.error(f"[admin_management.recalculate_stats] Error processing channel {channel.id}: {e}")
                    error_count += 1
            
            # Send completion response
            embed = discord.Embed(
                title="✅ Statistics Recalculation Complete",
                description="Channel statistics have been recalculated for tracked categories only\n📊 Activity reports have been updated",
                color=0x00ff00,
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(name="Channels Processed", value=f"{processed_count}", inline=True)
            embed.add_field(name="Errors", value=f"{error_count}", inline=True)
            embed.add_field(name="Excluded", value=f"{excluded_count} report channels", inline=True)
            embed.add_field(name="Lookback Period", value=f"{months_back} month(s)", inline=True)
            embed.add_field(name="Processed by", value=interaction.user.mention, inline=True)
            
            await interaction.edit_original_response(embed=embed)
            
            # Send admin log
            await self._send_admin_log_stats(interaction.user, processed_count, error_count, months_back)
            
            # Update activity reports after recalculation
            try:
                tasks_cog = self.bot.get_cog('BackgroundTasksCog')
                if tasks_cog:
                    await tasks_cog._update_proposed_activity_report()
                    await tasks_cog._update_permanent_activity_report()
                    self.logger.info("[admin_management.recalculate_stats] Activity reports updated after recalculation")
                else:
                    self.logger.warning("[admin_management.recalculate_stats] BackgroundTasksCog not found, skipping report update")
            except Exception as e:
                self.logger.error(f"[admin_management.recalculate_stats] Error updating reports: {e}")
            
            self.logger.info(f"[admin_management.recalculate_stats] Completed: {processed_count} processed, {error_count} errors")
            
        except Exception as e:
            self.logger.error(f"[admin_management.recalculate_stats] Error during recalculation: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ **Error**: Failed to recalculate statistics. Please try again later.",
                ephemeral=True
            )
    
    @app_commands.command(name="refresh_channels", description="Refresh channel tracking and force update activity reports")
    async def refresh_channels(self, interaction: discord.Interaction):
        """Command to refresh channel tracking and update reports."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            self.logger.info(f"[admin_management.refresh_channels] Channel refresh requested by {interaction.user.id}")
            
            # Update tracked channels in database
            proposed_category = self.bot.get_channel(self.bot.proposed_channel_category_id)
            permanent_category = self.bot.get_channel(self.bot.permanent_channel_category_id)
            
            current_channels = set()
            
            if proposed_category:
                for channel in proposed_category.text_channels:
                    current_channels.add((channel.id, 'proposed'))
            
            if permanent_category:
                for channel in permanent_category.text_channels:
                    current_channels.add((channel.id, 'permanent'))
            
            # Update database
            async with self.bot.db_manager.get_pg_session() as session:
                from sqlalchemy import select, delete
                
                # Get existing tracked channels
                result = await session.execute(select(TrackedChannel))
                existing_channels = {(tc.channel_id, tc.category) for tc in result.scalars().all()}
                
                # Find channels to add and remove
                to_add = current_channels - existing_channels
                to_remove = existing_channels - current_channels
                
                # Add new channels
                for channel_id, category in to_add:
                    tracked_channel = TrackedChannel(
                        channel_id=channel_id,
                        category=category
                    )
                    session.add(tracked_channel)
                
                # Remove old channels
                for channel_id, category in to_remove:
                    await session.execute(
                        delete(TrackedChannel).where(
                            TrackedChannel.channel_id == channel_id,
                            TrackedChannel.category == category
                        )
                    )
                
                await session.commit()
            
            # Force update activity reports
            tasks_cog = self.bot.get_cog('BackgroundTasksCog')
            if tasks_cog:
                await tasks_cog._update_proposed_activity_report()
                await tasks_cog._update_permanent_activity_report()
            
            # Send response
            embed = discord.Embed(
                title="✅ Channels Refreshed",
                description="Channel tracking and activity reports have been updated",
                color=0x00ff00,
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(name="Channels Added", value=f"{len(to_add)}", inline=True)
            embed.add_field(name="Channels Removed", value=f"{len(to_remove)}", inline=True)
            embed.add_field(name="Total Tracked", value=f"{len(current_channels)}", inline=True)
            embed.add_field(name="Refreshed by", value=interaction.user.mention, inline=True)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            self.logger.info(f"[admin_management.refresh_channels] Completed: {len(to_add)} added, {len(to_remove)} removed")
            
        except Exception as e:
            self.logger.error(f"[admin_management.refresh_channels] Error during refresh: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ **Error**: Failed to refresh channels. Please try again later.",
                ephemeral=True
            )
    
    async def _update_channel_tracking(self, channel_id: int, old_category: str, new_category: str):
        """Update channel tracking in database."""
        try:
            async with self.bot.db_manager.get_pg_session() as session:
                from sqlalchemy import select, delete
                
                # Remove old tracking record
                await session.execute(
                    delete(TrackedChannel).where(
                        TrackedChannel.channel_id == channel_id,
                        TrackedChannel.category == old_category
                    )
                )
                
                # Add new tracking record
                tracked_channel = TrackedChannel(
                    channel_id=channel_id,
                    category=new_category
                )
                session.add(tracked_channel)
                
                await session.commit()
                
        except Exception as e:
            self.logger.error(f"[admin_management._update_channel_tracking] Error updating tracking for channel {channel_id}: {e}")
    
    async def _send_promotion_announcement(self, channel: discord.TextChannel, admin: discord.Member):
        """Send public announcement about channel promotion."""
        try:
            # Try to load promotion announcement template
            try:
                with open('/app/templates/promoted_channel_announcement.md', 'r') as f:
                    template = f.read()
            except FileNotFoundError:
                # Fallback template
                template = """🎉 **Channel Promoted to Permanent!**

{channel_mention} has been promoted to permanent status due to high community engagement!

**Promoted by:** {admin_mention}

This channel has shown excellent activity and will now be part of our permanent channel lineup. Keep up the great conversations!
"""
            
            # Get public announcement channel
            announcement_channel = self.bot.get_channel(self.bot.public_announcement_channel_id)
            if not announcement_channel:
                self.logger.warning("[admin_management._send_promotion_announcement] Public announcement channel not found")
                return
            
            # Format template
            formatted_message = template.format(
                channel_mention=channel.mention,
                admin_mention=admin.mention,
                channel_name=channel.name
            )
            
            await announcement_channel.send(formatted_message)
            
            self.logger.info(f"[admin_management._send_promotion_announcement] Promotion announcement sent for channel {channel.name}")
            
        except Exception as e:
            self.logger.error(f"[admin_management._send_promotion_announcement] Error sending announcement: {e}", exc_info=True)
    
    async def _send_admin_log(self, channel: discord.TextChannel, admin: discord.Member, action: str):
        """Send admin log message about channel action."""
        try:
            admin_channel = self.bot.get_channel(self.bot.admin_notification_channel_id)
            if not admin_channel:
                return
            
            embed = discord.Embed(
                title=f"🔄 Channel {action.title()}",
                color=0x9b59b6,
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(name="Channel", value=channel.mention, inline=True)
            embed.add_field(name="Admin", value=admin.mention, inline=True)
            embed.add_field(name="Action", value=action.title(), inline=True)
            
            # Add statistics if available
            if hasattr(self.bot.db_manager, 'redis_stats'):
                stats = await self.bot.db_manager.redis_stats.get_channel_stats(channel.id)
                score = await self.bot.db_manager.redis_stats.calculate_channel_score(channel.id)
                embed.add_field(name="Activity Score", value=f"{score:.1f}", inline=True)
                embed.add_field(name="Total Messages", value=f"{stats['total_messages']:,}", inline=True)
            
            await admin_channel.send(embed=embed)
            
        except Exception as e:
            self.logger.error(f"[admin_management._send_admin_log] Error sending admin log: {e}", exc_info=True)
    
    async def _send_admin_log_stats(self, admin: discord.Member, processed: int, errors: int, months: int):
        """Send admin log about statistics recalculation."""
        try:
            admin_channel = self.bot.get_channel(self.bot.admin_notification_channel_id)
            if not admin_channel:
                return
            
            embed = discord.Embed(
                title="📊 Statistics Recalculated",
                color=0x9b59b6,
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(name="Admin", value=admin.mention, inline=True)
            embed.add_field(name="Processed", value=f"{processed} channels", inline=True)
            embed.add_field(name="Errors", value=f"{errors}", inline=True)
            embed.add_field(name="Lookback", value=f"{months} month(s)", inline=True)
            
            await admin_channel.send(embed=embed)
            
        except Exception as e:
            self.logger.error(f"[admin_management._send_admin_log_stats] Error sending admin log: {e}", exc_info=True)
    
    async def _recalculate_channel_stats(self, channel: discord.TextChannel, cutoff_date: datetime):
        """Recalculate statistics for a single channel."""
        try:
            if not hasattr(self.bot.db_manager, 'redis_stats'):
                return
            
            # Clear existing stats
            await self.bot.db_manager.redis_stats.clear_channel_stats(channel.id)
            
            # Fetch messages and recalculate
            message_count = 0
            async for message in channel.history(limit=None, after=cutoff_date):
                if not message.author.bot:
                    timestamp = int(message.created_at.timestamp())
                    await self.bot.db_manager.redis_stats.increment_channel_messages(
                        channel.id,
                        message.id,
                        timestamp
                    )
                    message_count += 1
            
            self.logger.debug(f"[admin_management._recalculate_channel_stats] Recalculated {message_count} messages for channel {channel.id}")
            
        except Exception as e:
            self.logger.error(f"[admin_management._recalculate_channel_stats] Error recalculating channel {channel.id}: {e}")
            raise


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(AdminManagementCog(bot))
    logging.getLogger('cogs.admin_management').info("[admin_management.setup] Admin management cog loaded")