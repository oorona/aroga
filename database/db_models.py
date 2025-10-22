"""
Database Models

SQLAlchemy models for the Agora Discord Bot database schema.
These models define the structure for PostgreSQL tables.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

# Create the base class for all models
Base = declarative_base()

logger = logging.getLogger('db_models')

class Proposal(Base):
    """Model for channel and emoji proposals."""
    
    __tablename__ = 'proposals'
    
    proposal_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    proposal_type = Column(String(20), nullable=False)  # 'channel' or 'emoji'
    status = Column(String(20), nullable=False, default='pending')  # 'pending', 'approved', 'rejected'
    original_text = Column(Text, nullable=False)
    llm_suggestion = Column(Text, nullable=True)
    final_name = Column(Text, nullable=True)
    file_url = Column(Text, nullable=True)  # For emoji attachments
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    def __repr__(self):
        return f"<Proposal(id={self.proposal_id}, type={self.proposal_type}, status={self.status})>"

class Report(Base):
    """Model for user reports."""
    
    __tablename__ = 'reports'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    reporter_id = Column(BigInteger, nullable=False, index=True)  # User who submitted the report
    reported_user_id = Column(BigInteger, nullable=True, index=True)  # User being reported (optional)
    report_type = Column(String(50), nullable=False)  # Type of report (spam, harassment, etc.)
    status = Column(String(20), nullable=False, default='pending')  # 'pending', 'investigating', 'resolved', 'dismissed', 'escalated'
    description = Column(Text, nullable=False)  # Report description
    channel_id = Column(BigInteger, nullable=False)  # Channel where report was made
    guild_id = Column(BigInteger, nullable=False)  # Guild/server ID
    admin_id = Column(BigInteger, nullable=True)  # Admin who handled the report
    admin_response = Column(Text, nullable=True)  # Admin's response to reporter
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)  # When report was resolved
    
    def __repr__(self):
        return f"<Report(id={self.id}, type={self.report_type}, status={self.status})>"

class TrackedChannel(Base):
    """Model for tracking channels in proposed or permanent categories."""
    
    __tablename__ = 'tracked_channels'
    
    channel_id = Column(BigInteger, primary_key=True)
    category = Column(String(20), nullable=False)  # 'proposed' or 'permanent'
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    def __repr__(self):
        return f"<TrackedChannel(id={self.channel_id}, category={self.category})>"

class PersistentEmbed(Base):
    """Model for managing persistent bot embeds that need to be updated."""
    
    __tablename__ = 'persistent_embeds'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    embed_type = Column(String(50), nullable=False)  # e.g., 'proposal_queue', 'report_queue'
    channel_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=False)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    def __repr__(self):
        return f"<PersistentEmbed(type={self.embed_type}, channel={self.channel_id}, message={self.message_id})>"

# Log model initialization
logger.info("[db_models] Database models defined successfully")