# 💠 NamFulgor: AI-Powered Battery Sales & Fitment Assistant 💠

NamFulgor is a Python Flask web application backend designed to power a conversational AI assistant specialized in automotive batteries. It seamlessly integrates with **Nulu AI** (a customer interaction platform) and manages an internal battery catalog with vehicle fitment data. Battery prices are updated dynamically via a dedicated email processing system. This system enables customers on platforms like WhatsApp and Instagram (through Nulu AI) to engage in natural language conversations to find the correct battery for their vehicle, inquire about specifications, check prices, and availability using intelligent assistance.

---

## ✨ Core Strategy & How It Works

The primary goal of NamFulgor is to provide accurate and contextually relevant battery information to users, assisting them in finding the correct battery for their vehicle. This is achieved through:

1.  **🔋 Internal Battery Catalog & Vehicle Fitment Data:**
    *   NamFulgor maintains a local PostgreSQL database storing:
        *   **Battery Specifications:** Details for each battery model (brand, model code, warranty, prices, etc.). This is represented by the `Product` model internally (defined in `models/product.py`), mapped to a `batteries` table.
        *   **Vehicle Fitment Data:** Information on which vehicles (make, model, year range, engine) are compatible with specific battery models, managed by the `VehicleBatteryFitment` model (also in `models/product.py`).
    *   **Initial Data Load:** Battery specifications and vehicle fitment data are populated into the database using initial data load scripts (located in `initial_data_scripts/` at the project root).
    *   **Price Updates via Email:**
        *   A separate **Email Processor Service** (running in its own Docker container, defined in the `email_processor/` directory at the project root) monitors a designated email account for messages containing battery price updates (typically as a CSV attachment).
        *   Upon receiving a valid email from an authorized sender with the correct format, the Email Processor parses the data and securely calls a dedicated API endpoint in NamFulgor (`/api/battery/update-prices`) to update the battery prices in the database.

2.  **🚗 Intelligent Battery Search by Vehicle Fitment:**
    *   When a user inquires about a battery for their vehicle, NamFulgor uses this information (make, model, year) to query its local database.
    *   It identifies compatible battery models based on the stored vehicle fitment data.
    *   *(Semantic Search for Batteries is currently not implemented, relying on structured fitment search).*

3.  **🤖 Intelligent LLM Interaction & Tool Usage:**
    *   User messages received via Nulu AI are passed to a Large Language Model (LLM), such as Google's Gemini or OpenAI's GPT models (configured via `services/openai_service.py` or `services/google_service.py`).
    *   The LLM is equipped with **custom tools (functions)** it can decide to call:
        *   `search_vehicle_batteries`: This is the primary tool. Given a vehicle's make, model, and (optionally) year, it queries the internal database (via `services/product_service.py`) to find compatible battery models, returning their specifications, current prices, and warranty details.
        *   *(Optional: `get_specific_battery_details` could be added if needed).*
        *   *(Optional: Lead Generation Tools like `initiate_customer_information_collection` and `submit_customer_information_for_crm` if lead capture is enabled, using `services/lead_api_client.py`).*

4.  **💬 Nulu AI Integration (Multi-Channel Communication):**
    *   **Incoming Messages:** NamFulgor listens for new messages via a Nulu AI webhook configured at `/api/sb-webhook` (defined in `api/routes.py`).
    *   **Contextual Awareness & Outgoing Replies:** Handled via `services/support_board_service.py` and direct WhatsApp API integration if configured.

5.  **🧑‍💼 Human Agent Takeover & Bot Pause:**
    *   Managed via the `ConversationPause` model (in `models/conversation_pause.py`) and logic within `api/routes.py`, using `utils/db_utils.py`.

---

## 🚀 Key Features

*   **📡 Nulu AI Webhook Integration:** Handles incoming `message-sent` events (`api/routes.py`).
*   **📧 Email-Based Price Updates:** A dedicated Email Processor service updates battery prices via the `/api/battery/update-prices` endpoint (defined in `api/battery_api_routes.py`).
*   **🚗 Vehicle-Specific Battery Search:** Core functionality to find compatible batteries.
*   **📱 (Optional) Direct WhatsApp Cloud API Integration.**
*   **🗣️ Nulu AI API Integration.**
*   **🤖 Advanced LLM Function Calling** (e.g., `search_vehicle_batteries`).
*   **🐘 PostgreSQL Backend:** Robust storage for battery specifications (`batteries` table via `models/product.py`), vehicle fitment data, and application state (`conversation_pauses` table). `pgvector` extension is optional unless semantic search on battery text is implemented.
*   **⏸️ Human Agent Takeover Pause.**
*   **⚙️ Environment-Based Configuration** via `.env` file (parsed by `config/config.py`).
*   **📝 Structured Logging** (to `logs/namfulgor_app.log`).
*   **🌍 Production Ready:** Designed for deployment with Gunicorn.

---

## 📁 Folder Structure (NamFulgor Application Server - Main Components)

/NAMFULGOR_APP_ROOT/  # Project Root
|-- namwoo_app/         # Main Flask application package
|   |-- __init__.py     # App factory
|   |-- api/
|   |   |-- __init__.py
|   |   |-- battery_api_routes.py # Handles /api/battery/update-prices
|   |   |-- routes.py             # Handles /api/sb-webhook, /api/health
|   |-- config/
|   |   |-- config.py             # Application configuration
|   |   |-- __init__.py
|   |-- data/
|   |   |-- schema.sql            # Database schema (updated for batteries)
|   |   |-- system_prompt.txt     # LLM system prompt (updated for batteries)
|   |-- models/
|   |   |-- __init__.py
|   |   |-- conversation_pause.py # Manages conversation pause state
|   |   |-- product.py            # Defines Product (as Battery) & VehicleBatteryFitment models
|   |-- scheduler/                # (If used for any NamFulgor-specific tasks, otherwise can be removed)
|   |   |-- tasks.py
|   |   |-- __init__.py
|   |-- services/
|   |   |-- __init__.py
|   |   |-- google_service.py       # (If Google LLM is used)
|   |   |-- lead_api_client.py    # (If lead generation is used)
|   |   |-- openai_service.py       # LLM interaction logic, uses battery tools
|   |   |-- product_service.py      # Core logic for batteries & fitments (refactored)
|   |   |-- support_board_service.py # Nulu AI interaction
|   |-- utils/
|   |   |-- __init__.py
|   |   |-- db_utils.py             # Database utilities (history functions removed)
|   |   |-- product_utils.py        # Contains generate_battery_product_id
|   |-- __init__.py                 # (Duplicate? Seems you have one at namwoo_app level and one inside it - likely a typo in tree output)
|
|-- email_processor/      # NEW: Separate service for email parsing
|   |-- processor.py
|   |-- requirements.txt
|   |-- Dockerfile
|   |-- data/                 # For persistent state (e.g., processed email UIDs)
|
|-- initial_data_scripts/ # NEW: Scripts for populating initial battery & fitment data
|   |-- populate_batteries.py
|   |-- populate_vehicle_configurations.py
|   |-- populate_battery_to_vehicle_links.py
|
|-- logs/                   # Runtime logs (e.g., namfulgor_app.log)
|-- .env
|-- .env.example          # Updated for NamFulgor
|-- .gitignore
|-- requirements.txt      # Updated for NamFulgor (e.g., Celery removed)
|-- run.py                  # Flask app entry point
|-- Dockerfile              # For the main Flask app
|-- docker-compose.yml      # Updated (includes email_processor, Celery/Redis removed if not used)
|-- README.md               # This file

*(Note: The `logs/sync.log` may no longer be relevant if the Damasco sync mechanism is removed. The `scheduler/` directory's purpose should be re-evaluated for NamFulgor.)*

---

## 🛠️ Setup & Installation Guide (NamFulgor Application Server)

**Prerequisites:**

*   🐍 Python 3.9+
*   🐘 PostgreSQL Server (v13-v16 recommended). `pgvector` extension is optional.
*   🐳 Docker (Highly recommended for PostgreSQL & Email Processor Service).
*   🐙 Git.
*   🔑 Access to:
    *   (Optional) Meta Developer App & WhatsApp Business Account.
    *   Nulu AI installation/account.
    *   An LLM provider API Key (OpenAI, Google Gemini).
*   📧 A dedicated email account (with IMAP access) for receiving price update CSVs.

**Steps:**

1.  **Clone the Repository:**
    ```bash
    git clone <your-namfulgor-repo-url>
    cd namfulgor
    ```

2.  **Set Up PostgreSQL (Docker Example):**
    a.  Modify `docker-compose.yml` to define the `postgres_db` service (e.g., using `postgres:16` or `pgvector/pgvector:pg16` image).
    b.  Ensure `data/schema.sql` reflects the NamFulgor battery-centric schema.
    c.  (When running `docker-compose up`, the schema can be applied via an init script linked in `docker-compose.yml` or manually as described below).

3.  **Configure Environment Variables:**
    *   Copy `cp .env.example .env`.
    *   Edit `.env` and fill in all variables required by `config/config.py` for NamFulgor, including database credentials, `INTERNAL_SERVICE_API_KEY`, LLM keys, Nulu AI details, and IMAP settings for the email processor.

4.  **Build and Run with Docker Compose:**
    *   Ensure `docker-compose.yml` defines the `namfulgor_app_service` (your Flask app) and the `email_price_updater` service.
    ```bash
    docker-compose up --build -d
    ```
    *   **Apply Database Schema (if not handled by init script):**
        After the PostgreSQL container is running:
        ```bash
        docker cp ./data/schema.sql <postgres_container_name>:/tmp/schema.sql
        docker exec -u postgres <postgres_container_name> psql -d <your_db_name> -f /tmp/schema.sql
        ```

5.  **Run Initial Data Population Scripts:**
    *   You may need to run these scripts by executing them within the running Flask app container or by setting up your local environment to connect to the Dockerized DB.
    ```bash
    # Example: Running within the Flask app container
    docker exec -it <namfulgor_app_container_name> python initial_data_scripts/populate_batteries.py
    docker exec -it <namfulgor_app_container_name> python initial_data_scripts/populate_vehicle_configurations.py
    docker exec -it <namfulgor_app_container_name> python initial_data_scripts/populate_battery_to_vehicle_links.py
    ```
    *(Alternatively, for local execution, activate venv, install `requirements.txt`, ensure `.env` is configured for the Docker DB, then run `python initial_data_scripts/...`)*

6.  **Configure Nulu AI Webhook:**
    *   URL: `https://your-public-domain.com/api/sb-webhook`
    *   Ensure `message-sent` event is active.

7.  **Test Thoroughly:**
    *   Test battery searches via Nulu AI.
    *   Send a correctly formatted email with a CSV to the designated email account and verify prices update in the database (check `namfulgor_app.log` and email processor logs via `docker logs <email_processor_container_name>`).
    *   Test human agent takeover.

---

## 💡 Important Considerations & Future Enhancements

*   **Email Processor Robustness:** Implement comprehensive error handling, retries, and notifications for the email processing service.
*   **Security:** Secure the `INTERNAL_SERVICE_API_KEY` and the email account used for price updates. Consider IP whitelisting for the price update API endpoint.
*   **Admin Interface:** A simple web interface for managing battery data, fitments, and viewing price update history could be beneficial.
*   **Monitoring & Alerting:** Set up for both the Flask application and the Email Processor service.
