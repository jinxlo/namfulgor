# NAMWOO/services/product_service.py

import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation as InvalidDecimalOperation # For price handling

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..models.product import Product
from ..utils import db_utils, embedding_utils
from ..config import Config

logger = logging.getLogger(__name__)

# --- Semantic Helpers (Keep as is) ---
# ... (your existing _ACCESSORY_PAT, _MAIN_TYPE_PAT, _is_accessory, _extract_main_type) ...
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
    if not name: return False
    return bool(_ACCESSORY_PAT.search(name))

def _extract_main_type(text: str) -> str:
    if not text: return ""
    m = _MAIN_TYPE_PAT.search(text)
    return m.group(0).lower() if m else ""


# --- Search Products (Keep as is) ---
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

    query_emb = embedding_utils.get_embedding(query_text, model=Config.OPENAI_EMBEDDING_MODEL)
    if not query_emb:
        logger.error("Query embedding generation failed – aborting search.")
        return None

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
                q = q.filter(Product.stock > 0)

            q = q.filter(
                (1 - Product.embedding.cosine_distance(query_emb)) >= min_score
            )
            q = q.order_by(Product.embedding.cosine_distance(query_emb)).limit(limit)

            rows: List[Tuple[Product, float]] = q.all()

            results: List[Dict[str, Any]] = []
            for prod_location_entry, sim_score in rows:
                item_dict = prod_location_entry.to_dict()
                item_dict.update({
                    "similarity": round(float(sim_score), 4),
                    "is_accessory": _is_accessory(prod_location_entry.item_name or ""),
                    "main_type": _extract_main_type(prod_location_entry.item_name or ""),
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

# Helper function to normalize strings: strip whitespace and convert empty strings to None
def _normalize_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None # Converts "" to None, otherwise returns stripped string

# --- Insert or Update Product-Location Entry (Delta logic implemented) ---
def add_or_update_product_in_db(
    session: Session,
    damasco_product_data: Dict[str, Any],
    embedding_vector: List[float],
    text_used_for_embedding: str
) -> Tuple[bool, str]:
    if not damasco_product_data or not isinstance(damasco_product_data, dict):
        return False, "Missing Damasco product data."
    if not embedding_vector or not isinstance(embedding_vector, list):
        return False, "Missing or invalid embedding vector."
    if len(embedding_vector) != Config.EMBEDDING_DIMENSION:
        return False, (f"Embedding dimension mismatch (expected {Config.EMBEDDING_DIMENSION}, "
                       f"got {len(embedding_vector)}).")
    if not text_used_for_embedding or not isinstance(text_used_for_embedding, str): # Already a processed string
        return False, "Missing text_used_for_embedding."

    # Get key identifiers from Damasco data (camelCase from input)
    item_code_raw = damasco_product_data.get("itemCode")
    whs_name_raw = damasco_product_data.get("whsName")

    item_code = _normalize_string(item_code_raw) # Stripped or None
    whs_name_for_storage_and_id = _normalize_string(whs_name_raw) # Stripped or None

    if not item_code:
        return False, "Damasco data missing or empty 'itemCode'."
    if not whs_name_for_storage_and_id:
        return False, f"Damasco data for item '{item_code or 'UNKNOWN'}' missing or empty 'whsName'."

    # Create the composite primary key
    sanitized_whs_name_for_id_part = re.sub(r'[^a-zA-Z0-9_-]', '_', whs_name_for_storage_and_id)
    product_location_id = f"{item_code}_{sanitized_whs_name_for_id_part}"
    if len(product_location_id) > 512:
        product_location_id = product_location_id[:512]
        logger.warning(f"Generated product_location_id for {item_code} was truncated: {product_location_id}")

    log_prefix = f"ProductLocation(id='{product_location_id}'):"

    # Prepare new values with normalization for comparison and update
    price_from_damasco = damasco_product_data.get("price")
    normalized_price_for_db = None
    if price_from_damasco is not None:
        try:
            # Convert to Decimal, standardizing to 2 decimal places for comparison
            normalized_price_for_db = Decimal(str(price_from_damasco)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except InvalidDecimalOperation:
            logger.warning(f"{log_prefix} Invalid price value '{price_from_damasco}', treating as None.")
            normalized_price_for_db = None # Or handle as an error / default value if preferred

    stock_from_damasco = damasco_product_data.get("stock")
    normalized_stock_for_db = 0 # Default stock to 0
    if stock_from_damasco is not None:
        try:
            normalized_stock_for_db = int(stock_from_damasco)
        except (ValueError, TypeError):
            logger.warning(f"{log_prefix} Invalid stock value '{stock_from_damasco}', defaulting to 0.")
            normalized_stock_for_db = 0

    # This dictionary holds values intended for DB storage and for comparison logic
    new_values_for_db = {
        "item_name": _normalize_string(damasco_product_data.get("itemName")),
        "category": _normalize_string(damasco_product_data.get("category")),
        "sub_category": _normalize_string(damasco_product_data.get("subCategory")),
        "brand": _normalize_string(damasco_product_data.get("brand")),
        "line": _normalize_string(damasco_product_data.get("line")),
        "item_group_name": _normalize_string(damasco_product_data.get("itemGroupName")),
        "warehouse_name": whs_name_for_storage_and_id, # Already normalized
        "branch_name": _normalize_string(damasco_product_data.get("branchName")),
        "price": normalized_price_for_db, # Decimal or None
        "stock": normalized_stock_for_db, # int
        "searchable_text_content": text_used_for_embedding.strip(), # Ensure text is stripped
    }

    try:
        entry = session.query(Product).filter_by(id=product_location_id).first()

        if entry:
            # Compare existing entry with new normalized values
            is_unchanged = True
            changed_fields_details = [] # For logging which specific field changed

            fields_to_compare = [
                "item_name", "category", "sub_category", "brand", "line",
                "item_group_name", "warehouse_name", "branch_name",
                "price", "stock", "searchable_text_content"
            ]

            for field_key in fields_to_compare:
                db_value = getattr(entry, field_key)
                new_value = new_values_for_db[field_key]

                # Price needs careful comparison (Decimal vs Decimal, or None)
                if field_key == "price":
                    # Both db_value and new_value are Decimal or None here
                    if db_value != new_value:
                        is_unchanged = False
                        changed_fields_details.append(f"{field_key}: DB='{db_value}' New='{new_value}'")
                # Other fields (strings, int)
                elif db_value != new_value:
                    is_unchanged = False
                    changed_fields_details.append(f"{field_key}: DB='{db_value}' New='{new_value}'")
            
            if is_unchanged:
                logger.info(f"{log_prefix} No changes detected in comparable fields. Skipping update.")
                return True, "skipped_no_change"
            else:
                logger.info(f"{log_prefix} Changes detected: {'; '.join(changed_fields_details)}. Updating entry.")
                # Update all fields from new_values_for_db
                for key, value in new_values_for_db.items():
                    setattr(entry, key, value)
                # Also update embedding and source_data_json as these always come with an update decision
                entry.embedding = embedding_vector
                entry.source_data_json = damasco_product_data # Store raw for audit
                # updated_at is handled by DB trigger or onupdate=func.now()
                # No need to explicitly set entry.item_code as it's part of the ID and set on creation.
                logger.info(f"{log_prefix} Entry updated.")
                return True, "updated"
        else:
            # New entry
            entry = Product(id=product_location_id, item_code=item_code) # item_code is already normalized
            for key, value in new_values_for_db.items():
                setattr(entry, key, value)
            entry.embedding = embedding_vector
            entry.source_data_json = damasco_product_data # Store raw for audit
            session.add(entry)
            logger.info(f"{log_prefix} New entry added.")
            return True, "added"

    except SQLAlchemyError as db_exc:
        logger.error(f"{log_prefix} DB error during add/update: {db_exc}", exc_info=True)
        return False, f"DB error: {str(db_exc)}"
    except Exception as exc:
        logger.exception(f"{log_prefix} Unexpected error processing: {exc}")
        return False, f"Unexpected error: {str(exc)}"

# --- Get Live Product Details by SKU (item_code) ---
def get_live_product_details_by_sku(item_code_query: str) -> Optional[List[Dict[str, Any]]]:
    if not item_code_query:
        logger.error("get_live_product_details_by_sku: Missing item_code_query argument.")
        return None # Or an empty list: []
    
    normalized_item_code = _normalize_string(item_code_query)
    if not normalized_item_code:
        logger.warning(f"get_live_product_details_by_sku: item_code_query '{item_code_query}' normalized to empty/None.")
        return []


    with db_utils.get_db_session() as session:
        if not session:
            logger.error("DB session unavailable for get_live_product_details_by_sku.")
            return None
        try:
            product_entries = session.query(Product).filter_by(item_code=normalized_item_code).all()
            if not product_entries:
                logger.info("No product entries found with item_code: %s", normalized_item_code)
                return []
            results = [entry.to_dict() for entry in product_entries]
            logger.info(f"Found {len(results)} locations for item_code: {normalized_item_code}")
            return results
        except SQLAlchemyError as db_exc:
            logger.exception("DB error fetching product by item_code: %s", db_exc)
            return None # Indicates error
        except Exception as exc:
            logger.exception("Unexpected error fetching product by item_code: %s", exc)
            return None # Indicates error

# --- Get Live Product Details by composite ID ---
def get_live_product_details_by_id(composite_id: str) -> Optional[Dict[str, Any]]:
    if not composite_id: # The ID is composite, so it's less likely to just be whitespace
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
                return None # Not found, but not an error in processing
            return product_entry.to_dict()
        except SQLAlchemyError as db_exc:
            logger.exception("DB error fetching product by composite_id: %s", db_exc)
            return None # Indicates error
        except Exception as exc:
            logger.exception("Unexpected error fetching product by composite_id: %s", exc)
            return None # Indicates error