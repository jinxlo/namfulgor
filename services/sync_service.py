import logging
import time
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from flask import Flask # Required for app context

# Import necessary services and utilities
# Use relative imports for sibling packages
from . import woocommerce_service, product_service
from ..utils import db_utils, embedding_utils
from ..models.product import Product # Import model for type hinting and direct use

# Use the specific 'sync' logger configured in __init__.py
sync_logger = logging.getLogger('sync')
# Also use the general app logger for context if needed
logger = logging.getLogger(__name__)

# --- Constants ---
# How many products to process before committing the DB transaction during a sync.
# Smaller batches mean less memory usage and faster feedback on errors per batch,
# but more commit overhead. Larger batches are faster overall if no errors occur.
# Set to 0 or None to commit only once at the very end (atomic sync).
COMMIT_BATCH_SIZE = 100 # Example: Commit roughly every 2 API pages if per_page is 50

# --- Main Sync Logic ---

def run_full_sync(app: Flask) -> Tuple[int, int, int, int]:
    """
    Performs a full synchronization of products from WooCommerce to the local DB.
    Fetches all published products, generates embeddings, and updates the DB.

    Args:
        app: The Flask application instance (needed for context).

    Returns:
        A tuple containing: (processed_count, added_count, updated_count, failed_count)
    """
    sync_logger.info("====== Starting FULL WooCommerce Product Sync ======")
    start_time = time.time()
    processed_count = 0
    added_count = 0
    updated_count = 0
    failed_count = 0
    batch_num = 0

    # Ensure execution within Flask app context to access config, extensions etc.
    with app.app_context():
        # Get product batches from WooCommerce using the generator
        # Pass the configured per_page size (using the constant from woocommerce_service)
        product_batches_generator = woocommerce_service.get_all_products_for_sync(
            per_page=woocommerce_service.PER_PAGE_DEFAULT # Use the constant
        )

        if product_batches_generator is None:
            sync_logger.error("Failed to initiate product fetching from WooCommerce. Aborting sync.")
            return 0, 0, 0, 0

        # Process products batch by batch
        with db_utils.get_db_session() as session:
            if not session:
                sync_logger.error("Database session not available. Aborting sync.")
                return 0, 0, 0, 0

            try:
                for product_batch in product_batches_generator:
                    batch_num += 1
                    sync_logger.info(f"--- Processing Sync Batch #{batch_num} ({len(product_batch)} products) ---")

                    if not product_batch: # Should not happen with current generator logic, but check
                        sync_logger.warning(f"Received empty product batch #{batch_num}. Skipping.")
                        continue

                    for product_data in product_batch:
                        processed_count += 1
                        wc_id = product_data.get('id', 'N/A')
                        sku = product_data.get('sku', 'N/A')

                        # 1. Prepare text for embedding
                        try:
                            # Use the static method from Product model for consistency
                            text_to_embed = Product.prepare_searchable_text(product_data)
                        except Exception as e:
                            sync_logger.error(f"Error preparing searchable text for WC ID {wc_id} (SKU: {sku}): {e}. Skipping.")
                            failed_count += 1
                            continue

                        if not text_to_embed:
                             sync_logger.warning(f"Generated empty searchable text for WC ID {wc_id} (SKU: {sku}). Skipping embedding.")
                             failed_count += 1
                             continue


                        # 2. Generate embedding (with retries handled internally)
                        embedding = embedding_utils.get_embedding(text_to_embed)
                        if not embedding:
                            sync_logger.error(f"Failed to generate embedding for WC ID {wc_id} (SKU: {sku}). Skipping DB update.")
                            failed_count += 1
                            continue # Skip DB update if embedding fails

                        # 3. Add or Update in DB (within the session)
                        success, operation_or_error = product_service.add_or_update_product_in_db(session, product_data, embedding)

                        if success:
                            if operation_or_error == 'added':
                                added_count += 1
                            elif operation_or_error == 'updated':
                                updated_count += 1
                        else:
                            # Error logged within add_or_update_product_in_db
                            sync_logger.error(f"Failed to add/update product WC ID {wc_id} (SKU: {sku}) in DB. Reason: {operation_or_error}")
                            failed_count += 1
                            # Continue processing other products in the batch

                    # --- Batch Committing Logic ---
                    # Check if COMMIT_BATCH_SIZE is enabled and if enough products have been processed
                    # Corrected condition using the imported constant
                    if COMMIT_BATCH_SIZE and COMMIT_BATCH_SIZE > 0:
                        # Calculate how many products constitute roughly COMMIT_BATCH_SIZE / PER_PAGE_DEFAULT batches
                        # This is an approximation if PER_PAGE_DEFAULT is not a divisor of COMMIT_BATCH_SIZE
                        approx_batches_to_commit = max(1, COMMIT_BATCH_SIZE // woocommerce_service.PER_PAGE_DEFAULT)
                        if batch_num % approx_batches_to_commit == 0:
                             try:
                                 sync_logger.info(f"Committing transaction after processing ~{processed_count} products (Batch #{batch_num})...")
                                 session.commit()
                                 sync_logger.info("Transaction committed.")
                                 # Start a new transaction implicitly on next operation within the session scope
                             except Exception as commit_error:
                                  sync_logger.exception(f"Error committing sync batch ending around #{batch_num}. Rolling back current changes in transaction. Error: {commit_error}")
                                  session.rollback()
                                  sync_logger.error("Aborting sync due to commit error.")
                                  # Set counts to reflect committed state (which is likely the state before this failed batch started)
                                  # This is hard to track perfectly without more state, maybe return current successful counts?
                                  # For simplicity, we just break here. Data added/updated in this failed transaction is lost.
                                  break # Stop the sync process

                # --- Final Commit ---
                # Commit any remaining changes after the loop finishes (if not committing in batches, or for the last partial batch)
                # The context manager (`with get_db_session()`) handles the final commit automatically if no exceptions occurred
                # OR if batch commits were disabled (COMMIT_BATCH_SIZE=0).
                # We only need an explicit final commit message here if batching was disabled.
                if not (COMMIT_BATCH_SIZE and COMMIT_BATCH_SIZE > 0):
                    sync_logger.info("Committing final transaction at end of sync...")
                # Commit is handled by context manager exit if no errors bubbled up

            except Exception as e:
                # Catch errors during the generator iteration or main loop logic
                sync_logger.exception(f"An unexpected error occurred during the sync process (outside product loop). Rolling back. Error: {e}")
                # Rollback handled by context manager
                failed_count = processed_count - added_count - updated_count # Rough estimate of failures

    # --- Sync Summary ---
    end_time = time.time()
    duration = end_time - start_time
    sync_logger.info("====== FULL WooCommerce Product Sync Finished ======")
    sync_logger.info(f"Duration: {duration:.2f} seconds")
    sync_logger.info(f"Total Products Processed (Attempted): {processed_count}")
    sync_logger.info(f"Products Added: {added_count}")
    sync_logger.info(f"Products Updated: {updated_count}")
    sync_logger.info(f"Products Failed/Skipped: {failed_count}")
    sync_logger.info("================================================")

    return processed_count, added_count, updated_count, failed_count


def run_incremental_sync(app: Flask):
    """
    Placeholder for incremental synchronization logic.
    """
    sync_logger.info("====== Starting INCREMENTAL WooCommerce Product Sync ======")
    sync_logger.warning("Incremental sync logic is not yet implemented. Skipping.")
    sync_logger.info("====== INCREMENTAL WooCommerce Product Sync Finished (Skipped) ======")
    return 0, 0, 0, 0