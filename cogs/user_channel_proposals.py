"""
User Channel Proposals Cog - Commands for users to propose new channels

This cog handles user functionality for submitting channel proposals
with LLM-assisted name suggestions.
"""

import logging
import json
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from database.db_models import Proposal, PersistentEmbed


class UserChannelProposalsCog(commands.Cog):
    """Cog for user channel proposal functionality."""
    
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger('cogs.user_channel_proposals')
    
    @app_commands.command(name="propose_channel", description="Propose a new channel for the server")
    @app_commands.describe(
        description="Detailed description of the channel purpose and content (will be used for LLM name suggestion)"
    )
    async def propose_channel(self, interaction: discord.Interaction, description: str):
        """Command for users to propose new channels."""
        await interaction.response.defer(ephemeral=True)
        
        try:
            self.logger.info(f"[user_channel_proposals.propose_channel] Channel proposal by {interaction.user.id}")
            
            # Validate description length
            if len(description.strip()) < 10:
                await interaction.followup.send(
                    "❌ **Error**: Channel description must be at least 10 characters long.",
                    ephemeral=True
                )
                return
            
            if len(description) > 1000:
                await interaction.followup.send(
                    "❌ **Error**: Channel description must be 1000 characters or less.",
                    ephemeral=True
                )
                return
            
            # Clean and validate description
            clean_description = description.strip()
            if not self._validate_channel_description(clean_description):
                await interaction.followup.send(
                    "❌ **Error**: Channel description contains inappropriate content or formatting.",
                    ephemeral=True
                )
                return
            
            # Check if user already has a pending channel proposal
            if await self._user_has_pending_channel_proposal(interaction.user.id):
                await interaction.followup.send(
                    "❌ **Error**: You already have a pending channel proposal. Please wait for it to be reviewed before submitting another.",
                    ephemeral=True
                )
                return
            
            # Check channel limits
            if not await self._check_channel_limits():
                await interaction.followup.send(
                    "❌ **Error**: Maximum number of proposed channels reached. Please wait for existing proposals to be processed.",
                    ephemeral=True
                )
                return
            
            # Create initial proposal record (before LLM processing)
            proposal_id = await self._create_initial_proposal(interaction.user.id, clean_description)
            
            # Send immediate response to user
            embed = discord.Embed(
                title="📝 Channel Proposal Submitted",
                description="Your channel proposal has been submitted and will be reviewed by administrators.",
                color=0x00ff00,
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(name="Proposal ID", value=f"`{proposal_id}`", inline=True)
            embed.add_field(name="Status", value="Awaiting Review", inline=True)
            embed.add_field(name="Description", value=clean_description[:500] + "..." if len(clean_description) > 500 else clean_description, inline=False)
            
            embed.set_footer(text="You will be notified when your proposal is reviewed by administrators.")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            # Process LLM suggestion asynchronously
            await self._process_llm_suggestion(proposal_id, clean_description, interaction.user.id)
            
            self.logger.info(f"[user_channel_proposals.propose_channel] Channel proposal {proposal_id} submitted by {interaction.user.id}")
            
        except Exception as e:
            self.logger.error(f"[user_channel_proposals.propose_channel] Error creating channel proposal: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ **Error**: Failed to submit channel proposal. Please try again later.",
                ephemeral=True
            )
    
    def _validate_channel_description(self, description: str) -> bool:
        """Validate channel description content."""
        # Check for minimum content requirements
        if not description or len(description.strip()) < 10:
            return False
        
        # Remove excessive whitespace
        cleaned = ' '.join(description.split())
        if len(cleaned) < 10:
            return False
        
        # Basic content filtering (extend as needed)
        prohibited_patterns = [
            # Add patterns for inappropriate content
            r'@everyone', r'@here',  # Prevent mention abuse
            r'discord\.gg/', r'discord\.com/invite/',  # Prevent invite links
        ]
        
        import re
        for pattern in prohibited_patterns:
            if re.search(pattern, description, re.IGNORECASE):
                return False
        
        return True
    
    async def _user_has_pending_channel_proposal(self, user_id: int) -> bool:
        """Check if user already has a pending channel proposal."""
        async with self.bot.db_manager.get_pg_session() as session:
            from sqlalchemy import select, and_
            result = await session.execute(
                select(Proposal).where(
                    and_(
                        Proposal.user_id == user_id,
                        Proposal.proposal_type == 'channel',
                        Proposal.status.in_(['pending', 'needs_changes'])
                    )
                )
            )
            return result.scalar_one_or_none() is not None
    
    async def _check_channel_limits(self) -> bool:
        """Check if we're under the channel proposal limits."""
        try:
            # Get current number of channels in proposed category
            proposed_category = self.bot.get_channel(self.bot.proposed_channel_category_id)
            if not proposed_category:
                self.logger.warning("[user_channel_proposals._check_channel_limits] Proposed category not found")
                return True  # Allow if category not found
            
            current_count = len([ch for ch in proposed_category.channels if isinstance(ch, discord.TextChannel)])
            
            # Check against configured limit
            if current_count >= self.bot.max_proposed_channels:
                self.logger.info(f"[user_channel_proposals._check_channel_limits] Channel limit reached: {current_count}/{self.bot.max_proposed_channels}")
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"[user_channel_proposals._check_channel_limits] Error checking limits: {e}", exc_info=True)
            return True  # Allow on error to prevent blocking
    
    async def _create_initial_proposal(self, user_id: int, description: str) -> int:
        """Create initial proposal record in database."""
        async with self.bot.db_manager.get_pg_session() as session:
            proposal = Proposal(
                user_id=user_id,
                proposal_type='channel',
                original_text=description,
                status='pending'
            )
            
            session.add(proposal)
            await session.commit()
            await session.refresh(proposal)
            
            return proposal.proposal_id
    
    async def _process_llm_suggestion(self, proposal_id: int, description: str, user_id: int):
        """Process LLM suggestion for channel name."""
        try:
            self.logger.info(f"[user_channel_proposals._process_llm_suggestion] Processing LLM for proposal {proposal_id}")
            
            # Get LLM suggestion
            llm_suggestion = await self._get_llm_channel_suggestion(description)
            
            # Update proposal with LLM suggestion
            async with self.bot.db_manager.get_pg_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Proposal).where(Proposal.proposal_id == proposal_id)
                )
                proposal = result.scalar_one_or_none()
                
                if proposal:
                    proposal.llm_suggestion = llm_suggestion
                    await session.commit()
            
            # Always send admin notification, but indicate LLM status
            await self._send_admin_notification(proposal_id, user_id, description, llm_suggestion)
            await self._update_proposal_queue_embed()
            
            if llm_suggestion:
                self.logger.info(f"[user_channel_proposals._process_llm_suggestion] LLM processing complete for proposal {proposal_id} with suggestion: {llm_suggestion}")
            else:
                self.logger.warning(f"[user_channel_proposals._process_llm_suggestion] LLM failed to generate suggestion for proposal {proposal_id}, admin notification sent with error indication")
            
        except Exception as e:
            self.logger.error(f"[user_channel_proposals._process_llm_suggestion] Error processing LLM for proposal {proposal_id}: {e}", exc_info=True)
            # Still send admin notification even if there's an exception
            await self._send_admin_notification(proposal_id, user_id, description, None)
            await self._update_proposal_queue_embed()
    
    async def _get_llm_channel_suggestion(self, description: str) -> Optional[str]:
        """Get channel name suggestion from LLM."""
        try:
            # Read prompt template
            try:
                prompt_file_path = '/app/prompts/channel_name_suggestion.txt'
                self.logger.info(f"[user_channel_proposals._get_llm_channel_suggestion] Attempting to read prompt from: {prompt_file_path}")
                
                with open(prompt_file_path, 'r') as f:
                    prompt_template = f.read().strip()
                
                self.logger.info(f"[user_channel_proposals._get_llm_channel_suggestion] Successfully loaded prompt from file (length: {len(prompt_template)})")
                
            except FileNotFoundError as e:
                self.logger.error(f"[user_channel_proposals._get_llm_channel_suggestion] Prompt file not found: {e}")
                # According to specs, no hardcoded values allowed - fail if prompt file missing
                self.logger.error("[user_channel_proposals._get_llm_channel_suggestion] No fallback prompt allowed per specs - LLM processing failed")
                return None
            except Exception as e:
                self.logger.error(f"[user_channel_proposals._get_llm_channel_suggestion] Error reading prompt file: {e}")
                return None
            
            # Format prompt with description
            formatted_prompt = prompt_template.format(description=description)
            
            # Prepare LLM request
            headers = {
                'Content-Type': 'application/json'
            }
            
            # Add authorization if token is available
            self.logger.info("[user_channel_proposals._get_llm_channel_suggestion] Checking for LLM token...")
            try:
                # Use same pattern as Discord and database tokens
                from pathlib import Path
                
                token_path = Path('/run/secrets/open_webui_token.txt')
                if not token_path.exists():
                    # Fallback to local development (same pattern as Discord/DB)
                    token_path = Path('secrets/open_webui_token.txt')
                
                if token_path.exists():
                    token = token_path.read_text().strip()
                    if token:
                        headers['Authorization'] = f'Bearer {token}'
                        self.logger.info(f"[user_channel_proposals._get_llm_channel_suggestion] Successfully loaded token from {token_path}")
                    else:
                        self.logger.warning(f"[user_channel_proposals._get_llm_channel_suggestion] Empty token file at: {token_path}")
                else:
                    self.logger.warning("[user_channel_proposals._get_llm_channel_suggestion] LLM token file not found")
                    
            except Exception as e:
                self.logger.error(f"[user_channel_proposals._get_llm_channel_suggestion] Error reading token: {e}")
            
            # Prepare request payload with function calling for structured response
            payload = {
                "model": self.bot.llm_model,
                "messages": [
                    {
                        "role": "user",
                        "content": formatted_prompt
                    }
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "suggest_channel_names",
                            "description": "Suggest Discord channel names in the format 'emoji・name' based on description",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "suggestions": {
                                        "type": "array",
                                        "items": {
                                            "type": "string",
                                            "pattern": "^.・[a-z0-9\\-_]+$",
                                            "description": "Channel name in format 'emoji・name' (e.g., '⚛️・react', '🎮・gaming')"
                                        },
                                        "description": "Array of 3 channel name suggestions in format 'emoji・name'",
                                        "minItems": 1,
                                        "maxItems": 3
                                    }
                                },
                                "required": ["suggestions"]
                            }
                        }
                    }
                ],
                "tool_choice": {
                    "type": "function",
                    "function": {"name": "suggest_channel_names"}
                },
                "max_tokens": 800
            }
            
            # Make LLM request
            self.logger.info(f"[user_channel_proposals._get_llm_channel_suggestion] Making request to: {self.bot.llm_url}")
            self.logger.info(f"[user_channel_proposals._get_llm_channel_suggestion] Model: {payload.get('model')}")
            
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.bot.llm_url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    self.logger.info(f"[user_channel_proposals._get_llm_channel_suggestion] Response status: {response.status}")
                    
                    if response.status == 200:
                        data = await response.json()
                        self.logger.info(f"[user_channel_proposals._get_llm_channel_suggestion] LLM response data: {data}")
                        
                        # Parse function call response
                        if 'choices' in data and len(data['choices']) > 0:
                            choice = data['choices'][0]
                            self.logger.info(f"[user_channel_proposals._get_llm_channel_suggestion] Choice data: {choice}")
                            
                            if 'message' in choice and 'tool_calls' in choice['message']:
                                tool_calls = choice['message']['tool_calls']
                                self.logger.info(f"[user_channel_proposals._get_llm_channel_suggestion] Tool calls: {tool_calls}")
                                
                                if len(tool_calls) > 0:
                                    function_args = json.loads(tool_calls[0]['function']['arguments'])
                                    suggestions = function_args.get('suggestions', [])
                                    self.logger.info(f"[user_channel_proposals._get_llm_channel_suggestion] Raw suggestions: {suggestions}")
                                    
                                    if suggestions:
                                        # Validate and clean suggestions
                                        valid_suggestions = []
                                        for suggestion in suggestions[:3]:  # Max 3
                                            cleaned = self._clean_channel_name(suggestion)
                                            self.logger.info(f"[user_channel_proposals._get_llm_channel_suggestion] Suggestion '{suggestion}' cleaned to '{cleaned}'")
                                            if cleaned and self._validate_channel_name(cleaned):
                                                valid_suggestions.append(cleaned)
                                            else:
                                                self.logger.warning(f"[user_channel_proposals._get_llm_channel_suggestion] Suggestion '{cleaned}' failed validation")
                                        
                                        if valid_suggestions:
                                            result = ", ".join(valid_suggestions)
                                            self.logger.info(f"[user_channel_proposals._get_llm_channel_suggestion] Final valid suggestions: {result}")
                                            return result
                        
                        # Fallback: try to parse regular text response
                        if 'choices' in data and len(data['choices']) > 0:
                            content = data['choices'][0].get('message', {}).get('content', '')
                            self.logger.info(f"[user_channel_proposals._get_llm_channel_suggestion] Fallback text content: {content}")
                            if content:
                                return self._parse_text_suggestions(content)
                    
                    else:
                        # Get response body for debugging
                        try:
                            error_text = await response.text()
                            self.logger.error(f"[user_channel_proposals._get_llm_channel_suggestion] LLM API error: {response.status}")
                            self.logger.error(f"[user_channel_proposals._get_llm_channel_suggestion] Response headers: {dict(response.headers)}")
                            self.logger.error(f"[user_channel_proposals._get_llm_channel_suggestion] Response body: {error_text}")
                        except Exception as e:
                            self.logger.error(f"[user_channel_proposals._get_llm_channel_suggestion] LLM API error: {response.status}, failed to read response: {e}")
            
        except Exception as e:
            self.logger.error(f"[user_channel_proposals._get_llm_channel_suggestion] Error calling LLM: {e}", exc_info=True)
        
        return None
    
    def _clean_channel_name(self, name: str) -> str:
        """Clean and format channel name according to Discord standards with emoji・name format."""
        if not name:
            return ""
        
        # Check if name already has the emoji・name format
        if '・' in name:
            return name.strip()  # Keep the original format if it uses the separator
        
        # If it's a plain name, we can't add emoji here - that's for LLM to do
        # Just clean the name part
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
        
        # Truncate to 100 characters
        return cleaned[:100]
    
    def _validate_channel_name(self, name: str) -> bool:
        """Validate channel name according to Discord requirements and emoji・name format."""
        self.logger.debug(f"[user_channel_proposals._validate_channel_name] Validating: '{name}'")
        
        if not name or len(name) < 1 or len(name) > 100:
            self.logger.debug(f"[user_channel_proposals._validate_channel_name] Failed length check: {len(name) if name else 'None'}")
            return False
        
        # Check for emoji・name format
        if '・' in name:
            parts = name.split('・', 1)
            if len(parts) != 2:
                self.logger.debug(f"[user_channel_proposals._validate_channel_name] Failed split check: {len(parts)} parts")
                return False
            
            emoji_part = parts[0].strip()
            name_part = parts[1].strip()
            
            self.logger.debug(f"[user_channel_proposals._validate_channel_name] Emoji part: '{emoji_part}', Name part: '{name_part}'")
            
            # Validate emoji part (should be 1-4 characters, likely emoji)
            if not emoji_part or len(emoji_part) > 4:
                self.logger.debug(f"[user_channel_proposals._validate_channel_name] Failed emoji length check: {len(emoji_part) if emoji_part else 'None'}")
                return False
            
            # Validate name part (Discord channel naming rules)
            if not name_part:
                self.logger.debug("[user_channel_proposals._validate_channel_name] Empty name part")
                return False
            
            import re
            if not re.match(r'^[a-z0-9\-_]+$', name_part):
                self.logger.debug(f"[user_channel_proposals._validate_channel_name] Failed regex check for name part: '{name_part}'")
                return False
            
            # Can't start or end with hyphen
            if name_part.startswith('-') or name_part.endswith('-'):
                self.logger.debug(f"[user_channel_proposals._validate_channel_name] Failed hyphen check for name part: '{name_part}'")
                return False
            
            self.logger.debug(f"[user_channel_proposals._validate_channel_name] Validation passed for: '{name}'")
            return True
        else:
            # Fallback validation for plain names (should not happen with LLM)
            import re
            if not re.match(r'^[a-z0-9\-_]+$', name):
                self.logger.debug(f"[user_channel_proposals._validate_channel_name] Failed regex check for plain name: '{name}'")
                return False
            
            # Can't start or end with hyphen
            if name.startswith('-') or name.endswith('-'):
                self.logger.debug(f"[user_channel_proposals._validate_channel_name] Failed hyphen check for plain name: '{name}'")
                return False
            
            self.logger.debug(f"[user_channel_proposals._validate_channel_name] Plain name validation passed for: '{name}'")
            return True
    
    def _parse_text_suggestions(self, content: str) -> Optional[str]:
        """Parse channel name suggestions from plain text response with emoji・name format."""
        try:
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            suggestions = []
            
            for line in lines[:3]:  # Max 3 suggestions
                # Remove bullet points, numbers, etc.
                import re
                cleaned_line = re.sub(r'^[-*•\d\.\)]\s*', '', line)
                
                # For emoji・name format, minimal cleaning to preserve emojis and separator
                channel_name = cleaned_line.strip()
                
                if channel_name and self._validate_channel_name(channel_name):
                    suggestions.append(channel_name)
            
            return ", ".join(suggestions) if suggestions else None
            
        except Exception as e:
            self.logger.error(f"[user_channel_proposals._parse_text_suggestions] Error parsing suggestions: {e}")
            return None
    
    async def _send_admin_notification(self, proposal_id: int, user_id: int, description: str, llm_suggestion: Optional[str]):
        """Send notification to admin channel about new proposal."""
        try:
            admin_channel = self.bot.get_channel(self.bot.admin_notification_channel_id)
            if not admin_channel:
                self.logger.error("[user_channel_proposals._send_admin_notification] Admin notification channel not found")
                return
            
            embed = discord.Embed(
                title="💬 New Channel Proposal",
                description=f"**Proposal ID:** `{proposal_id}`",
                color=0x5865f2,
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(name="Proposer", value=f"<@{user_id}>", inline=True)
            embed.add_field(name="Type", value="Channel", inline=True)
            embed.add_field(name="Status", value="Pending Review", inline=True)
            
            # Add description
            embed.add_field(
                name="Description",
                value=description[:1000] + "..." if len(description) > 1000 else description,
                inline=False
            )
            
            # Add LLM suggestions if available
            if llm_suggestion:
                embed.add_field(
                    name="🤖 LLM Suggestions",
                    value=f"`{llm_suggestion}`",
                    inline=False
                )
                embed.color = 0x00ff00  # Green if LLM processed successfully
            else:
                embed.add_field(
                    name="🤖 LLM Suggestions",
                    value="*LLM processing failed - manual review required*",
                    inline=False
                )
                embed.color = 0xff9900  # Orange if LLM failed
            
            embed.set_footer(text=f"Use /review_proposal {proposal_id} to take action")
            
            message = await admin_channel.send(embed=embed)
            
            # Store notification message ID
            async with self.bot.db_manager.get_pg_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Proposal).where(Proposal.proposal_id == proposal_id)
                )
                proposal = result.scalar_one_or_none()
                
                if proposal:
                    proposal.notification_message_id = message.id
                    await session.commit()
            
            self.logger.info(f"[user_channel_proposals._send_admin_notification] Admin notification sent for proposal {proposal_id}")
            
        except Exception as e:
            self.logger.error(f"[user_channel_proposals._send_admin_notification] Error sending admin notification: {e}", exc_info=True)
    
    async def _update_proposal_queue_embed(self):
        """Update the persistent proposal queue embed."""
        try:
            queue_channel = self.bot.get_channel(self.bot.queue_channel_id)
            if not queue_channel:
                return
            
            # Get all pending proposals
            async with self.bot.db_manager.get_pg_session() as session:
                from sqlalchemy import select, desc
                result = await session.execute(
                    select(Proposal).where(
                        Proposal.status.in_(['pending', 'needs_changes'])
                    ).order_by(desc(Proposal.created_at))
                )
                proposals = result.scalars().all()
            
            # Create embed
            embed = discord.Embed(
                title="📋 Proposal Queue",
                description=f"**{len(proposals)}** proposals awaiting review",
                color=0x9b59b6,
                timestamp=discord.utils.utcnow()
            )
            
            if proposals:
                # Separate by type
                emoji_proposals = [p for p in proposals if p.proposal_type == 'emoji']
                channel_proposals = [p for p in proposals if p.proposal_type == 'channel']
                
                # Add emoji proposals
                if emoji_proposals:
                    emoji_lines = []
                    for proposal in emoji_proposals[:5]:  # Max 5
                        status_emoji = '🟡' if proposal.status == 'pending' else '🔄'
                        name = proposal.final_name or proposal.llm_suggestion or proposal.original_text
                        created_date = proposal.created_at.strftime('%m/%d')
                        emoji_lines.append(f"{status_emoji} `{proposal.proposal_id}` :{name}: - <@{proposal.user_id}> ({created_date})")
                    
                    embed.add_field(
                        name=f"🎨 Emoji Proposals ({len(emoji_proposals)})",
                        value="\n".join(emoji_lines),
                        inline=False
                    )
                
                # Add channel proposals
                if channel_proposals:
                    channel_lines = []
                    for proposal in channel_proposals[:5]:  # Max 5
                        status_emoji = '🟡' if proposal.status == 'pending' else '🔄'
                        name = proposal.final_name or proposal.llm_suggestion or "Unnamed"
                        created_date = proposal.created_at.strftime('%m/%d')
                        channel_lines.append(f"{status_emoji} `{proposal.proposal_id}` #{name} - <@{proposal.user_id}> ({created_date})")
                    
                    embed.add_field(
                        name=f"💬 Channel Proposals ({len(channel_proposals)})",
                        value="\n".join(channel_lines),
                        inline=False
                    )
                
                # Add legend
                embed.add_field(
                    name="📋 Legend",
                    value="🟡 Pending Review • 🔄 Needs Changes",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Queue Status",
                    value="No proposals currently awaiting review",
                    inline=False
                )
            
            embed.set_footer(text="Updated automatically when proposals are submitted or reviewed")
            
            # Find or create persistent embed
            async with self.bot.db_manager.get_pg_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(PersistentEmbed).where(PersistentEmbed.embed_type == 'proposal_queue')
                )
                persistent_embed = result.scalar_one_or_none()
                
                if persistent_embed and persistent_embed.message_id:
                    # Update existing embed
                    try:
                        message = await queue_channel.fetch_message(persistent_embed.message_id)
                        await message.edit(embed=embed)
                        self.logger.debug("[user_channel_proposals._update_proposal_queue_embed] Updated existing queue embed")
                    except discord.NotFound:
                        # Message was deleted, create new one
                        message = await queue_channel.send(embed=embed)
                        persistent_embed.message_id = message.id
                        await session.commit()
                        self.logger.info("[user_channel_proposals._update_proposal_queue_embed] Recreated queue embed")
                else:
                    # Create new embed
                    message = await queue_channel.send(embed=embed)
                    
                    if not persistent_embed:
                        persistent_embed = PersistentEmbed(
                            embed_type='proposal_queue',
                            channel_id=queue_channel.id,
                            message_id=message.id
                        )
                        session.add(persistent_embed)
                    else:
                        persistent_embed.message_id = message.id
                    
                    await session.commit()
                    self.logger.info("[user_channel_proposals._update_proposal_queue_embed] Created new queue embed")
            
        except Exception as e:
            self.logger.error(f"[user_channel_proposals._update_proposal_queue_embed] Error updating queue embed: {e}", exc_info=True)


async def setup(bot):
    """Setup function for the cog."""
    await bot.add_cog(UserChannelProposalsCog(bot))
    logging.getLogger('cogs.user_channel_proposals').info("[user_channel_proposals.setup] User channel proposals cog loaded")