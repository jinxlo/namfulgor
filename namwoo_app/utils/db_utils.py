# NAMWOO/utils/db_utils.py
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session, Session # Session is correctly imported
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from contextlib import contextmanager
from typing import Optional, Generator, List, Dict

from ..models import Base 

logger = logging.getLogger(__name__)

engine = None
# _SessionFactory will store the result of sessionmaker()
_SessionFactory: Optional[sessionmaker] = None
# _ScopedSessionFactory will store the result of scoped_session(_SessionFactory)
_ScopedSessionFactory: Optional[scoped_session] = None

def init_db(app):
    global engine, _SessionFactory, _ScopedSessionFactory # Include _ScopedSessionFactory

    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI')
    if not db_uri:
        logger.error("SQLALCHEMY_DATABASE_URI not configured. Database features will fail.")
        return False

    try:
        db_uri_parts = db_uri.split('@')
        loggable_db_uri = db_uri_parts[-1] if len(db_uri_parts) > 1 else db_uri
        logger.info(f"Attempting to connect to database: {loggable_db_uri}")
        
        engine = create_engine(
            db_uri,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=app.config.get('SQLALCHEMY_ECHO', False)
        )
        with engine.connect() as connection:
            logger.info("Database connection test successful.")

        _SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        # Create the scoped_session factory using the sessionmaker
        _ScopedSessionFactory = scoped_session(_SessionFactory)
        logger.info("SQLAlchemy SessionFactory and ScopedSessionFactory initialized successfully.")
        return True

    except OperationalError as oe:
        logger.error(f"Database connection failed (OperationalError): {oe}", exc_info=True)
        engine = None; _SessionFactory = None; _ScopedSessionFactory = None
        return False
    except Exception as e:
        logger.error(f"Database initialization failed: {e}", exc_info=True)
        engine = None; _SessionFactory = None; _ScopedSessionFactory = None
        return False

@contextmanager
def get_db_session() -> Generator[Optional[Session], None, None]:
    """Provides a transactional scope around a series of operations using a scoped session."""
    if not _ScopedSessionFactory: # Check if the scoped_session factory is initialized
        logger.error("ScopedSessionFactory not initialized. Cannot create DB session.")
        yield None
        return

    # Get a Session instance from the scoped_session factory
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
        # For a session obtained from scoped_session(), calling .remove() on the
        # scoped_session factory itself is the standard way to ensure the Session
        # is returned to the pool or otherwise disposed of correctly for the current scope.
        _ScopedSessionFactory.remove() 
        logger.debug(f"DB Session {id(session)} removed from current scope by ScopedSessionFactory.")

# --- create_all_tables (no changes needed from your version, it uses db_utils.engine correctly) ---
def create_all_tables(app): 
    if not engine:
        logger.error("Database engine not initialized. Cannot create tables.")
        return False
    try:
        logger.info("Attempting to create tables from SQLAlchemy models (if they don't already exist)...")
        Base.metadata.create_all(bind=engine) 
        logger.info("SQLAlchemy Base.metadata.create_all() executed.")

        with engine.connect() as connection:
            with connection.begin(): 
                logger.info("Ensuring pgvector extension exists in the database...")
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                logger.info("pgvector extension check complete.")
        return True
    except Exception as e:
        logger.error(f"Error during create_all_tables: {e}", exc_info=True)
        return False

# --- Conversation History Functions (no changes needed from your version, they use get_db_session) ---
def fetch_history(session_id: str) -> Optional[List[Dict]]:
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