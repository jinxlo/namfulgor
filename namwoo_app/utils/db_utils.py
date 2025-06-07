# namwoo_app/utils/db_utils.py (NamFulgor Version - Corrected Imports)

import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session, Session as SQLAlchemySession
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from contextlib import contextmanager
from typing import Optional, Generator, List, Dict # List, Dict might not be needed if history is removed

import datetime
from datetime import timezone

# --- CORRECTED IMPORTS ---
from models import Base # Assumes Base is defined/exported by namwoo_app/models/__init__.py
from models.conversation_pause import ConversationPause # Assumes this class is in namwoo_app/models/conversation_pause.py
# REMOVE: from models.history import ConversationHistory # As you confirmed you don't have this model/file
from config.config import Config # Assumes Config class is in namwoo_app/config/config.py

logger = logging.getLogger(__name__)

_engine = None
_SessionFactory = None
_ScopedSessionFactory = None

def init_db(app) -> bool:
    """
    Initialize the SQLAlchemy engine and session factories using app config.
    """
    global _engine, _SessionFactory, _ScopedSessionFactory

    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI')
    if not db_uri:
        logger.error("SQLALCHEMY_DATABASE_URI not configured. Database features will fail.")
        return False

    try:
        db_uri_parts = db_uri.split('@')
        loggable_db_uri = db_uri_parts[-1] if len(db_uri_parts) > 1 else db_uri
        logger.info(f"Attempting to connect to database for NamFulgor: {loggable_db_uri}")

        _engine = create_engine(
            db_uri,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=app.config.get('SQLALCHEMY_ECHO', False)
        )
        with _engine.connect() as connection:
            logger.info("Database connection test successful for NamFulgor.")

        _SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
        _ScopedSessionFactory = scoped_session(_SessionFactory)
        logger.info("SQLAlchemy SessionFactory and ScopedSessionFactory initialized successfully for NamFulgor.")
        return True

    except OperationalError as oe:
        logger.error(f"Database connection failed (OperationalError) for NamFulgor: {oe}", exc_info=True)
        _engine = None; _SessionFactory = None; _ScopedSessionFactory = None
        return False
    except Exception as e:
        logger.error(f"Database initialization failed for NamFulgor: {e}", exc_info=True)
        _engine = None; _SessionFactory = None; _ScopedSessionFactory = None
        return False

@contextmanager
def get_db_session() -> Generator[Optional[SQLAlchemySession], None, None]:
    """
    Yields a SQLAlchemy Session, handles commit/rollback, and always removes session from scope.
    """
    if not _ScopedSessionFactory:
        logger.error("ScopedSessionFactory not initialized. Cannot create DB session.")
        yield None
        return

    session: SQLAlchemySession = _ScopedSessionFactory()
    try:
        yield session
        session.commit()
    except SQLAlchemyError as e:
        logger.error(f"DB Session {id(session)} SQLAlchemy error: {e}", exc_info=True)
        session.rollback()
        raise
    except Exception as e:
        logger.error(f"DB Session {id(session)} unexpected error: {e}", exc_info=True)
        session.rollback()
        raise
    finally:
        _ScopedSessionFactory.remove()

def create_all_tables(app) -> bool:
    """
    Create all tables from SQLAlchemy models (linked to Base.metadata)
    and ensure pgvector extension is present.
    For NamFulgor, this creates 'batteries', 'vehicle_battery_fitment',
    'battery_vehicle_fitments', 'conversation_pauses'.
    """
    if not _engine:
        logger.error("Database engine not initialized. Cannot create tables for NamFulgor.")
        return False
    try:
        logger.info("Attempting to create tables for NamFulgor from SQLAlchemy models...")
        Base.metadata.create_all(bind=_engine)
        logger.info("SQLAlchemy Base.metadata.create_all() executed for NamFulgor.")

        with _engine.connect() as connection:
            with connection.begin():
                logger.info("Ensuring pgvector extension exists in the database for NamFulgor...")
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                logger.info("pgvector extension check complete for NamFulgor.")
        return True
    except Exception as e:
        logger.error(f"Error during NamFulgor create_all_tables: {e}", exc_info=True)
        return False

# --- Conversation History Functions REMOVED ---
# def fetch_history(...)
# def save_history(...)

# --- CONVERSATION PAUSE MANAGEMENT FUNCTIONS (Kept as is, imports are now absolute if they were relative) ---
# (The internal logic of these functions should be fine, their imports were at the top of the file)

def is_conversation_paused(conversation_id: str) -> bool:
    with get_db_session() as session:
        if not session:
            logger.error(f"Cannot check pause status for conv {conversation_id}: DB session not available.")
            return False
        try:
            now_utc = datetime.datetime.now(timezone.utc)
            pause_record = session.query(ConversationPause)\
                .filter(ConversationPause.conversation_id == conversation_id)\
                .filter(ConversationPause.paused_until > now_utc)\
                .first()
            return True if pause_record else False
        except Exception as e:
            logger.exception(f"Error checking pause status for conversation {conversation_id}: {e}")
            return False

def get_pause_record(conversation_id: str) -> Optional[ConversationPause]:
    with get_db_session() as session:
        if not session: return None
        try:
            now_utc = datetime.datetime.now(timezone.utc)
            return session.query(ConversationPause)\
                .filter(ConversationPause.conversation_id == conversation_id)\
                .filter(ConversationPause.paused_until > now_utc)\
                .first()
        except Exception as e:
            logger.exception(f"Error getting pause record for conversation {conversation_id}: {e}")
            return None

def pause_conversation_for_duration(conversation_id: str, duration_seconds: int):
    with get_db_session() as session:
        if not session: return
        try:
            pause_until_time = datetime.datetime.now(timezone.utc) + datetime.timedelta(seconds=duration_seconds)
            pause_record = session.query(ConversationPause).filter_by(conversation_id=conversation_id).first()
            if pause_record:
                pause_record.paused_until = pause_until_time
            else:
                pause_record = ConversationPause(conversation_id=conversation_id, paused_until=pause_until_time)
                session.add(pause_record)
            logger.info(f"Pause set/updated for conversation {conversation_id} until {pause_until_time.isoformat()}.")
        except Exception as e:
            logger.exception(f"Error pausing conversation {conversation_id}: {e}")

def unpause_conversation(conversation_id: str):
    with get_db_session() as session:
        if not session: return
        try:
            pause_record = session.query(ConversationPause).filter_by(conversation_id=conversation_id).first()
            if pause_record:
                session.delete(pause_record)
                logger.info(f"Deleted pause record for conversation {conversation_id}.")
        except Exception as e:
            logger.exception(f"Error unpausing conversation {conversation_id}: {e}")