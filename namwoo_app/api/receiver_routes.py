# NAMWOO/api/receiver_routes.py

import logging
from flask import request, jsonify, current_app
# Removed SQLAlchemyError as direct DB operations are moved to Celery
# from sqlalchemy.exc import SQLAlchemyError

# Removed direct service/model imports not used by this enqueuing route
# from ..utils import db_utils
# from ..services import product_service
# from ..services.openai_service import generate_product_embedding
# from ..models.product import Product

# Import the Celery task
from ..celery_tasks import process_product_item_task

from . import api_bp  # Use the main API blueprint

logger = logging.getLogger(__name__)

# Helper to convert incoming camelCase from Fetcher to snake_case for Celery task
# This ensures the Celery task receives data in the format its Pydantic model expects.
def _convert_api_input_to_snake_case_for_task(data_camel: dict) -> dict:
    """
    Converts a dictionary with camelCase keys (from API input)
    to snake_case keys (for Celery task).
    """
    if not data_camel:
        return {}
    
    # Define the mapping from camelCase (API input from Fetcher)
    # to snake_case (as expected by DamascoProductDataSnake Pydantic model in celery_tasks.py)
    key_map = {
        "itemCode": "item_code",
        "itemName": "item_name",
        "subCategory": "sub_category",
        "itemGroupName": "item_group_name",
        "whsName": "warehouse_name",
        "branchName": "branch_name",
        # Keys that are the same (or already snake_case if fetcher sends them mixed)
        "description": "description", # Pass raw HTML description
        "stock": "stock",
        "price": "price",
        "category": "category",
        "brand": "brand",
        "line": "line",
    }
    
    data_snake = {}
    for camel_key, value in data_camel.items():
        snake_key = key_map.get(camel_key)
        if snake_key: # Only include keys that are defined in our map
            data_snake[snake_key] = value
        else:
            # Optionally log unmapped keys if you want to be strict
            # logger.debug(f"Unmapped key '{camel_key}' in product data from fetcher. Will not be passed to Celery task unless Pydantic 'extra=allow' and task handles it.")
            # If Pydantic model has extra='allow', unmapped keys might pass if they match existing field names directly (e.g. if a key is already snake_case)
            # For clarity, it's best to ensure all expected fields by the Pydantic model are mapped.
            pass # Ignoring unmapped keys for now
    return data_snake


@api_bp.route('/receive-products', methods=['POST'])
def receive_data():
    """
    Receives JSON payload of product entries from Fetcher EC2.
    Validates API token.
    For each product entry, converts to snake_case and enqueues a Celery task for processing.
    Returns an HTTP 202 Accepted response.
    """
    auth_token = request.headers.get('X-API-KEY')
    expected_token = current_app.config.get('DAMASCO_API_SECRET')

    if not expected_token:
        logger.critical("DAMASCO_API_SECRET not configured in app settings. Cannot authenticate request.")
        return jsonify({"status": "error", "message": "Server misconfiguration - API Secret missing"}), 500

    if not auth_token or auth_token != expected_token:
        logger.warning("Unauthorized /receive-products request. Invalid or missing API token.")
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    damasco_payload_camel_case = request.get_json(force=True) # Assuming fetcher sends camelCase
    if not damasco_payload_camel_case or not isinstance(damasco_payload_camel_case, list):
        logger.error("Invalid data received for /receive-products. Expected a JSON list of product entries.")
        return jsonify({"status": "error", "message": "Invalid JSON format: Expected a list."}), 400

    if not damasco_payload_camel_case:
        logger.info("Received an empty list of products. No action taken.")
        return jsonify({
            "status": "ok", # Or "accepted"
            "message": "Received empty product list. No tasks enqueued.",
            "tasks_enqueued": 0
        }), 200 # 200 OK is fine for an empty list that requires no action.

    logger.info(f"Received {len(damasco_payload_camel_case)} product entries from fetcher. Attempting to enqueue for Celery processing.")

    enqueued_count = 0
    failed_to_enqueue_count = 0
    items_skipped_validation_count = 0 # Count items that don't pass basic structural check

    for i, product_entry_camel in enumerate(damasco_payload_camel_case):
        # Log using keys as received from payload
        item_code_log = product_entry_camel.get('itemCode', 'N/A')
        whs_name_log = product_entry_camel.get('whsName', 'N/A')
        log_prefix = f"Payload Entry [{i+1}/{len(damasco_payload_camel_case)}] ({item_code_log} @ {whs_name_log}):"

        if not isinstance(product_entry_camel, dict):
            logger.warning(f"{log_prefix} Item in payload is not a dictionary. Skipping enqueue.")
            items_skipped_validation_count += 1
            continue

        # Convert incoming camelCase product data to snake_case for the Celery task
        product_data_snake = _convert_api_input_to_snake_case_for_task(product_entry_camel)

        # Basic check: Ensure essential keys for task identification are present after conversion
        if not product_data_snake.get("item_code") or not product_data_snake.get("warehouse_name"):
            logger.warning(f"{log_prefix} Missing essential 'item_code' or 'warehouse_name' after conversion to snake_case. Skipping enqueue. Original: {product_entry_camel}, Converted: {product_data_snake}")
            items_skipped_validation_count += 1
            continue
        
        try:
            # Enqueue the task with the snake_case data dictionary
            process_product_item_task.delay(product_data_snake)
            logger.info(f"{log_prefix} Successfully enqueued for Celery processing.")
            enqueued_count += 1
        except Exception as e:
            logger.error(f"{log_prefix} Failed to enqueue task for Celery: {e}", exc_info=True)
            failed_to_enqueue_count +=1
            
    response_summary = {
        "status": "accepted", # HTTP 202: Request accepted for processing
        "message": "Product data received and tasks enqueued for processing.",
        "total_payload_items": len(damasco_payload_camel_case),
        "tasks_successfully_enqueued": enqueued_count,
        "items_skipped_pre_enqueue_validation": items_skipped_validation_count,
        "tasks_failed_to_enqueue": failed_to_enqueue_count
    }
    logger.info(f"Enqueue summary for /receive-products: {response_summary}")
    return jsonify(response_summary), 202 # HTTP 202 Accepted

# --- /health endpoint REMOVED (as per your original file) ---