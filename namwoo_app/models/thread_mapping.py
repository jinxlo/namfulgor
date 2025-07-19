# namwoo_app/models/thread_mapping.py
import datetime
from sqlalchemy import Column, Integer, String, DateTime, func, UniqueConstraint
from . import Base

class ThreadMapping(Base):
    """
    SQLAlchemy ORM model for the 'thread_mappings' table.
    Maps a Support Board conversation ID to a provider-specific thread ID
    (e.g., an OpenAI Assistant thread_id).
    """
    __tablename__ = 'thread_mappings'

    id = Column(Integer, primary_key=True)
    sb_conversation_id = Column(String(255), nullable=False, index=True)
    provider = Column(String(50), nullable=False, comment="e.g., 'openai_assistant', 'azure_assistant'")
    thread_id = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint('sb_conversation_id', 'provider', name='uq_sb_conversation_provider'),
    )

    def __repr__(self):
        return (f"<ThreadMapping(sb_conv_id='{self.sb_conversation_id}', "
                f"provider='{self.provider}', thread_id='{self.thread_id}')>")