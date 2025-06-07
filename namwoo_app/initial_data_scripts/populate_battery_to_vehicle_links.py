# initial_data_scripts/populate_battery_to_vehicle_links.py
import json
import os
import sys
import logging

# --- Python Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
print(f"INFO: [populate_battery_to_vehicle_links] Project root added to sys.path: {PROJECT_ROOT}")
# --- End Python Path Setup ---

# --- Load .env ---
from dotenv import load_dotenv
DOTENV_PATH = os.path.join(PROJECT_ROOT, '.env')
if os.path.exists(DOTENV_PATH):
    print(f"INFO: [populate_battery_to_vehicle_links] Loading .env from {DOTENV_PATH}")
    load_dotenv(DOTENV_PATH)
else:
    print(f"WARNING: [populate_battery_to_vehicle_links] .env file not found at {DOTENV_PATH}")
# --- End .env loading ---

try:
    # Corrected imports relative to PROJECT_ROOT
    from __init__ import create_app, db # Assuming db is your SQLAlchemy instance
    from utils.db_utils import get_db_session
    from models.product import Product as BatteryModel 
    from models.product import VehicleBatteryFitment as VehicleConfigModel # Model for 'vehicle_battery_fitment' table
    from models.product import product_vehicle_fitments_table # The SQLAlchemy Table object for the junction table
    from utils.product_utils import generate_battery_product_id 
    from sqlalchemy import select, insert # For SQLAlchemy Core operations
    from sqlalchemy.exc import IntegrityError, SQLAlchemyError
except ImportError as e:
    print(f"CRITICAL ERROR: [populate_battery_to_vehicle_links] Failed to import application components: {e}")
    print("  Current sys.path:", sys.path)
    print("  Ensure that:")
    print(f"  1. Your project root is correctly identified as: {PROJECT_ROOT}")
    print(f"  2. An '__init__.py' file exists at the project root ('{PROJECT_ROOT}/__init__.py') containing 'create_app' and 'db'.")
    print(f"  3. The 'utils' and 'models' directories exist directly under '{PROJECT_ROOT}'.")
    print(f"  4. All necessary __init__.py files exist in these subdirectories to make them packages.")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger(__name__)

JSON_DATA_FILE = os.path.join(SCRIPT_DIR, 'vehicle_fitments_data.json') # Output from models_set.py

def populate_battery_vehicle_links(): # Renamed function for clarity
    logger.info(f"Populating 'battery_vehicle_fitments' (junction table) from: {JSON_DATA_FILE}")

    if not os.path.exists(JSON_DATA_FILE):
        logger.error(f"ABORTING: Data file not found: {JSON_DATA_FILE}")
        return

    # create_app() uses the default Config; passing a string can cause
    # ImportStringError, so do not provide one.
    flask_app = create_app()
    with flask_app.app_context():
        with get_db_session() as session:
            if not session:
                logger.error("Failed to get DB session. Aborting.")
                return
            
            try:
                with open(JSON_DATA_FILE, 'r', encoding='utf-8') as f:
                    fitments_data_list = json.load(f)
            except Exception as e:
                logger.error(f"Error reading or parsing {JSON_DATA_FILE}: {e}")
                return

            links_added_count = 0
            links_skipped_count = 0 
            error_count = 0
            
            logger.info(f"Processing {len(fitments_data_list)} vehicle fitment entries from JSON.")

            for idx, fit_entry in enumerate(fitments_data_list):
                # Construct filter arguments for finding the vehicle configuration
                filter_args_vehicle = {
                    'vehicle_make': fit_entry.get('vehicle_make'),
                    'vehicle_model': fit_entry.get('vehicle_model'),
                    'year_start': fit_entry.get('year_start'),
                    'year_end': fit_entry.get('year_end')
                }
                # Add engine_details to filter if it's present in the JSON and part of your VehicleConfigModel uniqueness
                if 'engine_details' in fit_entry and fit_entry.get('engine_details') is not None:
                    filter_args_vehicle['engine_details'] = fit_entry.get('engine_details')
                
                vehicle_config = session.query(VehicleConfigModel).filter_by(**filter_args_vehicle).first()

                if not vehicle_config:
                    logger.warning(f"Vehicle configuration not found in DB for: {fit_entry.get('vehicle_make')} {fit_entry.get('vehicle_model')} ({fit_entry.get('year_start')}-{fit_entry.get('year_end')}) [Engine: {fit_entry.get('engine_details','N/A')}]. Skipping its battery links.")
                    error_count += len(fit_entry.get('compatible_battery_model_codes', [])) # Count all potential links for this vehicle as errors
                    continue
                
                vehicle_config_db_id = vehicle_config.fitment_id # This is the PK of 'vehicle_battery_fitment' table

                for comp_bat_data in fit_entry.get('compatible_battery_model_codes', []):
                    battery_brand = comp_bat_data.get('brand')
                    battery_model_code = comp_bat_data.get('model_code') # This MUST be the CANONICAL model code

                    if not battery_brand or not battery_model_code:
                        logger.warning(f"Skipping battery link for vehicle config ID {vehicle_config_db_id} due to missing battery brand/model in compatible_battery_model_codes: {comp_bat_data}")
                        error_count += 1
                        continue

                    # Generate the Battery Product String ID CONSISTENTLY with how it was created in populate_batteries.py
                    battery_product_pk_str = generate_battery_product_id(battery_brand, battery_model_code)
                    
                    if not battery_product_pk_str:
                        logger.warning(f"Could not generate battery ID for Brand='{battery_brand}', Model='{battery_model_code}'. Skipping link for vehicle config ID {vehicle_config_db_id}.")
                        error_count += 1
                        continue

                    # Check if the battery product itself exists using its string PK
                    # Note: session.get(Model, pk_value) is a direct way to get by PK
                    battery_product = session.get(BatteryModel, battery_product_pk_str) 

                    if not battery_product:
                        logger.warning(f"Battery product with ID '{battery_product_pk_str}' (Brand: '{battery_brand}', Model: '{battery_model_code}') not found in 'batteries' table. Skipping this link for vehicle config ID {vehicle_config_db_id}.")
                        error_count += 1
                        continue
                    
                    # Check if the link already exists in the junction table
                    stmt_check = select(product_vehicle_fitments_table.c.battery_product_id_fk).where(
                        (product_vehicle_fitments_table.c.fitment_id_fk == vehicle_config_db_id) &
                        (product_vehicle_fitments_table.c.battery_product_id_fk == battery_product_pk_str)
                    )
                    existing_link_check = session.execute(stmt_check).first()

                    if not existing_link_check:
                        try:
                            stmt_insert = product_vehicle_fitments_table.insert().values(
                                fitment_id_fk=vehicle_config_db_id,
                                battery_product_id_fk=battery_product_pk_str
                            )
                            session.execute(stmt_insert)
                            links_added_count += 1
                        except IntegrityError: # Specifically catch unique constraint violations (link already exists)
                            # session.rollback() # Rollback only the failed insert attempt
                            # logger.warning(f"Link for vehicle_config_id={vehicle_config_db_id}, battery_id='{battery_product_pk_str}' likely already exists (IntegrityError). Skipping.")
                            # links_skipped_count += 1 
                            # It's better to let the existing_link_check handle this. If it reaches here, it's an unexpected IntegrityError.
                            logger.exception(f"Unexpected IntegrityError inserting link for vehicle_config_id={vehicle_config_db_id}, battery_id='{battery_product_pk_str}'")
                            error_count += 1
                            # Important: If session is in bad state after IntegrityError, might need broader rollback or careful handling.
                            # For now, we assume get_db_session context manager handles final rollback if errors propagate.
                        except SQLAlchemyError as e_insert: 
                            logger.error(f"SQLAlchemyError inserting link for vehicle_config_id={vehicle_config_db_id}, battery_id='{battery_product_pk_str}': {e_insert}")
                            error_count += 1
                    else:
                        links_skipped_count += 1
            
            try:
                # Commit all successful inserts. Context manager should handle rollback on exception.
                session.commit() 
            except Exception as e_commit:
                # session.rollback() # Redundant if context manager does it
                logger.error(f"Final commit for links failed: {e_commit}")


            logger.info("--- Fitment Link Population Summary ---")
            logger.info(f"Links attempted based on JSON entries: {len(fitments_data_list)} vehicles processed (multiple links per vehicle possible).")
            logger.info(f"Newly added links: {links_added_count}")
            logger.info(f"Skipped (already existing): {links_skipped_count}")
            logger.info(f"Errors (vehicle/battery not found or insert failed): {error_count}")

    logger.info("Battery-to-Vehicle link population script finished.")

if __name__ == "__main__":
    populate_battery_vehicle_links() # Call the renamed function