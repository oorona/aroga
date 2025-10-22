"""
Admin Reports Cog - Commands for administrators to manage user reports

This cog handles admin functionality for reviewing, responding to,
and managing user-submitted reports.
"""

import logging
from datetime import datetime
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from database.db_models import Report


class AdminReportsCog(commands.Cog):
    """Cog for admin report management functionality."""
    
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('cogs.admin_reports')
    
    def cog_check(self, ctx):
        """Check if user has admin permissions."""
        return self.bot.has_admin_permissions(ctx.author)
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if user has admin permissions for slash commands."""
        return self.bot.has_admin_permissions(interaction.user)
    
    @app_commands.command(name="review_report", description="Review and take action on a user report")
    @app_commands.describe(
        report_id="ID of the report to review",
        action="Action to take on the report",
        response="Response message to send to the reporter (optional)"
    )
    async def review_report(
        self,
        interaction: discord.Interaction,
        report_id: int,
        action: str,
        response: Optional[str] = None
    ):
        """Command for admins to review and act on reports."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            self.logger.info(f"[admin_reports.review_report] Report {report_id} being reviewed by {interaction.user.id}")
            
            # Validate action
            valid_actions = ['resolved', 'dismissed', 'escalated', 'investigating']
            if action not in valid_actions:
                await interaction.followup.send(
                    f"❌ **Error**: Invalid action. Valid actions: {', '.join(valid_actions)}",
                    ephemeral=True
                )
                return
            
            # Get report from database
            async with self.bot.db_manager.get_pg_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Report).where(Report.id == report_id)
                )
                report = result.scalar_one_or_none()
                
                if not report:
                    await interaction.followup.send(
                        f"❌ **Error**: Report ID `{report_id}` not found.",
                        ephemeral=True
                    )
                    return
                
                # Only block truly final states (resolved/dismissed are final closure)
                if report.status in ['resolved', 'dismissed']:
                    await interaction.followup.send(
                        f"❌ **Error**: Report `{report_id}` has already been {report.status} and is closed. Use a new report if needed.",
                        ephemeral=True
                    )
                    return
                
                # Update report status
                report.status = action
                report.admin_id = interaction.user.id
                report.admin_response = response
                report.resolved_at = datetime.utcnow()
                
                await session.commit()
            
            # Send confirmation to admin
            embed = discord.Embed(
                title="✅ Report Reviewed",
                description=f"Report `{report_id}` has been marked as **{action}**",
                color=0x00ff00,
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(name="Report Type", value=report.report_type.replace('_', ' ').title(), inline=True)
            embed.add_field(name="Reporter", value=f"<@{report.reporter_id}>", inline=True)
            embed.add_field(name="Reviewed By", value=interaction.user.mention, inline=True)
            
            if report.reported_user_id:
                embed.add_field(name="Reported User", value=f"<@{report.reported_user_id}>", inline=True)
            
            if response:
                embed.add_field(name="Response Sent", value=response[:100] + "..." if len(response) > 100 else response, inline=False)
            
            # Add status information
            if action in ['investigating', 'escalated']:
                embed.add_field(name="Next Steps", value="Report can be updated again or moved to final status", inline=False)
            elif action in ['resolved', 'dismissed']:
                embed.add_field(name="Status", value="Report is now closed and reporter has been notified", inline=False)
            else:
                embed.add_field(name="Status", value="Reporter has been notified of the status change", inline=False)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            # Send notification to reporter when there's a response or for final actions
            if response or action in ['resolved', 'dismissed', 'escalated']:
                await self._notify_reporter(report, action, response, interaction.user)
            
            # Update report queue embed
            await self._update_report_queue_embed()
            
            # Send admin log
            await self._send_admin_log(report, action, response, interaction.user)
            
            self.logger.info(f"[admin_reports.review_report] Report {report_id} marked as {action} by {interaction.user.id}")
            
        except Exception as e:
            self.logger.error(f"[admin_reports.review_report] Error reviewing report {report_id}: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ **Error**: Failed to review report. Please try again later.",
                ephemeral=True
            )
    
    @review_report.autocomplete('action')
    async def action_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete for report actions."""
        actions = [
            ('Resolved', 'resolved'),
            ('Dismissed', 'dismissed'),
            ('Escalated', 'escalated'),
            ('Investigating', 'investigating')
        ]
        
        return [
            app_commands.Choice(name=name, value=value)
            for name, value in actions
            if current.lower() in name.lower()
        ][:25]  # Discord limit
    
    @app_commands.command(name="list_reports", description="List reports with filtering options")
    @app_commands.describe(
        status="Filter by report status",
        report_type="Filter by report type",
        limit="Number of reports to show (default: 10, max: 25)"
    )
    async def list_reports(
        self,
        interaction: discord.Interaction,
        status: Optional[str] = None,
        report_type: Optional[str] = None,
        limit: int = 10
    ):
        """Command to list reports with filters."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            if limit > 25:
                limit = 25
            elif limit < 1:
                limit = 1
            
            # Build query
            async with self.bot.db_manager.get_pg_session() as session:
                from sqlalchemy import select, desc
                query = select(Report).order_by(desc(Report.created_at)).limit(limit)
                
                if status:
                    query = query.where(Report.status == status)
                
                if report_type:
                    query = query.where(Report.report_type == report_type)
                
                result = await session.execute(query)
                reports = result.scalars().all()
            
            if not reports:
                await interaction.followup.send(
                    "📋 No reports found matching the specified criteria.",
                    ephemeral=True
                )
                return
            
            # Calculate summary statistics
            status_counts = {}
            admin_counts = {}
            
            for report in reports:
                # Count by status
                status_counts[report.status] = status_counts.get(report.status, 0) + 1
                
                # Count by admin (for handled reports)
                if report.admin_id:
                    admin_counts[report.admin_id] = admin_counts.get(report.admin_id, 0) + 1
            
            # Create embed
            embed = discord.Embed(
                title="📋 Reports List",
                description=f"Showing {len(reports)} reports",
                color=0x3498db,
                timestamp=discord.utils.utcnow()
            )
            
            if status:
                embed.description += f" with status: **{status}**"
            if report_type:
                embed.description += f" of type: **{report_type.replace('_', ' ').title()}**"
            
            # Add summary statistics
            status_summary = []
            for status_name, count in status_counts.items():
                emoji = {
                    'pending': '🟡',
                    'resolved': '✅', 
                    'dismissed': '❌',
                    'escalated': '🔺',
                    'investigating': '🔍'
                }.get(status_name, '❓')
                status_summary.append(f"{emoji} {status_name.title()}: {count}")
            
            embed.add_field(
                name="📊 Summary by Status",
                value="\n".join(status_summary),
                inline=True
            )
            
            # Add admin statistics if there are handled reports
            if admin_counts:
                admin_summary = []
                for admin_id, count in admin_counts.items():
                    admin_summary.append(f"<@{admin_id}>: {count}")
                
                embed.add_field(
                    name="👥 Handled by Admins",
                    value="\n".join(admin_summary[:5]),  # Show top 5 admins
                    inline=True
                )
            
            embed.add_field(name="\u200b", value="\u200b", inline=True)  # Empty field for spacing
            
            report_lines = []
            for report in reports:
                status_emoji = {
                    'pending': '🟡',
                    'resolved': '✅', 
                    'dismissed': '❌',
                    'escalated': '🔺',
                    'investigating': '🔍'
                }.get(report.status, '❓')
                
                created_date = report.created_at.strftime('%m/%d %H:%M')
                report_type_display = report.report_type.replace('_', ' ').title()
                
                # Build the report line with more detail
                line = f"{status_emoji} `{report.id}` **{report_type_display}**"
                
                # Reporter info
                line += f"\n   📝 Reporter: <@{report.reporter_id}>"
                
                # Reported user info (if applicable)
                if report.reported_user_id:
                    line += f" → <@{report.reported_user_id}>"
                
                # Admin assignment info
                if report.admin_id:
                    resolved_date = ""
                    if report.resolved_at:
                        resolved_date = f" on {report.resolved_at.strftime('%m/%d %H:%M')}"
                    line += f"\n   👤 Handled by: <@{report.admin_id}>{resolved_date}"
                else:
                    line += f"\n   👤 Unassigned"
                
                # Creation date
                line += f"\n   📅 Created: {created_date}"
                
                # Add admin response if available
                if report.admin_response:
                    response_preview = report.admin_response[:50] + "..." if len(report.admin_response) > 50 else report.admin_response
                    line += f"\n   💬 Response: \"{response_preview}\""
                
                report_lines.append(line)
            
            # Split into multiple fields if too many reports to avoid embed limits
            if len(reports) <= 5:
                embed.add_field(
                    name="Reports",
                    value="\n\n".join(report_lines),
                    inline=False
                )
            else:
                # Split into chunks for better readability
                chunk_size = 3
                for i in range(0, len(report_lines), chunk_size):
                    chunk = report_lines[i:i+chunk_size]
                    field_name = f"Reports {i+1}-{min(i+chunk_size, len(reports))}"
                    embed.add_field(
                        name=field_name,
                        value="\n\n".join(chunk),
                        inline=False
                    )
            
            # Add legend and instructions
            embed.add_field(
                name="📋 Legend",
                value="🟡 Pending • 🔍 Investigating • ✅ Resolved • ❌ Dismissed • 🔺 Escalated",
                inline=False
            )
            
            embed.set_footer(text="Use /get_report <id> for details • /review_report <id> to take action")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            self.logger.info(f"[admin_reports.list_reports] Report list requested by {interaction.user.id}")
            
        except Exception as e:
            self.logger.error(f"[admin_reports.list_reports] Error listing reports: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ **Error**: Failed to list reports. Please try again later.",
                ephemeral=True
            )
    
    @list_reports.autocomplete('status')
    async def status_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete for report status."""
        statuses = [
            ('Pending', 'pending'),
            ('Resolved', 'resolved'),
            ('Dismissed', 'dismissed'),
            ('Escalated', 'escalated'),
            ('Investigating', 'investigating')
        ]
        
        return [
            app_commands.Choice(name=name, value=value)
            for name, value in statuses
            if current.lower() in name.lower()
        ][:25]
    
    @list_reports.autocomplete('report_type')
    async def list_report_type_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete for report types in list command."""
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
        ][:25]
    
    @app_commands.command(name="get_report", description="Get detailed information about a specific report")
    @app_commands.describe(report_id="ID of the report to view")
    async def get_report(
        self,
        interaction: discord.Interaction,
        report_id: int
    ):
        """Command to get detailed report information."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get report from database
            async with self.bot.db_manager.get_pg_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Report).where(Report.id == report_id)
                )
                report = result.scalar_one_or_none()
                
                if not report:
                    await interaction.followup.send(
                        f"❌ **Error**: Report ID `{report_id}` not found.",
                        ephemeral=True
                    )
                    return
            
            # Create detailed embed
            status_color = {
                'pending': 0xffd700,
                'resolved': 0x00ff00,
                'dismissed': 0xff0000,
                'escalated': 0xff6600,
                'investigating': 0x3498db
            }.get(report.status, 0x888888)
            
            embed = discord.Embed(
                title=f"📋 Report Details - ID: {report.id}",
                color=status_color,
                timestamp=report.created_at
            )
            
            embed.add_field(name="Status", value=report.status.title(), inline=True)
            embed.add_field(name="Type", value=report.report_type.replace('_', ' ').title(), inline=True)
            embed.add_field(name="Reporter", value=f"<@{report.reporter_id}> ({report.reporter_id})", inline=True)
            
            if report.reported_user_id:
                embed.add_field(name="Reported User", value=f"<@{report.reported_user_id}> ({report.reported_user_id})", inline=True)
            
            embed.add_field(name="Channel", value=f"<#{report.channel_id}>", inline=True)
            embed.add_field(name="Guild ID", value=str(report.guild_id), inline=True)
            
            embed.add_field(name="Description", value=report.description, inline=False)
            
            if report.admin_id:
                embed.add_field(name="Reviewed By", value=f"<@{report.admin_id}> ({report.admin_id})", inline=True)
            
            if report.resolved_at:
                embed.add_field(name="Resolved At", value=discord.utils.format_dt(report.resolved_at, 'F'), inline=True)
            
            if report.admin_response:
                embed.add_field(name="Admin Response", value=report.admin_response, inline=False)
            
            embed.set_footer(text=f"Created at {report.created_at.strftime('%Y-%m-%d %H:%M:%S')} UTC")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            self.logger.info(f"[admin_reports.get_report] Report {report_id} details viewed by {interaction.user.id}")
            
        except Exception as e:
            self.logger.error(f"[admin_reports.get_report] Error getting report {report_id}: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ **Error**: Failed to get report details. Please try again later.",
                ephemeral=True
            )
    
    async def _notify_reporter(
        self,
        report: Report,
        action: str,
        response: str,
        admin: discord.Member
    ):
        """Send notification to the reporter about report resolution."""
        try:
            reporter = self.bot.get_user(report.reporter_id)
            if not reporter:
                self.logger.warning(f"[admin_reports._notify_reporter] Reporter {report.reporter_id} not found")
                return
            
            action_color = {
                'resolved': 0x00ff00,
                'dismissed': 0xff6600,
                'escalated': 0xff0000,
                'investigating': 0x3498db
            }.get(action, 0x888888)
            
            action_messages = {
                'resolved': "Your report has been **resolved**",
                'dismissed': "Your report has been **dismissed**", 
                'escalated': "Your report has been **escalated** to higher authorities for further review",
                'investigating': "Your report is being **investigated** by our moderation team"
            }
            
            # If there's a response, prioritize communication over status
            if response:
                description = f"**Update from our moderation team** (Status: {action.title()})"
            else:
                description = action_messages.get(action, f"Your report status has been updated to **{action}**")
            
            embed = discord.Embed(
                title=f"📋 Report Update - ID: {report.id}",
                description=description,
                color=action_color,
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(name="Report Type", value=report.report_type.replace('_', ' ').title(), inline=True)
            embed.add_field(name="Status", value=action.title(), inline=True)
            
            if response:
                embed.add_field(name="Administrator Response", value=response, inline=False)
            
            # Set appropriate footer based on status
            if action in ['resolved', 'dismissed']:
                footer_text = "Thank you for helping keep our server safe. This report is now closed."
            elif action == 'escalated':
                footer_text = "Your report remains active and may receive further updates."
            elif action == 'investigating':
                footer_text = "We may contact you for additional information if needed."
            else:
                footer_text = "Thank you for helping keep our server safe."
            
            embed.set_footer(text=footer_text)
            
            try:
                await reporter.send(embed=embed)
                self.logger.info(f"[admin_reports._notify_reporter] Notification sent to reporter {report.reporter_id}")
            except discord.Forbidden:
                self.logger.warning(f"[admin_reports._notify_reporter] Cannot DM reporter {report.reporter_id}")
            
        except Exception as e:
            self.logger.error(f"[admin_reports._notify_reporter] Error notifying reporter: {e}", exc_info=True)
    
    async def _send_admin_log(
        self,
        report: Report,
        action: str,
        response: Optional[str],
        admin: discord.Member
    ):
        """Send admin log message about report resolution."""
        try:
            admin_channel = self.bot.get_channel(self.bot.admin_notification_channel_id)
            if not admin_channel:
                return
            
            action_emoji = {
                'resolved': '✅',
                'dismissed': '❌',
                'escalated': '🔺',
                'investigating': '🔍'
            }.get(action, '📋')
            
            embed = discord.Embed(
                title=f"{action_emoji} Report {action.title()} - ID: {report.id}",
                color=0x3498db,
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(name="Type", value=report.report_type.replace('_', ' ').title(), inline=True)
            embed.add_field(name="Reporter", value=f"<@{report.reporter_id}>", inline=True)
            embed.add_field(name="Admin", value=admin.mention, inline=True)
            
            if report.reported_user_id:
                embed.add_field(name="Reported User", value=f"<@{report.reported_user_id}>", inline=True)
            
            if response:
                embed.add_field(name="Response", value=response[:500] + "..." if len(response) > 500 else response, inline=False)
            
            await admin_channel.send(embed=embed)
            
        except Exception as e:
            self.logger.error(f"[admin_reports._send_admin_log] Error sending admin log: {e}", exc_info=True)
    
    async def _update_report_queue_embed(self):
        """Update the persistent report queue embed."""
        try:
            # Import UserReportsCog method to avoid code duplication
            from cogs.user_reports import UserReportsCog
            user_reports_cog = self.bot.get_cog('UserReportsCog')
            if user_reports_cog:
                await user_reports_cog._update_report_queue_embed()
            
        except Exception as e:
            self.logger.error(f"[admin_reports._update_report_queue_embed] Error updating queue: {e}", exc_info=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(AdminReportsCog(bot))
    logging.getLogger('cogs.admin_reports').info("[admin_reports.setup] Admin reports cog loaded")