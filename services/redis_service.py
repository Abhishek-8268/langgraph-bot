# services/redis_service.py
"""Async Redis service for session and state management - FIXED for new flow"""

import redis.asyncio as redis
import pickle
import logging
from typing import Optional, Dict, Any, List, cast
from datetime import datetime, timedelta
import os
from contextlib import asynccontextmanager

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage, BaseMessage
from models.state_model import ConversationState

logger = logging.getLogger(__name__)


class RedisConfig:
    """Redis configuration handler"""

    def __init__(self):
        # Environment-based configuration
        self.redis_host = os.environ.get("REDIS_HOST", "localhost")
        self.redis_port = int(os.environ.get("REDIS_PORT", 6379))
        self.redis_password = os.environ.get("REDIS_PASSWORD", None)
        self.redis_db = int(os.environ.get("REDIS_DB", 0))
        self.redis_ssl = os.environ.get("REDIS_SSL", "false").lower() == "true"

        # Session settings
        self.session_ttl = int(os.environ.get("SESSION_TTL_HOURS", 1)) * 3600  # Convert to seconds
        self.max_pool_connections = int(os.environ.get("REDIS_MAX_CONNECTIONS", 50))

    def get_connection_params(self) -> Dict[str, Any]:
        """Get Redis connection parameters"""
        params = {
            "host": self.redis_host,
            "port": self.redis_port,
            "db": self.redis_db,
            "decode_responses": False,  # We'll handle encoding/decoding ourselves
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
            "retry_on_timeout": True,
            "health_check_interval": 30,
        }

        if self.redis_password:
            params["password"] = self.redis_password

        if self.redis_ssl:
            params["ssl"] = True
            params["ssl_cert_reqs"] = "required"

        return params


class MessageSerializer:
    """Handle serialization of LangChain messages"""

    @staticmethod
    def serialize_message(message: BaseMessage) -> Dict[str, Any]:
        """Convert a LangChain message to a serializable dict"""
        msg_dict = {
            "type": message.__class__.__name__,
            "content": message.content,
        }

        # Add additional fields based on message type
        if isinstance(message, AIMessage):
            if hasattr(message, 'tool_calls'):
                msg_dict["tool_calls"] = message.tool_calls

        elif isinstance(message, ToolMessage):
            if hasattr(message, 'tool_call_id'):
                msg_dict["tool_call_id"] = message.tool_call_id
            if hasattr(message, 'name'):
                msg_dict["name"] = message.name

        return msg_dict

    @staticmethod
    def deserialize_message(msg_dict: Dict[str, Any]) -> BaseMessage:
        """Convert a dict back to a LangChain message"""
        msg_type = msg_dict.get("type")
        content = msg_dict.get("content", "")

        if msg_type == "HumanMessage":
            return HumanMessage(content=content)
        elif msg_type == "AIMessage":
            ai_msg = AIMessage(content=content)
            if "tool_calls" in msg_dict:
                ai_msg.tool_calls = msg_dict["tool_calls"]
            return ai_msg
        elif msg_type == "SystemMessage":
            return SystemMessage(content=content)
        elif msg_type == "ToolMessage":
            tool_msg = ToolMessage(
                content=content,
                tool_call_id=msg_dict.get("tool_call_id", ""),
                name=msg_dict.get("name", "")
            )
            return tool_msg
        else:
            # Fallback to HumanMessage
            logger.warning(f"Unknown message type: {msg_type}, using HumanMessage")
            return HumanMessage(content=content)


class AsyncRedisSessionManager:
    """Async Redis session manager for the cab booking bot"""

    def __init__(self):
        self.config = RedisConfig()
        self.pool = None
        self.redis_client = None
        self.message_serializer = MessageSerializer()
        self._initialized = False

    async def initialize(self):
        """Initialize Redis connection pool - call this on startup"""
        if self._initialized:
            return

        try:
            self.pool = redis.ConnectionPool(
                **self.config.get_connection_params(),
                max_connections=self.config.max_pool_connections
            )
            self.redis_client = redis.Redis(connection_pool=self.pool)

            # Test connection
            await self.redis_client.ping()
            logger.info(f"✅ Redis connected successfully at {self.config.redis_host}:{self.config.redis_port}")
            self._initialized = True

        except redis.ConnectionError as e:
            logger.error(f"❌ Failed to connect to Redis: {e}")
            logger.warning("⚠️ Falling back to in-memory storage")
            self.redis_client = None
            self._initialized = True

    async def close(self):
        """Close Redis connections - call this on shutdown"""
        if self.redis_client:
            await self.redis_client.close()
            if self.pool:
                await self.pool.disconnect()
            logger.info("Redis connections closed")

    @asynccontextmanager
    async def get_redis(self):
        """Async context manager for Redis operations with fallback"""
        if not self._initialized:
            await self.initialize()

        if self.redis_client:
            try:
                yield self.redis_client
            except redis.RedisError as e:
                logger.error(f"Redis operation failed: {e}")
                yield None
        else:
            yield None

    def _get_session_key(self, user_id: str) -> str:
        """Generate Redis key for user session"""
        return f"cab_bot:session:{user_id}"

    def _get_message_cache_key(self, user_id: str) -> str:
        """Generate Redis key for processed messages cache"""
        return f"cab_bot:messages:{user_id}"

    def _serialize_state(self, state: ConversationState) -> bytes:
        """Serialize ConversationState to bytes for Redis storage - FIXED for new flow"""
        # Convert state to dict - ONLY include fields that exist in new state model
        state_dict = {
            "chat_history": [
                self.message_serializer.serialize_message(msg)
                for msg in state.chat_history
            ],
            "applied_filters": state.applied_filters,
            "trip_id": state.trip_id,
            "pickup_location": state.pickup_location,
            "drop_location": state.drop_location,
            "trip_type": state.trip_type,
            "start_date": state.start_date,
            "end_date": state.end_date,
            "customer_id": state.customer_id,
            "customer_name": state.customer_name,
            "customer_phone": state.customer_phone,
            "customer_profile": state.customer_profile,
            "last_bot_response": state.last_bot_response,
            "tool_calls": state.tool_calls,
            "booking_status": state.booking_status,
            "drivers_notified": state.drivers_notified,
            "last_activity": datetime.now().isoformat(),
        }

        # Use pickle for complex objects
        return pickle.dumps(state_dict)

    def _deserialize_state(self, data: bytes) -> ConversationState:
        """Deserialize bytes from Redis to ConversationState - FIXED for new flow"""
        state_dict = pickle.loads(data)

        # Reconstruct chat history
        chat_history = [
            self.message_serializer.deserialize_message(msg_dict)
            for msg_dict in state_dict.get("chat_history", [])
        ]

        # Create ConversationState - ONLY with fields that exist in new model
        state = ConversationState(
            chat_history=chat_history,
            applied_filters=state_dict.get("applied_filters", {}),
            trip_id=state_dict.get("trip_id"),
            pickup_location=state_dict.get("pickup_location"),
            drop_location=state_dict.get("drop_location"),
            trip_type=state_dict.get("trip_type"),
            start_date=state_dict.get("start_date"),
            end_date=state_dict.get("end_date"),
            customer_id=state_dict.get("customer_id"),
            customer_name=state_dict.get("customer_name"),
            customer_phone=state_dict.get("customer_phone"),
            customer_profile=state_dict.get("customer_profile"),
            last_bot_response=state_dict.get("last_bot_response"),
            tool_calls=state_dict.get("tool_calls", []),
            booking_status=state_dict.get("booking_status"),
            drivers_notified=state_dict.get("drivers_notified", 0)
        )

        return state

    async def get_session(self, user_id: str) -> Optional[ConversationState]:
        """Retrieve user session from Redis"""
        async with self.get_redis() as r:
            if not r:
                return None

            try:
                key = self._get_session_key(user_id)
                data = await r.get(key)

                if data:
                    state = self._deserialize_state(data)
                    logger.info(f"📥 Retrieved session for user {user_id}")

                    # Refresh TTL on access
                    await r.expire(key, self.config.session_ttl)

                    return state
                else:
                    logger.info(f"🆕 No existing session for user {user_id}")
                    return None

            except Exception as e:
                logger.error(f"Error retrieving session for {user_id}: {e}")
                return None

    async def save_session(self, user_id: str, state: ConversationState) -> bool:
        """Save user session to Redis"""
        async with self.get_redis() as r:
            if not r:
                return False

            try:
                key = self._get_session_key(user_id)
                data = self._serialize_state(state)

                # Save with TTL
                await r.setex(key, self.config.session_ttl, data)

                logger.debug(f"💾 Saved session for user {user_id} with {self.config.session_ttl}s TTL")
                return True

            except Exception as e:
                logger.error(f"Error saving session for {user_id}: {e}")
                return False

    async def delete_session(self, user_id: str) -> bool:
        """Delete user session from Redis"""
        async with self.get_redis() as r:
            if not r:
                return False

            try:
                key = self._get_session_key(user_id)
                deleted = await r.delete(key) > 0

                if deleted:
                    logger.info(f"🗑️ Deleted session for user {user_id}")

                # Also clear message cache
                msg_key = self._get_message_cache_key(user_id)
                await r.delete(msg_key)

                return deleted

            except Exception as e:
                logger.error(f"Error deleting session for {user_id}: {e}")
                return False

    async def extend_session(self, user_id: str) -> bool:
        """Extend session TTL for active user"""
        async with self.get_redis() as r:
            if not r:
                return False

            try:
                key = self._get_session_key(user_id)
                return await r.expire(key, self.config.session_ttl)

            except Exception as e:
                logger.error(f"Error extending session for {user_id}: {e}")
                return False

    async def is_duplicate_message(self, user_id: str, message: str, timestamp: str) -> bool:
        """Check if message is duplicate"""
        async with self.get_redis() as r:
            if not r:
                return False
            try:
                key = self._get_message_cache_key(user_id)
                message_id = f"{message}:{timestamp}"

                exists = cast(bool, await r.sismember(key, message_id))

                if not exists:
                    await r.sadd(key, message_id)
                    await r.expire(key, 3600)

                    if cast(int, await r.scard(key)) > 100:
                        members = cast(set[bytes], await r.smembers(key))
                        if len(members) > 50:
                            to_remove = list(members)[:-50]
                            await r.srem(key, *to_remove)

                return bool(exists)

            except Exception as e:
                logger.error(f"Error checking duplicate message: {e}")
                return False

    async def get_all_active_sessions(self) -> List[str]:
        """Get list of all active user sessions"""
        async with self.get_redis() as r:
            if not r:
                return []

            try:
                pattern = "cab_bot:session:*"
                keys = []
                async for key in r.scan_iter(match=pattern):
                    keys.append(key)

                # Extract user IDs from keys
                user_ids = [
                    key.decode('utf-8').replace('cab_bot:session:', '')
                    for key in keys
                ]

                return user_ids

            except Exception as e:
                logger.error(f"Error getting active sessions: {e}")
                return []

    async def get_session_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get session metadata without loading full state"""
        async with self.get_redis() as r:
            if not r:
                return None

            try:
                key = self._get_session_key(user_id)
                ttl = await r.ttl(key)

                if ttl > 0:
                    return {
                        "user_id": user_id,
                        "ttl_seconds": ttl,
                        "expires_in": str(timedelta(seconds=ttl)),
                        "exists": True
                    }
                else:
                    return {
                        "user_id": user_id,
                        "exists": False
                    }

            except Exception as e:
                logger.error(f"Error getting session info for {user_id}: {e}")
                return None

    async def health_check(self) -> Dict[str, Any]:
        """Check Redis connection health"""
        async with self.get_redis() as r:
            if not r:
                return {
                    "status": "disconnected",
                    "redis_available": False
                }

            try:
                await r.ping()
                info = await r.info()

                return {
                    "status": "healthy",
                    "redis_available": True,
                    "redis_version": info.get("redis_version"),
                    "connected_clients": info.get("connected_clients"),
                    "used_memory_human": info.get("used_memory_human"),
                    "total_connections_received": info.get("total_connections_received"),
                    "total_commands_processed": info.get("total_commands_processed"),
                }

            except Exception as e:
                return {
                    "status": "error",
                    "redis_available": False,
                    "error": str(e)
                }


# Create singleton instance
redis_manager = AsyncRedisSessionManager()
