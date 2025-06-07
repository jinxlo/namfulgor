# initial_data_scripts/populate_batteries.py
import json
import os
import sys
import logging
# from decimal import Decimal, ROUND_HALF_UP, InvalidOperation # Only needed if service doesn't handle string prices

# --- Python Path Setup ---
# Ensures the project root (containing __init__.py, models/, services/, etc.) is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..')) # This should resolve to /usr/src/app in Docker
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
print(f"INFO: [populate_batteries] Project root added to sys.path: {PROJECT_ROOT}")
print(f"INFO: [populate_batteries] Current sys.path: {sys.path}") # For debugging
# --- End Python Path Setup ---

# --- Load .env from the project root ---
from dotenv import load_dotenv
DOTENV_PATH = os.path.join(PROJECT_ROOT, '.env')
if os.path.exists(DOTENV_PATH):
    print(f"INFO: [populate_batteries] Loading .env from {DOTENV_PATH}")
    load_dotenv(DOTENV_PATH)
else:
    print(f"WARNING: [populate_batteries] .env file not found at {DOTENV_PATH}. Using environment variables if set elsewhere.")
# --- End .env loading ---

try:
    # Imports are now relative to PROJECT_ROOT (/usr/src/app)
    from __init__ import create_app, db  # create_app and db from project root
    from models.product import Product as BatteryModel
    from services.product_service import add_or_update_battery_product
    from utils.product_utils import generate_battery_product_id
except ImportError as e:
    print(f"CRITICAL ERROR: [populate_batteries] Failed to import application components: {e}")
    print("  Check that:")
    print(f"  1. Project root is correctly set to: {PROJECT_ROOT}")
    print("  2. Directories 'models', 'services', 'utils' and the root '__init__.py' exist directly under the project root.")
    print("  3. There are no circular dependencies or other Python import errors within your application modules.")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger(__name__)

JSON_DATA_FILE = os.path.join(SCRIPT_DIR, 'batteries_master_data.json')

def populate_batteries_from_json():
    logger.info(f"Starting battery data population from: {JSON_DATA_FILE}")
    
    if not os.path.exists(JSON_DATA_FILE):
        logger.error(f"ABORTING: Data file not found: {JSON_DATA_FILE}")
        return

    # create_app() defaults to using the Config class from config/config.py.
    # Passing a string like 'default' leads to ImportStringError, so we simply
    # call it without arguments.
    flask_app = create_app()

    with flask_app.app_context():
        session = db.session

        try:
            with open(JSON_DATA_FILE, 'r', encoding='utf-8') as f:
                batteries_master_list = json.load(f)
        except Exception as e:
            logger.error(f"Error reading or parsing {JSON_DATA_FILE}: {e}")
            return

        populated_count = 0
        updated_count = 0
        skipped_count = 0
        error_count = 0

        logger.info(f"Found {len(batteries_master_list)} battery entries in JSON file.")

        try:
            for idx, bat_json_data in enumerate(batteries_master_list):
                brand = bat_json_data.get("brand")
                model_code = bat_json_data.get("model_code") 
                
                if not brand or not model_code:
                    logger.error(f"Entry #{idx+1} in JSON is missing 'brand' or 'model_code': {bat_json_data}. Skipping.")
                    error_count += 1
                    continue
                
                battery_id_pk = generate_battery_product_id(brand, model_code) 
                if not battery_id_pk:
                    logger.error(f"Could not generate battery ID for brand='{brand}', model_code='{model_code}'. Skipping.")
                    error_count +=1
                    continue

                logger.info(f"Processing battery {idx+1}/{len(batteries_master_list)}: ID='{battery_id_pk}', Brand='{brand}', Model='{model_code}'")
                
                data_for_service = {
                    "brand": brand,
                    "model_code": model_code, 
                    # No 'original_input_model_code' in your Product model, so it's not passed
                    "price_regular": str(bat_json_data.get("price_full")), 
                    "battery_price_discount_fx": str(bat_json_data.get("price_discounted_usd")), 
                    "warranty_months": bat_json_data.get("warranty_months"),
                    # These fields are in your Product model, ensure they are in your JSON or handle defaults
                    "item_name": bat_json_data.get("item_name", f"{brand} {model_code}"), 
                    "description": bat_json_data.get("description"), 
                    "stock": bat_json_data.get("stock", 0), 
                    "additional_data": bat_json_data.get("additional_data") 
                }
                data_for_service_cleaned = {k: v for k, v in data_for_service.items() if v is not None}
                
                if 'price_regular' not in data_for_service_cleaned and bat_json_data.get("price_full") is None:
                    logger.error(f"Battery ID {battery_id_pk} missing price_full and schema requires price_regular. Skipping.")
                    error_count +=1
                    continue

                try:
                    success, status_message = add_or_update_battery_product(
                        session=session,
                        battery_id=battery_id_pk,
                        battery_data=data_for_service_cleaned
                    )

                    if success:
                        if "added" in status_message.lower():
                            populated_count += 1
                        elif "updated" in status_message.lower():
                            updated_count += 1
                        elif "skipped" in status_message.lower():
                            skipped_count += 1
                    else:
                        logger.error(f"Service call failed for battery ID {battery_id_pk}: {status_message}")
                        error_count += 1
                except Exception as e:
                    logger.exception(f"Exception during service call for battery ID {battery_id_pk} ({brand} {model_code}): {e}")
                    error_count += 1

            session.commit()
            logger.info("--- Battery Population Summary ---")
            logger.info(f"Total battery entries in JSON: {len(batteries_master_list)}")
            logger.info(f"Newly added to DB: {populated_count}")
            logger.info(f"Updated in DB: {updated_count}")
            logger.info(f"Skipped: {skipped_count}")
            logger.info(f"Errors: {error_count}")

        except Exception as e:
            session.rollback()
            logger.exception(f"An error occurred during battery population batch: {e}")

    logger.info("Battery data population script finished.")

if __name__ == "__main__":
    populate_batteries_from_json()
