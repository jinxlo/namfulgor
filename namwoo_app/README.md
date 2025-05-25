# 💠 NamDamasco: AI-Powered Sales & Support Assistant 💠

**Version: 1.1** (Example version, update as you see fit)
**Last Updated:** May 22, 2025 (Example date)

## 📖 Overview

NamDamasco is an advanced Python Flask web application backend designed to serve as the intelligent core for a multi-channel conversational AI sales and support assistant. It seamlessly integrates with the Nulu AI customer interaction platform, enabling businesses to offer sophisticated, AI-driven conversations on popular messaging channels like WhatsApp and Instagram (via Facebook Messenger).

The system's primary function is to understand customer inquiries in natural language, search a locally synchronized and enhanced product catalog, provide accurate product information (including details, availability, and pricing), and facilitate a smooth shopping experience. It leverages Large Language Models (LLMs) for natural language understanding and response generation, vector embeddings for semantic product search, and a robust data pipeline for keeping product information up-to-date.

## ✨ Core Strategy & System Architecture

NamDamasco's architecture is built around providing a highly responsive, accurate, and context-aware conversational experience. This is achieved through several key components and processes:

### 1. Data Ingestion & Asynchronous Processing Pipeline

The system relies on an external **Fetcher Service** to acquire product data from the primary Damasco inventory API. This ensures that the main NamDamasco application remains decoupled from the complexities of external API interactions and potential VPN requirements.

*   **Fetcher Service (External Component):**
    *   Periodically connects to the Damasco company's internal inventory API.
    *   Retrieves the complete product catalog, including item codes, names, **raw HTML descriptions**, categories, brands, stock levels per warehouse/branch (`almacen`/`whsName`), and prices.
    *   Securely transmits this data (typically as a list of product dictionaries with camelCase keys) to the NamDamasco application via a dedicated, authenticated API endpoint: `/api/receive-products`.

*   **NamDamasco API Endpoint (`/api/receive-products`):**
    *   **Authentication:** Validates an `X-API-KEY` from the Fetcher Service.
    *   **Basic Payload Validation:** Ensures the incoming data is a list of dictionaries.
    *   **Data Transformation:** Converts the received camelCase product data keys to snake\_case, which is the internal convention for Celery task arguments.
    *   **Asynchronous Task Enqueuing:** For each valid product item, it enqueues a background task (`process_product_item_task`) using Celery. This allows the API to respond almost instantly (HTTP 202 Accepted) to the Fetcher, acknowledging receipt and offloading the intensive processing.

*   **Celery Background Task (`process_product_item_task`):**
    This is where the core data enrichment and database operations occur for each product:
    1.  **Data Validation:** The snake\_case product data is validated using a Pydantic model (`DamascoProductDataSnake`).
    2.  **Key Case Conversion:** Data is converted back to camelCase (`product_data_camel`) for consistent interaction with internal services and model methods that expect this format for original Damasco field names.
    3.  **Conditional LLM Summarization:**
        *   The task determines if a new LLM-generated summary is needed for the product's HTML description. This occurs if:
            *   The product is new to the database.
            *   The incoming raw HTML description has changed compared to the version currently stored in the database.
            *   An LLM-generated summary does not yet exist for this product, even if the HTML description is unchanged.
        *   If a new summary is required and an HTML description is available:
            *   The raw HTML is passed to `llm_processing_service.generate_llm_product_summary()`.
            *   This service first strips all HTML tags using `BeautifulSoup` (via `text_utils.strip_html_to_text`) to get plain text.
            *   The plain text is then sent to the configured LLM provider (OpenAI or Google Gemini, based on `.env` settings) with a specialized prompt to generate a concise, factual, plain-text summary (typically 50-75 words).
        *   If a new summary is not needed (e.g., HTML is identical and a summary already exists), the existing summary from the database is re-used.
    4.  **Text Preparation for Embedding (`Product.prepare_text_for_embedding()`):**
        *   This crucial step constructs the `searchable_text_content`.
        *   It **prioritizes the `llm_generated_summary`**. If a summary is available, it's used as the primary descriptive component.
        *   If no LLM summary is available (e.g., summarization was skipped, failed, or the product had no initial HTML description), it falls back to using the plain text obtained by stripping the raw HTML description from `product_data_camel`.
        *   This processed description is then concatenated with other key product attributes (brand, name, category, sub-category, item group name, line) to form the final `text_to_embed`.
    5.  **Vector Embedding Generation (`openai_service.generate_product_embedding()`):**
        *   The `text_to_embed` is converted into a high-dimensional numerical vector (embedding) using a pre-trained AI model (e.g., OpenAI's `text-embedding-3-small`).
    6.  **Database Upsert with Delta Detection (`product_service.add_or_update_product_in_db()`):**
        *   This service function is responsible for efficiently updating the PostgreSQL database.
        *   It compares the new, processed values (including the normalized raw HTML `description`, the new/re-used `llm_summarized_description`, the `searchable_text_content`, `embedding_vector`, price, stock, and other textual attributes) against the existing record for that specific item-warehouse combination.
        *   **If no significant changes are detected**, the database write operation is skipped for that item (returns `"skipped_no_change"`).
        *   If changes are found, or if the item is new:
            *   The raw HTML description is stored in the `products.description` column.
            *   The LLM-generated summary (if any) is stored in `products.llm_summarized_description`.
            *   The `text_used_for_embedding` is stored in `products.searchable_text_content`.
            *   The new `embedding_vector` is stored in `products.embedding`.
            *   Other product attributes (price, stock, etc.) are updated.
            *   The original camelCase `damasco_product_data` received by the service is stored in `products.source_data_json` for auditing.

### 2. Semantic Product Search via Vector Embeddings

*   When a user makes a product-related query (e.g., "do you have 32-inch smart TVs?"), NamDamasco converts this natural language query into a vector embedding.
*   It then performs a cosine similarity search using `pgvector` against the embeddings of all products stored in the `products.embedding` column.
*   This semantic search capability allows the system to find products based on meaning and context, rather than just exact keyword matches, leading to more relevant results.

### 3. Intelligent LLM Interaction & Tool Usage for Conversational AI

*   User messages received from Nulu AI (originating from WhatsApp, Instagram, etc.) are routed to a configured Large Language Model (LLM), such as Google's Gemini series or OpenAI's GPT models.
*   The LLM is augmented with a predefined set of "tools" (functions) that it can choose to call to retrieve specific information or perform actions:
    *   **`search_local_products`**: The primary tool for product discovery. When the LLM determines the user is looking for products, it calls this tool with the user's query text. The tool then performs the vector search described above and returns a list of matching products (including their name, brand, category, price, stock, and a formatted LLM-friendly description derived from the stored `llm_summarized_description` or stripped HTML).
    *   **`get_live_product_details`**: If the LLM or user identifies a specific product (by its `item_code` for all locations, or a composite `id` for a specific warehouse location), this tool retrieves its detailed, up-to-date information directly from the local PostgreSQL database.

### 4. Nulu AI Integration for Multi-Channel Communication

*   **Incoming Messages:** A webhook endpoint (`/api/sb-webhook`) is configured in Nulu AI to send `message-sent` events from users on connected channels (WhatsApp, Instagram) to NamDamasco.
*   **Contextual Enrichment:** NamDamasco can use the Nulu AI API to fetch conversation history and user details, providing valuable context to the LLM for more personalized and accurate responses.
*   **Outgoing Replies:**
    *   **WhatsApp:** Bot replies are sent directly to the user via the Meta WhatsApp Cloud API, using the customer's WAID.
    *   **Instagram/Facebook Messenger:** Bot replies are sent through Nulu AI's platform API, using the customer's PSID.
    *   **Dashboard Synchronization:** For all bot replies sent externally, a copy is also logged internally within the Nulu AI conversation using `send-message`. This ensures human agents have full visibility into the bot's interactions in the Nulu AI dashboard.

### 5. Human Agent Takeover & Bot Pause Mechanism

*   The system monitors messages for those originating from configured human agent IDs within Nulu AI.
*   If a human agent sends a message in a conversation, NamDamasco automatically pauses the bot's responses for that specific conversation for a configurable duration (e.g., 30 minutes).
*   This pause state is managed in the `conversation_pauses` table in PostgreSQL, preventing the bot from interfering once a human has taken over.

## 🚀 Key Features

*   📡 **Nulu AI Webhook Integration:** Robustly handles `message-sent` events via `/api/sb-webhook`.
*   📦 **Secure Product Data Receiver:** Authenticated `/api/receive-products` endpoint for ingesting inventory data from the external Damasco Fetcher.
*   ✨ **Asynchronous & Efficient Product Processing:**
    *   Utilizes Celery for background processing of incoming product data, ensuring API responsiveness.
    *   Implements **delta detection** to compare incoming data against stored records, only processing and re-embedding items with meaningful changes.
*   📝 **Advanced Description Handling:**
    *   Accepts and stores raw **HTML descriptions** from the source.
    *   Performs **conditional LLM-powered summarization** to generate concise, plain-text summaries, optimizing for LLM calls by summarizing only new or changed descriptions, or when a summary is missing.
    *   Prioritizes LLM summaries for generating `searchable_text_content` used for vector embeddings, with a fallback to stripped HTML.
*   📱 **Direct WhatsApp Cloud API Integration** for sending messages.
*   🗣️ **Nulu AI API Integration** for fetching conversation context and sending replies on platforms like Instagram/Facebook Messenger.
*   🔎 **Intelligent Semantic Product Search:** Leverages `pgvector` for vector similarity searches on product embeddings derived from names, categories, brands, and processed descriptions.
*   🤖 **Advanced LLM Function Calling:** Empowers LLMs (OpenAI/Google) with tools (`search_local_products`, `get_live_product_details`) for dynamic information retrieval.
*   🐘 **PostgreSQL + `pgvector` Backend:** Provides robust and scalable storage for product data, vector embeddings, and application state.
*   🔄 **Decoupled Data Synchronization:** Architecture relies on an external `fetcher_scripts` component for interacting with the Damasco API and pushing data.
*   ⏸️ **Human Agent Takeover Pause:** Ensures smooth transitions between bot and human support.
*   ⚙️ **Environment-Based Configuration:** Flexible setup via `.env` files for different environments.
*   📝 **Structured & Multi-Destination Logging:** Comprehensive logging to console and rotating files for application events, synchronization processes, and Celery tasks.
*   🌍 **Production-Ready Design:** Built for deployment using Gunicorn (with gevent workers) behind a reverse proxy like Caddy or Nginx.

## 📁 Folder Structure (NamDamasco Application Server)
/NAMDAMASCO_APP_ROOT/
|-- namwoo_app/ # Main application package
| |-- init.py # App factory (create_app), main app config
| |-- api/
| | |-- init.py # Defines 'api_bp' Blueprint, imports route modules
| | |-- receiver_routes.py # Handles /api/receive-products (enqueues Celery tasks)
| | |-- routes.py # Handles /api/sb-webhook, /api/health
| |-- celery_app.py # Celery application setup (with Flask context management)
| |-- celery_tasks.py # Celery task definitions (product processing, summarization)
| |-- config/
| | |-- config.py # Defines Config class, loads .env
| |-- data/ # Static data, e.g., LLM system prompts
| | |-- system_prompt.txt
| |-- models/
| | |-- init.py # Defines SQLAlchemy Base, imports all models
| | |-- product.py # Product ORM model (with description, llm_summarized_description)
| | |-- conversation_pause.py # ConversationPause ORM model
| |-- services/
| | |-- init.py # Exposes service functions/modules for easy import
| | |-- damasco_service.py # Helper for initial processing of raw Damasco data (outputs snake_case)
| | |-- google_service.py # Google Gemini specific logic (chat, summarization)
| | |-- openai_service.py # OpenAI specific logic (chat, embedding, summarization)
| | |-- product_service.py # Core logic for DB ops, vector search, delta detection
| | |-- support_board_service.py # Nulu AI API interactions
| | |-- sync_service.py # Coordinates bulk data sync (can call Celery or product_service)
| | |-- llm_processing_service.py # NEW: Dispatches summarization to configured LLM provider
| |-- utils/
| | |-- init.py
| | |-- db_utils.py # Database session management
| | |-- embedding_utils.py # Helper for calling embedding models
| | |-- text_utils.py # NEW: Contains strip_html_to_text
| | |-- product_utils.py # NEW (Recommended): Shared product ID generation logic
| |-- scheduler/ # APScheduler related tasks (if used for other cron jobs)
| |-- init.py
| |-- tasks.py
|-- data/ # Project-level data (e.g., SQL schema if not using migrations)
| |-- schema.sql # Must include 'description' and 'llm_summarized_description' columns
|-- logs/ # Created at runtime for log files
|-- venv/ # Python virtual environment (.gitignored)
|-- .env # Environment variables (SECRET! .gitignored)
|-- .env.example # Example environment variables
|-- .gitignore
|-- requirements.txt # Python dependencies (add beautifulsoup4)
|-- run.py # Entry point for Gunicorn (e.g., run:app which calls create_app)
|-- gunicorn.conf.py # (Optional) Gunicorn configuration file
|-- Caddyfile # Example Caddy reverse proxy configuration
|-- README.md # This file
*(Note: The `fetcher_scripts/` directory for Damasco data acquisition is considered a separate, complementary project/component that pushes data to this application.)*

## 🛠️ Setup & Installation Guide (NamDamasco Application Server)

### Prerequisites:

*   🐍 **Python:** 3.9+
*   🐘 **PostgreSQL Server:** Version 13-16 recommended.
    *   **`pgvector` Extension:** Must be installed and enabled in your PostgreSQL database.
*   💾 **Redis Server:** Recommended for Celery message broker and result backend.
*   🐳 **Docker & Docker Compose:** Highly recommended for easily managing PostgreSQL (with `pgvector`) and Redis services.
*   🐙 **Git:** For version control.
*   🔑 **API Keys & Credentials:**
    *   Meta Developer App credentials for WhatsApp Cloud API.
    *   Nulu AI installation/account with API token and necessary User/Conversation IDs.
    *   LLM Provider API Key (OpenAI API Key and/or Google AI API Key for Gemini).
    *   `DAMASCO_API_SECRET`: A secret key to authenticate requests from your Fetcher Service to the `/api/receive-products` endpoint.
*   📡 **External Fetcher Service:** An independent script or service (e.g., `fetcher_scripts/fetch_and_send.py`) must be set up and configured to:
    *   Periodically query the Damasco API.
    *   **Crucially, fetch the raw HTML product descriptions.**
    *   Send the product data (including the HTML description under the key `"description"`) to NamDamasco's `/api/receive-products` endpoint.

### Installation Steps:

1.  **Clone the Repository:**
    ```bash
    git clone <your-namdamasco-repo-url>
    cd namdamasco 
    ```

2.  **Create and Activate Python Virtual Environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install Python Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    *(Ensure `beautifulsoup4` is added to `requirements.txt`)*

4.  **Set Up PostgreSQL & Redis (Docker Example):**
    *   **a. Run PostgreSQL Container (with `pgvector`):**
        ```bash
        docker run --name namwoo-postgres \
          -e POSTGRES_USER=namwoo \
          -e POSTGRES_PASSWORD=damasco2025! \
          -e POSTGRES_DB=namwoo \
          -p 5432:5432 \
          -v namwoo_postgres_data:/var/lib/postgresql/data \
          -d pgvector/pgvector:pg16 
        ```
        *(Using `pgvector/pgvector:pg16` as an example; choose the version compatible with your needs. Added a volume for data persistence.)*
    *   **b. Apply Database Schema & Enable `pgvector`:**
        *   Ensure your `data/schema.sql` (or equivalent migration scripts if using Alembic) defines the `products` table with all columns, including:
            *   `description TEXT NULLABLE`
            *   `llm_summarized_description TEXT NULLABLE`
            *   The `embedding vector(1536)` column (adjust dimension if needed).
        *   If using `schema.sql`:
            ```bash
            docker cp ./data/schema.sql namwoo-postgres:/tmp/schema.sql
            docker exec -u postgres namwoo-postgres psql -d namwoo -c "CREATE EXTENSION IF NOT EXISTS vector;"
            docker exec -u postgres namwoo-postgres psql -d namwoo -f /tmp/schema.sql
            ```
        *   Grant necessary privileges to your application user (`namwoo`):
            ```bash
            docker exec -u postgres namwoo-postgres psql -d namwoo -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO namwoo;"
            docker exec -u postgres namwoo-postgres psql -d namwoo -c "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO namwoo;"
            ```
    *   **c. Run Redis Container (for Celery):**
        ```bash
        docker run --name namwoo-redis -p 6379:6379 -v namwoo_redis_data:/data -d redis:latest redis-server --save 60 1 --loglevel warning
        ```
        *(Added a volume for Redis data persistence and basic save configuration.)*

5.  **Configure Environment Variables:**
    *   Copy the example environment file: `cp .env.example .env`
    *   Edit the `.env` file and meticulously fill in all required variables:
        *   `SECRET_KEY`
        *   `FLASK_ENV` (e.g., `development` or `production`)
        *   `LOG_LEVEL`
        *   `DATABASE_URL` (e.g., `postgresql://namwoo:damasco2025!@localhost:5432/namwoo`)
        *   `CELERY_BROKER_URL` (e.g., `redis://localhost:6379/0`)
        *   `CELERY_RESULT_BACKEND` (e.g., `redis://localhost:6379/0`)
        *   `LLM_PROVIDER` (`openai` or `google`)
        *   `OPENAI_API_KEY`, `OPENAI_EMBEDDING_MODEL`, `OPENAI_CHAT_MODEL`
        *   `GOOGLE_API_KEY`, `GOOGLE_GEMINI_MODEL`
        *   `EMBEDDING_DIMENSION` (e.g., `1536` for `text-embedding-3-small`)
        *   All Support Board (Nulu AI) related IDs and tokens.
        *   All WhatsApp Cloud API related IDs and tokens.
        *   `DAMASCO_API_SECRET` (must match the key used by your Fetcher Service).

6.  **Database Migrations (If using Flask-Migrate/Alembic):**
    *   If you defined the new `description` and `llm_summarized_description` columns via Alembic migrations (instead of `schema.sql`):
        ```bash
        flask db migrate -m "Add description and llm_summary columns to products" 
        flask db upgrade
        ```
    *   If you used `schema.sql` and this is a fresh setup, this step is not needed. If evolving an existing DB with Alembic, migrations are preferred over raw SQL for schema changes.

7.  **Run Initial Data Sync (Trigger External Fetcher):**
    *   Ensure your external **Fetcher Service is updated** to fetch product descriptions (HTML) and sends them in its payload to `/api/receive-products`.
    *   Execute the Fetcher Service to populate NamDamasco with initial data. This will trigger Celery tasks for processing.

8.  **Run NamDamasco Application (Development/Testing):**
    *   **Terminal 1: Flask Application Server (Gunicorn)**
        ```bash
        # Ensure your virtual environment is activated: source venv/bin/activate
        gunicorn --bind 0.0.0.0:5100 "run:app" --log-level debug --worker-class gevent --workers 4 --timeout 300
        ```
        *(Adjust port, workers, and timeout as needed. `run:app` refers to the `app` object created by `create_app()` in `run.py`.)*
    *   **Terminal 2: Celery Worker(s)**
        ```bash
        # Ensure your virtual environment is activated: source venv/bin/activate
        celery -A namwoo_app.celery_app worker -l INFO -P gevent -c 2 
        ```
        *(Adjust concurrency `-c` as needed. Using `gevent` pool if your Gunicorn also uses it.)*
    *   **(Optional) Terminal 3: Celery Beat (if you have scheduled tasks within Celery)**
        ```bash
        # celery -A namwoo_app.celery_app beat -l INFO
        ```

9.  **Configure Nulu AI Webhook:**
    *   **URL:** `https://your-public-domain-or-ngrok-url.com/api/sb-webhook`
    *   Ensure `message-sent` event is active.
    *   If using a local development server with `ngrok` or similar for a public URL, update Nulu AI with that URL.

10. **Test Thoroughly:**
    *   **Data Ingestion:** Send data batches via the Fetcher to `/api/receive-products`.
        *   Check Gunicorn logs for HTTP 202 responses and enqueue messages.
        *   Check Celery worker logs for detailed processing: HTML stripping, summarization calls (conditional logic), embedding, DB upsert status ("added", "updated", "skipped\_no\_change").
    *   **Database Verification:** Directly query PostgreSQL to inspect `description`, `llm_summarized_description`, `searchable_text_content`, and `embedding` fields.
    *   **Delta Detection:** Send identical data again; verify `skipped_no_change` in logs. Send data with minor changes (e.g., price, stock, then HTML description, then only non-textual changes) to confirm only necessary updates and re-processing occur.
    *   **Conversational AI:** Test product searches via your Nulu AI channels to see if results are relevant and if the LLM uses the summarized descriptions effectively.
    *   **Human Agent Takeover:** Test the bot pause functionality.

11. **Production Deployment:**
    *   Utilize robust process management like `systemd` for Gunicorn and Celery services.
    *   Place the application behind a reverse proxy (Caddy, Nginx) for SSL termination, load balancing (if applicable), and security.
    *   Schedule the external Fetcher Service using `cron` or a similar task scheduler.

## 💡 Important Considerations & Future Enhancements

*   **Error Handling & Resilience:** Implement comprehensive error handling, dead-letter queues for Celery, and monitoring/alerting.
*   **API Rate Limits:** Be mindful of rate limits for LLM APIs (OpenAI, Google) and the WhatsApp Cloud API, especially during bulk processing or high user traffic. Implement backoff and retry strategies.
*   **Security:**
    *   Protect all API keys and credentials (e.g., using AWS Secrets Manager or HashiCorp Vault in production).
    *   Continue rigorous input validation.
    *   Implement webhook signature validation for the Nulu AI webhook if sensitive.
*   **Scalability:**
    *   The current architecture with Celery is a good foundation. Further scaling might involve more Celery workers, optimizing database queries, or exploring more distributed task queue setups.
    *   Consider if the Fetcher Service itself could be optimized to only send deltas from Damasco, further reducing load on NamDamasco.
*   **Vector Database Optimization:** For very large product catalogs, explore dedicated vector databases or advanced indexing strategies within `pgvector`.
*   **Advanced Location-Based Search/Filtering:** Enhance product search to incorporate user location for stock availability if branches map to geographical areas.
*   **Cost Management:** Regularly review LLM and embedding API usage to manage costs. Optimize prompts and conditional logic where possible.
*   **Idempotency:** While delta detection helps, ensure critical operations (like sending a message) are as idempotent as possible if tasks might be retried.

