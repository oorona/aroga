"""
Admin Commands Cog - Organized admin command groups

This cog organizes admin commands into logical groups for better UX.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


class AdminCommandsCog(commands.Cog):
    """Cog for organized admin command groups."""
    
    def __init__(self, bot):
        """Initialize the admin commands cog."""
        self.bot = bot
        self.logger = logging.getLogger('admin_commands')
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if user has admin permissions for all commands in this cog."""
        return self.bot.has_admin_permissions(interaction.user)

    # Management Group
    management_group = app_commands.Group(
        name="manage",
        description="Channel and server management commands"
    )

    @management_group.command(name="promote_channel", description="Promote a channel from proposed to permanent")
    async def promote_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Promote a channel from proposed to permanent category."""
        # Delegate to existing admin_management cog
        admin_mgmt_cog = self.bot.get_cog('AdminManagementCog')
        if admin_mgmt_cog:
            await admin_mgmt_cog.promote_channel(interaction, channel)
        else:
            await interaction.response.send_message("❌ Admin management cog not available", ephemeral=True)

    @management_group.command(name="recalculate_stats", description="Recalculate activity statistics")
    async def recalculate_stats(self, interaction: discord.Interaction):
        """Recalculate activity statistics for tracked channels."""
        # Delegate to existing admin_management cog
        admin_mgmt_cog = self.bot.get_cog('AdminManagementCog')
        if admin_mgmt_cog:
            await admin_mgmt_cog.recalculate_stats(interaction)
        else:
            await interaction.response.send_message("❌ Admin management cog not available", ephemeral=True)

    @management_group.command(name="refresh_channels", description="Refresh channel tracking")
    async def refresh_channels(self, interaction: discord.Interaction):
        """Refresh channel tracking and force update activity reports."""
        # Delegate to existing admin_management cog
        admin_mgmt_cog = self.bot.get_cog('AdminManagementCog')
        if admin_mgmt_cog:
            await admin_mgmt_cog.refresh_channels(interaction)
        else:
            await interaction.response.send_message("❌ Admin management cog not available", ephemeral=True)

    # Proposals Group
    proposals_group = app_commands.Group(
        name="proposals",
        description="Review and manage user proposals"
    )

    @proposals_group.command(name="review", description="Review a user proposal")
    async def review_proposal(
        self, 
        interaction: discord.Interaction, 
        proposal_id: int,
        action: str,
        final_name: Optional[str] = None,
        response: Optional[str] = None
    ):
        """Review and take action on a user proposal."""
        # Delegate to existing admin_emoji_management cog
        admin_emoji_cog = self.bot.get_cog('AdminEmojiManagementCog')
        if admin_emoji_cog:
            await admin_emoji_cog.review_proposal(interaction, proposal_id, action, final_name, response)
        else:
            await interaction.response.send_message("❌ Admin emoji management cog not available", ephemeral=True)

    @proposals_group.command(name="list", description="List pending proposals")
    async def list_proposals(
        self,
        interaction: discord.Interaction,
        status: Optional[str] = None,
        proposal_type: Optional[str] = None,
        user: Optional[discord.Member] = None
    ):
        """List proposals with filtering options."""
        # Delegate to existing admin_emoji_management cog
        admin_emoji_cog = self.bot.get_cog('AdminEmojiManagementCog')
        if admin_emoji_cog:
            await admin_emoji_cog.list_proposals(interaction, status, proposal_type, user)
        else:
            await interaction.response.send_message("❌ Admin emoji management cog not available", ephemeral=True)

    @proposals_group.command(name="get", description="Get detailed info about a proposal")
    async def get_proposal(self, interaction: discord.Interaction, proposal_id: int):
        """Get detailed information about a specific proposal."""
        # Delegate to existing admin_emoji_management cog
        admin_emoji_cog = self.bot.get_cog('AdminEmojiManagementCog')
        if admin_emoji_cog:
            await admin_emoji_cog.get_proposal(interaction, proposal_id)
        else:
            await interaction.response.send_message("❌ Admin emoji management cog not available", ephemeral=True)

    # Reports Group
    reports_group = app_commands.Group(
        name="reports",
        description="Review and manage user reports"
    )

    @reports_group.command(name="review", description="Review a user report")
    async def review_report(
        self,
        interaction: discord.Interaction,
        report_id: int,
        action: str,
        response: Optional[str] = None
    ):
        """Review and take action on a user report."""
        # Delegate to existing admin_reports cog
        admin_reports_cog = self.bot.get_cog('AdminReportsCog')
        if admin_reports_cog:
            await admin_reports_cog.review_report(interaction, report_id, action, response)
        else:
            await interaction.response.send_message("❌ Admin reports cog not available", ephemeral=True)

    @reports_group.command(name="list", description="List pending reports")
    async def list_reports(
        self,
        interaction: discord.Interaction,
        status: Optional[str] = None,
        user: Optional[discord.Member] = None
    ):
        """List reports with filtering options."""
        # Delegate to existing admin_reports cog
        admin_reports_cog = self.bot.get_cog('AdminReportsCog')
        if admin_reports_cog:
            await admin_reports_cog.list_reports(interaction, status, user)
        else:
            await interaction.response.send_message("❌ Admin reports cog not available", ephemeral=True)

    @reports_group.command(name="get", description="Get detailed info about a report")
    async def get_report(self, interaction: discord.Interaction, report_id: int):
        """Get detailed information about a specific report."""
        # Delegate to existing admin_reports cog
        admin_reports_cog = self.bot.get_cog('AdminReportsCog')
        if admin_reports_cog:
            await admin_reports_cog.get_report(interaction, report_id)
        else:
            await interaction.response.send_message("❌ Admin reports cog not available", ephemeral=True)

    # Debug Group
    debug_group = app_commands.Group(
        name="debug",
        description="Debug and troubleshooting commands"
    )

    @debug_group.command(name="activity", description="Debug activity scoring system")
    async def debug_activity(self, interaction: discord.Interaction):
        """Debug the activity scoring system."""
        # Delegate to existing debug_commands cog
        debug_cog = self.bot.get_cog('DebugCommandsCog')
        if debug_cog:
            await debug_cog.debug_activity(interaction)
        else:
            await interaction.response.send_message("❌ Debug commands cog not available", ephemeral=True)

    @debug_group.command(name="channel", description="Debug specific channel activity")
    async def debug_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Debug channel activity and scoring."""
        # Delegate to existing debug_commands cog
        debug_cog = self.bot.get_cog('DebugCommandsCog')
        if debug_cog:
            await debug_cog.debug_channel(interaction, channel)
        else:
            await interaction.response.send_message("❌ Debug commands cog not available", ephemeral=True)

    @debug_group.command(name="test_tracking", description="Add test message data")
    async def test_message_tracking(
        self, 
        interaction: discord.Interaction, 
        channel: discord.TextChannel, 
        message_count: int = 5
    ):
        """Add test message data to Redis for a channel."""
        # Delegate to existing debug_commands cog
        debug_cog = self.bot.get_cog('DebugCommandsCog')
        if debug_cog:
            await debug_cog.test_message_tracking(interaction, channel, message_count)
        else:
            await interaction.response.send_message("❌ Debug commands cog not available", ephemeral=True)

    @debug_group.command(name="backfill", description="Backfill message statistics")
    async def backfill_stats(
        self, 
        interaction: discord.Interaction, 
        channel: Optional[discord.TextChannel] = None, 
        days: int = 7
    ):
        """Backfill message statistics from recent channel history."""
        # Delegate to existing debug_commands cog
        debug_cog = self.bot.get_cog('DebugCommandsCog')
        if debug_cog:
            await debug_cog.backfill_stats(interaction, channel, days)
        else:
            await interaction.response.send_message("❌ Debug commands cog not available", ephemeral=True)

    @debug_group.command(name="inspect_redis", description="Inspect Redis data")
    async def inspect_redis(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Inspect Redis data for a specific channel."""
        # Delegate to existing debug_commands cog
        debug_cog = self.bot.get_cog('DebugCommandsCog')
        if debug_cog:
            await debug_cog.inspect_redis(interaction, channel)
        else:
            await interaction.response.send_message("❌ Debug commands cog not available", ephemeral=True)

    @debug_group.command(name="trigger_reports", description="Trigger activity report update")
    async def trigger_activity_report(self, interaction: discord.Interaction):
        """Manually trigger activity report update."""
        # Delegate to existing debug_commands cog
        debug_cog = self.bot.get_cog('DebugCommandsCog')
        if debug_cog:
            await debug_cog.trigger_activity_report(interaction)
        else:
            await interaction.response.send_message("❌ Debug commands cog not available", ephemeral=True)

    @debug_group.command(name="sync", description="Sync slash commands")
    async def sync_commands(self, interaction: discord.Interaction):
        """Manually sync slash commands."""
        # Delegate to existing debug_commands cog
        debug_cog = self.bot.get_cog('DebugCommandsCog')
        if debug_cog:
            await debug_cog.sync_commands(interaction)
        else:
            await interaction.response.send_message("❌ Debug commands cog not available", ephemeral=True)

    # System Group
    system_group = app_commands.Group(
        name="system",
        description="System information and health commands"
    )

    @system_group.command(name="status", description="Check bot and database health")
    async def status(self, interaction: discord.Interaction):
        """Check bot and database health status."""
        # Delegate to existing core cog
        core_cog = self.bot.get_cog('CoreCog')
        if core_cog:
            await core_cog.status(interaction)
        else:
            await interaction.response.send_message("❌ Core cog not available", ephemeral=True)

    @system_group.command(name="info", description="Get bot information")
    async def info(self, interaction: discord.Interaction):
        """Display bot information and basic statistics."""
        # Delegate to existing core cog
        core_cog = self.bot.get_cog('CoreCog')
        if core_cog:
            await core_cog.info(interaction)
        else:
            await interaction.response.send_message("❌ Core cog not available", ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        """Called when the cog is ready."""
        self.logger.info("[admin_commands.on_ready] Admin commands cog is ready")
        self.logger.info("[admin_commands.on_ready] Available command groups: manage, proposals, reports, debug, system")


async def setup(bot):
    """Add cog to bot."""
    await bot.add_cog(AdminCommandsCog(bot))
    logging.getLogger('cogs.admin_commands').info("[admin_commands.setup] Admin commands cog loaded successfully")