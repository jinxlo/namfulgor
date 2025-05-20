import logging
import time
from typing import Optional, Tuple
from flask import Flask

from . import product_service
from ..utils import db_utils, embedding_utils
from ..models.product import Product

sync_logger = logging.getLogger('sync')
logger = logging.getLogger(__name__)

# --- Constants ---
COMMIT_BATCH_SIZE = 100  # Adjust as needed

# --- Main Sync Logic ---

def run_full_sync(app: Flask, damasco_product_data: list) -> Tuple[int, int, int, int]:
    """
    Performs a full synchronization of products from provided Damasco data.
    Generates embeddings and updates the local DB.

    Args:
        app: Flask application context
        damasco_product_data: List of cleaned product dictionaries (from fetcher EC2)

    Returns:
        (processed_count, added_count, updated_count, failed_count)
    """
    sync_logger.info("====== Starting FULL Damasco Product Sync ======")
    start_time = time.time()
    processed_count = 0
    added_count = 0
    updated_count = 0
    failed_count = 0

    with app.app_context():
        if not damasco_product_data:
            sync_logger.error("No product data received from fetcher. Aborting sync.")
            return 0, 0, 0, 0

        sync_logger.info(f"Received {len(damasco_product_data)} products from fetcher.")

        with db_utils.get_db_session() as session:
            if not session:
                sync_logger.error("Database session not available. Aborting sync.")
                return 0, 0, 0, 0

            try:
                for index, product_data in enumerate(damasco_product_data, start=1):
                    processed_count += 1
                    item_code = product_data.get('item_code', 'N/A')

                    try:
                        text_to_embed = Product.prepare_searchable_text(product_data)
                    except Exception as e:
                        sync_logger.error(f"Error preparing searchable text for Item Code {item_code}: {e}")
                        failed_count += 1
                        continue

                    if not text_to_embed:
                        sync_logger.warning(f"Empty searchable text for Item Code {item_code}. Skipping.")
                        failed_count += 1
                        continue

                    embedding = embedding_utils.get_embedding(text_to_embed)
                    if not embedding:
                        sync_logger.error(f"Failed to generate embedding for Item Code {item_code}. Skipping DB update.")
                        failed_count += 1
                        continue

                    success, operation_or_error = product_service.add_or_update_product_in_db(session, product_data, embedding)

                    if success:
                        if operation_or_error == 'added':
                            added_count += 1
                        elif operation_or_error == 'updated':
                            updated_count += 1
                    else:
                        sync_logger.error(f"Failed to add/update Item Code {item_code} in DB. Reason: {operation_or_error}")
                        failed_count += 1

                    # Commit batching
                    if COMMIT_BATCH_SIZE and processed_count % COMMIT_BATCH_SIZE == 0:
                        try:
                            sync_logger.info(f"Committing after {processed_count} products...")
                            session.commit()
                        except Exception as commit_error:
                            sync_logger.exception(f"Commit error after {processed_count} products. Rolling back. Error: {commit_error}")
                            session.rollback()
                            break  # Stop sync on critical DB error

                # Final commit
                sync_logger.info("Committing final transaction at end of sync...")
                session.commit()

            except Exception as e:
                sync_logger.exception(f"Unexpected error during sync process. Rolling back. Error: {e}")
                failed_count = processed_count - added_count - updated_count

    duration = time.time() - start_time
    sync_logger.info("====== FULL Damasco Product Sync Finished ======")
    sync_logger.info(f"Duration: {duration:.2f} seconds")
    sync_logger.info(f"Total Products Processed: {processed_count}")
    sync_logger.info(f"Products Added: {added_count}")
    sync_logger.info(f"Products Updated: {updated_count}")
    sync_logger.info(f"Products Failed/Skipped: {failed_count}")
    sync_logger.info("================================================")

    return processed_count, added_count, updated_count, failed_count

def run_incremental_sync(app: Flask):
    """
    Placeholder for future incremental sync logic.
    """
    sync_logger.info("====== Starting INCREMENTAL Damasco Product Sync ======")
    sync_logger.warning("Incremental sync logic not implemented. Skipping.")
    sync_logger.info("====== INCREMENTAL Damasco Product Sync Finished (Skipped) ======")
    return 0, 0, 0, 0
