"""
Database Session Management

This module handles the initialization and management of database connections
for both PostgreSQL (primary data) and Redis (volatile stats).
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import redis.asyncio as redis
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from .db_models import Base
from .redis_client import RedisStatsManager

class DatabaseManager:
    """Manages database connections for PostgreSQL and Redis."""
    
    def __init__(self):
        """Initialize the database manager."""
        self.logger = logging.getLogger('database')
        self.pg_engine = None
        self.pg_session_factory = None
        self.redis_client: Optional[redis.Redis] = None
        self.redis_stats: Optional[RedisStatsManager] = None
        
        # Load database configuration
        self._load_config()
    
    def _load_config(self):
        """Load database configuration from environment variables."""
        self.logger.info("[database._load_config] Loading database configuration...")
        
        # PostgreSQL configuration
        self.db_host = os.getenv('DB_HOST', 'postgres')
        self.db_port = int(os.getenv('DB_PORT', '5432'))
        self.db_name = os.getenv('DB_NAME', 'discord')
        self.db_user = os.getenv('DB_USER', 'discord')
        
        # Redis configuration
        self.redis_host = os.getenv('REDIS_HOST', 'redis')
        self.redis_port = int(os.getenv('REDIS_PORT', '6379'))
        self.redis_db = int(os.getenv('REDIS_DB', '0'))
        
        self.logger.info("[database._load_config] Database configuration loaded")
    
    def _get_db_password(self) -> str:
        """Get database password from secrets."""
        password_path = Path('/run/secrets/db_password.txt')
        if not password_path.exists():
            # Fallback to local development
            password_path = Path('secrets/db_password.txt')
        
        if not password_path.exists():
            raise FileNotFoundError("Database password not found in secrets")
        
        password = password_path.read_text().strip()
        if not password:
            raise ValueError("Database password is empty")
        
        return password
    
    async def initialize(self):
        """Initialize database connections."""
        self.logger.info("[database.initialize] Initializing database connections...")
        
        try:
            # Initialize PostgreSQL connection
            await self._initialize_postgresql()
            
            # Initialize Redis connection
            await self._initialize_redis()
            
            self.logger.info("[database.initialize] Database connections initialized successfully")
            
        except Exception as e:
            self.logger.error(f"[database.initialize] Failed to initialize databases: {e}", exc_info=True)
            raise
    
    async def _initialize_postgresql(self):
        """Initialize PostgreSQL connection and create tables."""
        try:
            db_password = self._get_db_password()
            
            # Create async engine
            database_url = f"postgresql+asyncpg://{self.db_user}:{db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
            self.pg_engine = create_async_engine(
                database_url,
                echo=False,  # Set to True for SQL debugging
                pool_pre_ping=True,
                pool_recycle=3600
            )
            
            # Create session factory
            self.pg_session_factory = sessionmaker(
                bind=self.pg_engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
            
            # Handle database schema updates
            await self._handle_schema_updates()
            
            self.logger.info("[database._initialize_postgresql] PostgreSQL connection established")
            
        except Exception as e:
            self.logger.error(f"[database._initialize_postgresql] PostgreSQL initialization failed: {e}", exc_info=True)
            raise
    
    async def _handle_schema_updates(self):
        """Handle database schema creation and updates."""
        async with self.pg_engine.begin() as conn:
            # Check if we need to update the reports table schema
            try:
                from sqlalchemy import text
                
                # Try to check if the old schema exists
                result = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'reports'"))
                columns = [row[0] for row in result.fetchall()]
                
                # If the old schema exists (has 'user_id' but not 'reporter_id'), drop and recreate
                if 'user_id' in columns and 'reporter_id' not in columns:
                    self.logger.info("[database._handle_schema_updates] Updating reports table schema...")
                    await conn.execute(text("DROP TABLE IF EXISTS reports CASCADE"))
                    self.logger.info("[database._handle_schema_updates] Dropped old reports table")
                
                # If the old persistent_embeds schema exists (has 'embed_name' but not 'embed_type'), drop and recreate
                result = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'persistent_embeds'"))
                columns = [row[0] for row in result.fetchall()]
                
                if 'embed_name' in columns and 'embed_type' not in columns:
                    self.logger.info("[database._handle_schema_updates] Updating persistent_embeds table schema...")
                    await conn.execute(text("DROP TABLE IF EXISTS persistent_embeds CASCADE"))
                    self.logger.info("[database._handle_schema_updates] Dropped old persistent_embeds table")
                    
            except Exception as e:
                # Table might not exist yet, which is fine
                self.logger.debug(f"[database._handle_schema_updates] Schema check info: {e}")
            
            # Create all tables with current schema
            await conn.run_sync(Base.metadata.create_all)
            self.logger.info("[database._handle_schema_updates] Database schema updated")
    
    async def _initialize_redis(self):
        """Initialize Redis connection."""
        try:
            self.redis_client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True
            )
            
            # Test the connection
            await self.redis_client.ping()
            
            # Initialize Redis stats manager
            self.redis_stats = RedisStatsManager(self.redis_client)
            self.logger.info("[database._initialize_redis] Redis stats manager created successfully")
            
            self.logger.info("[database._initialize_redis] Redis connection and stats manager initialized")
            
        except Exception as e:
            self.logger.error(f"[database._initialize_redis] Redis initialization failed: {e}", exc_info=True)
            raise
    
    def get_pg_session(self) -> AsyncSession:
        """Get a new PostgreSQL session."""
        if not self.pg_session_factory:
            raise RuntimeError("PostgreSQL not initialized")
        return self.pg_session_factory()
    
    def get_redis_client(self) -> redis.Redis:
        """Get the Redis client."""
        if not self.redis_client:
            raise RuntimeError("Redis not initialized")
        return self.redis_client
    
    async def test_connections(self) -> dict:
        """Test database connections and return status."""
        status = {
            'postgresql': False,
            'redis': False,
            'redis_stats': False
        }
        
        # Test PostgreSQL
        try:
            async with self.get_pg_session() as session:
                from sqlalchemy import text
                await session.execute(text("SELECT 1"))
            status['postgresql'] = True
            self.logger.debug("[database.test_connections] PostgreSQL connection OK")
        except Exception as e:
            self.logger.error(f"[database.test_connections] PostgreSQL connection failed: {e}")
        
        # Test Redis
        try:
            await self.redis_client.ping()
            status['redis'] = True
            self.logger.debug("[database.test_connections] Redis connection OK")
        except Exception as e:
            self.logger.error(f"[database.test_connections] Redis connection failed: {e}")
        
        # Test Redis stats
        try:
            if self.redis_stats:
                # Try a simple stats operation
                await self.redis_stats.get_channel_stats(123456789)  # Test with dummy ID
                status['redis_stats'] = True
                self.logger.debug("[database.test_connections] Redis stats manager OK")
            else:
                self.logger.warning("[database.test_connections] Redis stats manager not initialized")
        except Exception as e:
            self.logger.error(f"[database.test_connections] Redis stats test failed: {e}")
        
        return status
    
    async def close(self):
        """Close all database connections."""
        self.logger.info("[database.close] Closing database connections...")
        
        # Close Redis stats manager
        if self.redis_stats:
            self.redis_stats = None
            self.logger.info("[database.close] Redis stats manager cleared")
        
        # Close Redis connection
        if self.redis_client:
            try:
                await self.redis_client.close()
                self.logger.info("[database.close] Redis connection closed")
            except Exception as e:
                self.logger.error(f"[database.close] Error closing Redis: {e}")
        
        # Close PostgreSQL engine
        if self.pg_engine:
            try:
                await self.pg_engine.dispose()
                self.logger.info("[database.close] PostgreSQL engine disposed")
            except Exception as e:
                self.logger.error(f"[database.close] Error disposing PostgreSQL engine: {e}")
        
        self.logger.info("[database.close] Database connections closed")