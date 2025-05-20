# NAMWOO/services/product_service.py

import logging
import re
from typing import List, Dict, Any, Optional, Tuple

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..models.product import Product # Your updated Product model
from ..utils import db_utils, embedding_utils # embedding_utils is used by search, not directly here for add/update
from ..config import Config

logger = logging.getLogger(__name__)

# --- Semantic Helpers (Keep as is, used by search_local_products) ---
_ACCESSORY_PAT = re.compile(
    r"(base para|soporte|mount|stand|bracket|control(?: remoto)?|adaptador|"
    r"compresor|enfriador|deshumidificador)",
    flags=re.I,
)
_MAIN_TYPE_PAT = re.compile(
    r"\b(tv|televisor|pantalla|nevera|refrigerador|aire acondicionado|"
    r"lavadora|secadora|freidora|microondas|horno)\b",
    flags=re.I,
)

def _is_accessory(name: str) -> bool:
    return bool(_ACCESSORY_PAT.search(name))

def _extract_main_type(text: str) -> str:
    m = _MAIN_TYPE_PAT.search(text)
    return m.group(0).lower() if m else ""

# --- Search Products (Keep as is for now, review later based on new schema impact) ---
def search_local_products(
    query_text: str,
    limit: int = 30,
    filter_stock: bool = True,
    min_score: float = 0.10,
) -> Optional[List[Dict[str, Any]]]:
    if not query_text or not isinstance(query_text, str):
        logger.warning("Search query is empty or invalid.")
        return []

    logger.info(
        "Vector search initiated: '%s…' (limit=%d, stock=%s, min_score=%.2f)",
        query_text[:80],
        limit,
        filter_stock,
        min_score,
    )

    # embedding_utils.get_embedding is called here for the query text
    query_emb = embedding_utils.get_embedding(query_text, model=Config.OPENAI_EMBEDDING_MODEL)
    if not query_emb:
        logger.error("Query embedding generation failed – aborting search.")
        return None # Return None to indicate a more significant failure

    with db_utils.get_db_session() as session:
        if not session:
            logger.error("DB session unavailable for search.")
            return None

        try:
            q = session.query(
                Product,
                (1 - Product.embedding.cosine_distance(query_emb)).label("similarity"),
            )

            if filter_stock:
                q = q.filter(Product.stock > 0) # This will filter by stock at specific locations

            q = q.filter(
                (1 - Product.embedding.cosine_distance(query_emb)) >= min_score
            )
            # Order by similarity (cosine_distance is 0 for identical, 1 for opposite, so order by ascending distance)
            q = q.order_by(Product.embedding.cosine_distance(query_emb)).limit(limit)

            rows: List[Tuple[Product, float]] = q.all()

            results: List[Dict[str, Any]] = []
            for prod_location_entry, sim_score in rows:
                # prod_location_entry is now an instance of our revised Product model,
                # representing a product at a specific location.
                item_dict = prod_location_entry.to_dict() # Use the to_dict() method from the model
                item_dict.update({
                    "similarity": round(float(sim_score), 4),
                    "is_accessory": _is_accessory(prod_location_entry.item_name),
                    "main_type": _extract_main_type(prod_location_entry.item_name),
                    # Add LLM formatted string for convenience if needed by frontend/LLM directly
                    "llm_formatted_description": prod_location_entry.format_for_llm()
                })
                results.append(item_dict)

            logger.info("Vector search returned %d product location entries.", len(results))
            return results

        except SQLAlchemyError as db_exc:
            logger.exception("Database error during product search: %s", db_exc)
            return None
        except Exception as exc:
            logger.exception("Unexpected error during product search: %s", exc)
            return None

# --- Insert or Update Product-Location Entry ---
def add_or_update_product_in_db(
    session: Session,
    damasco_product_data: Dict[str, Any], # This is the raw data from Damasco for ONE warehouse line item
    embedding_vector: List[float],
    text_used_for_embedding: str
) -> Tuple[bool, str]:
    """
    Adds or updates a product-location entry in the 'products' table.
    Uses a composite ID (item_code + warehouse_name) for uniqueness.
    """
    if not damasco_product_data or not isinstance(damasco_product_data, dict):
        return False, "Missing Damasco product data."
    if not embedding_vector or not isinstance(embedding_vector, list):
        return False, "Missing or invalid embedding vector."
    if len(embedding_vector) != Config.EMBEDDING_DIMENSION:
        return False, (f"Embedding dimension mismatch (expected {Config.EMBEDDING_DIMENSION}, "
                       f"got {len(embedding_vector)}).")
    if not text_used_for_embedding or not isinstance(text_used_for_embedding, str):
        return False, "Missing text_used_for_embedding."

    # Get key identifiers from Damasco data
    item_code = damasco_product_data.get("itemCode") # Case sensitive from Damasco JSON
    whs_name = damasco_product_data.get("whsName")   # Case sensitive from Damasco JSON

    if not item_code:
        return False, "Damasco data missing 'itemCode'."
    if not whs_name:
        return False, f"Damasco data for item '{item_code}' missing 'whsName'."

    # Create the composite primary key for our 'products' table
    # Sanitize whs_name for use in an ID (replace spaces, slashes, etc.)
    sanitized_whs_name = re.sub(r'[^a-zA-Z0-9_-]', '_', whs_name) # Keep alphanumeric, underscore, hyphen
    product_location_id = f"{item_code}_{sanitized_whs_name}"
    if len(product_location_id) > 512: # Max length of Product.id
        product_location_id = product_location_id[:512]
        logger.warning(f"Generated product_location_id for {item_code} was truncated to 512 chars.")


    log_prefix = f"ProductLocation(id='{product_location_id}'):"

    try:
        # Query for existing entry using the new composite ID
        entry = session.query(Product).filter_by(id=product_location_id).first()
        # Using .with_for_update() if high concurrency and you want to lock the row:
        # entry = session.query(Product).filter_by(id=product_location_id).with_for_update().first()


        operation_type = "updated"
        if not entry:
            entry = Product(id=product_location_id, item_code=item_code) # Set id and item_code on creation
            operation_type = "added"
            session.add(entry)
            logger.info(f"{log_prefix} New entry, will be added.")
        else:
            logger.info(f"{log_prefix} Existing entry, will be updated.")

        # Populate/update fields from damasco_product_data, mapping to Product model attributes
        entry.item_name = damasco_product_data.get("itemName", entry.item_name) # Keep old if new is None
        entry.category = damasco_product_data.get("category", entry.category)
        entry.sub_category = damasco_product_data.get("subCategory", entry.sub_category)
        entry.brand = damasco_product_data.get("brand", entry.brand)
        entry.line = damasco_product_data.get("line", entry.line)
        entry.item_group_name = damasco_product_data.get("itemGroupName", entry.item_group_name)
        
        entry.warehouse_name = whs_name # From Damasco 'whsName'
        entry.branch_name = damasco_product_data.get("branchName", entry.branch_name) # From Damasco 'branchName'
        
        entry.price = float(damasco_product_data.get("price", entry.price if entry.price is not None else 0.0))
        entry.stock = int(damasco_product_data.get("stock", entry.stock if entry.stock is not None else 0))
        
        entry.searchable_text_content = text_used_for_embedding
        entry.embedding = embedding_vector # Store the pgvector embedding
        
        # Store the original Damasco data for this entry (good for auditing/debugging)
        entry.source_data_json = damasco_product_data 
        
        # last_synced_at is handled by server_default and onupdate in the model/DB

        # session.flush() # Not strictly necessary here, commit in route will handle it.
                        # Useful if you need an auto-generated ID immediately (not the case here).
        
        logger.debug(f"{log_prefix} Data prepared for {operation_type}.")
        return True, operation_type

    except SQLAlchemyError as db_exc:
        logger.error(f"{log_prefix} DB error during add/update: {db_exc}", exc_info=True)
        # session.rollback() # Consider if rollback should happen here or at a higher level (route)
        return False, f"DB error: {str(db_exc)}"
    except Exception as exc:
        logger.exception(f"{log_prefix} Unexpected error processing: {exc}")
        # session.rollback()
        return False, f"Unexpected error: {str(exc)}"

# --- Get Live Product Details by SKU (item_code) ---
def get_live_product_details_by_sku(item_code_query: str) -> Optional[List[Dict[str, Any]]]:
    """
    Retrieves all locations/stock details for a given item_code from the local DB.
    Returns a list of dictionaries, as one item_code can be in multiple locations.
    """
    if not item_code_query:
        logger.error("get_live_product_details_by_sku: Missing item_code_query argument.")
        return None

    with db_utils.get_db_session() as session:
        if not session:
            logger.error("DB session unavailable for get_live_product_details_by_sku.")
            return None
        try:
            # Query for all entries matching the item_code
            product_entries = session.query(Product).filter_by(item_code=item_code_query).all()
            
            if not product_entries:
                logger.info("No product entries found with item_code: %s", item_code_query)
                return [] # Return empty list if not found

            # Convert each entry to its dictionary representation
            results = [entry.to_dict() for entry in product_entries]
            logger.info(f"Found {len(results)} locations for item_code: {item_code_query}")
            return results

        except SQLAlchemyError as db_exc:
            logger.exception("DB error fetching product by item_code: %s", db_exc)
            return None
        except Exception as exc:
            logger.exception("Unexpected error fetching product by item_code: %s", exc)
            return None

# --- Get Live Product Details by wc_product_id ---
# This function seems to query by a field 'wc_product_id' which is NOT in your
# current Product model or schema.sql. If this is a legacy function or if
# 'wc_product_id' should be another field (e.g., our composite 'id'), it needs adjustment.
# For now, I will assume it's not directly relevant to the Damasco sync with the current model.
# If it IS relevant, we need to add 'wc_product_id' to the Product model and schema.
def get_live_product_details_by_id(composite_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves the product details from the local DB by its composite ID
    (e.g., "ITEMCODE_WAREHOUSENAME").
    """
    if not composite_id:
        logger.error("get_live_product_details_by_id: Missing composite_id argument.")
        return None

    with db_utils.get_db_session() as session:
        if not session:
            logger.error("DB session unavailable for get_live_product_details_by_id.")
            return None
        try:
            product_entry = session.query(Product).filter_by(id=composite_id).first()
            if not product_entry:
                logger.info("No product entry found with composite_id: %s", composite_id)
                return None

            return product_entry.to_dict()

        except SQLAlchemyError as db_exc:
            logger.exception("DB error fetching product by composite_id: %s", db_exc)
            return None
        except Exception as exc:
            logger.exception("Unexpected error fetching product by composite_id: %s", exc)
            return None