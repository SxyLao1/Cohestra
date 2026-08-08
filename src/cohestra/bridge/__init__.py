"""Schema-7 SQLite coordination bridge."""

from .db import SCHEMA_VERSION, BridgeError, ConversationBridge

__all__ = ["BridgeError", "ConversationBridge", "SCHEMA_VERSION"]
