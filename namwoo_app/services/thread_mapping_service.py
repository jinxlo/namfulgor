# namwoo_app/services/thread_mapping_service.py
import logging
from typing import Optional

# --- CORRECTED IMPORTS ---
from utils import db_utils
from models.thread_mapping import ThreadMapping
# -------------------------

logger = logging.getLogger(__name__)

def get_thread_id(sb_conversation_id: str, provider: str) -> Optional[str]:
    """
    Retrieves a provider-specific thread_id from the database for a given conversation.
    """
    with db_utils.get_db_session() as session:
        if not session:
            logger.error(f"Cannot get thread ID for {sb_conversation_id}: DB session not available.")
            return None
        
        mapping = session.query(ThreadMapping).filter_by(
            sb_conversation_id=sb_conversation_id,
            provider=provider
        ).first()

        if mapping:
            logger.debug(f"Found existing thread_id '{mapping.thread_id}' for conv {sb_conversation_id} and provider '{provider}'.")
            return mapping.thread_id
        
        logger.debug(f"No thread_id found for conv {sb_conversation_id} and provider '{provider}'.")
        return None

def store_thread_id(sb_conversation_id: str, thread_id: str, provider: str) -> bool:
    """
    Stores a new mapping between a conversation_id and a provider's thread_id.
    """
    with db_utils.get_db_session() as session:
        if not session:
            logger.error(f"Cannot store thread ID for {sb_conversation_id}: DB session not available.")
            return False
        
        try:
            existing = session.query(ThreadMapping).filter_by(
                sb_conversation_id=sb_conversation_id,
                provider=provider
            ).first()

            if existing:
                if existing.thread_id != thread_id:
                    logger.warning(f"Attempted to store a different thread_id for an existing mapping. Conv: {sb_conversation_id}, Provider: {provider}. Keeping original.")
                return True

            new_mapping = ThreadMapping(
                sb_conversation_id=sb_conversation_id,
                thread_id=thread_id,
                provider=provider
            )
            session.add(new_mapping)
            session.commit()
            logger.info(f"Successfully stored new thread mapping for conv {sb_conversation_id}, provider '{provider}'.")
            return True
        except Exception as e:
            logger.exception(f"Error storing thread mapping for conv {sb_conversation_id}: {e}")
            session.rollback()
            return False