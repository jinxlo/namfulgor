import os
import logging
from logging.config import dictConfig
from flask import Flask, g # Import g for application context storage if needed
# Corrected Imports: Use relative import for Config and import basedir directly
from .config import Config # Import the configuration class using relative import
from .config.config import basedir # Import the basedir variable calculated in config.py

# --- Logging Configuration ---
# Using dictConfig for more structured logging setup
log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
# Corrected log_dir path calculation: Use the imported 'basedir' variable
log_dir = os.path.join(basedir, 'logs')
os.makedirs(log_dir, exist_ok=True) # Ensure log directory exists

logging_config = {
    'version': 1,
    'disable_existing_loggers': False, # Keep default Flask/Werkzeug loggers
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S'
        },
    },
    'handlers': {
        'console': {
            'level': log_level,
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
            'stream': 'ext://sys.stdout', # Output to stdout
        },
        'app_file': {
            'level': log_level,
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'standard',
            'filename': os.path.join(log_dir, 'app.log'),
            'maxBytes': 10485760,  # 10MB
            'backupCount': 5,
            'encoding': 'utf8',
        },
         'sync_file': { # Separate handler for sync logs
            'level': log_level,
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'standard',
            'filename': os.path.join(log_dir, 'sync.log'),
            'maxBytes': 5242880,  # 5MB
            'backupCount': 3,
            'encoding': 'utf8',
        }
    },
    'loggers': {
        '': {  # Root logger
            'handlers': ['console', 'app_file'], # Default handlers
            'level': log_level,
            'propagate': True
        },
        'werkzeug': { # Control Werkzeug (Flask dev server) logs
             'handlers': ['console', 'app_file'],
             'level': 'INFO', # Can set to WARNING for less noise in prod
             'propagate': False,
         },
         'sqlalchemy.engine': { # Control SQLAlchemy logs
              'handlers': ['console', 'app_file'],
              'level': 'WARNING', # Set to INFO or DEBUG for SQL query logging (if SQLALCHEMY_ECHO=True)
              'propagate': False,
          },
        'apscheduler': { # Control APScheduler logs
            'handlers': ['console', 'app_file'],
            'level': 'INFO', # Set to WARNING for less noise
            'propagate': False,
        },
         'sync': { # Specific logger for sync operations
             'handlers': ['console', 'sync_file'], # Log sync to console and sync.log
             'level': log_level,
             'propagate': False, # Don't send sync logs to root handlers again
         },
         # Add other library-specific loggers here if needed
    }
}

dictConfig(logging_config)
logger = logging.getLogger(__name__) # Get logger for this module


def create_app(config_class=Config):
    """
    Factory function to create and configure the Flask application instance.
    """
    logger.info("--- Creating Flask Application Instance ---")
    # Use the imported Config class directly here
    app = Flask(__name__)
    app.config.from_object(config_class)

    logger.info(f"Flask Environment: {app.config['FLASK_ENV']}")
    logger.info(f"Debug Mode: {app.config['DEBUG']}")

    # --- Initialize Extensions & Services ---
    logger.info("Initializing application components...")

    # Database Initialization (must happen before services that use DB)
    # Use relative imports for sibling packages/modules
    from .utils import db_utils
    if not db_utils.init_db(app):
        logger.critical("Database initialization failed. Application might not function correctly.")
        # Depending on severity, you might exit here in a real scenario
        # import sys
        # sys.exit(1)

    # Initialize OpenAI clients (done implicitly when modules are imported)
    from .utils import embedding_utils
    from .services import openai_service
    logger.info("OpenAI clients initialized (via module import).")

    # Initialize WooCommerce API client (done implicitly when module is imported)
    from .services import woocommerce_service
    logger.info("WooCommerce client initialized (via module import).")

    # --- Register Blueprints ---
    from .api import api_bp # Import the blueprint instance
    app.register_blueprint(api_bp)
    logger.info(f"API Blueprint registered under url_prefix: {api_bp.url_prefix}")

    # --- Initialize Background Scheduler ---
    # Avoid starting scheduler in Flask debug reloader's child process
    # Also check config if automatic sync is enabled
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        if app.config.get('SYNC_INTERVAL_MINUTES', 0) > 0:
            logger.info("Initializing background scheduler...")
            from .scheduler import tasks as scheduler_tasks
            # Store scheduler on app context? Not strictly necessary as tasks manages it.
            app.scheduler = scheduler_tasks.start_scheduler(app)
            if app.scheduler:
                 logger.info(f"Scheduler started. Sync interval: {app.config['SYNC_INTERVAL_MINUTES']} minutes.")
            else:
                 logger.warning("Scheduler failed to start.")
        else:
            logger.info("Automatic background sync is disabled (SYNC_INTERVAL_MINUTES <= 0).")
    else:
        # This log appears when Flask reloader starts the initial process
        logger.debug("Scheduler initialization skipped in Flask debug main process.")


    # --- Register CLI Commands ---
    register_cli_commands(app)

    logger.info("--- Namwoo Application Initialization Complete ---")
    return app


def register_cli_commands(app):
    """Registers custom CLI commands for the Flask app."""

    @app.cli.command("run-sync")
    # @click.option('--full', is_flag=True, help='Perform a full resync, ignoring modification dates.') # Example option
    def run_sync_command():
        """Runs the WooCommerce product synchronization manually."""
        logger.info("Manual sync triggered via CLI.")
        print("--- Starting Manual WooCommerce Product Sync ---")
        try:
            # Ensure we have app context for accessing config, db, etc.
            with app.app_context():
                # Use relative imports inside functions too if needed, though direct might work here
                from .scheduler import tasks as scheduler_tasks
                # Re-use the core sync logic from the scheduled task
                # Pass full_resync=True if needed (e.g., via click option)
                scheduler_tasks.run_sync_logic(app, full_resync=True)
            print("--- Manual Sync Finished ---")
            print("Check logs/sync.log for details.")
            logger.info("Manual sync finished successfully via CLI.")
        except Exception as e:
            logger.exception("Error during manual sync via CLI.")
            print(f"An error occurred during manual sync: {e}")
            print("Check logs/app.log and logs/sync.log for detailed error information.")

    @app.cli.command("create-db")
    def create_db_command():
         """Creates database tables based on defined models."""
         logger.info("Database table creation triggered via CLI.")
         print("--- Creating Database Tables ---")
         try:
              with app.app_context():
                  # Use relative imports
                  from .utils import db_utils
                  from .models import Base # Import Base from models package __init__
                  if db_utils.engine:
                       print("Creating tables...")
                       Base.metadata.create_all(bind=db_utils.engine)
                       print("Database tables created successfully (if they didn't exist).")
                       logger.info("Database tables created successfully via CLI.")
                  else:
                       print("Error: Database engine not initialized. Cannot create tables.")
                       logger.error("Database engine not initialized in create-db command.")
         except Exception as e:
              logger.exception("Error during database table creation via CLI.")
              print(f"An error occurred during table creation: {e}")

    # Add more CLI commands here (e.g., clear-history, test-embedding)

    logger.info("Custom CLI commands registered.")