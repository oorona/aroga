"""
Background Tasks Cog - Handles scheduled statistics reporting and maintenance

This cog manages background tasks including activity score calculation,
statistics reporting, and data cleanup.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import discord
from discord.ext import commands, tasks

from database.db_models import TrackedChannel, PersistentEmbed


class BackgroundTasksCog(commands.Cog):
    """Cog for background tasks and statistics reporting."""
    
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('cogs.tasks')
        
        # Start background tasks when cog loads
        self.stats_report_task.start()
        self.cleanup_task.start()
    
    def cog_unload(self):
        """Clean up tasks when cog is unloaded."""
        self.stats_report_task.cancel()
        self.cleanup_task.cancel()
    
    @tasks.loop(minutes=30)  # Will be configured from STATS_REFRESH_INTERVAL_MINUTES
    async def stats_report_task(self):
        """Background task to update activity statistics reports."""
        try:
            self.logger.info("[tasks.stats_report_task] Starting statistics update")
            
            # Update both proposed and permanent channel activity reports
            await self._update_proposed_activity_report()
            await self._update_permanent_activity_report()
            
            self.logger.info("[tasks.stats_report_task] Statistics update completed")
            
        except Exception as e:
            self.logger.error(f"[tasks.stats_report_task] Error updating statistics: {e}", exc_info=True)
    
    @tasks.loop(hours=6)  # Cleanup every 6 hours
    async def cleanup_task(self):
        """Background task for data cleanup and maintenance."""
        try:
            self.logger.info("[tasks.cleanup_task] Starting cleanup tasks")
            
            # Clean up old Redis activity data
            await self._cleanup_old_activity_data()
            
            # Update tracked channels in database
            await self._update_tracked_channels()
            
            self.logger.info("[tasks.cleanup_task] Cleanup tasks completed")
            
        except Exception as e:
            self.logger.error(f"[tasks.cleanup_task] Error during cleanup: {e}", exc_info=True)
    
    @stats_report_task.before_loop
    async def before_stats_report_task(self):
        """Wait for bot to be ready before starting stats task."""
        await self.bot.wait_until_ready()
        
        # Update task interval from configuration
        try:
            interval_minutes = int(getattr(self.bot, 'stats_refresh_interval_minutes', 30))
            self.stats_report_task.change_interval(minutes=interval_minutes)
            self.logger.info(f"[tasks.before_stats_report_task] Set stats interval to {interval_minutes} minutes")
        except Exception as e:
            self.logger.warning(f"[tasks.before_stats_report_task] Could not set custom interval: {e}")
    
    @cleanup_task.before_loop
    async def before_cleanup_task(self):
        """Wait for bot to be ready before starting cleanup task."""
        await self.bot.wait_until_ready()
    
    async def _update_proposed_activity_report(self):
        """Update the proposed channels activity report."""
        try:
            # Get proposed channels report channel
            report_channel_id = getattr(self.bot, 'proposed_activity_report_channel_id', None)
            if not report_channel_id:
                self.logger.warning("[tasks._update_proposed_activity_report] No proposed activity report channel configured")
                return
            
            report_channel = self.bot.get_channel(report_channel_id)
            if not report_channel:
                self.logger.warning(f"[tasks._update_proposed_activity_report] Report channel not found: {report_channel_id}")
                return
            
            # Get proposed category channels
            proposed_category = self.bot.get_channel(self.bot.proposed_channel_category_id)
            if not proposed_category:
                self.logger.warning("[tasks._update_proposed_activity_report] Proposed category not found")
                return
            
            self.logger.info(f"[tasks._update_proposed_activity_report] Found proposed category: {proposed_category.name} (ID: {proposed_category.id})")
            self.logger.info(f"[tasks._update_proposed_activity_report] Text channels in category: {len(proposed_category.text_channels)}")
            self.logger.debug(f"[tasks._update_proposed_activity_report] DatabaseManager redis_stats available: {hasattr(self.bot.db_manager, 'redis_stats')}")
            if hasattr(self.bot.db_manager, 'redis_stats'):
                self.logger.debug(f"[tasks._update_proposed_activity_report] redis_stats object: {self.bot.db_manager.redis_stats}")
            
            # Get report channel IDs to exclude from scoring
            proposed_report_channel_id = int(os.getenv('PROPOSED_ACTIVITY_REPORT_CHANNEL_ID', '0'))
            permanent_report_channel_id = int(os.getenv('PERMANENT_ACTIVITY_REPORT_CHANNEL_ID', '0'))
            
            # Calculate scores for all text channels in category (excluding report channels)
            channel_scores = []
            for channel in proposed_category.text_channels:
                # Skip report channels
                if channel.id in [proposed_report_channel_id, permanent_report_channel_id]:
                    self.logger.debug(f"[tasks._update_proposed_activity_report] Skipping report channel: {channel.name} (ID: {channel.id})")
                    continue
                    
                self.logger.debug(f"[tasks._update_proposed_activity_report] Processing channel: {channel.name} (ID: {channel.id})")
                
                if hasattr(self.bot.db_manager, 'redis_stats'):
                    try:
                        score = await self.bot.db_manager.redis_stats.calculate_channel_score(channel.id)
                        stats = await self.bot.db_manager.redis_stats.get_channel_stats(channel.id)
                        recent_count = await self.bot.db_manager.redis_stats.get_recent_message_count(channel.id, 7)
                        
                        self.logger.info(f"[tasks._update_proposed_activity_report] Channel {channel.name}: score={score}, total={stats['total_messages']}, recent={recent_count}")
                        
                        channel_scores.append({
                            'channel': channel,
                            'score': score,
                            'total_messages': stats['total_messages'],
                            'recent_messages': recent_count
                        })
                    except Exception as e:
                        self.logger.error(f"[tasks._update_proposed_activity_report] Error processing channel {channel.name}: {e}")
                else:
                    self.logger.warning("[tasks._update_proposed_activity_report] redis_stats not available")
            
            self.logger.info(f"[tasks._update_proposed_activity_report] Processed {len(channel_scores)} channels with scores")
            
            # Sort by score (highest first)
            channel_scores.sort(key=lambda x: x['score'], reverse=True)
            
            # Create embed
            embed = await self._create_activity_embed(
                "📊 Proposed Channels Activity Report",
                channel_scores,
                "proposed"
            )
            
            # Update or create persistent embed
            await self._update_persistent_activity_embed(report_channel, embed, 'proposed_activity')
            
            self.logger.debug(f"[tasks._update_proposed_activity_report] Updated report for {len(channel_scores)} channels")
            
        except Exception as e:
            self.logger.error(f"[tasks._update_proposed_activity_report] Error updating report: {e}", exc_info=True)
    
    async def _update_permanent_activity_report(self):
        """Update the permanent channels activity report."""
        try:
            # Get permanent channels report channel
            report_channel_id = getattr(self.bot, 'permanent_activity_report_channel_id', None)
            if not report_channel_id:
                self.logger.warning("[tasks._update_permanent_activity_report] No permanent activity report channel configured")
                return
            
            report_channel = self.bot.get_channel(report_channel_id)
            if not report_channel:
                self.logger.warning(f"[tasks._update_permanent_activity_report] Report channel not found: {report_channel_id}")
                return
            
            # Get permanent category channels
            permanent_category = self.bot.get_channel(self.bot.permanent_channel_category_id)
            if not permanent_category:
                self.logger.warning("[tasks._update_permanent_activity_report] Permanent category not found")
                return
            
            # Get report channel IDs to exclude from scoring
            proposed_report_channel_id = int(os.getenv('PROPOSED_ACTIVITY_REPORT_CHANNEL_ID', '0'))
            permanent_report_channel_id = int(os.getenv('PERMANENT_ACTIVITY_REPORT_CHANNEL_ID', '0'))
            
            # Calculate scores for all text channels in category (excluding report channels)
            channel_scores = []
            for channel in permanent_category.text_channels:
                # Skip report channels
                if channel.id in [proposed_report_channel_id, permanent_report_channel_id]:
                    self.logger.debug(f"[tasks._update_permanent_activity_report] Skipping report channel: {channel.name} (ID: {channel.id})")
                    continue
                    
                if hasattr(self.bot.db_manager, 'redis_stats'):
                    score = await self.bot.db_manager.redis_stats.calculate_channel_score(channel.id)
                    stats = await self.bot.db_manager.redis_stats.get_channel_stats(channel.id)
                    recent_count = await self.bot.db_manager.redis_stats.get_recent_message_count(channel.id, 7)
                    
                    self.logger.info(f"[tasks._update_permanent_activity_report] Channel {channel.name}: score={score}, total={stats['total_messages']}, recent={recent_count}")
                    
                    channel_scores.append({
                        'channel': channel,
                        'score': score,
                        'total_messages': stats['total_messages'],
                        'recent_messages': recent_count
                    })
            
            # Sort by creation date (most recent first) for permanent channels
            channel_scores.sort(key=lambda x: x['channel'].created_at, reverse=True)
            
            # Create embed
            embed = await self._create_activity_embed(
                "📊 Permanent Channels Activity Report", 
                channel_scores,
                "permanent"
            )
            
            # Update or create persistent embed
            await self._update_persistent_activity_embed(report_channel, embed, 'permanent_activity')
            
            self.logger.debug(f"[tasks._update_permanent_activity_report] Updated report for {len(channel_scores)} channels")
            
        except Exception as e:
            self.logger.error(f"[tasks._update_permanent_activity_report] Error updating report: {e}", exc_info=True)
    
    async def _create_activity_embed(self, title: str, channel_scores: List[Dict], category_type: str) -> discord.Embed:
        """Create activity report embed."""
        embed = discord.Embed(
            title=title,
            description=f"Activity report for {len(channel_scores)} channels",
            color=0x5865f2 if category_type == 'proposed' else 0x57f287,
            timestamp=discord.utils.utcnow()
        )
        
        if not channel_scores:
            embed.add_field(
                name="No Data",
                value="No channels found in this category",
                inline=False
            )
            embed.set_footer(text="Report updates every 30 minutes")
            return embed
        
        # Add summary statistics
        total_messages = sum(ch['total_messages'] for ch in channel_scores)
        total_recent = sum(ch['recent_messages'] for ch in channel_scores)
        avg_score = sum(ch['score'] for ch in channel_scores) / len(channel_scores) if channel_scores else 0
        
        embed.add_field(
            name="📈 Summary",
            value=f"**Total Messages:** {total_messages:,}\n**Recent (7d):** {total_recent:,}\n**Avg Score:** {avg_score:.1f}",
            inline=True
        )
        
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # Spacer
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # Spacer
        
        # Add top channels
        top_channels = channel_scores[:15]  # Show top 15
        
        if category_type == 'proposed':
            # For proposed channels, sort by score for ranking
            lines = []
            for i, ch_data in enumerate(top_channels, 1):
                channel = ch_data['channel']
                score = ch_data['score']
                total = ch_data['total_messages']
                recent = ch_data['recent_messages']
                
                emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                lines.append(f"{emoji} {channel.mention} - **{score:.1f}** pts ({total:,} total, {recent} recent)")
            
            embed.add_field(
                name="🏆 Top Channels by Activity Score",
                value="\n".join(lines[:10]) if lines else "No active channels",
                inline=False
            )
            
            if len(lines) > 10:
                embed.add_field(
                    name="📋 More Channels",
                    value="\n".join(lines[10:15]),
                    inline=False
                )
        
        else:
            # For permanent channels, show by recency (most recent first)
            lines = []
            for ch_data in top_channels:
                channel = ch_data['channel']
                score = ch_data['score']
                total = ch_data['total_messages']
                recent = ch_data['recent_messages']
                
                created_date = channel.created_at.strftime('%m/%d')
                lines.append(f"• {channel.mention} - Created {created_date} ({total:,} total, {recent} recent)")
            
            embed.add_field(
                name="📅 Channels by Creation Date",
                value="\n".join(lines[:10]) if lines else "No channels",
                inline=False
            )
            
            if len(lines) > 10:
                embed.add_field(
                    name="📋 More Channels",
                    value="\n".join(lines[10:15]),
                    inline=False
                )
        
        # Add legend (different for proposed vs permanent channels)
        if category_type == 'proposed':
            embed.add_field(
                name="📋 Legend",
                value="**Score Formula:** (total × 0.4) + (recent × 0.6)\n**Recent:** Messages in last 7 days",
                inline=False
            )
            embed.set_footer(text="Report updates automatically • Use /promote_channel to move top performers")
        else:
            embed.add_field(
                name="📋 Legend", 
                value="**Ordering:** Channels ordered by creation date (newest first)\n**Recent:** Messages in last 7 days",
                inline=False
            )
            embed.set_footer(text="Report updates automatically • Permanent channels")
        
        return embed
    
    async def _update_persistent_activity_embed(self, channel: discord.TextChannel, embed: discord.Embed, embed_type: str):
        """Update or create a persistent activity embed."""
        try:
            async with self.bot.db_manager.get_pg_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(PersistentEmbed).where(PersistentEmbed.embed_type == embed_type)
                )
                persistent_embed = result.scalar_one_or_none()
                
                if persistent_embed and persistent_embed.message_id:
                    # Update existing embed
                    try:
                        message = await channel.fetch_message(persistent_embed.message_id)
                        await message.edit(embed=embed)
                        self.logger.debug(f"[tasks._update_persistent_activity_embed] Updated existing {embed_type} embed")
                    except discord.NotFound:
                        # Message was deleted, create new one
                        message = await channel.send(embed=embed)
                        persistent_embed.message_id = message.id
                        await session.commit()
                        self.logger.info(f"[tasks._update_persistent_activity_embed] Recreated {embed_type} embed")
                else:
                    # Create new embed
                    message = await channel.send(embed=embed)
                    
                    if not persistent_embed:
                        persistent_embed = PersistentEmbed(
                            embed_type=embed_type,
                            channel_id=channel.id,
                            message_id=message.id
                        )
                        session.add(persistent_embed)
                    else:
                        persistent_embed.message_id = message.id
                    
                    await session.commit()
                    self.logger.info(f"[tasks._update_persistent_activity_embed] Created new {embed_type} embed")
            
        except Exception as e:
            self.logger.error(f"[tasks._update_persistent_activity_embed] Error updating {embed_type} embed: {e}", exc_info=True)
    
    async def _cleanup_old_activity_data(self):
        """Clean up old activity data from Redis."""
        try:
            if not hasattr(self.bot.db_manager, 'redis_stats'):
                return
            
            # Get all tracked channels
            tracked_channels = await self.bot.db_manager.redis_stats.get_all_tracked_channels()
            
            cleanup_count = 0
            for channel_id in tracked_channels:
                await self.bot.db_manager.redis_stats.cleanup_old_activity(channel_id, days=7)
                cleanup_count += 1
            
            if cleanup_count > 0:
                self.logger.info(f"[tasks._cleanup_old_activity_data] Cleaned up activity data for {cleanup_count} channels")
            
        except Exception as e:
            self.logger.error(f"[tasks._cleanup_old_activity_data] Error during cleanup: {e}", exc_info=True)
    
    async def _update_tracked_channels(self):
        """Update the tracked channels table based on current categories."""
        try:
            # Get channels in both categories
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
                
                if to_add or to_remove:
                    self.logger.info(f"[tasks._update_tracked_channels] Added {len(to_add)}, removed {len(to_remove)} tracked channels")
            
        except Exception as e:
            self.logger.error(f"[tasks._update_tracked_channels] Error updating tracked channels: {e}", exc_info=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(BackgroundTasksCog(bot))
    logging.getLogger('cogs.tasks').info("[tasks.setup] Background tasks cog loaded")