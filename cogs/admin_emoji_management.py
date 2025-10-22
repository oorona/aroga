"""
Admin Emoji Management Cog - Commands for administrators to manage emoji proposals

This cog handles admin functionality for reviewing, approving, and managing
emoji proposals including LLM-assisted suggestions.
"""

import logging
from datetime import datetime
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from database.db_models import Proposal


class AdminEmojiManagementCog(commands.Cog):
    """Cog for admin emoji proposal management functionality."""
    
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('cogs.admin_emoji_management')
    
    def cog_check(self, ctx):
        """Check if user has admin permissions."""
        return self.bot.has_admin_permissions(ctx.author)
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if user has admin permissions for slash commands."""
        return self.bot.has_admin_permissions(interaction.user)
    
    @app_commands.command(name="review_proposal", description="Review and take action on a user proposal")
    @app_commands.describe(
        proposal_id="ID of the proposal to review",
        action="Action to take on the proposal",
        final_name="Final name to use (optional - overrides LLM suggestion)",
        response="Response message to send to the proposer (optional)"
    )
    async def review_proposal(
        self,
        interaction: discord.Interaction,
        proposal_id: int,
        action: str,
        final_name: Optional[str] = None,
        response: Optional[str] = None
    ):
        """Command for admins to review and act on proposals."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            self.logger.info(f"[admin_emoji_management.review_proposal] Proposal {proposal_id} being reviewed by {interaction.user.id}")
            
            # Validate action
            valid_actions = ['approved', 'rejected', 'needs_changes']
            if action not in valid_actions:
                await interaction.followup.send(
                    f"❌ **Error**: Invalid action. Valid actions: {', '.join(valid_actions)}",
                    ephemeral=True
                )
                return
            
            # Get proposal from database
            async with self.bot.db_manager.get_pg_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Proposal).where(Proposal.proposal_id == proposal_id)
                )
                proposal = result.scalar_one_or_none()
                
                if not proposal:
                    await interaction.followup.send(
                        f"❌ **Error**: Proposal ID `{proposal_id}` not found.",
                        ephemeral=True
                    )
                    return
                
                # Only allow updates to pending proposals or those needing changes
                if proposal.status not in ['pending', 'needs_changes']:
                    await interaction.followup.send(
                        f"❌ **Error**: Proposal `{proposal_id}` has already been {proposal.status}.",
                        ephemeral=True
                    )
                    return
                
                # Validate final_name if provided based on proposal type
                if final_name:
                    if proposal.proposal_type == 'emoji':
                        if not self._validate_emoji_name(final_name):
                            await interaction.followup.send(
                                "❌ **Error**: Emoji name must be 2-32 characters, alphanumeric and underscores only.",
                                ephemeral=True
                            )
                            return
                    elif proposal.proposal_type == 'channel':
                        if not self._validate_channel_name(final_name):
                            await interaction.followup.send(
                                "❌ **Error**: Channel name must be valid Discord channel name format.",
                                ephemeral=True
                            )
                            return
                
                # Update proposal status
                proposal.status = action
                if final_name:
                    proposal.final_name = final_name.strip().lower()
                
                await session.commit()
            
            # If approved, create the emoji or channel
            if action == 'approved':
                if proposal.proposal_type == 'emoji':
                    emoji_created = await self._create_emoji(proposal, interaction.guild)
                    if not emoji_created:
                        # Revert status if emoji creation failed
                        async with self.bot.db_manager.get_pg_session() as session:
                            result = await session.execute(
                                select(Proposal).where(Proposal.proposal_id == proposal_id)
                            )
                            proposal_update = result.scalar_one()
                            proposal_update.status = 'needs_changes'
                            await session.commit()
                        
                        await interaction.followup.send(
                            f"❌ **Error**: Failed to create emoji. Proposal marked as needs changes.",
                            ephemeral=True
                        )
                        return
                    else:
                        # Send public announcement for emoji
                        await self._send_emoji_announcement(proposal)
                elif proposal.proposal_type == 'channel':
                    channel_created = await self._create_channel(proposal, interaction.guild)
                    if not channel_created:
                        # Revert status if channel creation failed
                        async with self.bot.db_manager.get_pg_session() as session:
                            result = await session.execute(
                                select(Proposal).where(Proposal.proposal_id == proposal_id)
                            )
                            proposal_update = result.scalar_one()
                            proposal_update.status = 'needs_changes'
                            await session.commit()
                        
                        await interaction.followup.send(
                            f"❌ **Error**: Failed to create channel. Proposal marked as needs changes.",
                            ephemeral=True
                        )
                        return
            
            # Send confirmation to admin
            embed = discord.Embed(
                title="✅ Proposal Reviewed",
                description=f"Proposal `{proposal_id}` has been **{action}**",
                color=0x00ff00 if action == 'approved' else 0xff9900,
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(name="Proposal Type", value=proposal.proposal_type.title(), inline=True)
            embed.add_field(name="Proposer", value=f"<@{proposal.user_id}>", inline=True)
            embed.add_field(name="Reviewed By", value=interaction.user.mention, inline=True)
            
            if proposal.proposal_type == 'emoji':
                emoji_name = final_name or proposal.llm_suggestion or proposal.original_text
                embed.add_field(name="Emoji Name", value=f":{emoji_name}:", inline=True)
                if proposal.file_url:
                    embed.set_thumbnail(url=proposal.file_url)
            elif proposal.proposal_type == 'channel':
                channel_name = final_name or proposal.llm_suggestion or proposal.original_text
                embed.add_field(name="Channel Name", value=f"#{channel_name}", inline=True)
                embed.add_field(name="Description", value=proposal.original_text[:200] + "..." if len(proposal.original_text) > 200 else proposal.original_text, inline=False)
            
            if final_name:
                if proposal.proposal_type == 'emoji':
                    embed.add_field(name="Final Name", value=f":{final_name}:", inline=True)
                else:
                    embed.add_field(name="Final Name", value=f"#{final_name}", inline=True)
            
            if response:
                embed.add_field(name="Response Sent", value=response[:100] + "..." if len(response) > 100 else response, inline=False)
            
            # Add status information
            if action == 'needs_changes':
                embed.add_field(name="Next Steps", value="Proposer will be notified to make changes", inline=False)
            elif action == 'approved':
                if proposal.proposal_type == 'emoji':
                    embed.add_field(name="Status", value="Emoji has been added to the server", inline=False)
                elif proposal.proposal_type == 'channel':
                    embed.add_field(name="Status", value="Channel has been created in the proposed category", inline=False)
                else:
                    embed.add_field(name="Status", value="Proposal approved and proposer notified", inline=False)
            else:
                embed.add_field(name="Status", value="Proposal rejected and proposer notified", inline=False)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            # Send notification to proposer
            await self._notify_proposer(proposal, action, final_name, response, interaction.user)
            
            # Update proposal queue embed
            await self._update_proposal_queue_embed()
            
            # Send admin log
            await self._send_admin_log(proposal, action, final_name, response, interaction.user)
            
            self.logger.info(f"[admin_emoji_management.review_proposal] Proposal {proposal_id} marked as {action} by {interaction.user.id}")
            
        except Exception as e:
            self.logger.error(f"[admin_emoji_management.review_proposal] Error reviewing proposal {proposal_id}: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ **Error**: Failed to review proposal. Please try again later.",
                ephemeral=True
            )
    
    @review_proposal.autocomplete('action')
    async def action_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete for proposal actions."""
        actions = [
            ('Approved', 'approved'),
            ('Rejected', 'rejected'),
            ('Needs Changes', 'needs_changes')
        ]
        
        return [
            app_commands.Choice(name=name, value=value)
            for name, value in actions
            if current.lower() in name.lower()
        ][:25]
    
    @app_commands.command(name="list_proposals", description="List proposals with filtering options")
    @app_commands.describe(
        proposal_type="Filter by proposal type (emoji or channel)",
        status="Filter by proposal status",
        limit="Number of proposals to show (default: 10, max: 25)"
    )
    async def list_proposals(
        self,
        interaction: discord.Interaction,
        proposal_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10
    ):
        """Command to list proposals with filters."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            if limit > 25:
                limit = 25
            elif limit < 1:
                limit = 1
            
            # Build query
            async with self.bot.db_manager.get_pg_session() as session:
                from sqlalchemy import select, desc
                query = select(Proposal).order_by(desc(Proposal.created_at)).limit(limit)
                
                if proposal_type:
                    query = query.where(Proposal.proposal_type == proposal_type)
                
                if status:
                    query = query.where(Proposal.status == status)
                
                result = await session.execute(query)
                proposals = result.scalars().all()
            
            if not proposals:
                await interaction.followup.send(
                    "📋 No proposals found matching the specified criteria.",
                    ephemeral=True
                )
                return
            
            # Calculate summary statistics
            status_counts = {}
            type_counts = {}
            
            for proposal in proposals:
                status_counts[proposal.status] = status_counts.get(proposal.status, 0) + 1
                type_counts[proposal.proposal_type] = type_counts.get(proposal.proposal_type, 0) + 1
            
            # Create embed
            embed = discord.Embed(
                title="📋 Proposals List",
                description=f"Showing {len(proposals)} proposals",
                color=0x9b59b6,
                timestamp=discord.utils.utcnow()
            )
            
            if proposal_type:
                embed.description += f" of type: **{proposal_type}**"
            if status:
                embed.description += f" with status: **{status}**"
            
            # Add summary statistics
            status_summary = []
            for status_name, count in status_counts.items():
                emoji = {
                    'pending': '🟡',
                    'approved': '✅',
                    'rejected': '❌',
                    'needs_changes': '🔄'
                }.get(status_name, '❓')
                status_summary.append(f"{emoji} {status_name.replace('_', ' ').title()}: {count}")
            
            embed.add_field(
                name="📊 Summary by Status",
                value="\n".join(status_summary),
                inline=True
            )
            
            # Add type statistics
            type_summary = []
            for type_name, count in type_counts.items():
                emoji = '🎨' if type_name == 'emoji' else '💬'
                type_summary.append(f"{emoji} {type_name.title()}: {count}")
            
            embed.add_field(
                name="📊 Summary by Type",
                value="\n".join(type_summary),
                inline=True
            )
            
            embed.add_field(name="\u200b", value="\u200b", inline=True)  # Empty field for spacing
            
            # Show detailed proposal list
            proposal_lines = []
            for proposal in proposals[:10]:  # Show max 10 proposals
                status_emoji = {
                    'pending': '🟡',
                    'approved': '✅',
                    'rejected': '❌',
                    'needs_changes': '🔄'
                }.get(proposal.status, '❓')
                
                type_emoji = '🎨' if proposal.proposal_type == 'emoji' else '💬'
                created_date = proposal.created_at.strftime('%m/%d %H:%M')
                
                # Build proposal line
                if proposal.proposal_type == 'emoji':
                    name = proposal.final_name or proposal.llm_suggestion or proposal.original_text
                    line = f"{status_emoji}{type_emoji} `{proposal.proposal_id}` :{name}: - <@{proposal.user_id}> ({created_date})"
                else:
                    name = proposal.final_name or proposal.original_text
                    line = f"{status_emoji}{type_emoji} `{proposal.proposal_id}` {name} - <@{proposal.user_id}> ({created_date})"
                
                proposal_lines.append(line)
            
            if len(proposals) <= 5:
                embed.add_field(
                    name="Proposals",
                    value="\n".join(proposal_lines),
                    inline=False
                )
            else:
                # Split into chunks for better readability
                chunk_size = 5
                for i in range(0, len(proposal_lines), chunk_size):
                    chunk = proposal_lines[i:i+chunk_size]
                    field_name = f"Proposals {i+1}-{min(i+chunk_size, len(proposals))}"
                    embed.add_field(
                        name=field_name,
                        value="\n".join(chunk),
                        inline=False
                    )
            
            # Add legend
            embed.add_field(
                name="📋 Legend",
                value="🟡 Pending • ✅ Approved • ❌ Rejected • 🔄 Needs Changes\n🎨 Emoji • 💬 Channel",
                inline=False
            )
            
            embed.set_footer(text="Use /get_proposal <id> for details • /review_proposal <id> to take action")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            self.logger.info(f"[admin_emoji_management.list_proposals] Proposal list requested by {interaction.user.id}")
            
        except Exception as e:
            self.logger.error(f"[admin_emoji_management.list_proposals] Error listing proposals: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ **Error**: Failed to list proposals. Please try again later.",
                ephemeral=True
            )
    
    @list_proposals.autocomplete('proposal_type')
    async def proposal_type_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete for proposal types."""
        types = [
            ('Emoji', 'emoji'),
            ('Channel', 'channel')
        ]
        
        return [
            app_commands.Choice(name=name, value=value)
            for name, value in types
            if current.lower() in name.lower()
        ]
    
    @list_proposals.autocomplete('status')
    async def status_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete for proposal statuses."""
        statuses = [
            ('Pending', 'pending'),
            ('Approved', 'approved'),
            ('Rejected', 'rejected'),
            ('Needs Changes', 'needs_changes')
        ]
        
        return [
            app_commands.Choice(name=name, value=value)
            for name, value in statuses
            if current.lower() in name.lower()
        ]
    
    @app_commands.command(name="get_proposal", description="Get detailed information about a specific proposal")
    @app_commands.describe(proposal_id="ID of the proposal to view")
    async def get_proposal(self, interaction: discord.Interaction, proposal_id: int):
        """Command to get detailed information about a specific proposal."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            async with self.bot.db_manager.get_pg_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Proposal).where(Proposal.proposal_id == proposal_id)
                )
                proposal = result.scalar_one_or_none()
                
                if not proposal:
                    await interaction.followup.send(
                        f"❌ **Error**: Proposal ID `{proposal_id}` not found.",
                        ephemeral=True
                    )
                    return
            
            # Create detailed embed
            status_colors = {
                'pending': 0xffa500,
                'approved': 0x00ff00,
                'rejected': 0xff0000,
                'needs_changes': 0xff9900
            }
            
            status_emoji = {
                'pending': '🟡',
                'approved': '✅',
                'rejected': '❌',
                'needs_changes': '🔄'
            }.get(proposal.status, '❓')
            
            embed = discord.Embed(
                title=f"{status_emoji} Proposal Details - ID: {proposal_id}",
                description=f"**Status**: {proposal.status.replace('_', ' ').title()}",
                color=status_colors.get(proposal.status, 0x888888),
                timestamp=proposal.created_at
            )
            
            # Basic information
            embed.add_field(name="Type", value=proposal.proposal_type.title(), inline=True)
            embed.add_field(name="Proposer", value=f"<@{proposal.user_id}>", inline=True)
            embed.add_field(name="Created", value=f"<t:{int(proposal.created_at.timestamp())}:R>", inline=True)
            
            # Proposal content
            if proposal.proposal_type == 'emoji':
                embed.add_field(name="Original Name", value=f":{proposal.original_text}:", inline=True)
                
                if proposal.llm_suggestion:
                    embed.add_field(name="LLM Suggestion", value=f":{proposal.llm_suggestion}:", inline=True)
                else:
                    embed.add_field(name="LLM Suggestion", value="*Not processed yet*", inline=True)
                
                if proposal.final_name:
                    embed.add_field(name="Final Name", value=f":{proposal.final_name}:", inline=True)
                else:
                    embed.add_field(name="Final Name", value="*Not set*", inline=True)
                
                if proposal.file_url:
                    embed.set_image(url=proposal.file_url)
                    embed.add_field(name="Image URL", value=f"[View Original]({proposal.file_url})", inline=False)
            else:
                # Channel proposal
                embed.add_field(name="Original Text", value=proposal.original_text, inline=False)
                
                if proposal.llm_suggestion:
                    embed.add_field(name="LLM Suggestion", value=proposal.llm_suggestion, inline=True)
                else:
                    embed.add_field(name="LLM Suggestion", value="*Not processed yet*", inline=True)
                
                if proposal.final_name:
                    embed.add_field(name="Final Name", value=proposal.final_name, inline=True)
                else:
                    embed.add_field(name="Final Name", value="*Not set*", inline=True)
            
            # Admin information
            if proposal.status != 'pending':
                embed.add_field(name="Created", value=f"<t:{int(proposal.created_at.timestamp())}:R>", inline=True)
            
            # Action buttons for pending proposals and those needing changes
            if proposal.status in ['pending', 'needs_changes']:
                embed.add_field(
                    name="Available Actions",
                    value="Use `/review_proposal` to approve, reject, or request changes",
                    inline=False
                )
            
            embed.set_footer(text=f"Proposal ID: {proposal_id}")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            self.logger.info(f"[admin_emoji_management.get_proposal] Proposal {proposal_id} viewed by {interaction.user.id}")
            
        except Exception as e:
            self.logger.error(f"[admin_emoji_management.get_proposal] Error getting proposal {proposal_id}: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ **Error**: Failed to retrieve proposal. Please try again later.",
                ephemeral=True
            )
    
    def _validate_emoji_name(self, name: str) -> bool:
        """Validate emoji name according to Discord requirements."""
        if not name or len(name) < 2 or len(name) > 32:
            return False
        
        allowed_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_')
        if not all(c in allowed_chars for c in name):
            return False
        
        return True
    
    def _validate_channel_name(self, name: str) -> bool:
        """Validate channel name according to Discord requirements (allows emojis and special chars)."""
        if not name or len(name) < 1 or len(name) > 100:
            return False
        
        # Discord channels allow emojis and many special characters
        # Main restrictions: no spaces (replaced with hyphens), reasonable length
        # The emoji・name format should be allowed
        
        # Check for basic validity - allow emojis, special chars, but not just whitespace
        cleaned = name.strip()
        if not cleaned:
            return False
        
        # Allow the emoji・name format and other valid Discord channel patterns
        return True
    
    async def _create_emoji(self, proposal: Proposal, guild: discord.Guild) -> bool:
        """Create the emoji in the guild."""
        try:
            # Get the emoji name to use
            emoji_name = proposal.final_name or proposal.llm_suggestion or proposal.original_text
            
            # Download the image
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(proposal.file_url) as response:
                    if response.status != 200:
                        self.logger.error(f"[admin_emoji_management._create_emoji] Failed to download emoji file: HTTP {response.status}")
                        return False
                    
                    image_data = await response.read()
            
            # Create the emoji
            emoji = await guild.create_custom_emoji(
                name=emoji_name,
                image=image_data,
                reason=f"Approved emoji proposal #{proposal.proposal_id}"
            )
            
            self.logger.info(f"[admin_emoji_management._create_emoji] Created emoji :{emoji_name}: (ID: {emoji.id})")
            return True
            
        except discord.HTTPException as e:
            self.logger.error(f"[admin_emoji_management._create_emoji] Discord API error creating emoji: {e}")
            return False
        except Exception as e:
            self.logger.error(f"[admin_emoji_management._create_emoji] Error creating emoji: {e}", exc_info=True)
            return False
    
    async def _create_channel(self, proposal: Proposal, guild: discord.Guild) -> bool:
        """Create the channel in the guild."""
        try:
            # Get the channel name to use
            channel_name = proposal.final_name or proposal.llm_suggestion or proposal.original_text
            
            # Clean and validate channel name
            channel_name = self._clean_channel_name(channel_name)
            if not self._validate_channel_name(channel_name):
                self.logger.error(f"[admin_emoji_management._create_channel] Invalid channel name: {channel_name}")
                return False
            
            # Get the proposed category
            proposed_category = guild.get_channel(self.bot.proposed_channel_category_id)
            if not proposed_category:
                self.logger.error(f"[admin_emoji_management._create_channel] Proposed category not found")
                return False
            
            # Create the channel
            channel = await guild.create_text_channel(
                name=channel_name,
                category=proposed_category,
                topic=f"Channel created from proposal #{proposal.proposal_id}: {proposal.original_text[:100]}",
                reason=f"Approved channel proposal #{proposal.proposal_id}"
            )
            
            # Send welcome message to the new channel
            welcome_embed = discord.Embed(
                title="🎉 Welcome to your new channel!",
                description=f"This channel was created from proposal #{proposal.proposal_id}",
                color=0x00ff00,
                timestamp=discord.utils.utcnow()
            )
            
            welcome_embed.add_field(name="Proposed by", value=f"<@{proposal.user_id}>", inline=True)
            welcome_embed.add_field(name="Channel Purpose", value=proposal.original_text[:500] + "..." if len(proposal.original_text) > 500 else proposal.original_text, inline=False)
            welcome_embed.set_footer(text="This channel can be promoted to permanent status based on activity")
            
            await channel.send(embed=welcome_embed)
            
            # Send public announcement
            await self._send_channel_announcement(proposal, channel)
            
            self.logger.info(f"[admin_emoji_management._create_channel] Created channel #{channel_name} (ID: {channel.id})")
            return True
            
        except discord.HTTPException as e:
            self.logger.error(f"[admin_emoji_management._create_channel] Discord API error creating channel: {e}")
            return False
        except Exception as e:
            self.logger.error(f"[admin_emoji_management._create_channel] Error creating channel: {e}", exc_info=True)
            return False
    
    def _clean_channel_name(self, name: str) -> str:
        """Clean and format channel name according to Discord standards with emoji・name format."""
        if not name:
            return "unnamed-channel"
        
        # Check if name already has the emoji・name format
        if '・' in name:
            return name.strip()  # Keep the original format if it uses the separator
        
        # If it's a plain name, clean it normally
        cleaned = name.strip().lower()
        
        # Replace spaces with hyphens
        cleaned = cleaned.replace(' ', '-')
        
        # Remove invalid characters (keep only alphanumeric, hyphens, underscores for name part)
        import re
        cleaned = re.sub(r'[^a-z0-9\-_]', '', cleaned)
        
        # Remove consecutive hyphens/underscores
        cleaned = re.sub(r'[-_]+', '-', cleaned)
        
        # Remove leading/trailing hyphens
        cleaned = cleaned.strip('-_')
        
        # Ensure minimum length
        if len(cleaned) < 1:
            cleaned = "unnamed-channel"
        
        # Truncate to 100 characters
        return cleaned[:100]
    
    def _validate_channel_name(self, name: str) -> bool:
        """Validate channel name according to Discord requirements and emoji・name format."""
        if not name or len(name) < 1 or len(name) > 100:
            return False
        
        # Check for emoji・name format
        if '・' in name:
            parts = name.split('・', 1)
            if len(parts) != 2:
                return False
            
            emoji_part = parts[0].strip()
            name_part = parts[1].strip()
            
            # Validate emoji part (should be 1-4 characters, likely emoji)
            if not emoji_part or len(emoji_part) > 4:
                return False
            
            # Validate name part (Discord channel naming rules)
            if not name_part:
                return False
            
            import re
            if not re.match(r'^[a-z0-9\-_]+$', name_part):
                return False
            
            # Can't start or end with hyphen
            if name_part.startswith('-') or name_part.endswith('-'):
                return False
            
            return True
        else:
            # Fallback validation for plain names
            import re
            if not re.match(r'^[a-z0-9\-_]+$', name):
                return False
            
            # Can't start or end with hyphen
            if name.startswith('-') or name.endswith('-'):
                return False
            
            return True
    
    async def _send_channel_announcement(self, proposal: Proposal, channel: discord.TextChannel):
        """Send public announcement about new channel creation."""
        try:
            # Get public announcement channel
            announcement_channel_id = getattr(self.bot, 'public_announcement_channel_id', None)
            if not announcement_channel_id:
                self.logger.warning("[admin_emoji_management._send_channel_announcement] No public announcement channel configured")
                return
            
            announcement_channel = self.bot.get_channel(announcement_channel_id)
            if not announcement_channel:
                self.logger.warning("[admin_emoji_management._send_channel_announcement] Public announcement channel not found")
                return
            
            # Create embed for channel announcement
            embed = discord.Embed(
                title="🎉 New Channel Created!",
                description=f"A new channel {channel.mention} has been created based on a community proposal!",
                color=0x00ff00,  # Green color for success
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(
                name="👤 Proposed by",
                value=f"<@{proposal.user_id}>",
                inline=True
            )
            
            embed.add_field(
                name="📝 Channel Purpose",
                value=proposal.original_text[:500] + "..." if len(proposal.original_text) > 500 else proposal.original_text,
                inline=False
            )
            
            embed.add_field(
                name="💡 Next Steps",
                value="Check it out and join the conversation! Active channels may be promoted to permanent status based on community engagement.",
                inline=False
            )
            
            embed.set_footer(text="Community-driven channel creation")
            
            await announcement_channel.send(embed=embed)
            
            self.logger.info(f"[admin_emoji_management._send_channel_announcement] Public announcement sent for channel {channel.name}")
            
        except Exception as e:
            self.logger.error(f"[admin_emoji_management._send_channel_announcement] Error sending announcement: {e}", exc_info=True)
    
    async def _send_emoji_announcement(self, proposal: Proposal):
        """Send public announcement about new emoji creation."""
        try:
            # Get public announcement channel
            announcement_channel_id = getattr(self.bot, 'public_announcement_channel_id', None)
            if not announcement_channel_id:
                self.logger.warning("[admin_emoji_management._send_emoji_announcement] No public announcement channel configured")
                return
            
            announcement_channel = self.bot.get_channel(announcement_channel_id)
            if not announcement_channel:
                self.logger.warning("[admin_emoji_management._send_emoji_announcement] Public announcement channel not found")
                return
            
            # Get emoji name
            emoji_name = proposal.final_name or proposal.original_text
            
            # Create embed for emoji announcement
            embed = discord.Embed(
                title="✨ New Emoji Added!",
                description=f"A new emoji :{emoji_name}: has been added to the server based on a community proposal!",
                color=0xffcc00,  # Gold color for emoji
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(
                name="👤 Proposed by",
                value=f"<@{proposal.user_id}>",
                inline=True
            )
            
            embed.add_field(
                name="😊 Emoji Name",
                value=f":{emoji_name}:",
                inline=True
            )
            
            if proposal.original_text and proposal.original_text != emoji_name:
                embed.add_field(
                    name="📝 Description",
                    value=proposal.original_text[:300] + "..." if len(proposal.original_text) > 300 else proposal.original_text,
                    inline=False
                )
            
            embed.add_field(
                name="🎉 Usage",
                value=f"You can now use this emoji by typing `:{emoji_name}:` in your messages!",
                inline=False
            )
            
            embed.set_footer(text="Community-driven emoji creation")
            
            await announcement_channel.send(embed=embed)
            
            self.logger.info(f"[admin_emoji_management._send_emoji_announcement] Public announcement sent for emoji :{emoji_name}:")
            
        except Exception as e:
            self.logger.error(f"[admin_emoji_management._send_emoji_announcement] Error sending announcement: {e}", exc_info=True)
    
    async def _notify_proposer(
        self,
        proposal: Proposal,
        action: str,
        final_name: Optional[str],
        response: Optional[str],
        admin: discord.Member
    ):
        """Send notification to the proposer about proposal resolution."""
        try:
            proposer = self.bot.get_user(proposal.user_id)
            if not proposer:
                self.logger.warning(f"[admin_emoji_management._notify_proposer] Proposer {proposal.user_id} not found")
                return
            
            action_color = {
                'approved': 0x00ff00,
                'rejected': 0xff0000,
                'needs_changes': 0xff9900
            }.get(action, 0x888888)
            
            action_messages = {
                'approved': "Your proposal has been **approved**! 🎉",
                'rejected': "Your proposal has been **rejected**",
                'needs_changes': "Your proposal **needs changes** before it can be approved"
            }
            
            embed = discord.Embed(
                title=f"🎨 Proposal Update - ID: {proposal.proposal_id}",
                description=action_messages.get(action, f"Your proposal status has been updated to **{action}**"),
                color=action_color,
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(name="Proposal Type", value=proposal.proposal_type.title(), inline=True)
            embed.add_field(name="Status", value=action.replace('_', ' ').title(), inline=True)
            
            if proposal.proposal_type == 'emoji':
                emoji_name = final_name or proposal.llm_suggestion or proposal.original_text
                embed.add_field(name="Emoji Name", value=f":{emoji_name}:", inline=True)
                if proposal.file_url:
                    embed.set_thumbnail(url=proposal.file_url)
            elif proposal.proposal_type == 'channel':
                channel_name = final_name or proposal.llm_suggestion or proposal.original_text
                embed.add_field(name="Channel Name", value=f"#{channel_name}", inline=True)
            
            if response:
                embed.add_field(name="Administrator Response", value=response, inline=False)
            
            # Set appropriate footer based on action
            if action == 'approved':
                if proposal.proposal_type == 'emoji':
                    footer_text = "Your emoji has been added to the server! Thank you for contributing."
                elif proposal.proposal_type == 'channel':
                    footer_text = "Your channel has been created! Thank you for contributing to the community."
                else:
                    footer_text = "Thank you for your contribution to the server!"
            elif action == 'needs_changes':
                footer_text = "You can submit a new proposal with the requested changes."
            else:
                footer_text = "Thank you for your interest in contributing to the server."
            
            embed.set_footer(text=footer_text)
            
            try:
                await proposer.send(embed=embed)
                self.logger.info(f"[admin_emoji_management._notify_proposer] Notification sent to proposer {proposal.user_id}")
            except discord.Forbidden:
                self.logger.warning(f"[admin_emoji_management._notify_proposer] Cannot DM proposer {proposal.user_id}")
            
        except Exception as e:
            self.logger.error(f"[admin_emoji_management._notify_proposer] Error notifying proposer: {e}", exc_info=True)
    
    async def _send_admin_log(
        self,
        proposal: Proposal,
        action: str,
        final_name: Optional[str],
        response: Optional[str],
        admin: discord.Member
    ):
        """Send admin log message about proposal resolution."""
        try:
            admin_channel = self.bot.get_channel(self.bot.admin_notification_channel_id)
            if not admin_channel:
                return
            
            action_emoji = {
                'approved': '✅',
                'rejected': '❌',
                'needs_changes': '🔄'
            }.get(action, '📋')
            
            embed = discord.Embed(
                title=f"{action_emoji} Proposal {action.replace('_', ' ').title()} - ID: {proposal.proposal_id}",
                color=0x9b59b6,
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(name="Type", value=proposal.proposal_type.title(), inline=True)
            embed.add_field(name="Proposer", value=f"<@{proposal.user_id}>", inline=True)
            embed.add_field(name="Admin", value=admin.mention, inline=True)
            
            if proposal.proposal_type == 'emoji':
                emoji_name = final_name or proposal.llm_suggestion or proposal.original_text
                embed.add_field(name="Emoji Name", value=f":{emoji_name}:", inline=True)
            elif proposal.proposal_type == 'channel':
                channel_name = final_name or proposal.llm_suggestion or proposal.original_text
                embed.add_field(name="Channel Name", value=f"#{channel_name}", inline=True)
            
            if response:
                embed.add_field(name="Response", value=response[:500] + "..." if len(response) > 500 else response, inline=False)
            
            await admin_channel.send(embed=embed)
            
        except Exception as e:
            self.logger.error(f"[admin_emoji_management._send_admin_log] Error sending admin log: {e}", exc_info=True)
    
    async def _update_proposal_queue_embed(self):
        """Update the persistent proposal queue embed."""
        try:
            # Import method from user emoji proposals cog to avoid code duplication
            from cogs.user_emoji_proposals import UserEmojiProposalsCog
            user_proposals_cog = self.bot.get_cog('UserEmojiProposalsCog')
            if user_proposals_cog:
                await user_proposals_cog._update_proposal_queue_embed()
            
        except Exception as e:
            self.logger.error(f"[admin_emoji_management._update_proposal_queue_embed] Error updating queue: {e}", exc_info=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(AdminEmojiManagementCog(bot))
    logging.getLogger('cogs.admin_emoji_management').info("[admin_emoji_management.setup] Admin emoji management cog loaded")