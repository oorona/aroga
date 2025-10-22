"""
User Reports Cog - Commands for users to report issues

This cog handles user-submitted reports including validation,
database storage, and admin notifications.
"""

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from database.db_models import Report


class UserReportsCog(commands.Cog):
    """Cog for user reporting functionality."""
    
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('cogs.user_reports')
    
    @app_commands.command(name="report", description="Report an issue or user behavior")
    @app_commands.describe(
        report_type="Type of report",
        target_user="User being reported (optional for general issues)",
        description="Detailed description of the issue",
        evidence="Optional image evidence (screenshot, etc.)"
    )
    async def report_issue(
        self,
        interaction: discord.Interaction,
        report_type: str,
        description: str,
        target_user: Optional[discord.Member] = None,
        evidence: Optional[discord.Attachment] = None
    ):
        """Command for users to submit reports."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            self.logger.info(f"[user_reports.report_issue] Report initiated by {interaction.user.id}")
            
            # Validation
            if len(description.strip()) < 10:
                await interaction.followup.send(
                    "❌ **Error**: Description must be at least 10 characters long.",
                    ephemeral=True
                )
                return
            
            if len(description) > 2000:
                await interaction.followup.send(
                    "❌ **Error**: Description cannot exceed 2000 characters.",
                    ephemeral=True
                )
                return
            
            # Sanitize input
            description = description.strip()
            report_type = report_type.strip().lower()
            
            # Validate report type
            valid_types = ['user_behavior', 'spam', 'harassment', 'inappropriate_content', 'technical_issue', 'other']
            if report_type not in valid_types:
                await interaction.followup.send(
                    f"❌ **Error**: Invalid report type. Valid types: {', '.join(valid_types)}",
                    ephemeral=True
                )
                return
            
            # Check if reporting themselves
            if target_user and target_user.id == interaction.user.id:
                await interaction.followup.send(
                    "❌ **Error**: You cannot report yourself.",
                    ephemeral=True
                )
                return
            
            # Check if reporting a bot
            if target_user and target_user.bot:
                await interaction.followup.send(
                    "❌ **Error**: You cannot report bots.",
                    ephemeral=True
                )
                return
            
            # Validate evidence attachment if provided
            if evidence:
                # Check file size (max 25MB - Discord's attachment limit is 25MB for normal users)
                max_size = 25 * 1024 * 1024  # 25MB in bytes
                if evidence.size > max_size:
                    await interaction.followup.send(
                        "❌ **Error**: Evidence file is too large. Maximum size is 25MB.",
                        ephemeral=True
                    )
                    return
                
                # Check file type - allow common image formats
                allowed_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.webp']
                file_extension = evidence.filename.lower().split('.')[-1] if '.' in evidence.filename else ''
                if not any(evidence.filename.lower().endswith(ext) for ext in allowed_extensions):
                    await interaction.followup.send(
                        f"❌ **Error**: Evidence must be an image file ({', '.join(allowed_extensions)}).",
                        ephemeral=True
                    )
                    return
            
            # Store report in database
            report = Report(
                reporter_id=interaction.user.id,
                reported_user_id=target_user.id if target_user else None,
                report_type=report_type,
                description=description,
                channel_id=interaction.channel.id,
                guild_id=interaction.guild.id,
                status='pending'
            )
            
            async with self.bot.db_manager.get_pg_session() as session:
                session.add(report)
                await session.commit()
                await session.refresh(report)
                report_id = report.id
            
            # Send confirmation to user
            embed = discord.Embed(
                title="✅ Report Submitted",
                description="Your report has been submitted and will be reviewed by administrators.",
                color=0x00ff00,
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Report ID", value=f"`{report_id}`", inline=True)
            embed.add_field(name="Type", value=report_type.replace('_', ' ').title(), inline=True)
            embed.add_field(name="Status", value="Pending Review", inline=True)
            
            if target_user:
                embed.add_field(name="Reported User", value=target_user.mention, inline=False)
            
            if evidence:
                embed.add_field(name="Evidence", value="✅ Image evidence attached", inline=False)
            
            embed.set_footer(text="You will be notified when the report is reviewed.")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            # Send admin notification
            await self._send_admin_notification(report_id, interaction.user, target_user, report_type, description, evidence)
            
            # Update persistent embed queue
            await self._update_report_queue_embed()
            
            self.logger.info(f"[user_reports.report_issue] Report {report_id} created by {interaction.user.id}")
            
        except Exception as e:
            self.logger.error(f"[user_reports.report_issue] Error creating report: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ **Error**: Failed to submit report. Please try again later.",
                ephemeral=True
            )
    
    @report_issue.autocomplete('report_type')
    async def report_type_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete for report types."""
        report_types = [
            ('User Behavior', 'user_behavior'),
            ('Spam', 'spam'),
            ('Harassment', 'harassment'),
            ('Inappropriate Content', 'inappropriate_content'),
            ('Technical Issue', 'technical_issue'),
            ('Other', 'other')
        ]
        
        return [
            app_commands.Choice(name=name, value=value)
            for name, value in report_types
            if current.lower() in name.lower()
        ][:25]  # Discord limit
    
    async def _send_admin_notification(
        self,
        report_id: int,
        reporter: discord.Member,
        target_user: Optional[discord.Member],
        report_type: str,
        description: str,
        evidence: Optional[discord.Attachment] = None
    ):
        """Send notification to admin channel about new report."""
        try:
            admin_channel = self.bot.get_channel(self.bot.admin_notification_channel_id)
            if not admin_channel:
                self.logger.warning(f"[user_reports._send_admin_notification] Admin channel not found")
                return
            
            embed = discord.Embed(
                title="🚨 New Report Submitted",
                description=f"Report ID: `{report_id}`",
                color=0xff9900,
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(name="Reporter", value=f"{reporter.mention} ({reporter.id})", inline=True)
            embed.add_field(name="Type", value=report_type.replace('_', ' ').title(), inline=True)
            embed.add_field(name="Status", value="Pending", inline=True)
            
            if target_user:
                embed.add_field(name="Reported User", value=f"{target_user.mention} ({target_user.id})", inline=False)
            
            # Truncate description if too long
            display_description = description
            if len(description) > 1000:
                display_description = description[:1000] + "..."
            
            embed.add_field(name="Description", value=display_description, inline=False)
            
            # Add evidence information if provided
            if evidence:
                embed.add_field(name="Evidence", value=f"📎 **{evidence.filename}** ({evidence.size:,} bytes)", inline=False)
                embed.set_image(url=evidence.url)  # Display the image in the embed
            
            embed.set_footer(text="Use /review_report to take action")
            
            await admin_channel.send(embed=embed)
            self.logger.info(f"[user_reports._send_admin_notification] Admin notification sent for report {report_id}")
            
        except Exception as e:
            self.logger.error(f"[user_reports._send_admin_notification] Failed to send admin notification: {e}", exc_info=True)
    
    async def _update_report_queue_embed(self):
        """Update the persistent report queue embed."""
        try:
            # Get queue channel
            queue_channel = self.bot.get_channel(self.bot.queue_channel_id)
            if not queue_channel:
                self.logger.warning("[user_reports._update_report_queue_embed] Queue channel not found")
                return
            
            # Get active reports from database (pending and investigating)
            async with self.bot.db_manager.get_pg_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Report).where(Report.status.in_(['pending', 'investigating'])).order_by(Report.created_at)
                )
                active_reports = result.scalars().all()
            
            # Separate by status for display
            pending_reports = [r for r in active_reports if r.status == 'pending']
            investigating_reports = [r for r in active_reports if r.status == 'investigating']
            
            # Create embed
            embed = discord.Embed(
                title="📋 Active Reports Queue",
                description=f"Total active reports: {len(active_reports)} ({len(pending_reports)} pending, {len(investigating_reports)} investigating)",
                color=0xff9900,
                timestamp=discord.utils.utcnow()
            )
            
            if active_reports:
                report_list = []
                for report in active_reports[:10]:  # Show max 10 reports
                    report_type_display = report.report_type.replace('_', ' ').title()
                    created_date = report.created_at.strftime('%m/%d %H:%M')
                    
                    # Status emoji
                    status_emoji = '🟡' if report.status == 'pending' else '🔍'
                    
                    reporter_mention = f"<@{report.reporter_id}>"
                    if report.reported_user_id:
                        target_mention = f" → <@{report.reported_user_id}>"
                    else:
                        target_mention = ""
                    
                    report_list.append(
                        f"{status_emoji} `{report.id}` {report_type_display} - {reporter_mention}{target_mention} ({created_date})"
                    )
                
                embed.add_field(
                    name="Recent Reports",
                    value="\n".join(report_list),
                    inline=False
                )
                
                if len(active_reports) > 10:
                    embed.add_field(
                        name="Note",
                        value=f"Showing 10 of {len(active_reports)} active reports",
                        inline=False
                    )
            else:
                embed.add_field(name="Status", value="No active reports", inline=False)
            
            embed.add_field(name="Legend", value="🟡 Pending • 🔍 Investigating", inline=False)
            
            embed.set_footer(text="Updates automatically when new reports are submitted")
            
            # Update or send the embed
            await self._update_persistent_embed("report_queue", embed, queue_channel)
            
        except Exception as e:
            self.logger.error(f"[user_reports._update_report_queue_embed] Error updating report queue: {e}", exc_info=True)
    
    async def _update_persistent_embed(self, embed_type: str, embed: discord.Embed, channel: discord.TextChannel):
        """Update or create a persistent embed."""
        try:
            from database.db_models import PersistentEmbed
            from sqlalchemy import select
            
            async with self.bot.db_manager.get_pg_session() as session:
                # Check if embed already exists
                result = await session.execute(
                    select(PersistentEmbed).where(
                        PersistentEmbed.embed_type == embed_type,
                        PersistentEmbed.channel_id == channel.id
                    )
                )
                persistent_embed = result.scalar_one_or_none()
                
                if persistent_embed:
                    # Update existing embed
                    try:
                        message = await channel.fetch_message(persistent_embed.message_id)
                        await message.edit(embed=embed)
                        self.logger.debug(f"[user_reports._update_persistent_embed] Updated {embed_type} embed")
                    except discord.NotFound:
                        # Message was deleted, create new one
                        message = await channel.send(embed=embed)
                        persistent_embed.message_id = message.id
                        await session.commit()
                        self.logger.info(f"[user_reports._update_persistent_embed] Recreated {embed_type} embed")
                else:
                    # Create new embed
                    message = await channel.send(embed=embed)
                    new_embed = PersistentEmbed(
                        embed_type=embed_type,
                        channel_id=channel.id,
                        message_id=message.id
                    )
                    session.add(new_embed)
                    await session.commit()
                    self.logger.info(f"[user_reports._update_persistent_embed] Created new {embed_type} embed")
                
        except Exception as e:
            self.logger.error(f"[user_reports._update_persistent_embed] Error managing persistent embed: {e}", exc_info=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(UserReportsCog(bot))
    logging.getLogger('cogs.user_reports').info("[user_reports.setup] User reports cog loaded")