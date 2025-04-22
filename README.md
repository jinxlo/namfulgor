# Namwoo - WooCommerce Dialogflow Assistant Backend

## Overview

Namwoo is a Python Flask web application designed as a high-performance webhook backend for a Google Dialogflow ES agent. It empowers a chatbot to interact with a WooCommerce store, allowing users to search for products, inquire about details, and check availability.

The core strategy focuses on speed to meet Dialogflow's 5-second timeout requirement:
1.  **Local Caching:** Product data (name, SKU, description, price, stock status, etc.) is periodically synced from WooCommerce into a local PostgreSQL database.
2.  **Vector Search:** Product text is converted into embeddings (using OpenAI's models by default) and stored in PostgreSQL using the `pgvector` extension. This enables fast, semantic search (understanding meaning, not just keywords).
3.  **OpenAI Function Calling:** GPT models (like `gpt-3.5-turbo` or `gpt-4`) interpret user queries and intelligently decide when to:
    *   Call `search_local_products`: Queries the *fast local cache* using vector similarity for general product discovery.
    *   Call `get_live_product_details`: Makes a targeted, *real-time API call* to WooCommerce for specific details (like exact stock count) only when necessary for an already identified product.
4.  **Persistent History:** Conversation context is maintained across user turns within a Dialogflow session using the PostgreSQL database.

## Features

*   **Dialogflow ES Webhook Integration:** Handles fulfillment requests.
*   **Intelligent Product Search:** Combines semantic search (via `pgvector`) with optional stock filtering on cached data.
*   **Real-time Detail Fetching:** Retrieves live stock and price for specific items directly from WooCommerce when needed.
*   **OpenAI Function Calling:** Leverages LLMs for natural language understanding and action triggering.
*   **WooCommerce Integration:** Connects securely to the WooCommerce REST API.
*   **PostgreSQL Backend:** Stores product cache, vector embeddings, and conversation history.
*   **Automatic Sync:** Periodically updates the local product cache and embeddings using a background scheduler (APScheduler).
*   **Manual Sync Command:** Allows triggering a full data synchronization via the Flask CLI.
*   **Configuration:** Easily configured via a `.env` file.
*   **Structured Logging:** Separate logs for application events and synchronization tasks.
*   **Production Ready:** Includes setup for running with Gunicorn behind a reverse proxy (like Caddy or Nginx).

## Folder Structure


/namwoo/ # Project Root
|-- namwoo_app/ # Main Flask application package
| |-- init.py # App factory, initializes extensions, logging, scheduler, CLI
| |-- api/ # API Blueprint (webhook, health check)
| | |-- init.py # Blueprint setup
| | |-- routes.py # Webhook request handling logic
| |-- models/ # SQLAlchemy ORM Models
| | |-- init.py # Base model definition
| | |-- product.py # Product table model
| | |-- history.py # ConversationHistory table model
| |-- services/ # Business logic modules
| | |-- init.py
| | |-- openai_service.py # Handles OpenAI Chat Completions & Function Calling
| | |-- product_service.py # Handles querying LOCAL product data (SQL + Vector Search) & DB updates
| | |-- woocommerce_service.py # Handles LIVE calls to WooCommerce API
| | |-- sync_service.py # Logic for fetching data from WooComm & triggering DB updates/embeddings
| |-- scheduler/ # Background task scheduling (APScheduler)
| | |-- init.py
| | |-- tasks.py # Defines the scheduled sync task & scheduler management
| |-- utils/ # Utility modules
| | |-- init.py
| | |-- db_utils.py # Handles PostgreSQL connection, session management, history CRUD
| | |-- embedding_utils.py # Helper to generate embeddings via OpenAI API
|-- config/ # Configuration files
| |-- init.py
| |-- config.py # Loads config from .env into Flask app config
|-- data/ # SQL schema file(s)
| |-- schema.sql # Contains CREATE TABLE statements (incl. pgvector extension & trigger)
|-- logs/ # Log files (app.log, sync.log) - Created automatically
|-- venv/ # Python virtual environment folder (add to .gitignore)
|-- .env # Environment variables (API Keys, DB URL, WooComm keys - SECRET!)
|-- .env.example # Example environment file
|-- .gitignore # Git ignore rules (add .env, venv/, pycache etc.)
|-- requirements.txt # Python package dependencies
|-- run.py # Application entry point (Flask dev server / Gunicorn target)
|-- README.md # This file

## Setup Instructions

1.  **Prerequisites:**
    *   Python 3.9+
    *   PostgreSQL server (e.g., v13+)
    *   Git

2.  **Clone Repository:**
    ```bash
    git clone <your-repo-url>
    cd namwoo
    ```

3.  **Create & Activate Virtual Environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # Linux/macOS
    # venv\Scripts\activate    # Windows
    ```

4.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

5.  **Setup PostgreSQL Database:**
    *   Connect to your PostgreSQL instance (using `psql` or a GUI tool).
    *   Create a database: `CREATE DATABASE namwoo_db;`
    *   Create a user and grant privileges:
        ```sql
        CREATE USER namwoo_user WITH PASSWORD 'your_strong_db_password';
        GRANT ALL PRIVILEGES ON DATABASE namwoo_db TO namwoo_user;
        -- Connect to the new DB: \c namwoo_db
        -- Grant schema usage (if needed): GRANT USAGE ON SCHEMA public TO namwoo_user;
        -- Grant permissions on future tables (optional but helpful):
        -- ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO namwoo_user;
        -- ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO namwoo_user;
        ```
    *   **Crucially, enable the `pgvector` extension within the `namwoo_db` database:**
        ```sql
        -- Run this command while connected to namwoo_db
        CREATE EXTENSION IF NOT EXISTS vector;
        ```

6.  **Configure Environment Variables:**
    *   Copy the example file: `cp .env.example .env`
    *   Edit the `.env` file and **fill in all required values**:
        *   `SECRET_KEY`: Generate a strong random key (e.g., `python -c 'import secrets; print(secrets.token_hex(24))'`).
        *   `OPENAI_API_KEY`: Your key from OpenAI.
        *   `DATABASE_URL`: Your PostgreSQL connection string (e.g., `postgresql://namwoo_user:your_strong_db_password@localhost:5432/namwoo_db`).
        *   `WOOCOMMERCE_URL`: Your store's HTTPS URL.
        *   `WOOCOMMERCE_KEY` & `WOOCOMMERCE_SECRET`: Generate Read/Write API keys in your WooCommerce admin panel.
        *   Adjust `SYNC_INTERVAL_MINUTES`, `LOG_LEVEL`, etc., if needed.
        *   Optionally set `DIALOGFLOW_WEBHOOK_SECRET` for added security.

7.  **Create Database Schema:**
    *   Ensure your virtual environment is active and you are in the project root (`namwoo/`).
    *   Run the Flask CLI command to create tables based on your models and the `schema.sql` definitions (ensure DB connection details in `.env` are correct):
        ```bash
        flask create-db
        ```
    *   Alternatively, manually execute the SQL commands from `data/schema.sql` against your `namwoo_db` database using `psql` or a GUI client.

8.  **Run Initial Product Sync:**
    *   This step populates your local database with data from WooCommerce and generates the necessary embeddings. **This is essential for the search functionality to work.**
    *   This command can take a significant amount of time depending on the number of products in your store.
    *   Run the Flask CLI command:
        ```bash
        flask run-sync
        ```
    *   Monitor the console output and check `logs/sync.log` for progress and potential errors.

9.  **Run Application (Development):**
    *   Start the Flask development server:
        ```bash
        flask run
        ```
    *   The server will typically run on `http://127.0.0.1:5000` or `http://0.0.0.0:5000`.

10. **Configure Dialogflow:**
    *   Go to your Dialogflow ES agent's **Fulfillment** settings.
    *   Enable the **Webhook**.
    *   Set the **Webhook URL** to the publicly accessible URL where your Namwoo application will be running (e.g., `https://your-namwoo-domain.com/api/webhook`). You'll likely need a reverse proxy (like Caddy or Nginx) and potentially a tool like `ngrok` for local testing.
    *   **(Optional Security):** Under **Headers**, add a custom header (e.g., `Key: X-Webhook-Secret`, `Value: your_shared_secret_value`) matching the `DIALOGFLOW_WEBHOOK_SECRET` in your `.env` file.
    *   Save the fulfillment settings.
    *   For each **Intent** that should trigger this backend, go to its settings, expand the **Fulfillment** section, and check **Enable webhook call for this intent**.

11. **Test:**
    *   Use the Dialogflow simulator or an integrated chat client.
    *   Ask questions that should trigger the webhook (e.g., "Do you have helmets?", "Is SKU TSHIRT-RED in stock?").
    *   Monitor the application logs (`logs/app.log`) and potentially the sync logs (`logs/sync.log`) for activity and errors.

## Production Deployment (Recommended)

1.  **WSGI Server:** Do *not* use the Flask development server (`flask run`) in production. Use a production-grade WSGI server like Gunicorn.
    ```bash
    # Example: Run Gunicorn binding to localhost (proxy will handle external traffic)
    # Adjust --workers based on your server's CPU cores (e.g., 2 * cores + 1)
    gunicorn --bind 127.0.0.1:5000 --workers 4 --timeout 120 --log-level info "run:app"
    ```
    *   Ensure Gunicorn is in `requirements.txt`.
    *   Consider running Gunicorn as a system service (e.g., using systemd).

2.  **Reverse Proxy:** Set up a reverse proxy like Nginx or Caddy in front of Gunicorn.
    *   **Responsibilities:** Handle incoming HTTPS traffic, manage SSL certificates (Caddy does this automatically), terminate SSL, and proxy requests to the Gunicorn server listening on `127.0.0.1:5000`.
    *   **Benefits:** Security, load balancing (if running multiple instances), serving static files (if any), handling compressed responses.

3.  **Environment:** Set `FLASK_ENV=production` in your production environment (e.g., systemd service file or environment variables). This disables debug mode. Adjust `LOG_LEVEL` accordingly (e.g., `INFO` or `WARNING`).

4.  **Database:** Ensure your PostgreSQL database is configured for production performance and security (strong passwords, appropriate resource allocation, backups).

5.  **Monitoring:** Implement monitoring for application performance, errors (e.g., using Sentry or similar), server resources, and database health.

## Important Considerations

*   **Error Handling:** While basic error handling is included, production systems require more robust strategies (e.g., specific error types, user-friendly fallback messages, alerting).
*   **Sync Performance:** The full sync can be resource-intensive. Monitor its duration and impact. Consider implementing true incremental sync if your store is large and changes frequently. Tune `COMMIT_BATCH_SIZE`.
*   **Embedding Quality:** The relevance of `search_local_products` depends heavily on the text used for embeddings (`Product.prepare_searchable_text`) and the chosen embedding model. Experiment as needed.
*   **Vector Index Tuning:** The `pgvector` index (`hnsw` or `ivfflat`) parameters in `schema.sql` might need tuning based on your data size and performance testing for optimal search speed vs. accuracy.
*   **API Rate Limits:** Be mindful of potential rate limits for both the OpenAI API and the WooCommerce API, especially during syncs. Implement backoff/retry logic where appropriate (basic retries are included).
*   **Security:** Regularly review security practices: update dependencies, use strong secrets, restrict database access, validate inputs, consider webhook secret validation.
*   **Scalability:** For high traffic, consider scaling horizontally (multiple app instances behind a load balancer) and ensure your database can handle the load. Profile database queries.
*   **Dialogflow Timeout:** The entire webhook request-response cycle must complete within Dialogflow's timeout (usually 5 seconds, configurable up to 15). The reliance on the local cache is key to meeting this. Monitor response times.
IGNORE_WHEN_COPYING_START
content_copy
download
Use code with caution.
IGNORE_WHEN_COPYING_END

Instructions: Copy the Markdown content above and save it as README.md in your project root directory (namwoo/README.md).