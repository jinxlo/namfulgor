import logging
# Import List, Optional, Dict for type hinting
from typing import List, Optional, Dict, Any
from sqlalchemy import text, func # For raw SQL, functions if needed
from sqlalchemy.orm import Session, joinedload # Use joinedload for eager loading if needed
from sqlalchemy.exc import SQLAlchemyError

# Use relative imports
from ..models.product import Product
from ..utils import db_utils, embedding_utils # Import DB context and embedding generator
from ..config import Config # Import Config for search limit, etc.

logger = logging.getLogger(__name__)


# MODIFIED return type hint
def search_local_products(query_text: str, limit: int = Config.PRODUCT_SEARCH_LIMIT, filter_stock: bool = True) -> Optional[List[Dict]]:
    """
    Searches for products in the local PostgreSQL database.
    Prioritizes vector similarity search using embeddings.
    Can optionally filter for in-stock items.

    Args:
        query_text: The user's search query or description.
        limit: Maximum number of products to return.
        filter_stock: If True, only return products with stock_status = 'instock'.

    Returns:
        A list of dictionaries representing matching products, or None if an error occurs
        during embedding generation or database query. Returns an empty list
        if no matches are found.
    """
    if not query_text or not isinstance(query_text, str):
        logger.warning("Search query is empty or invalid.")
        return [] # Return empty list for invalid query

    logger.info(f"Initiating local product search for query: '{query_text[:100]}...' (Limit: {limit}, FilterStock: {filter_stock})")

    # 1. Generate embedding for the search query
    logger.debug(f"Attempting to generate embedding for query: '{query_text}'")
    query_embedding = embedding_utils.get_embedding(query_text)
    if not query_embedding:
        logger.error("Failed to generate embedding for search query. Cannot perform vector search.")
        return None

    logger.debug("Embedding generated successfully.")

    # 2. Perform database query using the embedding
    with db_utils.get_db_session() as session:
        if not session:
            logger.error("Database session not available for product search.")
            return None # Indicate DB error

        try:
            logger.debug("Attempting database query for vector search...")

            # Base query construction using pgvector's distance operator
            query = session.query(Product)

            # Add stock filter if requested
            if filter_stock:
                query = query.filter(Product.stock_status == 'instock')
                logger.debug("Filtering search results for 'instock' status.")

            # --- Vector Search using pgvector ---
            query = query.order_by(Product.embedding.cosine_distance(query_embedding))

            # Apply the limit
            query = query.limit(limit)

            # Execute the query
            results = query.all() # Gets a list of Product ORM objects

            logger.debug(f"Database query executed. Found {len(results)} results.")

            # --- MODIFIED: Convert ORM objects to dictionaries ---
            result_dicts = [product.to_search_result_dict() for product in results]
            # --- END MODIFICATION ---

            num_results = len(results) # Keep using len(results) for logging count
            if num_results > 0:
                 logger.info(f"Found {num_results} product(s) via vector search matching query: '{query_text[:50]}...'")
            else:
                 logger.info(f"No products found via vector search for query: '{query_text[:50]}...'")

            # --- MODIFIED: Return the list of dictionaries ---
            return result_dicts

        except SQLAlchemyError as e:
            logger.exception(f"Database error during product search query execution: {e}")
            return None
        except Exception as e:
             logger.exception(f"Unexpected error during product search DB interaction: {e}")
             return None


def add_or_update_product_in_db(session: Session, product_data: Dict[str, Any], embedding: List[float]):
    """
    Adds a new product or updates an existing one in the local database *within* an existing transaction.
    Called by the sync_service.

    Args:
        session: The active SQLAlchemy session object.
        product_data: Dictionary containing product details fetched from WooCommerce API.
        embedding: The pre-computed embedding vector for this product.

    Returns:
        Tuple (bool, str): (True, 'added'/'updated') on success, (False, 'error message') on failure.
    """
    # (No changes needed in this function)
    if not product_data or not isinstance(product_data, dict):
        return False, "Missing product data."
    if not embedding or not isinstance(embedding, list):
        return False, "Missing or invalid embedding."
    if len(embedding) != Config.EMBEDDING_DIMENSION:
         return False, f"Embedding dimension mismatch (Expected {Config.EMBEDDING_DIMENSION}, Got {len(embedding)})."


    wc_id = product_data.get('id')
    if not wc_id:
        return False, "Product data missing 'id' (WooCommerce Product ID)."

    sku = product_data.get('sku')
    name = product_data.get('name')
    if not name:
        logger.warning(f"Product data for WC ID {wc_id} missing 'name'. Skipping update/add.")
        return False, "Product data missing 'name'."

    try:
        existing_product = session.query(Product).filter_by(wc_product_id=wc_id).with_for_update().first()

        search_text = Product.prepare_searchable_text(product_data)
        categories_str = Product.format_categories_tags(product_data.get('categories'))
        tags_str = Product.format_categories_tags(product_data.get('tags'))
        price_val = product_data.get('price')
        stock_quantity_val = product_data.get('stock_quantity')

        operation_type = 'updated' if existing_product else 'added'

        if existing_product:
            existing_product.sku = sku
            existing_product.name = name
            existing_product.description = Product._simple_strip_html(product_data.get('description', ''))
            existing_product.short_description = Product._simple_strip_html(product_data.get('short_description', ''))
            existing_product.searchable_text = search_text
            existing_product.price = float(price_val) if price_val is not None and price_val != '' else None
            existing_product.stock_status = product_data.get('stock_status')
            existing_product.stock_quantity = int(stock_quantity_val) if stock_quantity_val is not None else None
            existing_product.manage_stock = product_data.get('manage_stock', False)
            existing_product.permalink = product_data.get('permalink')
            existing_product.categories = categories_str
            existing_product.tags = tags_str
            existing_product.embedding = embedding
            logger.debug(f"Updating product WC ID: {wc_id}, SKU: {sku}")
        else:
            new_product = Product(
                wc_product_id=wc_id,
                sku=sku,
                name=name,
                description=Product._simple_strip_html(product_data.get('description', '')),
                short_description=Product._simple_strip_html(product_data.get('short_description', '')),
                searchable_text=search_text,
                price=float(price_val) if price_val is not None and price_val != '' else None,
                stock_status=product_data.get('stock_status'),
                stock_quantity=int(stock_quantity_val) if stock_quantity_val is not None else None,
                manage_stock=product_data.get('manage_stock', False),
                permalink=product_data.get('permalink'),
                categories=categories_str,
                tags=tags_str,
                embedding=embedding
            )
            session.add(new_product)
            logger.debug(f"Adding new product WC ID: {wc_id}, SKU: {sku}")

        session.flush()
        return True, operation_type

    except SQLAlchemyError as e:
        logger.error(f"Database error adding/updating product WC ID {wc_id} (SKU: {sku}): {e}")
        return False, f"Database error: {e}"
    except Exception as e:
        logger.exception(f"Unexpected error processing product WC ID {wc_id} (SKU: {sku}) for DB update: {e}")
        return False, f"Unexpected processing error: {e}"