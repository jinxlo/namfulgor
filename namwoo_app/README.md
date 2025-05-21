# 💠 NamDamasco: AI-Powered Sales & Support Assistant 💠

NamDamasco is a Python Flask (or FastAPI) web application backend designed to power a conversational AI assistant. It seamlessly integrates with **Nulu AI** (our customer interaction platform) and leverages product inventory data synced from an external **Damasco API Fetcher**. This system enables customers on platforms like WhatsApp and Instagram (through Nulu AI) to engage in natural language conversations to search for products, inquire about details, and check availability using intelligent assistance.

---

## ✨ Core Strategy & How It Works

The primary goal of NamDamasco is to provide accurate and contextually relevant product information to users, enhancing their shopping experience. This is achieved through:

1.  **📥 Data Ingestion & Local Caching:**
    *   An external **Fetcher Service** (typically `fetcher_scripts/fetch_and_send.py`) periodically connects to the Damasco company's internal inventory API (often requiring a VPN).
    *   This Fetcher retrieves the complete product catalog, including details like item codes, names, categories, brands, stock levels per warehouse (`almacen`), and prices.
    *   After fetching, the Fetcher securely sends this data to the NamDamasco application via a dedicated API endpoint (`/api/receive-products`).
    *   NamDamasco then processes this incoming data, storing it in a local **PostgreSQL database**. Each unique combination of an item and its warehouse location becomes a distinct record.

2.  **🧠 Semantic Search with Vector Embeddings:**
    *   Key descriptive text for each product (e.g., name, brand, category) is converted into numerical representations called **vector embeddings** using advanced AI models (like OpenAI's `text-embedding-3-small` or Google's Gemini embeddings).
    *   These embeddings are stored in the PostgreSQL database using the **`pgvector` extension**.
    *   When a user asks a question like "do you have 32-inch TVs?", NamDamasco converts the user's query into an embedding and performs a **vector similarity search** against the stored product embeddings. This allows the system to understand the *meaning* and *intent* behind the user's query, not just matching keywords.

3.  **🤖 Intelligent LLM Interaction & Tool Usage:**
    *   User messages received via Nulu AI are passed to a Large Language Model (LLM), such as Google's Gemini or OpenAI's GPT models.
    *   The LLM is equipped with **custom tools (functions)** it can decide to call:
        *   `search_local_products`: This is the primary tool for product discovery. It uses the vector search capability described above to find relevant products from the local database based on the user's query. It can also filter by stock availability.
        *   `get_live_product_details`: Once a specific product is identified (e.g., by its `item_code` or a unique `id` representing product-at-warehouse), this tool can retrieve its specific, up-to-date details directly from the local database. *Note: Direct real-time calls back to the Damasco API for individual items is a potential future enhancement if absolute real-time data is critical for certain queries.*
4.  **💬 Nulu AI Integration (Multi-Channel Communication):**
    *   **Incoming Messages:** NamDamasco listens for new messages from users on WhatsApp and Instagram via a Nulu AI webhook configured at `/api/sb-webhook` (or a more Nulu-specific path if desired).
    *   **Contextual Awareness:** It uses the Nulu AI API (`get-user`, `get-conversation` functionalities, however they are exposed) to fetch conversation history and customer details (like PSID for Facebook/Instagram or WAID for WhatsApp), providing richer context to the LLM.
    *   **Outgoing Replies:**
        *   **WhatsApp:** Replies are sent directly to the user via the Meta WhatsApp Cloud API.
        *   **Instagram/Facebook Messenger:** Replies are sent via the Nulu AI's equivalent of a `messenger-send-message` API (if Nulu AI proxies these or if you call Meta APIs directly based on Nulu AI's context).
        *   **Dashboard Visibility:** For both channels, a copy of the bot's reply is also sent *internally* to the Nulu AI conversation using its `send-message` API (or equivalent), ensuring human agents see the bot's interactions in the Nulu AI dashboard.

5.  **🧑‍💼 Human Agent Takeover & Bot Pause:**
    *   NamDamasco intelligently detects when a human agent (whose ID is configured) replies to a conversation in Nulu AI.
    *   When this happens, the bot automatically pauses its responses for that specific conversation for a configurable duration (e.g., 30 minutes). This pause state is managed in the PostgreSQL `conversation_pauses` table.
    *   This ensures a smooth handover and prevents the bot from interfering with human agent interactions.

---

## 🚀 Key Features

*   **📡 Nulu AI Webhook Integration:** Handles incoming `message-sent` events via `/api/sb-webhook` for seamless communication.
*   **📦 Product Data Receiver:** Dedicated `/api/receive-products` endpoint to ingest inventory data from the external Damasco fetcher.
*   **📱 Direct WhatsApp Cloud API Integration.**
*   **🗣️ Nulu AI API Integration:** For fetching conversation/user context and potentially sending FB/IG replies via Nulu AI's platform.
*   **🔎 Intelligent Product Search:** Semantic vector search using `pgvector` on locally cached Damasco product data.
*   **🤖 Advanced LLM Function Calling** for dynamic interaction.
*   **🐘 PostgreSQL + `pgvector` Backend:** Robust storage for product data, embeddings, and application state.
*   **🔄 Decoupled Data Synchronization:** Relies on an external `fetcher_scripts` process for Damasco API interaction and data pushing.
*   **⏸️ Human Agent Takeover Pause.**
*   **⚙️ Environment-Based Configuration** via `.env` file.
*   **📝 Structured Logging.**
*   **🌍 Production Ready:** Designed for deployment with Gunicorn behind a reverse proxy (Caddy, Nginx).

---

## 📁 Folder Structure (NamDamasco Application Server)


/NAMDAMASCO_APP_ROOT/ # Root of this main server application
|-- namwoo_app/ # Main application package
| |-- init.py # App factory (create_app)
| |-- api/
| | |-- init.py
| | |-- receiver_routes.py # Handles /api/receive-products
| | |-- routes.py # Handles /api/sb-webhook, /api/health
| |-- config/
| | |-- init.py
| | |-- config.py # Loads .env, application configuration
| |-- data/ # Static data, prompts (not for dynamic data files)
| | |-- system_prompt.txt
| |-- models/
| | |-- init.py # Defines Base, imports models
| | |-- product.py
| | |-- conversation_pause.py
| |-- scheduler/ # If APScheduler is used for internal app tasks (not Damasco sync)
| | |-- init.py
| | |-- tasks.py
| |-- services/
| | |-- init.py
| | |-- damasco_service.py # Potentially for future direct Damasco calls from app
| | |-- google_service.py # Or a generic llm_service.py
| | |-- openai_service.py # Or a generic llm_service.py
| | |-- product_service.py # Logic for DB + vector search on local products table
| | |-- support_board_service.py # Handles interactions with Nulu AI platform API & Direct WA Cloud API
| | |-- sync_service.py # Handles logic for processing data received at /api/receive-products
| |-- utils/
| | |-- init.py
| | |-- db_utils.py
| | |-- embedding_utils.py
|-- data/ # Project-level data like SQL schema
| |-- schema.sql
|-- logs/ # Created at runtime (app.log)
|-- venv/ # Python virtual environment (.gitignored)
|-- .env # Environment variables (API Keys, DB URL, etc. - SECRET!)
|-- .env.example
|-- .gitignore
|-- requirements.txt # Python dependencies for this application
|-- run.py # Entry point for Gunicorn (e.g., run:app)
|-- Caddyfile # Example Caddy configuration
|-- README.md # This file

*(Note: The `fetcher_scripts/` directory for Damasco data acquisition is a separate, complementary project/component.)*

---

## 🛠️ Setup & Installation Guide (NamDamasco Application Server)

**Prerequisites:**

*   🐍 Python 3.9+
*   🐘 PostgreSQL Server (v13-v15+ recommended) with `pgvector` extension enabled.
*   🐳 Docker (Highly recommended for PostgreSQL + pgvector & Redis if using Celery).
*   🐙 Git.
*   🔑 Access to:
    *   Meta Developer App & WhatsApp Business Account (for Cloud API credentials).
    *   **Nulu AI** installation/account (Cloud or Self-Hosted, with API token & necessary IDs).
    *   An LLM provider API Key (OpenAI, Google Gemini).
*   📡 An external **Fetcher Service** set up to periodically send product data to this application's `/api/receive-products` endpoint.

**Steps:**

1.  **Clone the Repository (if applicable):**
    ```bash
    git clone <your-namdamasco-repo-url>
    cd namdamasco
    ```

2.  **Create & Activate Python Virtual Environment for NamDamasco App:**
    (From the `NAMDAMASCO_APP_ROOT` directory)
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set Up PostgreSQL Database (Docker Example):**
    a.  **Run PostgreSQL Container:**
        ```bash
        docker run --name namwoo-postgres \
          -e POSTGRES_USER=namwoo \
          -e POSTGRES_PASSWORD=damasco2025! \
          -e POSTGRES_DB=namwoo \
          -p 5432:5432 \
          -d pgvector/pgvector:pg15
        ```
    b.  **Apply Database Schema:**
        *   Copy `data/schema.sql`: `docker cp ./data/schema.sql namwoo-postgres:/tmp/schema.sql`
        *   Execute schema: `docker exec -i namwoo-postgres psql -U postgres -d namwoo -f /tmp/schema.sql`
        *   Grant permissions to `namwoo` user (as shown previously).

5.  **Configure Environment Variables for NamDamasco Application:**
    *   Copy `cp .env.example .env`.
    *   Edit `.env` and fill in:
        *   `SECRET_KEY`, `LLM_PROVIDER`, `OPENAI_API_KEY`/`GEMINI_API_KEY`, `DATABASE_URL`
        *   `NULUAI_API_URL` (replace `SUPPORT_BOARD_API_URL`)
        *   `NULUAI_API_TOKEN` (replace `SUPPORT_BOARD_API_TOKEN`)
        *   `NULUAI_BOT_USER_ID` (replace `SUPPORT_BOARD_BOT_USER_ID`)
        *   `WHATSAPP_CLOUD_API_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_DEFAULT_COUNTRY_CODE`
        *   `NULUAI_AGENT_IDS` (replace `SUPPORT_BOARD_AGENT_IDS`, comma-separated list of Nulu AI User IDs)
        *   `HUMAN_TAKEOVER_PAUSE_MINUTES`
        *   `RECEIVER_API_KEY`
        *   `EMBEDDING_DIMENSION`
        *   (Optional) `NULUAI_WEBHOOK_SECRET` (replace `SUPPORT_BOARD_WEBHOOK_SECRET`)

6.  **Run Initial Data Sync (via External Fetcher):**
    *   Ensure the external Fetcher Service is configured with the correct `RECEIVER_URL` for this NamDamasco app and the matching `RECEIVER_API_KEY`.
    *   Execute the Fetcher Service.

7.  **Run NamDamasco Application (Development):**
    ```bash
    flask run 
    # Or using Gunicorn:
    # gunicorn --bind 127.0.0.1:5100 "run:app" --worker-class gevent --log-level debug
    ```

8.  **Configure Nulu AI Webhook:**
    *   In Nulu AI Admin Panel: **Settings -> Miscellaneous -> Webhooks** (or equivalent path).
    *   **Webhook URL:** `https://nam.worldapptechnologies.com/api/sb-webhook` (or your public URL).
    *   **Active Webhooks:** Ensure `message-sent` (or equivalent) is selected.
    *   (Optional) Configure shared secret.

9.  **Test Thoroughly:**
    *   Test messaging via WhatsApp and Instagram through Nulu AI.
    *   Verify product searches and human agent takeover.
    *   Monitor application logs (`logs/app.log` or `journalctl`).

**Production Deployment:**
    (Similar to previous instructions, using Gunicorn/Systemd and Caddy/Nginx. Schedule the *external fetcher script* with cron).

---

## 💡 Important Considerations & Future Enhancements

*   **Error Handling & Resilience:** Critical for both this app and the fetcher.
*   **API Rate Limits:** Be mindful of Damasco API, LLM provider, Meta Cloud, and Nulu AI API rate limits.
*   **Security:** Protect all credentials. Validate inputs. Consider webhook signature validation.
*   **Scalability (Future):**
    *   For `/api/receive-products`, use a task queue (Celery) for asynchronous processing.
    *   Implement delta/change-based synchronization in the Fetcher Service.
*   **Vector Database Optimization.**
*   **Advanced Location Features** (Geocoding for "closest store").

---