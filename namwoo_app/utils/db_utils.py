# namwoo_app/utils/db_utils.py

import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session, Session
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from contextlib import contextmanager
from typing import Optional, Generator, List, Dict

from ..models import Base

logger = logging.getLogger(__name__)

# Internal "private" globals (never access these outside this file)
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
        logger.info(f"Attempting to connect to database: {loggable_db_uri}")

        _engine = create_engine(
            db_uri,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=app.config.get('SQLALCHEMY_ECHO', False)
        )
        with _engine.connect() as connection:
            logger.info("Database connection test successful.")

        _SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
        _ScopedSessionFactory = scoped_session(_SessionFactory)
        logger.info("SQLAlchemy SessionFactory and ScopedSessionFactory initialized successfully.")
        return True

    except OperationalError as oe:
        logger.error(f"Database connection failed (OperationalError): {oe}", exc_info=True)
        _engine = None; _SessionFactory = None; _ScopedSessionFactory = None
        return False
    except Exception as e:
        logger.error(f"Database initialization failed: {e}", exc_info=True)
        _engine = None; _SessionFactory = None; _ScopedSessionFactory = None
        return False

@contextmanager
def get_db_session() -> Generator[Optional[Session], None, None]:
    """
    Yields a SQLAlchemy Session, handles commit/rollback, and always removes session from scope.
    Always use via: `with get_db_session() as session:`
    """
    if not _ScopedSessionFactory:
        logger.error("ScopedSessionFactory not initialized. Cannot create DB session.")
        yield None
        return

    session: Session = _ScopedSessionFactory()
    logger.debug(f"DB Session {id(session)} acquired from ScopedSessionFactory.")
    try:
        yield session
        session.commit()
        logger.debug(f"DB Session {id(session)} committed.")
    except SQLAlchemyError as e:
        logger.error(f"DB Session {id(session)} SQLAlchemy error: {e}", exc_info=True)
        session.rollback()
        logger.debug(f"DB Session {id(session)} rolled back due to SQLAlchemyError.")
        raise
    except Exception as e:
        logger.error(f"DB Session {id(session)} unexpected error: {e}", exc_info=True)
        session.rollback()
        logger.debug(f"DB Session {id(session)} rolled back due to unexpected error.")
        raise
    finally:
        logger.debug(f"DB Session {id(session)} scope ending. Calling ScopedSessionFactory.remove().")
        _ScopedSessionFactory.remove()
        logger.debug(f"DB Session {id(session)} removed from current scope by ScopedSessionFactory.")

def create_all_tables(app) -> bool:
    """
    Create all tables from SQLAlchemy models and ensure pgvector is present.
    """
    if not _engine:
        logger.error("Database engine not initialized. Cannot create tables.")
        return False
    try:
        logger.info("Attempting to create tables from SQLAlchemy models (if they don't already exist)...")
        Base.metadata.create_all(bind=_engine)
        logger.info("SQLAlchemy Base.metadata.create_all() executed.")

        with _engine.connect() as connection:
            with connection.begin():
                logger.info("Ensuring pgvector extension exists in the database...")
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                logger.info("pgvector extension check complete.")
        return True
    except Exception as e:
        logger.error(f"Error during create_all_tables: {e}", exc_info=True)
        return False

def fetch_history(session_id: str) -> Optional[List[Dict]]:
    """
    Fetches conversation history for a given session_id.
    """
    with get_db_session() as session:
        if not session: return None
        from ..models.history import ConversationHistory
        try:
            record = session.query(ConversationHistory).filter_by(session_id=session_id).first()
            if record and record.history_data:
                return record.history_data
            return []
        except Exception as e:
            logger.exception(f"Error fetching history for session {session_id}: {e}")
            return None

def save_history(session_id: str, history_list: List[Dict]) -> bool:
    """
    Saves or updates conversation history for a given session_id.
    """
    with get_db_session() as session:
        if not session: return False
        from ..models.history import ConversationHistory
        try:
            record = session.query(ConversationHistory).filter_by(session_id=session_id).first()
            if record:
                record.history_data = history_list
            else:
                record = ConversationHistory(session_id=session_id, history_data=history_list)
                session.add(record)
            return True
        except Exception as e:
            logger.exception(f"Error saving history for session {session_id}: {e}")
            return False

