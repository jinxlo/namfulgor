# namwoo_app/config/config.py (NamFulgor Version - Path Corrections)
# -*- coding: utf-8 -*-
import os
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# --- CORRECTED BASEDIR CALCULATION ---
# __file__ is namwoo_app/config/config.py
# os.path.dirname(__file__) is namwoo_app/config/
# os.path.join(os.path.dirname(__file__), '..') is namwoo_app/  <-- This is our project root
basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
dotenv_path = os.path.join(basedir, '.env') # Now correctly points to namwoo_app/.env

if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path, override=True)
    logger.debug("Loaded .env from: %s", dotenv_path)
else:
    logger.warning(".env file not found at %s", dotenv_path)

class Config:
    # --- Flask App ---
    SECRET_KEY = os.environ.get('SECRET_KEY', 'default-insecure-namfulgor-key')
    FLASK_ENV = os.environ.get('FLASK_ENV', 'production')
    DEBUG = FLASK_ENV == 'development'

    # --- Logging ---
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
    # LOG_DIR uses the corrected 'basedir'
    LOG_DIR = os.path.join(basedir, 'logs') # Now correctly points to namwoo_app/logs/
    os.makedirs(LOG_DIR, exist_ok=True)
    LOG_FILE = os.path.join(LOG_DIR, 'namfulgor_app.log') # Changed log file name for clarity

    # --- LLM Configuration ---
    LLM_PROVIDER = os.environ.get('LLM_PROVIDER', 'openai').lower()
    if LLM_PROVIDER not in ['openai', 'google']:
        logger.warning("Invalid LLM_PROVIDER '%s'. Defaulting to 'openai'.", LLM_PROVIDER)
        LLM_PROVIDER = 'openai'

    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    OPENAI_EMBEDDING_MODEL = os.environ.get('OPENAI_EMBEDDING_MODEL', 'text-embedding-3-small') # Optional if not using embeddings
    OPENAI_CHAT_MODEL = os.environ.get('OPENAI_CHAT_MODEL', 'gpt-4o-mini')
    OPENAI_MAX_TOKENS = int(os.environ.get('OPENAI_MAX_TOKENS', 1024))
    EMBEDDING_DIMENSION = int(os.environ.get('EMBEDDING_DIMENSION', 1536)) # Optional if not using embeddings
    OPENAI_REQUEST_TIMEOUT = float(os.environ.get('OPENAI_REQUEST_TIMEOUT', 60.0))

    GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
    GOOGLE_GEMINI_MODEL = os.environ.get('GOOGLE_GEMINI_MODEL', 'gemini-1.5-flash-latest')
    GOOGLE_MAX_TOKENS = int(os.environ.get('GOOGLE_MAX_TOKENS', 2048))
    GOOGLE_REQUEST_TIMEOUT = float(os.environ.get('GOOGLE_REQUEST_TIMEOUT', 60.0)) # Added for consistency

    # --- PostgreSQL Database ---
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = DEBUG # SQLALCHEMY_ECHO will be True if FLASK_ENV is 'development'

    # --- Celery & Scheduler REMOVED ---

    # --- Support Board Configuration ---
    SUPPORT_BOARD_API_URL = os.environ.get('SUPPORT_BOARD_API_URL')
    SUPPORT_BOARD_API_TOKEN = os.environ.get('SUPPORT_BOARD_API_TOKEN')
    SUPPORT_BOARD_WEBHOOK_SECRET = os.environ.get('SUPPORT_BOARD_WEBHOOK_SECRET')
    SUPPORT_BOARD_DM_BOT_USER_ID = os.environ.get('SUPPORT_BOARD_DM_BOT_USER_ID')
    COMMENT_BOT_PROXY_USER_ID = os.environ.get('COMMENT_BOT_PROXY_USER_ID')
    COMMENT_BOT_INITIATION_TAG = os.environ.get('COMMENT_BOT_INITIATION_TAG')
    _agent_ids_str = os.environ.get('SUPPORT_BOARD_AGENT_IDS', '')
    SUPPORT_BOARD_AGENT_IDS = {id.strip() for id in _agent_ids_str.split(',') if id.strip()} if _agent_ids_str else set()
    HUMAN_TAKEOVER_PAUSE_MINUTES = int(os.environ.get('HUMAN_TAKEOVER_PAUSE_MINUTES', 30)) # Adjusted default

    # --- WhatsApp Cloud API ---
    WHATSAPP_CLOUD_API_TOKEN = os.environ.get('WHATSAPP_CLOUD_API_TOKEN')
    WHATSAPP_PHONE_NUMBER_ID = os.environ.get('WHATSAPP_PHONE_NUMBER_ID')
    WHATSAPP_DEFAULT_COUNTRY_CODE = os.environ.get('WHATSAPP_DEFAULT_COUNTRY_CODE', '')
    WHATSAPP_API_VERSION = os.environ.get('WHATSAPP_API_VERSION', 'v19.0') # Kept your version

    # --- Application Specific ---
    MAX_HISTORY_MESSAGES = int(os.environ.get('MAX_HISTORY_MESSAGES', 16))

    # --- API Key for Price Updates (Email Processor) ---
    INTERNAL_SERVICE_API_KEY = os.environ.get('INTERNAL_SERVICE_API_KEY')
    if not INTERNAL_SERVICE_API_KEY:
        logger.warning("INTERNAL_SERVICE_API_KEY is not set. Price update endpoint is vulnerable.")

    # --- System Prompt for AI Assistant ---
    # Uses the corrected 'basedir' which is namwoo_app/ (or /usr/src/app/ in Docker)
    SYSTEM_PROMPT_FILE = os.path.join(basedir, 'data', 'system_prompt.txt') # Now correctly namwoo_app/data/system_prompt.txt
    try:
        with open(SYSTEM_PROMPT_FILE, 'r', encoding='utf-8') as f:
            SYSTEM_PROMPT = f.read().strip()
        logger.info("Loaded system prompt from %s", SYSTEM_PROMPT_FILE)
    except FileNotFoundError:
        logger.error("system_prompt.txt not found at %s. Using fallback.", SYSTEM_PROMPT_FILE)
        SYSTEM_PROMPT = (
            "Eres un asistente virtual especializado en baterías para vehículos. "
            "Ayuda a los clientes a encontrar la batería correcta y proporciona "
            "información sobre precios y garantía."
        )

    # --- Lead Capture API ---
    LEAD_CAPTURE_API_URL = os.environ.get('LEAD_CAPTURE_API_URL')
    LEAD_CAPTURE_API_KEY = os.environ.get('LEAD_CAPTURE_API_KEY')
    ENABLE_LEAD_GENERATION_TOOLS = os.environ.get('ENABLE_LEAD_GENERATION_TOOLS', 'true').lower() == 'true'


# --- Config Sanity Check ---
if __name__ != "__main__":  # This runs when the module is imported
    logger.info("--- NamFulgor Config Initialized (from %s) ---", __file__)
    logger.info("Project Basedir (for .env, logs): %s", basedir)
    logger.info(".env Loaded From: %s", dotenv_path if os.path.exists(dotenv_path) else 'Not Found')
    logger.info("ENV: %s, DEBUG=%s, LLM Provider: %s", Config.FLASK_ENV, Config.DEBUG, Config.LLM_PROVIDER)
    logger.info("DB URI: %s", 'SET' if Config.SQLALCHEMY_DATABASE_URI else 'MISSING')
    logger.info("Log File Path: %s", Config.LOG_FILE)
    logger.info("Support Board URL: %s", Config.SUPPORT_BOARD_API_URL)
    logger.info("DM Bot User ID: %s", Config.SUPPORT_BOARD_DM_BOT_USER_ID)
    logger.info("Internal Service API Key Loaded: %s", 'Yes' if Config.INTERNAL_SERVICE_API_KEY else 'No')
    logger.info(
        "System Prompt File: %s - Loaded: %s",
        Config.SYSTEM_PROMPT_FILE,
        'Yes' if Config.SYSTEM_PROMPT != 'Eres un asistente...' else 'Fallback Used'
    )
    logger.info("--------------------")
