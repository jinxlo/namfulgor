# /home/ec2-user/namwoo_app/namwoo_app/__init__.py
import os
import logging
from logging.config import dictConfig
from flask import Flask
from .config.config import Config

# --- Logging Configuration ---
log_level_env = os.environ.get('LOG_LEVEL', 'INFO').upper()
log_dir_path = os.path.join(Config.basedir if hasattr(Config, 'basedir') else os.path.abspath(os.path.join(os.path.dirname(__file__), '..')), 'logs')
os.makedirs(log_dir_path, exist_ok=True)

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
            'level': log_level_env,
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
            'stream': 'ext://sys.stdout',
        },
        'app_file': {
            'level': log_level_env,
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'standard',
            'filename': os.path.join(log_dir_path, 'app.log'),
            'maxBytes': 10485760,
            'backupCount': 5,
            'encoding': 'utf8',
        },
        'sync_file': {
            'level': log_level_env,
            'class': 'logging.handlers.RotatingFileHandler',
            'formatter': 'standard',
            'filename': os.path.join(log_dir_path, 'sync.log'),
            'maxBytes': 5242880,
            'backupCount': 3,
            'encoding': 'utf8',
        }
    },
    'loggers': {
        '': {
            'handlers': ['console', 'app_file'],
            'level': log_level_env,
            'propagate': True
        },
        'werkzeug': {'handlers': ['console', 'app_file'], 'level': 'INFO', 'propagate': False,},
        'sqlalchemy.engine': {'handlers': ['console', 'app_file'], 'level': 'WARNING','propagate': False,},
        'apscheduler': {'handlers': ['console', 'app_file'], 'level': 'INFO', 'propagate': False,},
        'sync': {'handlers': ['console', 'sync_file'], 'level': log_level_env, 'propagate': False,},
        'celery': {'handlers': ['console', 'app_file'], 'level': log_level_env, 'propagate': False,},
    }
}
dictConfig(logging_config)
logger = logging.getLogger(__name__)

def create_app(config_class=Config):
    logger.info("--- Creating Flask Application Instance ---")
    app = Flask(__name__)
    app.config.from_object(config_class)

    logger.info(f"Flask Environment: {app.config.get('FLASK_ENV', 'not_set')}")
    logger.info(f"Debug Mode: {app.config.get('DEBUG', False)}")

    # Initialize components
    from .utils import db_utils
    if not db_utils.init_db(app):
        logger.critical("Database initialization failed. Application might not function correctly.")

    logger.info("Dependent services (like OpenAI) will be initialized as needed or at module level.")

    # ----------- FIX IS HERE: REGISTER api_bp ONLY ONCE -----------
    from .api import api_bp
    if api_bp.name not in app.blueprints:
        app.register_blueprint(api_bp)
        logger.info(f"Main API Blueprint registered under url_prefix: {api_bp.url_prefix}")
    else:
        logger.warning(f"Blueprint {api_bp.name} already registered; skipping duplicate registration.")

    # ----------- REMOVE REDUNDANT BLUEPRINT REGISTRATION HERE! -----------

    # Background Scheduler (APScheduler)
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        if app.config.get('SYNC_INTERVAL_MINUTES', 0) > 0:
            logger.info("Initializing background scheduler (APScheduler)...")
            from .scheduler import tasks as scheduler_tasks
            scheduler_instance = getattr(app, 'scheduler', None)
            if scheduler_instance is None or not scheduler_instance.running:
                app.scheduler = scheduler_tasks.start_scheduler(app)
                if app.scheduler:
                    logger.info(f"APScheduler started. Sync interval: {app.config['SYNC_INTERVAL_MINUTES']} minutes.")
                else:
                    logger.warning("APScheduler failed to start or was disabled.")
            else:
                logger.info("APScheduler already running.")
        else:
            logger.info("Automatic background sync (APScheduler) is disabled (SYNC_INTERVAL_MINUTES <= 0).")
    else:
        logger.debug("APScheduler initialization skipped in Flask debug reloader process.")

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
                    print("Creating tables from SQLAlchemy models...")
                    Base.metadata.create_all(bind=db_utils.engine)
                    print("Database tables (from models) created successfully.")
                    logger.info("Database tables (from models) created successfully via CLI.")

                    from sqlalchemy import text
                    with db_utils.engine.connect() as connection:
                        with connection.begin():
                            logger.info("Ensuring pgvector extension exists in the database (CLI)...")
                            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                            logger.info("pgvector extension check complete (CLI).")
                else:
                    print("Error: Database engine not initialized.")
                    logger.error("Database engine not initialized in create-db command.")
        except Exception as e:
            logger.exception("Error during database table creation via CLI.")
            print(f"An error occurred during table creation: {e}")

    logger.info("Custom CLI commands registered.")
