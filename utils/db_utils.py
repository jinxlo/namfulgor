import logging
from sqlalchemy import create_engine, text # Keep text for db ping
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from contextlib import contextmanager
from typing import Optional, Generator # Removed List, Dict as they were for history

# --- REMOVED History Model Import ---
# from ..models.history import ConversationHistory

# Keep Base import if other models still use it (like Product)
from ..models import Base
# Keep Config import
from ..config import Config

logger = logging.getLogger(__name__)

# Module-level variables for engine and session factory
engine = None
SessionFactory = None # Will be configured by init_db

def init_db(app):
    """
    Initializes the database engine and session factory using Flask app config.
    Should be called once during application startup (in create_app).
    """
    global engine, SessionFactory

    loaded_db_uri = app.config.get('SQLALCHEMY_DATABASE_URI')
    # Use print for early debug before logging might be configured
    print(f"DEBUG [db_utils.init_db]: Checking SQLALCHEMY_DATABASE_URI. Value from app.config = {loaded_db_uri}")

    db_uri = loaded_db_uri
    if not db_uri:
        # Use logger if available, otherwise print as fallback
        log_func = logger.error if logger else print
        log_func("ERROR [db_utils.init_db]: DATABASE_URL is not configured. Database features will be disabled.")
        return False

    try:
        log_func = logger.info if logger else print
        log_func(f"INFO [db_utils.init_db]: Initializing database connection to: {db_uri.split('@')[-1]}")
        engine = create_engine(
            db_uri,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=app.config.get('SQLALCHEMY_ECHO', False)
        )

        # Test the connection
        with engine.connect() as connection:
             log_func("INFO [db_utils.init_db]: Database connection successful.")

        # Configure the session factory
        SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        log_func("INFO [db_utils.init_db]: Database SessionFactory configured.")

        return True

    except OperationalError as e:
         log_func = logger.exception if logger else print
         log_func(f"ERROR [db_utils.init_db]: Failed to connect to the database: {e}")
         engine = None
         SessionFactory = None
         return False
    except Exception as e:
        log_func = logger.exception if logger else print
        log_func(f"ERROR [db_utils.init_db]: An unexpected error occurred during database initialization: {e}")
        engine = None
        SessionFactory = None
        return False


@contextmanager
def get_db_session() -> Generator[Optional[scoped_session], None, None]:
    """
    Provides a transactional database session context.
    Handles session creation, commit, rollback, and closing.
    """
    if not SessionFactory:
        logger.error("Database SessionFactory not initialized. Cannot create session.")
        yield None # Indicate failure
        return

    # Use scoped_session for thread-local session management
    session = scoped_session(SessionFactory)
    try:
        yield session
        session.commit()
        # logger.debug("DB Session committed successfully.") # Usually too verbose
    except SQLAlchemyError as e:
        logger.exception(f"Database error occurred during session. Rolling back: {e}")
        session.rollback()
        raise # Re-raise to signal failure
    except Exception as e:
        logger.exception(f"An unexpected error occurred during DB session. Rolling back: {e}")
        session.rollback()
        raise # Re-raise
    finally:
        # logger.debug("Closing DB Session.") # Usually too verbose
        session.remove()

# --- REMOVED: Conversation History CRUD Operations ---
# def fetch_history(session_id: str) -> Optional[List[Dict]]:
#     """ (Removed - History fetched via Support Board API now) """
#     pass # Or delete function entirely

# def save_history(session_id: str, history_list: List[Dict]) -> bool:
#     """ (Removed - History state managed by Support Board now) """
#     pass # Or delete function entirely

# --- Database Creation Function (Keep this) ---
def create_all_tables():
    """Creates all database tables defined in models."""
    if not engine:
        logger.error("Database engine not initialized. Cannot create tables.")
        return False
    try:
        logger.info("Creating database tables based on models...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created (if they didn't exist).")

        # --- Add pgvector extension creation if not done elsewhere ---
        # It's often better done manually or via migration tools, but can be here.
        with engine.connect() as connection:
             with connection.begin(): # Start a transaction
                  logger.info("Ensuring pgvector extension exists...")
                  # Use IF NOT EXISTS to avoid errors if already present
                  connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                  logger.info("pgvector extension check complete.")
        # -------------------------------------------------------------
        return True
    except Exception as e:
        logger.exception(f"Error creating database tables: {e}")
        return False