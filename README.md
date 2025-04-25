# Namwoo - WooCommerce & Support Board Assistant Backend

## Overview

Namwoo is a Python Flask web application backend designed to power a conversational AI assistant integrated with **Support Board** and **WooCommerce**. It allows users interacting via **WhatsApp** and **Instagram** (through Support Board) to search for products, inquire about details, and check availability using natural language.

The core strategy focuses on providing relevant product information quickly:
1.  **Local Caching:** Product data (name, SKU, description, price, stock status, etc.) is periodically synced from WooCommerce into a local PostgreSQL database.
2.  **Vector Search:** Product text is converted into embeddings (using OpenAI's models by default) and stored in PostgreSQL using the `pgvector` extension. This enables fast, semantic search (understanding meaning, not just keywords).
3.  **OpenAI Function Calling:** GPT models (like `gpt-4o-mini`) interpret user queries and intelligently decide when to:
    *   Call `search_local_products`: Queries the *fast local cache* using vector similarity for general product discovery.
    *   Call `get_live_product_details`: Makes a targeted, *real-time API call* to WooCommerce for specific details (like exact stock count) only when necessary for an already identified product.
4.  **Support Board Integration:**
    *   Receives incoming messages from WhatsApp and Instagram via Support Board webhooks.
    *   Uses the Support Board API (`get-user`, `get-conversation`) to fetch context like customer details (PSID for Instagram/Facebook, Phone/WAID for WhatsApp) and conversation history.
    *   Sends outgoing **Instagram/Facebook** replies via the Support Board `messenger-send-message` API (using `metadata` for potential linking) AND logs the message internally using the SB `send-message` API for dashboard visibility.
    *   Sends outgoing **WhatsApp** replies **directly via the Meta WhatsApp Cloud API** AND logs the message internally using the SB `send-message` API for dashboard visibility.
5.  **Human Takeover:** Detects when a human agent replies in Support Board and pauses the bot's automatic responses for that specific conversation for a configurable duration. Pause state is managed in the PostgreSQL database.

## Features

*   **Support Board Webhook Integration:** Handles incoming `message-sent` webhooks for WhatsApp and Instagram.
*   **Direct WhatsApp Cloud API Integration:** Sends replies directly via Meta's API for WhatsApp messages.
*   **Support Board API Integration:** Uses SB API for context fetching (users, conversations) and sending replies to Instagram/Facebook.
*   **Intelligent Product Search:** Combines semantic search (via `pgvector`) with optional stock filtering on cached data.
*   **Real-time Detail Fetching:** Retrieves live stock and price for specific items directly from WooCommerce when needed.
*   **OpenAI Function Calling:** Leverages LLMs for natural language understanding and action triggering.
*   **WooCommerce Integration:** Connects securely to the WooCommerce REST API.
*   **PostgreSQL Backend:** Stores product cache, vector embeddings, and conversation pause state.
*   **Automatic Sync:** Periodically updates the local product cache and embeddings using a background scheduler (APScheduler).
*   **Manual Sync Command:** Allows triggering a full data synchronization via the Flask CLI.
*   **Human Agent Takeover Pause:** Temporarily stops bot replies in a specific conversation when a human agent intervenes.
*   **Configuration:** Easily configured via a `.env` file.
*   **Structured Logging:** Separate logs for application events and synchronization tasks.
*   **Production Ready:** Includes setup for running with Gunicorn behind a reverse proxy (like Caddy or Nginx).

## Folder Structure

/namwoo/ # Project Root
|-- namwoo_app/ # Main Flask application package
| |-- __init__.py # App factory, initializes extensions, logging, scheduler, CLI
| |-- api/ # API Blueprint (webhook, health check)
| | |-- __init__.py # Blueprint setup
| | |-- routes.py # Webhook request handling logic (incl. pause logic)
| |-- models/ # SQLAlchemy ORM Models
| | |-- __init__.py # Base model definition, imports models
| | |-- product.py # Product table model
| | |-- conversation_pause.py # ConversationPause table model (NEW)
| |-- services/ # Business logic modules
| | |-- __init__.py
| | |-- openai_service.py # Handles OpenAI Chat Completions & Function Calling
| | |-- product_service.py # Handles querying LOCAL product data (SQL + Vector Search) & DB updates
| | |-- woocommerce_service.py # Handles LIVE calls to WooCommerce API
| | |-- support_board_service.py # Handles interactions with SB API & Direct WA Cloud API (MODIFIED)
| | |-- sync_service.py # Logic for fetching data from WooComm & triggering DB updates/embeddings
| |-- scheduler/ # Background task scheduling (APScheduler)
| | |-- __init__.py
| | |-- tasks.py # Defines the scheduled sync task & scheduler management
| |-- utils/ # Utility modules
| | |-- __init__.py
| | |-- db_utils.py # Handles PostgreSQL connection, session management
| | |-- embedding_utils.py # Helper to generate embeddings via OpenAI API
|-- config/ # Configuration files
| |-- __init__.py
| |-- config.py # Loads config from .env into Flask app config (MODIFIED)
|-- data/ # SQL schema file(s)
| |-- schema.sql # Contains CREATE TABLE statements (MODIFIED - removed history, added pauses)
|-- logs/ # Log files (app.log, sync.log) - Created automatically
|-- venv/ # Python virtual environment folder (add to .gitignore)
|-- .env # Environment variables (API Keys, DB URL, WooComm keys, WA keys, Agent IDs - SECRET!) (MODIFIED)
|-- .env.example # Example environment file (Update with new vars)
|-- .gitignore # Git ignore rules (add .env, venv/, pycache etc.)
|-- requirements.txt # Python package dependencies
|-- run.py # Application entry point (Flask dev server / Gunicorn target)
|-- README.md # This file (MODIFIED)

## Setup Instructions

1.  **Prerequisites:**
    *   Python 3.9+
    *   PostgreSQL server (e.g., v13+) with `pgvector` extension enabled.
    *   Git
    *   Access to a Meta Developer App and WhatsApp Business Account for Cloud API credentials.
    *   Support Board installation (Cloud or Self-Hosted).

2.  **Clone Repository:**
    ```bash
    git clone <your-repo-url>
    cd namwoo
    ```

3.  **Create & Activate Virtual Environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate # Linux/macOS
    # venv\Scripts\activate # Windows
    ```

4.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

5.  **Setup PostgreSQL Database:**
    *   Connect to PostgreSQL.
    *   Create database: `CREATE DATABASE namwoo_db;`
    *   Create user: `CREATE USER namwoo_user WITH PASSWORD 'your_strong_db_password';`
    *   Grant privileges: `GRANT ALL PRIVILEGES ON DATABASE namwoo_db TO namwoo_user;`
    *   Connect to `namwoo_db` (`\c namwoo_db`).
    *   **Enable `pgvector` extension:** `CREATE EXTENSION IF NOT EXISTS vector;`

6.  **Configure Environment Variables:**
    *   Copy `cp .env.example .env` (or create `.env`).
    *   **Edit `.env` and fill in all required values:**
        *   `SECRET_KEY`: Generate a strong random key.
        *   `OPENAI_API_KEY`.
        *   `DATABASE_URL`: Full PostgreSQL connection string (e.g., `postgresql://namwoo_user:your_strong_db_password@localhost:5432/namwoo_db`).
        *   `WOOCOMMERCE_URL`, `WOOCOMMERCE_KEY`, `WOOCOMMERCE_SECRET` (if using WooComm sync).
        *   `SUPPORT_BOARD_API_URL`.
        *   `SUPPORT_BOARD_API_TOKEN` (Admin token from SB Users area).
        *   `SUPPORT_BOARD_BOT_USER_ID` (The User ID of your bot in SB).
        *   **`WHATSAPP_CLOUD_API_TOKEN`**: Your permanent Meta System User token with required permissions.
        *   **`WHATSAPP_PHONE_NUMBER_ID`**: The ID of the WA number you're sending from.
        *   **`WHATSAPP_DEFAULT_COUNTRY_CODE`**: Fallback country code (e.g., `58`).
        *   **`SUPPORT_BOARD_AGENT_IDS`**: Comma-separated list of *human* agent User IDs from SB (e.g., `5,12,33`).
        *   **`HUMAN_TAKEOVER_PAUSE_MINUTES`**: Pause duration (e.g., `30`).
        *   Optionally `SUPPORT_BOARD_WEBHOOK_SECRET`.
        *   Adjust `LOG_LEVEL`, `SYNC_INTERVAL_MINUTES` etc. if needed.

7.  **Create Database Schema:**
    *   Ensure the DB exists and the user has permissions.
    *   Connect to your database using `psql -h <host> -U <user> -d <db_name> -W`.
    *   Execute the commands in `data/schema.sql` to create the `products` and `conversation_pauses` tables and indexes:
        ```sql
        -- Inside psql connected to namwoo_db
        \i /path/to/your/project/data/schema.sql
        ```
    *   *(Alternatively, if using Alembic, set it up based on your models).*

8.  **Run Initial Product Sync (If Using WooCommerce):**
    *   **Essential for product search.** Can take time.
    *   ```bash
        flask run-sync
        ```
    *   Monitor `logs/sync.log`.

9.  **Run Application (Development):**
    ```bash
    flask run
    ```

10. **Configure Support Board Webhook:**
    *   Go to your Support Board Admin Area -> Settings -> Miscellaneous -> Webhooks.
    *   Enter the **Webhook URL**: The publicly accessible URL pointing to your Namwoo app's `/api/sb-webhook` endpoint (e.g., `https://your-namwoo-domain.com/api/sb-webhook`). Use a reverse proxy and potentially `ngrok` for local testing.
    *   **(Optional Security):** Enter a **Secret key** and set the matching `SUPPORT_BOARD_WEBHOOK_SECRET` in your `.env`.
    *   Under **Active webhooks**, ensure `message-sent` is included (or leave blank to send all).
    *   Save settings.

11. **Test:**
    *   Send messages via WhatsApp and Instagram to the numbers/accounts connected to Support Board.
    *   Have a human agent (with an ID listed in `SUPPORT_BOARD_AGENT_IDS`) reply from the Support Board dashboard to test the pause feature.
    *   Send messages as the customer during the pause window and after it expires.
    *   Monitor application logs (`logs/app.log`) for request processing, API calls, pause checks, and errors.
    *   Check if messages arrive correctly on the user's end (WhatsApp/Instagram) and appear correctly in the Support Board dashboard timeline.

## Production Deployment (Recommended)

(This section remains largely the same - Use Gunicorn/Systemd, Reverse Proxy, set `FLASK_ENV=production`, ensure DB security, implement monitoring)

1.  **WSGI Server:** Use Gunicorn (e.g., `gunicorn --bind 127.0.0.1:5000 --workers 4 "run:app"`). Run as a systemd service.
2.  **Reverse Proxy:** Nginx or Caddy for HTTPS, SSL termination, proxying to Gunicorn.
3.  **Environment:** `FLASK_ENV=production`, adjust `LOG_LEVEL`.
4.  **Database:** Production-ready PostgreSQL configuration.
5.  **Monitoring:** Application performance, errors, resources.

## Important Considerations

*   **Error Handling:** Production systems need robust error handling and user feedback.
*   **WAID Retrieval:** The reliability of getting the WAID depends on Support Board storing the user's phone number correctly (ideally in the `phone` detail). Manually correct missing/incorrect numbers in SB user profiles.
*   **WhatsApp 24-Hour Window:** Direct text messages via the Cloud API only work within 24 hours of the last user message. For proactive messages or replies outside this window, you **must** use pre-approved **Message Templates**. Implementing template sending logic is beyond the current scope but would be necessary for certain use cases.
*   **API Rate Limits:** Be mindful of Meta Cloud API and Support Board API rate limits.
*   **Security:** Use strong secrets, update dependencies, validate inputs, consider SB webhook validation.
*   **Vector Index Tuning:** `pgvector` index parameters might need tuning.
*   **Scalability:** Consider horizontal scaling and database optimization for high traffic.
