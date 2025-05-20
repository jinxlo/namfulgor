import os
import logging
from logging.config import dictConfig
from flask import Flask, g  # For app context if needed
from .config.config import Config
from .config.config import basedir

# --- Logging Configuration ---
log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
log_dir = os.path.join(basedir, 'logs')
os.makedirs(log_dir, exist_ok=True)

logging_config = {
    'version': 1,
    'disable_existing_loggers': False,
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
            'stream': 'ext://sys.stdout',
        },
        'app_file': {
            'level': log_level,
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'standard',
            'filename': os.path.join(log_dir, 'app.log'),
            'maxBytes': 10485760,
            'backupCount': 5,
            'encoding': 'utf8',
        },
        'sync_file': {
            'level': log_level,
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'standard',
            'filename': os.path.join(log_dir, 'sync.log'),
            'maxBytes': 5242880,
            'backupCount': 3,
            'encoding': 'utf8',
        }
    },
    'loggers': {
        '': {
            'handlers': ['console', 'app_file'],
            'level': log_level,
            'propagate': True
        },
        'werkzeug': {
            'handlers': ['console', 'app_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'sqlalchemy.engine': {
            'handlers': ['console', 'app_file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'apscheduler': {
            'handlers': ['console', 'app_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'sync': {
            'handlers': ['console', 'sync_file'],
            'level': log_level,
            'propagate': False,
        },
    }
}

dictConfig(logging_config)
logger = logging.getLogger(__name__)

def create_app(config_class=Config):
    logger.info("--- Creating Flask Application Instance ---")
    app = Flask(__name__)
    app.config.from_object(config_class)

    logger.info(f"Flask Environment: {app.config['FLASK_ENV']}")
    logger.info(f"Debug Mode: {app.config['DEBUG']}")

    # Initialize components
    from .utils import db_utils
    if not db_utils.init_db(app):
        logger.critical("Database initialization failed. Application might not function correctly.")

    from .utils import embedding_utils
    from .services import openai_service
    logger.info("OpenAI clients initialized (via module import).")

    # WooCommerce is deprecated — removed

    # Register API Blueprint
    from .api import api_bp
    app.register_blueprint(api_bp)
    logger.info(f"API Blueprint registered under url_prefix: {api_bp.url_prefix}")

    # Register Receiver Blueprint
    from .api.receiver_routes import receiver_bp
    app.register_blueprint(receiver_bp, url_prefix='/api')
    logger.info("Receiver Blueprint registered under url_prefix: /api")

    # Background Scheduler
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        if app.config.get('SYNC_INTERVAL_MINUTES', 0) > 0:
            logger.info("Initializing background scheduler...")
            from .scheduler import tasks as scheduler_tasks
            app.scheduler = scheduler_tasks.start_scheduler(app)
            if app.scheduler:
                logger.info(f"Scheduler started. Sync interval: {app.config['SYNC_INTERVAL_MINUTES']} minutes.")
            else:
                logger.warning("Scheduler failed to start.")
        else:
            logger.info("Automatic background sync is disabled (SYNC_INTERVAL_MINUTES <= 0).")
    else:
        logger.debug("Scheduler initialization skipped in Flask debug main process.")

    register_cli_commands(app)

    logger.info("--- Namwoo Application Initialization Complete ---")
    return app

def register_cli_commands(app):
    @app.cli.command("run-sync")
    def run_sync_command():
        logger.info("Manual sync triggered via CLI.")
        print("--- Starting Manual Product Sync ---")
        try:
            with app.app_context():
                from .scheduler import tasks as scheduler_tasks
                scheduler_tasks.run_sync_logic(app, full_resync=True)
            print("--- Manual Sync Finished ---")
            print("Check logs/sync.log for details.")
            logger.info("Manual sync finished successfully via CLI.")
        except Exception as e:
            logger.exception("Error during manual sync via CLI.")
            print(f"An error occurred during manual sync: {e}")

    @app.cli.command("create-db")
    def create_db_command():
        logger.info("Database table creation triggered via CLI.")
        print("--- Creating Database Tables ---")
        try:
            with app.app_context():
                from .utils import db_utils
                from .models import Base
                if db_utils.engine:
                    print("Creating tables...")
                    Base.metadata.create_all(bind=db_utils.engine)
                    print("Database tables created successfully.")
                    logger.info("Database tables created successfully via CLI.")
                else:
                    print("Error: Database engine not initialized.")
                    logger.error("Database engine not initialized in create-db command.")
        except Exception as e:
            logger.exception("Error during database table creation via CLI.")
            print(f"An error occurred during table creation: {e}")

    logger.info("Custom CLI commands registered.")
