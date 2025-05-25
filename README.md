# 💠 NamDamasco: AI-Powered Sales & Support Assistant 💠

NamDamasco is a Python Flask web application backend designed to power a conversational AI assistant. It seamlessly integrates with **Nulu AI** (our customer interaction platform) and leverages product inventory data synced from an external **Damasco API Fetcher**. This system enables customers on platforms like WhatsApp and Instagram (through Nulu AI) to engage in natural language conversations to search for products, inquire about details, and check availability using intelligent assistance.

---

## ✨ Core Strategy & How It Works

The primary goal of NamDamasco is to provide accurate and contextually relevant product information to users, enhancing their shopping experience. This is achieved through:

1.  **📥 Data Ingestion, Local Caching & Efficient Updates:**
    *   An external **Fetcher Service** (typically `fetcher_scripts/fetch_and_send.py`) periodically connects to the Damasco company's internal inventory API (often requiring a VPN).
    *   This Fetcher retrieves the complete product catalog, including details like item codes, names, descriptions, categories, brands, stock levels per warehouse (`almacen`), and prices.
    *   After fetching, the Fetcher securely sends this data to the NamDamasco application via a dedicated API endpoint (`/api/receive-products`).
    *   NamDamasco then processes this incoming data:
        *   **Delta Detection**: Before updating the database, NamDamasco compares the incoming product data (for each item-warehouse combination) against the existing record in the local PostgreSQL database. This comparison checks for changes in key fields (name, description, price, stock, category, brand, etc.) after normalizing the data (e.g., stripping whitespace, consistent handling of empty vs. null values, standardizing price to a fixed decimal precision).
        *   **Efficient Updates**: If no significant changes are detected for a product, the database update (and potentially re-generation of its vector embedding) is skipped for that item, significantly improving efficiency and reducing unnecessary processing.
        *   **Storage**: For new items or items with detected changes, the data is stored in the local PostgreSQL database. Each unique combination of an item and its warehouse location becomes a distinct record.

2.  **🧠 Semantic Search with Vector Embeddings:**
    *   Key descriptive text for each product (e.g., name, brand, category, **description**) is converted into numerical representations called **vector embeddings** using advanced AI models (like OpenAI's `text-embedding-3-small` or Google's Gemini embeddings).
    *   These embeddings are stored in the PostgreSQL database using the **`pgvector` extension**.
    *   When a user asks a question like "do you have 32-inch TVs?", NamDamasco converts the user's query into an embedding and performs a **vector similarity search** against the stored product embeddings. This allows the system to understand the *meaning* and *intent* behind the user's query, not just matching keywords.

3.  **🤖 Intelligent LLM Interaction & Tool Usage:**
    *   User messages received via Nulu AI are passed to a Large Language Model (LLM), such as Google's Gemini or OpenAI's GPT models.
    *   The LLM is equipped with **custom tools (functions)** it can decide to call:
        *   `search_local_products`: This is the primary tool for product discovery. It uses the vector search capability described above to find relevant products from the local database based on the user's query. It can also filter by stock availability.
        *   `get_live_product_details`: Once a specific product is identified (e.g., by its `item_code` or a unique `id` representing product-at-warehouse), this tool can retrieve its specific, up-to-date details (including description, price, stock) directly from the local database.

4.  **💬 Nulu AI Integration (Multi-Channel Communication):**
    *   **Incoming Messages:** NamDamasco listens for new messages from users on WhatsApp and Instagram via a Nulu AI webhook configured at `/api/sb-webhook`.
    *   **Contextual Awareness:** It uses the Nulu AI API to fetch conversation history and customer details, providing richer context to the LLM.
    *   **Outgoing Replies:**
        *   **WhatsApp:** Replies are sent directly to the user via the Meta WhatsApp Cloud API.
        *   **Instagram/Facebook Messenger:** Replies are sent via the Nulu AI's platform API.
        *   **Dashboard Visibility:** For both channels, a copy of the bot's reply is also sent *internally* to the Nulu AI conversation, ensuring human agents see the bot's interactions.

5.  **🧑‍💼 Human Agent Takeover & Bot Pause:**
    *   NamDamasco intelligently detects when a human agent (whose ID is configured) replies to a conversation in Nulu AI.
    *   When this happens, the bot automatically pauses its responses for that specific conversation for a configurable duration (e.g., 30 minutes). This pause state is managed in the PostgreSQL `conversation_pauses` table.
    *   This ensures a smooth handover and prevents the bot from interfering with human agent interactions.

---

## 🚀 Key Features

*   **📡 Nulu AI Webhook Integration:** Handles incoming `message-sent` events via `/api/sb-webhook`.
*   **📦 Product Data Receiver:** Dedicated `/api/receive-products` endpoint to ingest inventory data.
    *   **✨ Delta Detection & Efficient DB Updates:** Minimizes unnecessary database operations and embedding re-calculations by only processing changed product data.
*   **📱 Direct WhatsApp Cloud API Integration.**
*   **🗣️ Nulu AI API Integration:** For fetching context and sending replies.
*   **🔎 Intelligent Product Search:** Semantic vector search using `pgvector` on locally cached Damasco product data (including names, categories, and **descriptions**).
*   **🤖 Advanced LLM Function Calling** for dynamic interaction.
*   **🐘 PostgreSQL + `pgvector` Backend:** Robust storage for product data, embeddings, and application state.
*   **🔄 Decoupled Data Synchronization:** Relies on an external `fetcher_scripts` process for Damasco API interaction and data pushing.
*   **⏸️ Human Agent Takeover Pause.**
*   **⚙️ Environment-Based Configuration** via `.env` file.
*   **📝 Structured Logging.**
*   **🌍 Production Ready:** Designed for deployment with Gunicorn behind a reverse proxy.
*   **🔄 Asynchronous Product Processing (Celery - Optional but Recommended):** For handling product data updates from the `/api/receive-products` endpoint asynchronously, improving API responsiveness.

---

## 📁 Folder Structure (NamDamasco Application Server)


/NAMDAMASCO_APP_ROOT/ # Root of this main server application
|-- namwoo_app/ # Main application package
| |-- __init__.py # App factory (create_app)
| |-- api/
| | |-- __init__.py
| | |-- receiver_routes.py # Handles /api/receive-products
| | |-- routes.py # Handles /api/sb-webhook, /api/health
| |-- celery_app.py # Celery application setup
| |-- celery_tasks.py # Celery task definitions
| |-- config.py # Loads .env, application configuration (note: you had it in config/config.py, adjusting to root of package)
| |-- data/ # Static data, prompts
| | |-- system_prompt.txt
| |-- models/
| | |-- __init__.py # Defines Base, imports models
| | |-- product.py
| | |-- conversation_pause.py
| |-- services/
| | |-- __init__.py
| | |-- damasco_service.py # Helper for processing raw Damasco data
| | |-- google_service.py
| | |-- openai_service.py
| | |-- product_service.py # Logic for DB + vector search, includes delta detection
| | |-- support_board_service.py
| | |-- sync_service.py # Coordinates data sync (potentially calls celery tasks or product_service directly)
| |-- utils/
| | |-- __init__.py
| | |-- db_utils.py
| | |-- embedding_utils.py
|-- data/ # Project-level data like SQL schema
| |-- schema.sql
|-- logs/ # Created at runtime
|-- venv/ # Python virtual environment (.gitignored)
|-- .env # Environment variables (SECRET!)
|-- .env.example
|-- .gitignore
|-- requirements.txt
|-- run.py # Entry point for Gunicorn (e.g., run:app)
|-- Caddyfile # Example Caddy configuration
|-- README.md # This file

*(Note: The `fetcher_scripts/` directory for Damasco data acquisition is a separate, complementary project/component.)*

---

## 🛠️ Setup & Installation Guide (NamDamasco Application Server)

**Prerequisites:**

*   🐍 Python 3.9+
*   🐘 PostgreSQL Server (v13-v16 recommended) with `pgvector` extension enabled.
*   💾 Redis (Recommended for Celery message broker and result backend).
*   🐳 Docker (Highly recommended for PostgreSQL + pgvector & Redis).
*   🐙 Git.
*   🔑 Access to:
    *   Meta Developer App & WhatsApp Business Account.
    *   **Nulu AI** installation/account (with API token & necessary IDs).
    *   An LLM provider API Key (OpenAI, Google Gemini).
*   📡 An external **Fetcher Service** set up to periodically send product data (including **descriptions**) to `/api/receive-products`.

**Steps:**

1.  **Clone the Repository:**
    ```bash
    git clone <your-namdamasco-repo-url>
    cd namdamasco
    ```

2.  **Create & Activate Python Virtual Environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set Up PostgreSQL & Redis (Docker Example):**
    a.  **Run PostgreSQL Container (with pgvector):**
        ```bash
        docker run --name namwoo-postgres \
          -e POSTGRES_USER=namwoo \
          -e POSTGRES_PASSWORD=damasco2025! \
          -e POSTGRES_DB=namwoo \
          -p 5432:5432 \
          -d pgvector/pgvector:pg16 
        # Choose pgvector image compatible with your desired PostgreSQL version
        ```
    b.  **Apply Database Schema:**
        *   Ensure `data/schema.sql` includes the `description TEXT` column in the `products` table.
        *   `docker cp ./data/schema.sql namwoo-postgres:/tmp/schema.sql`
        *   `docker exec -u postgres namwoo-postgres psql -d namwoo -f /tmp/schema.sql`
        *   (Grant permissions if needed: `docker exec -u postgres namwoo-postgres psql -d namwoo -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO namwoo;"` and sequences if any).
    c.  **Run Redis Container (for Celery):**
        ```bash
        docker run --name namwoo-redis -p 6379:6379 -d redis:latest
        ```

5.  **Configure Environment Variables:**
    *   Copy `cp .env.example .env`.
    *   Edit `.env` and fill in all required variables, including:
        *   `DATABASE_URL` (e.g., `postgresql://namwoo:damasco2025!@localhost:5432/namwoo`)
        *   `CELERY_BROKER_URL` (e.g., `redis://localhost:6379/0`)
        *   `CELERY_RESULT_BACKEND` (e.g., `redis://localhost:6379/0`)
        *   `RECEIVER_API_KEY` (for `/api/receive-products` endpoint)
        *   All Nulu AI, LLM, and WhatsApp credentials.

6.  **Database Migrations (If using Alembic):**
    *   If you added the `description` column via an Alembic migration, run:
        ```bash
        flask db upgrade 
        # (Assuming you have Flask-Migrate setup)
        ```

7.  **Run Initial Data Sync (via External Fetcher):**
    *   Ensure the external Fetcher Service is updated to fetch product **descriptions** and includes them in the payload sent to `/api/receive-products`.
    *   Execute the Fetcher Service.

8.  **Run NamDamasco Application (Development):**
    ```bash
    # Terminal 1: Flask App
    python run.py 
    # or flask run --host=0.0.0.0 --port=5100 (if run.py is configured for FLASK_APP)

    # Terminal 2: Celery Worker
    celery -A namwoo_app.celery_app worker -l INFO
    ```
    For Gunicorn: `gunicorn --bind 0.0.0.0:5100 "run:app" --log-level debug`

9.  **Configure Nulu AI Webhook:**
    *   URL: `https://your-public-domain.com/api/sb-webhook`
    *   Ensure `message-sent` is active.

10. **Test Thoroughly:**
    *   Send data to `/api/receive-products` multiple times. Check logs for "skipped_no_change" and "updated" counts. Verify descriptions are stored.
    *   Test product searches that should leverage the new description field.
    *   Test human agent takeover.

**Production Deployment:**
    (Use Gunicorn/Systemd for Flask and Celery workers, and Caddy/Nginx. Schedule the *external fetcher script* with cron).

---

## 💡 Important Considerations & Future Enhancements

*   **Error Handling & Resilience.**
*   **API Rate Limits.**
*   **Security:** Protect credentials, validate inputs, webhook signatures.
*   **Scalability (Future):**
    *   The current delta detection is a good step. Further optimizations for the Fetcher to only send changed data can be explored.
*   **Vector Database Optimization.**
*   **Advanced Location Features.**

