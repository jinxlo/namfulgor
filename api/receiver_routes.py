# NAMWOO/api/receiver_routes.py
import logging
from flask import Blueprint, request, jsonify, current_app
from sqlalchemy.exc import SQLAlchemyError # For catching DB commit errors

from ..utils import db_utils # For `with db_utils.get_db_session() as session:`
from ..services import product_service
# from ..services import embedding_service # <<<--- REMOVED/COMMENTED OUT
from ..services.openai_service import generate_product_embedding # <<<--- MODIFIED IMPORT
from ..models.product import Product # Import the Product model for its static method

# Ensure your Blueprint registration is correct for your app structure
# Using 'receiver_api' as the Blueprint name for clarity, adjust if your app uses 'receiver_bp' from here.
receiver_bp = Blueprint('receiver_api', __name__, url_prefix='/api') # Match your app's setup

logger = logging.getLogger(__name__) # It's good practice to use __name__ for module-specific loggers

@receiver_bp.route('/receive-products', methods=['POST'])
def receive_data():
    """
    Receives JSON payload of product entries from Fetcher EC2.
    Validates API token.
    For each product entry:
        - Prepares descriptive text for embedding.
        - Generates an embedding for that text.
        - Stores/Updates the full product entry data (including location, stock, price)
          and its generated embedding in the database.
    """
    # --- Token Authentication ---
    auth_token = request.headers.get('X-API-KEY')
    expected_token = current_app.config.get('DAMASCO_API_SECRET')

    if not expected_token:
        logger.critical("DAMASCO_API_SECRET not configured in app settings. Cannot authenticate request.")
        return jsonify({"status": "error", "message": "Server misconfiguration - API Secret missing"}), 500

    if not auth_token or auth_token != expected_token:
        logger.warning("Unauthorized /receive-products request. Invalid or missing API token.")
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    # --- Parse Payload ---
    # Each item in damasco_payload is a dictionary representing one product at one warehouse
    damasco_payload = request.get_json(force=True) 
    if not damasco_payload or not isinstance(damasco_payload, list):
        logger.error("Invalid data received for /receive-products. Expected a JSON list of product entries.")
        return jsonify({"status": "error", "message": "Invalid JSON format: Expected a list."}), 400

    if not damasco_payload: # Empty list is valid but no work to do
        logger.info("Received an empty list of products. No action taken.")
        return jsonify({
            "status": "ok", 
            "message": "Received empty product list.", 
            "inserted_in_db":0, 
            "updated_in_db":0, 
            "total_failed_or_skipped":0,
            "total_received": 0
        }), 200

    logger.info(f"Received {len(damasco_payload)} product entries from fetcher for processing.")

    # --- Process Product Entries ---
    inserted_count = 0
    updated_count = 0
    skipped_no_text_for_embedding_count = 0
    skipped_embedding_generation_failed_count = 0
    db_processing_failed_count = 0
    
    with db_utils.get_db_session() as session:
        if not session:
            logger.critical("Failed to acquire DB session. Aborting batch processing for /receive-products.")
            return jsonify({"status": "error", "message": "Database session unavailable."}), 500

        for i, product_entry_data in enumerate(damasco_payload):
            # Construct a logging prefix for each item for better traceability
            # Using actual Damasco JSON keys for logging
            item_code_log = product_entry_data.get('itemCode', 'UNKNOWN_ITEMCODE') 
            whs_name_log = product_entry_data.get('whsName', 'UNKNOWN_WHS')     
            log_prefix = f"Entry [{i+1}/{len(damasco_payload)}] ({item_code_log} @ {whs_name_log}):"

            if not isinstance(product_entry_data, dict):
                logger.warning(f"{log_prefix} Item in payload is not a dictionary. Skipping.")
                db_processing_failed_count +=1 
                continue

            # 1. Prepare text for embedding using the static method from your Product model
            text_for_embedding = ""
            try:
                # Product.prepare_text_for_embedding expects the raw Damasco dict with camelCase keys
                text_for_embedding = Product.prepare_text_for_embedding(product_entry_data)
            except Exception as e:
                logger.error(f"{log_prefix} Error preparing text for embedding: {e}", exc_info=True)
                # This might be critical enough to skip the item
                skipped_no_text_for_embedding_count += 1
                continue
            
            if not text_for_embedding:
                logger.warning(f"{log_prefix} No text content generated for embedding after preparation. Skipping embedding and DB storage for this entry.")
                skipped_no_text_for_embedding_count += 1
                continue 

            # 2. Generate Embedding
            embedding_vector = None
            try:
                logger.debug(f"{log_prefix} Generating embedding for text: '{text_for_embedding[:150]}...'")
                # Call the imported function directly
                embedding_vector = generate_product_embedding(text_for_embedding) # <<<--- MODIFIED CALL
            except Exception as e: 
                logger.error(f"{log_prefix} Exception during embedding generation call: {e}", exc_info=True)
            
            if not embedding_vector:
                logger.warning(f"{log_prefix} Embedding generation failed or returned empty. Skipping DB storage for this entry.")
                skipped_embedding_generation_failed_count += 1
                continue 

            # 3. Add or Update Product-Location Entry in DB (which now includes the embedding)
            try:
                # Call the updated product_service function
                success, op_message = product_service.add_or_update_product_in_db(
                    session,
                    product_entry_data,         # Full original Damasco data for this warehouse entry
                    embedding_vector,           # Generated embedding
                    text_for_embedding          # Text used to create the embedding (for Product.searchable_text_content)
                )
                if success:
                    if op_message == "added": 
                        inserted_count += 1
                    elif op_message == "updated": 
                        updated_count += 1
                    else: 
                        logger.warning(f"{log_prefix} DB: Received unexpected success message '{op_message}'. Assuming update.")
                        updated_count +=1 
                    logger.info(f"{log_prefix} DB: Entry {op_message} successfully.")
                else:
                    logger.error(f"{log_prefix} DB: Processing failed - {op_message}")
                    db_processing_failed_count += 1
            except Exception as e: 
                logger.error(f"{log_prefix} Unhandled exception calling product_service.add_or_update_product_in_db: {e}", exc_info=True)
                db_processing_failed_count +=1
        
        try:
            session.commit()
            logger.info("Main database transaction committed successfully for the batch.")
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Main database commit FAILED for the batch. Rolled back. Error: {e}", exc_info=True)
            return jsonify({"status": "error", "message": "Database batch commit error after processing items."}), 500

    total_failed_or_skipped = skipped_no_text_for_embedding_count + \
                              skipped_embedding_generation_failed_count + \
                              db_processing_failed_count
    summary = {
        "status": "ok",
        "message": "Batch processing completed.",
        "total_received": len(damasco_payload),
        "inserted_in_db": inserted_count,
        "updated_in_db": updated_count,
        "skipped_due_to_no_text_for_embedding": skipped_no_text_for_embedding_count,
        "skipped_due_to_embedding_generation_failure": skipped_embedding_generation_failed_count,
        "failed_during_db_processing": db_processing_failed_count,
        "total_successfully_processed_to_db": inserted_count + updated_count,
        "total_failed_or_skipped": total_failed_or_skipped
    }
    logger.info(f"Batch processing summary: {summary}")
    return jsonify(summary), 200

# --- Health Check Endpoint ---
@receiver_bp.route('/health', methods=['GET'])
def health_check():
    logger.debug("Health check ping received.")
    return jsonify({"status": "ok", "message": "Namwoo receiver is alive"}), 200

# --- Blueprint Registration Note (as before) ---