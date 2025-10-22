#!/usr/bin/env python3
"""
Agora Discord Bot - Main Entry Point

This is the entry point for the Agora Discord bot. It initializes logging,
loads the bot configuration, and starts the bot.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

def setup_logging():
    """Configure logging for the application."""
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    
    # Clear any existing handlers to prevent conflicts
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Configure logging format (console only for Docker)
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ],
        force=True  # Force override any existing configuration
    )
    
    # Set discord.py logging level to WARNING to reduce noise
    logging.getLogger('discord').setLevel(logging.WARNING)
    logging.getLogger('discord.http').setLevel(logging.WARNING)
    
    logger = logging.getLogger('main')
    logger.info(f"[main.setup_logging] Logging initialized at {log_level} level")
    return logger

# Setup logging BEFORE any other imports to prevent conflicts
logger = setup_logging()

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import bot AFTER logging is set up
from bot import AgoraBot

async def main():
    """Main application entry point."""
    print("DEBUG: Starting main function...")
    
    try:
        print("DEBUG: About to initialize bot...")
        
        # Initialize and start the bot
        bot = AgoraBot()
        await bot.start_bot()
        
    except KeyboardInterrupt:
        logger.info("[main.main] Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"[main.main] Fatal error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown complete.")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)