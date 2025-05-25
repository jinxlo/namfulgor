# NAMWOO/services/sync_service.py

import logging
import time
import re # For ID generation if doing conditional summarization
from typing import Optional, Tuple, List, Dict, Any # Added List, Dict, Any
from flask import Flask

from . import product_service
from . import llm_processing_service # <-- IMPORT NEW SERVICE
from ..utils import db_utils, embedding_utils
from ..models.product import Product
from ..config import Config # For LLM_PROVIDER and EMBEDDING_DIMENSION

sync_logger = logging.getLogger('sync') # Your specific logger for sync
logger = logging.getLogger(__name__) # General logger for this module

# --- Constants ---
COMMIT_BATCH_SIZE = 100

# --- Helper Functions for sync_service (similar to celery_tasks.py) ---
def _sync_normalize_string_for_id_parts(value: Any) -> Optional[str]:
    if value is None: return None
    s = str(value).strip()
    return s if s else None

def _sync_generate_product_id(item_code_raw: Any, whs_name_raw: Any) -> Optional[str]:
    item_code = _sync_normalize_string_for_id_parts(item_code_raw)
    whs_name = _sync_normalize_string_for_id_parts(whs_name_raw)
    if not item_code or not whs_name: return None
    sanitized_whs_name = re.sub(r'[^a-zA-Z0-9_-]', '_', whs_name)
    product_id = f"{item_code}_{sanitized_whs_name}"
    if len(product_id) > 512: product_id = product_id[:512]
    return product_id

def _sync_convert_snake_to_camel_case(data_snake: Dict[str, Any]) -> Dict[str, Any]:
    if not data_snake: return {}
    key_map = {
        "item_code": "itemCode", "item_name": "itemName", "description": "description",
        "sub_category": "subCategory", "item_group_name": "itemGroupName",
        "warehouse_name": "whsName", "branch_name": "branchName", "stock": "stock",
        "price": "price", "category": "category", "brand": "brand", "line": "line",
    }
    data_camel = {}
    for snake_key, value in data_snake.items():
        camel_key = key_map.get(snake_key)
        if camel_key: data_camel[camel_key] = value
        elif snake_key in key_map.values() and snake_key not in data_camel:
             data_camel[snake_key] = value
    return data_camel

# --- Main Sync Logic ---
def run_full_sync(app: Flask, damasco_product_data_snake_list: list) -> Tuple[int, int, int, int, int]:
    """
    Performs a full synchronization of products from provided Damasco data.
    Assumes damasco_product_data_snake_list contains snake_case dictionaries.
    Includes LLM summarization, embedding generation, and updates the local DB.

    Args:
        app: Flask application context
        damasco_product_data_snake_list: List of product dictionaries with snake_case keys,
                                         including 'description' (raw HTML).

    Returns:
        (processed_count, added_count, updated_count, skipped_no_change_count, failed_count)
    """
    sync_logger.info("====== Starting FULL Damasco Product Sync (with LLM Summarization) ======")
    start_time = time.time()
    processed_count = 0
    added_count = 0
    updated_count = 0
    skipped_no_change_count = 0 # <-- ADDED for better stats
    failed_count = 0
    summaries_generated_count = 0
    summaries_reused_count = 0
    summaries_failed_count = 0

    with app.app_context(): # Essential for current_app.config access in services
        if not damasco_product_data_snake_list:
            sync_logger.error("No product data provided for sync. Aborting sync.")
            return 0, 0, 0, 0, 0

        sync_logger.info(f"Received {len(damasco_product_data_snake_list)} products for sync.")

        # Create one session for the entire batch operation
        with db_utils.get_db_session() as session:
            if not session:
                sync_logger.error("Database session not available. Aborting sync.")
                return 0, 0, 0, 0, len(damasco_product_data_snake_list) # All failed

            try:
                for index, product_data_snake in enumerate(damasco_product_data_snake_list, start=1):
                    processed_count += 1
                    item_code_log = product_data_snake.get('item_code', 'N/A')
                    whs_name_log = product_data_snake.get('warehouse_name', 'N/A')
                    log_prefix_sync = f"Sync Entry [{index}/{len(damasco_product_data_snake_list)}] ({item_code_log} @ {whs_name_log}):"
                    sync_logger.info(f"{log_prefix_sync} Starting processing.")

                    # 1. Convert to camelCase for internal use
                    product_data_camel = _sync_convert_snake_to_camel_case(product_data_snake)
                    if not product_data_camel.get("itemCode") or not product_data_camel.get("whsName"):
                        sync_logger.error(f"{log_prefix_sync} Critical keys 'itemCode' or 'whsName' missing after conversion. Skipping.")
                        failed_count += 1
                        continue
                    
                    if "description" in product_data_snake and "description" not in product_data_camel: # Ensure description is carried over
                        product_data_camel["description"] = product_data_snake["description"]


                    # 2. Conditional LLM Summarization
                    llm_generated_summary: Optional[str] = None
                    raw_html_description_incoming = product_data_camel.get("description")
                    item_name_for_summary = product_data_camel.get("itemName")
                    
                    product_id_for_fetch = _sync_generate_product_id(
                        product_data_camel.get("itemCode"),
                        product_data_camel.get("whsName")
                    )
                    existing_entry: Optional[Product] = None
                    needs_new_summary = False

                    if product_id_for_fetch:
                        # Use the existing session for this read since we are in a batch
                        existing_entry = session.query(Product).filter_by(id=product_id_for_fetch).first()

                    if existing_entry:
                        normalized_incoming_html = _sync_normalize_string_for_id_parts(raw_html_description_incoming)
                        normalized_stored_html = _sync_normalize_string_for_id_parts(existing_entry.description)

                        if normalized_incoming_html != normalized_stored_html:
                            sync_logger.info(f"{log_prefix_sync} Raw HTML description changed. Attempting new summarization.")
                            needs_new_summary = True
                        elif not existing_entry.llm_summarized_description and raw_html_description_incoming:
                            sync_logger.info(f"{log_prefix_sync} Raw HTML unchanged, but no existing LLM summary. Attempting summarization.")
                            needs_new_summary = True
                        else:
                            sync_logger.info(f"{log_prefix_sync} Raw HTML unchanged and LLM summary exists. Re-using stored summary.")
                            llm_generated_summary = existing_entry.llm_summarized_description
                            if llm_generated_summary: summaries_reused_count += 1
                    else: # New product
                        if raw_html_description_incoming:
                            needs_new_summary = True
                    
                    if needs_new_summary and raw_html_description_incoming:
                        sync_logger.info(f"{log_prefix_sync} Calling LLM for summarization.")
                        llm_generated_summary = llm_processing_service.generate_llm_product_summary(
                            html_description=raw_html_description_incoming,
                            item_name=item_name_for_summary
                        )
                        if llm_generated_summary:
                            summaries_generated_count +=1
                            sync_logger.info(f"{log_prefix_sync} LLM summary generated.")
                        else:
                            summaries_failed_count +=1
                            sync_logger.warning(f"{log_prefix_sync} LLM summarization failed.")
                    elif not raw_html_description_incoming:
                        llm_generated_summary = None


                    # 3. Prepare text for embedding
                    try:
                        text_to_embed = Product.prepare_text_for_embedding(
                            damasco_product_data=product_data_camel,
                            llm_generated_summary=llm_generated_summary
                        )
                    except Exception as e:
                        sync_logger.error(f"{log_prefix_sync} Error preparing text for embedding: {e}", exc_info=True)
                        failed_count += 1
                        continue

                    if not text_to_embed:
                        sync_logger.warning(f"{log_prefix_sync} Empty text_to_embed. Skipping.")
                        failed_count += 1
                        continue

                    # 4. Generate embedding
                    embedding_vector = embedding_utils.get_embedding(text_to_embed, model=Config.OPENAI_EMBEDDING_MODEL)
                    if not embedding_vector:
                        sync_logger.error(f"{log_prefix_sync} Failed to generate embedding. Skipping.")
                        failed_count += 1
                        continue

                    # 5. Upsert to DB
                    success, op_message = product_service.add_or_update_product_in_db(
                        session,
                        product_data_camel, # Pass camelCase data
                        embedding_vector,
                        text_to_embed,
                        llm_summarized_description=llm_generated_summary
                    )

                    if success:
                        if op_message == 'added': added_count += 1
                        elif op_message == 'updated': updated_count += 1
                        elif op_message == 'skipped_no_change': skipped_no_change_count +=1
                        sync_logger.info(f"{log_prefix_sync} DB operation: {op_message}")
                    else:
                        sync_logger.error(f"{log_prefix_sync} DB operation failed. Reason: {op_message}")
                        failed_count += 1

                    # Commit batching (your original logic)
                    if COMMIT_BATCH_SIZE and processed_count % COMMIT_BATCH_SIZE == 0:
                        try:
                            sync_logger.info(f"Committing batch after {processed_count} products...")
                            session.commit()
                        except Exception as commit_error:
                            sync_logger.exception(f"Commit error during batch processing. Rolling back current batch. Error: {commit_error}")
                            session.rollback()
                            # Depending on severity, you might want to break or continue with next batch after rollback
                            # For now, let's assume we try to continue with subsequent items after a batch rollback
                
                # Final commit for any remaining items
                sync_logger.info("Committing final transaction at end of sync...")
                session.commit()

            except Exception as e:
                sync_logger.exception(f"Unexpected error during sync process. Rolling back. Error: {e}")
                session.rollback() # Ensure rollback on any major loop error
                # Update failed_count to reflect all items not successfully added/updated/skipped
                failed_count = processed_count - (added_count + updated_count + skipped_no_change_count)


    duration = time.time() - start_time
    sync_logger.info("====== FULL Damasco Product Sync Finished ======")
    sync_logger.info(f"Duration: {duration:.2f} seconds")
    sync_logger.info(f"Total Products Received in Payload: {len(damasco_product_data_snake_list)}")
    sync_logger.info(f"Total Products Processed: {processed_count}")
    sync_logger.info(f"Products Added: {added_count}")
    sync_logger.info(f"Products Updated: {updated_count}")
    sync_logger.info(f"Products Skipped (No Change): {skipped_no_change_count}")
    sync_logger.info(f"LLM Summaries Newly Generated: {summaries_generated_count}")
    sync_logger.info(f"LLM Summaries Re-used: {summaries_reused_count}")
    sync_logger.info(f"LLM Summaries Failed/Skipped: {summaries_failed_count + (len(damasco_product_data_snake_list) - processed_count) + failed_count - (summaries_generated_count + summaries_reused_count) }") # More complex to track perfectly if items fail before summary stage
    sync_logger.info(f"Total Products Failed/Skipped in Processing: {failed_count}")
    sync_logger.info("================================================")

    return processed_count, added_count, updated_count, skipped_no_change_count, failed_count


def run_incremental_sync(app: Flask): # Kept as is
    """
    Placeholder for future incremental sync logic.
    """
    sync_logger.info("====== Starting INCREMENTAL Damasco Product Sync ======")
    sync_logger.warning("Incremental sync logic not implemented. Skipping.")
    sync_logger.info("====== INCREMENTAL Damasco Product Sync Finished (Skipped) ======")
    return 0, 0, 0, 0, 0 # Added skipped_no_change and failed to return tuple