"""
User Emoji Proposals Cog - Commands for users to propose custom emojis

This cog handles emoji submissions including validation, LLM processing,
database storage, and admin notifications.
"""

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image
import io

from database.db_models import Proposal


class UserEmojiProposalsCog(commands.Cog):
    """Cog for user emoji proposal functionality."""
    
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('cogs.user_emoji_proposals')
    
    @app_commands.command(name="propose_emoji", description="Propose a custom emoji for the server")
    @app_commands.describe(
        emoji_name="Name for the emoji (2-32 characters, alphanumeric and underscores only)",
        emoji_file="Image file for the emoji (PNG, JPG, GIF - max 256KB)",
        description="Brief description of the emoji and why it should be added"
    )
    async def propose_emoji(
        self,
        interaction: discord.Interaction,
        emoji_name: str,
        emoji_file: discord.Attachment,
        description: str
    ):
        """Command for users to submit emoji proposals."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            self.logger.info(f"[user_emoji_proposals.propose_emoji] Emoji proposal initiated by {interaction.user.id}")
            
            # Validate emoji name
            if not self._validate_emoji_name(emoji_name):
                await interaction.followup.send(
                    "❌ **Error**: Emoji name must be 2-32 characters, alphanumeric and underscores only (no spaces).",
                    ephemeral=True
                )
                return
            
            # Check if user already has a pending emoji proposal
            if await self._user_has_pending_emoji_proposal(interaction.user.id):
                await interaction.followup.send(
                    "❌ **Error**: You already have a pending emoji proposal. Please wait for it to be reviewed.",
                    ephemeral=True
                )
                return
            
            # Validate description
            if len(description.strip()) < 10:
                await interaction.followup.send(
                    "❌ **Error**: Description must be at least 10 characters long.",
                    ephemeral=True
                )
                return
            
            if len(description) > 500:
                await interaction.followup.send(
                    "❌ **Error**: Description cannot exceed 500 characters.",
                    ephemeral=True
                )
                return
            
            # Validate emoji file
            validation_result = await self._validate_emoji_file(emoji_file)
            if validation_result != "valid":
                await interaction.followup.send(f"❌ **Error**: {validation_result}", ephemeral=True)
                return
            
            # Sanitize inputs
            emoji_name = emoji_name.strip().lower()
            description = description.strip()
            
            # Store proposal in database
            proposal = Proposal(
                user_id=interaction.user.id,
                proposal_type='emoji',
                status='pending',
                original_text=emoji_name,
                llm_suggestion=None,  # Will be filled by LLM processing
                final_name=None,
                file_url=emoji_file.url
            )
            
            async with self.bot.db_manager.get_pg_session() as session:
                session.add(proposal)
                await session.commit()
                await session.refresh(proposal)
                proposal_id = proposal.proposal_id
            
            # Send confirmation to user
            embed = discord.Embed(
                title="✅ Emoji Proposed",
                description="Your emoji proposal has been submitted and will be reviewed by administrators.",
                color=0x00ff00,
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Proposal ID", value=f"`{proposal_id}`", inline=True)
            embed.add_field(name="Emoji Name", value=f":{emoji_name}:", inline=True)
            embed.add_field(name="Status", value="Pending Review", inline=True)
            embed.add_field(name="Description", value=description[:100] + "..." if len(description) > 100 else description, inline=False)
            
            # Show emoji preview
            embed.set_thumbnail(url=emoji_file.url)
            embed.set_footer(text="You will be notified when the proposal is reviewed.")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            # Send admin notification
            await self._send_admin_notification(proposal_id, interaction.user, emoji_name, description, emoji_file)
            
            # Update persistent embed queue
            await self._update_proposal_queue_embed()
            
            self.logger.info(f"[user_emoji_proposals.propose_emoji] Proposal {proposal_id} created by {interaction.user.id}")
            
        except Exception as e:
            self.logger.error(f"[user_emoji_proposals.propose_emoji] Error creating emoji proposal: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ **Error**: Failed to submit emoji proposal. Please try again later.",
                ephemeral=True
            )
    
    def _validate_emoji_name(self, name: str) -> bool:
        """Validate emoji name according to Discord requirements."""
        # Discord emoji names: 2-32 characters, alphanumeric and underscores only
        if not name or len(name) < 2 or len(name) > 32:
            return False
        
        # Only allow alphanumeric and underscores
        allowed_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_')
        if not all(c in allowed_chars for c in name):
            return False
        
        return True
    
    async def _validate_emoji_file(self, attachment: discord.Attachment) -> str:
        """
        Validate emoji file according to Discord requirements.
        Returns 'valid' if valid, or error message if invalid.
        """
        # Check file size (max 256KB)
        max_size = 256 * 1024  # 256KB in bytes
        if attachment.size > max_size:
            return f"File is too large ({attachment.size:,} bytes). Maximum size is 256KB."
        
        # Check file extension
        allowed_extensions = ['.png', '.jpg', '.jpeg', '.gif']
        file_extension = '.' + attachment.filename.lower().split('.')[-1] if '.' in attachment.filename else ''
        if file_extension not in allowed_extensions:
            return f"Invalid file type. Allowed formats: PNG, JPG, JPEG, GIF."
        
        try:
            # Download and validate image
            image_data = await attachment.read()
            
            # Validate it's actually an image
            try:
                with Image.open(io.BytesIO(image_data)) as img:
                    width, height = img.size
                    
                    # Check minimum dimensions (32x32)
                    if width < 32 or height < 32:
                        return f"Image too small ({width}x{height}). Minimum size is 32x32 pixels."
                    
                    # Check maximum dimensions (256x256)
                    if width > 256 or height > 256:
                        return f"Image too large ({width}x{height}). Maximum size is 256x256 pixels."
                    
                    # Recommend square aspect ratio (not strictly required but recommended)
                    if abs(width - height) > min(width, height) * 0.1:  # Allow 10% tolerance
                        # This is a warning, not an error
                        pass
                    
                    # Check format compatibility
                    if img.format not in ['PNG', 'JPEG', 'GIF']:
                        return f"Image format '{img.format}' not supported. Use PNG, JPEG, or GIF."
            
            except Exception as e:
                return f"Invalid or corrupted image file: {str(e)[:50]}"
            
        except Exception as e:
            return f"Failed to process image file: {str(e)[:50]}"
        
        return "valid"
    
    async def _user_has_pending_emoji_proposal(self, user_id: int) -> bool:
        """Check if user already has a pending emoji proposal."""
        async with self.bot.db_manager.get_pg_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(Proposal).where(
                    Proposal.user_id == user_id,
                    Proposal.proposal_type == 'emoji',
                    Proposal.status == 'pending'
                )
            )
            return result.scalar_one_or_none() is not None
    
    async def _send_admin_notification(
        self,
        proposal_id: int,
        user: discord.Member,
        emoji_name: str,
        description: str,
        emoji_file: discord.Attachment
    ):
        """Send notification to admin channel about new emoji proposal."""
        try:
            admin_channel = self.bot.get_channel(self.bot.admin_notification_channel_id)
            if not admin_channel:
                self.logger.warning("[user_emoji_proposals._send_admin_notification] Admin channel not found")
                return
            
            embed = discord.Embed(
                title="🎨 New Emoji Proposal",
                description=f"Proposal ID: `{proposal_id}`",
                color=0x9b59b6,
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(name="Proposer", value=f"{user.mention} ({user.id})", inline=True)
            embed.add_field(name="Emoji Name", value=f":{emoji_name}:", inline=True)
            embed.add_field(name="Status", value="Pending", inline=True)
            
            # File information
            embed.add_field(name="File Info", value=f"**{emoji_file.filename}**\nSize: {emoji_file.size:,} bytes", inline=True)
            
            # Description
            display_description = description
            if len(description) > 500:
                display_description = description[:500] + "..."
            
            embed.add_field(name="Description", value=display_description, inline=False)
            
            # Show emoji preview
            embed.set_image(url=emoji_file.url)
            embed.set_footer(text="Use /review_proposal to take action")
            
            await admin_channel.send(embed=embed)
            self.logger.info(f"[user_emoji_proposals._send_admin_notification] Admin notification sent for proposal {proposal_id}")
            
        except Exception as e:
            self.logger.error(f"[user_emoji_proposals._send_admin_notification] Failed to send admin notification: {e}", exc_info=True)
    
    async def _update_proposal_queue_embed(self):
        """Update the persistent proposal queue embed."""
        try:
            # Get queue channel
            queue_channel = self.bot.get_channel(self.bot.queue_channel_id)
            if not queue_channel:
                self.logger.warning("[user_emoji_proposals._update_proposal_queue_embed] Queue channel not found")
                return
            
            # Get pending proposals from database
            async with self.bot.db_manager.get_pg_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Proposal).where(Proposal.status == 'pending').order_by(Proposal.created_at)
                )
                pending_proposals = result.scalars().all()
            
            # Separate by type
            emoji_proposals = [p for p in pending_proposals if p.proposal_type == 'emoji']
            channel_proposals = [p for p in pending_proposals if p.proposal_type == 'channel']
            
            # Create embed
            embed = discord.Embed(
                title="📋 Pending Proposals Queue",
                description=f"Total pending: {len(pending_proposals)} ({len(emoji_proposals)} emojis, {len(channel_proposals)} channels)",
                color=0x9b59b6,
                timestamp=discord.utils.utcnow()
            )
            
            # Show emoji proposals
            if emoji_proposals:
                emoji_list = []
                for proposal in emoji_proposals[:5]:  # Show max 5 emoji proposals
                    created_date = proposal.created_at.strftime('%m/%d %H:%M')
                    emoji_list.append(
                        f"🎨 `{proposal.proposal_id}` :{proposal.original_text}: - <@{proposal.user_id}> ({created_date})"
                    )
                
                embed.add_field(
                    name="🎨 Emoji Proposals",
                    value="\n".join(emoji_list) if emoji_list else "None",
                    inline=False
                )
            
            # Show channel proposals
            if channel_proposals:
                channel_list = []
                for proposal in channel_proposals[:5]:  # Show max 5 channel proposals
                    created_date = proposal.created_at.strftime('%m/%d %H:%M')
                    channel_list.append(
                        f"💬 `{proposal.proposal_id}` {proposal.original_text} - <@{proposal.user_id}> ({created_date})"
                    )
                
                embed.add_field(
                    name="💬 Channel Proposals",
                    value="\n".join(channel_list) if channel_list else "None",
                    inline=False
                )
            
            if not pending_proposals:
                embed.add_field(name="Status", value="No pending proposals", inline=False)
            
            embed.set_footer(text="Updates automatically when new proposals are submitted")
            
            # Update or send the embed
            await self._update_persistent_embed("proposal_queue", embed, queue_channel)
            
        except Exception as e:
            self.logger.error(f"[user_emoji_proposals._update_proposal_queue_embed] Error updating proposal queue: {e}", exc_info=True)
    
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
                        self.logger.debug(f"[user_emoji_proposals._update_persistent_embed] Updated {embed_type} embed")
                    except discord.NotFound:
                        # Message was deleted, create new one
                        message = await channel.send(embed=embed)
                        persistent_embed.message_id = message.id
                        await session.commit()
                        self.logger.info(f"[user_emoji_proposals._update_persistent_embed] Recreated {embed_type} embed")
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
                    self.logger.info(f"[user_emoji_proposals._update_persistent_embed] Created new {embed_type} embed")
                
        except Exception as e:
            self.logger.error(f"[user_emoji_proposals._update_persistent_embed] Error managing persistent embed: {e}", exc_info=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(UserEmojiProposalsCog(bot))
    logging.getLogger('cogs.user_emoji_proposals').info("[user_emoji_proposals.setup] User emoji proposals cog loaded")