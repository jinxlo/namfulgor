# models/conversation_pause.py
import logging
from sqlalchemy import Column, String, DateTime, Integer # Added Integer just in case SB ID is numeric
from sqlalchemy.dialects.postgresql import VARCHAR, TIMESTAMP # Specific PG types
from . import Base # Import Base from the models package's __init__.py
import datetime

logger = logging.getLogger(__name__)

class ConversationPause(Base):
    """
    SQLAlchemy ORM model representing the 'conversation_pauses' table.
    Tracks when a conversation should be paused for the bot due to human takeover.
    """
    __tablename__ = 'conversation_pauses'

    # Corresponds to conversation_id VARCHAR(255) PRIMARY KEY in schema.sql
    conversation_id = Column(String(255), primary_key=True)

    # Corresponds to paused_until TIMESTAMP WITH TIME ZONE NOT NULL in schema.sql
    # Storing timezone-aware datetime is crucial for comparisons
    paused_until = Column(DateTime(timezone=True), nullable=False)

    def __repr__(self):
        """Provides a developer-friendly representation of the ConversationPause object."""
        # Format timestamp for better readability in logs/debug
        paused_str = self.paused_until.isoformat() if self.paused_until else 'None'
        return f"<ConversationPause(conversation_id='{self.conversation_id}', paused_until='{paused_str}')>"

    def is_active(self) -> bool:
        """Checks if the pause is currently active (paused_until is in the future)."""
        if not self.paused_until:
            return False # Should not happen due to NOT NULL, but safe check
        # Ensure comparison is timezone-aware
        return self.paused_until > datetime.datetime.now(datetime.timezone.utc)