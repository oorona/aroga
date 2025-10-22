"""
Redis Client Helper

Helper functions for Redis operations including channel statistics tracking.
"""

import logging
from typing import Dict, List, Optional

import redis.asyncio as redis

logger = logging.getLogger('redis_client')

class RedisStatsManager:
    """Manages Redis operations for channel statistics."""
    
    def __init__(self, redis_client: redis.Redis):
        """Initialize with a Redis client."""
        self.redis_client = redis_client
        self.logger = logging.getLogger('redis_stats')
    
    async def increment_channel_messages(self, channel_id: int, message_id: int, timestamp: int):
        """
        Increment message count for a channel and update activity tracking.
        
        Args:
            channel_id: Discord channel ID
            message_id: Discord message ID
            timestamp: Unix timestamp of the message
        """
        try:
            # Update hash with total messages and last message timestamp
            hash_key = f"channel_stats:{channel_id}"
            await self.redis_client.hincrby(hash_key, "total_messages", 1)
            await self.redis_client.hset(hash_key, "last_message_timestamp", timestamp)
            
            # Add to sorted set for recent activity tracking
            zset_key = f"channel_activity:{channel_id}"
            await self.redis_client.zadd(zset_key, {str(message_id): timestamp})
            
            # Debug: Verify the data was stored
            hash_data = await self.redis_client.hgetall(hash_key)
            zset_size = await self.redis_client.zcard(zset_key)
            
            self.logger.debug(f"[redis_stats.increment_channel_messages] Updated stats for channel {channel_id}")
            self.logger.debug(f"[redis_stats.increment_channel_messages] Hash data after update: {dict(hash_data)}")
            self.logger.debug(f"[redis_stats.increment_channel_messages] Sorted set size: {zset_size}")
            
        except Exception as e:
            self.logger.error(f"[redis_stats.increment_channel_messages] Error updating channel {channel_id}: {e}")
    
    async def get_channel_stats(self, channel_id: int) -> Dict[str, int]:
        """
        Get channel statistics.
        
        Args:
            channel_id: Discord channel ID
            
        Returns:
            Dictionary with total_messages and last_message_timestamp
        """
        try:
            hash_key = f"channel_stats:{channel_id}"
            stats = await self.redis_client.hgetall(hash_key)
            
            self.logger.debug(f"[redis_stats.get_channel_stats] Channel {channel_id}: Raw hash data = {dict(stats)}")
            
            result = {
                'total_messages': int(stats.get('total_messages', 0)),
                'last_message_timestamp': int(stats.get('last_message_timestamp', 0))
            }
            
            self.logger.debug(f"[redis_stats.get_channel_stats] Channel {channel_id}: Parsed result = {result}")
            
            return result

        except Exception as e:
            self.logger.error(f"[redis_stats.get_channel_stats] Error getting stats for channel {channel_id}: {e}")
            return {'total_messages': 0, 'last_message_timestamp': 0}
    
    async def get_recent_message_count(self, channel_id: int, days: int = 7) -> int:
        """
        Get count of messages in the last N days.
        
        Args:
            channel_id: Discord channel ID
            days: Number of days to look back
            
        Returns:
            Count of recent messages
        """
        try:
            import time
            
            # Calculate timestamp for N days ago
            current_time = int(time.time())
            cutoff_time = current_time - (days * 24 * 60 * 60)
            
            zset_key = f"channel_activity:{channel_id}"
            count = await self.redis_client.zcount(zset_key, cutoff_time, '+inf')
            
            self.logger.debug(f"[redis_stats.get_recent_message_count] Channel {channel_id}: cutoff_time={cutoff_time}, current_time={current_time}, count={count}")
            
            return int(count)
            
        except Exception as e:
            self.logger.error(f"[redis_stats.get_recent_message_count] Error getting recent count for channel {channel_id}: {e}")
            return 0
    
    async def cleanup_old_activity(self, channel_id: int, days: int = 7):
        """
        Remove activity data older than N days to keep memory usage reasonable.
        
        Args:
            channel_id: Discord channel ID
            days: Number of days of history to keep
        """
        try:
            import time
            
            # Calculate timestamp for N days ago
            current_time = int(time.time())
            cutoff_time = current_time - (days * 24 * 60 * 60)
            
            zset_key = f"channel_activity:{channel_id}"
            removed = await self.redis_client.zremrangebyscore(zset_key, '-inf', cutoff_time)
            
            if removed > 0:
                self.logger.debug(f"[redis_stats.cleanup_old_activity] Removed {removed} old entries for channel {channel_id}")
            
        except Exception as e:
            self.logger.error(f"[redis_stats.cleanup_old_activity] Error cleaning up channel {channel_id}: {e}")
    
    async def calculate_channel_score(self, channel_id: int) -> float:
        """
        Calculate activity score for a channel using the specified algorithm.
        Score = (total_messages * 0.4) + (recent_7day_messages * 0.6)
        
        Args:
            channel_id: Discord channel ID
            
        Returns:
            Calculated activity score
        """
        try:
            stats = await self.get_channel_stats(channel_id)
            recent_count = await self.get_recent_message_count(channel_id, 7)
            
            total_messages = stats['total_messages']
            score = (total_messages * 0.4) + (recent_count * 0.6)
            
            self.logger.debug(f"[redis_stats.calculate_channel_score] Channel {channel_id}: total={total_messages}, recent={recent_count}, score={score}")
            
            return score
            
        except Exception as e:
            self.logger.error(f"[redis_stats.calculate_channel_score] Error calculating score for channel {channel_id}: {e}")
            return 0.0
    
    async def clear_channel_stats(self, channel_id: int):
        """
        Clear all statistics for a channel.
        
        Args:
            channel_id: Discord channel ID
        """
        try:
            hash_key = f"channel_stats:{channel_id}"
            zset_key = f"channel_activity:{channel_id}"
            
            await self.redis_client.delete(hash_key, zset_key)
            
            self.logger.info(f"[redis_stats.clear_channel_stats] Cleared stats for channel {channel_id}")
            
        except Exception as e:
            self.logger.error(f"[redis_stats.clear_channel_stats] Error clearing stats for channel {channel_id}: {e}")
    
    async def get_all_tracked_channels(self) -> List[int]:
        """
        Get list of all channels that have statistics.
        
        Returns:
            List of channel IDs that have been tracked
        """
        try:
            pattern = "channel_stats:*"
            keys = await self.redis_client.keys(pattern)
            
            channel_ids = []
            for key in keys:
                # Extract channel ID from key
                channel_id = int(key.split(':')[1])
                channel_ids.append(channel_id)
            
            return channel_ids
            
        except Exception as e:
            self.logger.error(f"[redis_stats.get_all_tracked_channels] Error getting tracked channels: {e}")
            return []