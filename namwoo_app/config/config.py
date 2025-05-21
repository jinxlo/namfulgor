# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
dotenv_path = os.path.join(basedir, '.env')

if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path, override=True)
    print(f"DEBUG [config.py]: Loaded .env from: {dotenv_path}")
else:
    print(f"WARNING: .env file not found at {dotenv_path}")

class Config:
    # --- Flask App ---
    SECRET_KEY = os.environ.get('SECRET_KEY', 'default-insecure-secret-key')
    FLASK_ENV = os.environ.get('FLASK_ENV', 'production')
    DEBUG = FLASK_ENV == 'development'

    # --- Logging ---
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
    LOG_DIR = os.path.join(basedir, 'logs')
    os.makedirs(LOG_DIR, exist_ok=True)
    LOG_FILE = os.path.join(LOG_DIR, 'app.log')
    SYNC_LOG_FILE = os.path.join(LOG_DIR, 'sync.log')

    # --- LLM Configuration ---
    LLM_PROVIDER = os.environ.get('LLM_PROVIDER', 'openai').lower()
    if LLM_PROVIDER not in ['openai', 'google']:
        print(f"WARNING [Config]: Invalid LLM_PROVIDER '{LLM_PROVIDER}'. Defaulting to 'openai'.")
        LLM_PROVIDER = 'openai'

    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    OPENAI_EMBEDDING_MODEL = os.environ.get('OPENAI_EMBEDDING_MODEL', 'text-embedding-3-small')
    OPENAI_CHAT_MODEL = os.environ.get('OPENAI_CHAT_MODEL', 'gpt-4o-mini')
    OPENAI_MAX_TOKENS = int(os.environ.get('OPENAI_MAX_TOKENS', 1024))
    EMBEDDING_DIMENSION = int(os.environ.get('EMBEDDING_DIMENSION', 1536))

    GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
    GOOGLE_GEMINI_MODEL = os.environ.get('GOOGLE_GEMINI_MODEL', 'gemini-2.0-flash') # Reverted to your original
    GOOGLE_MAX_TOKENS = int(os.environ.get('GOOGLE_MAX_TOKENS', 2048))

    # --- PostgreSQL Database ---
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = DEBUG

    # --- Celery Task Queue Configuration (NEW SECTION) ---
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
    # Optional: Set a default task queue name if you plan to have multiple
    # CELERY_DEFAULT_QUEUE = 'namwoo_default_queue'
    # Optional: If tasks might be long-running, you might adjust visibility timeout
    # CELERY_BROKER_TRANSPORT_OPTIONS = {'visibility_timeout': 3600} # 1 hour example for Redis

    # --- Scheduler ---
    SYNC_INTERVAL_MINUTES = int(os.environ.get('SYNC_INTERVAL_MINUTES', 60))

    # --- Support Board Configuration ---
    SUPPORT_BOARD_API_URL = os.environ.get('SUPPORT_BOARD_API_URL')
    SUPPORT_BOARD_API_TOKEN = os.environ.get('SUPPORT_BOARD_API_TOKEN')
    SUPPORT_BOARD_BOT_USER_ID = os.environ.get('SUPPORT_BOARD_BOT_USER_ID')
    SUPPORT_BOARD_SENDER_USER_ID = os.environ.get('SUPPORT_BOARD_SENDER_USER_ID')
    SUPPORT_BOARD_WEBHOOK_SECRET = os.environ.get('SUPPORT_BOARD_WEBHOOK_SECRET')

    # --- WhatsApp Cloud API ---
    WHATSAPP_CLOUD_API_TOKEN = os.environ.get('WHATSAPP_CLOUD_API_TOKEN')
    WHATSAPP_PHONE_NUMBER_ID = os.environ.get('WHATSAPP_PHONE_NUMBER_ID')
    WHATSAPP_DEFAULT_COUNTRY_CODE = os.environ.get('WHATSAPP_DEFAULT_COUNTRY_CODE', '')
    WHATSAPP_API_VERSION = os.environ.get('WHATSAPP_API_VERSION', 'v19.0')

    # --- Human Takeover ---
    _agent_ids_str = os.environ.get('SUPPORT_BOARD_AGENT_IDS', '')
    # Kept your original logic for parsing agent IDs
    SUPPORT_BOARD_AGENT_IDS = {int(id.strip()) for id in _agent_ids_str.split(',') if id.strip()}
    HUMAN_TAKEOVER_PAUSE_MINUTES = int(os.environ.get('HUMAN_TAKEOVER_PAUSE_MINUTES', 30))

    # --- Application Specific ---
    MAX_HISTORY_MESSAGES = int(os.environ.get('MAX_HISTORY_MESSAGES', 16))
    PRODUCT_SEARCH_LIMIT = max(5, int(os.environ.get('PRODUCT_SEARCH_LIMIT', 10)))

    # --- Damasco Specific ---
    DAMASCO_RECEIVER_API_URL = os.environ.get('DAMASCO_RECEIVER_API_URL')
    DAMASCO_API_SECRET = os.environ.get('DAMASCO_API_SECRET')

    if not DAMASCO_API_SECRET:
        print("WARNING [Config]: DAMASCO_API_SECRET is not set. Receiver endpoint will reject requests.")

    # --- System Prompt for AI Assistant (from file) ---
    SYSTEM_PROMPT_FILE = os.path.join(basedir, 'data', 'system_prompt.txt')
    try:
        with open(SYSTEM_PROMPT_FILE, 'r', encoding='utf-8') as f:
            SYSTEM_PROMPT = f.read().strip()
        print(f"INFO [Config]: Loaded system prompt from {SYSTEM_PROMPT_FILE}")
    except FileNotFoundError:
        print(f"ERROR [Config]: system_prompt.txt not found at {SYSTEM_PROMPT_FILE}. Using fallback.")
        SYSTEM_PROMPT = "Default fallback system prompt content here." # Kept your original fallback

# --- Config Sanity Check (with new Celery vars) ---
# This part runs when config.py is imported.
if __name__ != "__main__":
    print(f"--- Config Initialized ---")
    print(f"ENV: {Config.FLASK_ENV}, DEBUG={Config.DEBUG}, LLM Provider: {Config.LLM_PROVIDER}")
    print(f"DB URI: {'SET' if Config.SQLALCHEMY_DATABASE_URI else 'MISSING'}")
    print(f"Celery Broker URL: {Config.CELERY_BROKER_URL}")
    print(f"Celery Result Backend: {Config.CELERY_RESULT_BACKEND}")
    print(f"Support Board URL: {Config.SUPPORT_BOARD_API_URL}")
    print(f"WhatsApp Config Loaded: {'Yes' if Config.WHATSAPP_CLOUD_API_TOKEN else 'No'}")
    print(f"Damasco Receiver API URL: {Config.DAMASCO_RECEIVER_API_URL}") # Kept as is from your original
    print(f"Damasco API Secret Loaded: {'Yes' if Config.DAMASCO_API_SECRET else 'No'}")
    print(f"--------------------")