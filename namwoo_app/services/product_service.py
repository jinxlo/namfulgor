# NAMWOO/services/product_service.py

import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation as InvalidDecimalOperation
from datetime import datetime

import numpy as np # Ensure this is imported
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..models.product import Product
from ..utils import db_utils, embedding_utils # embedding_utils is used in search_local_products
from ..config import Config

logger = logging.getLogger(__name__)

# --- Semantic Helpers ---
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

# --- Search Products ---
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
    # Ensure OPENAI_EMBEDDING_MODEL is correctly fetched from Config
    embedding_model = Config.OPENAI_EMBEDDING_MODEL if hasattr(Config, 'OPENAI_EMBEDDING_MODEL') else "text-embedding-3-small"
    query_emb = embedding_utils.get_embedding(query_text, model=embedding_model)
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

def _normalize_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None

def get_product_by_id_from_db(db_session: Session, product_id: str) -> Optional[Product]:
    if not product_id:
        return None
    return db_session.query(Product).filter(Product.id == product_id).first()

def add_or_update_product_in_db(
    session: Session,
    product_id_to_upsert: str,
    damasco_product_data_camel: Dict[str, Any],
    embedding_vector: Optional[Any], # Will be either List[float], np.ndarray, or None
    text_used_for_embedding: Optional[str],
    llm_summarized_description_to_store: Optional[str],
    raw_html_description_to_store: Optional[str],
    original_input_data_snake: Dict[str, Any]
) -> Tuple[bool, str]:
    
    if not product_id_to_upsert:
        return False, "Missing product_id_to_upsert."
    if not damasco_product_data_camel or not isinstance(damasco_product_data_camel, dict):
        return False, "Missing or invalid Damasco product data (camelCase)."

    embedding_vector_for_db: Optional[List[float]] = None
    if embedding_vector is not None:
        if isinstance(embedding_vector, np.ndarray):
            embedding_vector_for_db = embedding_vector.tolist() # Convert to list for DB
        elif isinstance(embedding_vector, list):
            embedding_vector_for_db = embedding_vector # Already a list
        else:
            # This case should ideally be caught earlier or handled by the caller
            logger.error(f"Product ID {product_id_to_upsert}: Unexpected embedding vector type ({type(embedding_vector)}). Expected list or numpy.ndarray.")
            return False, f"Invalid embedding vector type (must be list or numpy.ndarray, got {type(embedding_vector)})."

        # Dimension check (on the list version)
        expected_dim = Config.EMBEDDING_DIMENSION if hasattr(Config, 'EMBEDDING_DIMENSION') and Config.EMBEDDING_DIMENSION else None
        if expected_dim and len(embedding_vector_for_db) != expected_dim:
            return False, (f"Embedding dimension mismatch (expected {expected_dim}, "
                           f"got {len(embedding_vector_for_db)} for ID {product_id_to_upsert}).")

    if embedding_vector_for_db is not None and (not text_used_for_embedding or not isinstance(text_used_for_embedding, str)):
        logger.warning(f"Product ID {product_id_to_upsert}: Embedding vector present, but text_used_for_embedding is missing or invalid.")

    log_prefix = f"ProductService DB Upsert (ID='{product_id_to_upsert}'):"

    item_code = _normalize_string(damasco_product_data_camel.get("itemCode"))
    item_name = _normalize_string(damasco_product_data_camel.get("itemName"))
    
    price_from_damasco = damasco_product_data_camel.get("price")
    normalized_price_for_db = None
    if price_from_damasco is not None:
        try:
            normalized_price_for_db = Decimal(str(price_from_damasco)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        except InvalidDecimalOperation:
            logger.warning(f"{log_prefix} Invalid price value '{price_from_damasco}', treating as None.")

    stock_from_damasco = damasco_product_data_camel.get("stock")
    normalized_stock_for_db = 0
    if stock_from_damasco is not None:
        try:
            normalized_stock_for_db = int(stock_from_damasco)
            if normalized_stock_for_db < 0:
                logger.warning(f"{log_prefix} Negative stock value '{stock_from_damasco}' received, setting to 0.")
                normalized_stock_for_db = 0
        except (ValueError, TypeError):
            logger.warning(f"{log_prefix} Invalid stock value '{stock_from_damasco}', defaulting to 0.")
    
    norm_raw_html = _normalize_string(raw_html_description_to_store)
    norm_llm_summary = _normalize_string(llm_summarized_description_to_store)
    norm_searchable_text = _normalize_string(text_used_for_embedding)

    new_values_map = {
        "item_code": item_code,
        "item_name": item_name,
        "description": norm_raw_html,
        "llm_summarized_description": norm_llm_summary,
        "category": _normalize_string(damasco_product_data_camel.get("category")),
        "sub_category": _normalize_string(damasco_product_data_camel.get("subCategory")),
        "brand": _normalize_string(damasco_product_data_camel.get("brand")),
        "line": _normalize_string(damasco_product_data_camel.get("line")),
        "item_group_name": _normalize_string(damasco_product_data_camel.get("itemGroupName")),
        "warehouse_name": _normalize_string(damasco_product_data_camel.get("whsName")),
        "branch_name": _normalize_string(damasco_product_data_camel.get("branchName")),
        "price": normalized_price_for_db,
        "stock": normalized_stock_for_db,
        "searchable_text_content": norm_searchable_text,
        "embedding": embedding_vector_for_db, # Use the list version for DB
        "source_data_json": original_input_data_snake
    }

    try:
        entry = get_product_by_id_from_db(session, product_id_to_upsert)

        if entry:
            changed_fields_log_details = []
            needs_update = False

            for field_key, new_value in new_values_map.items():
                if field_key == "source_data_json": continue

                db_value = getattr(entry, field_key, None)
                
                is_different = False
                if field_key == "embedding":
                    # Convert DB value to list if it's a numpy array for consistent comparison
                    db_value_list = db_value.tolist() if isinstance(db_value, np.ndarray) else db_value
                    new_value_list = new_value # new_value is already a list or None from earlier conversion
                    
                    if (db_value_list is None and new_value_list is not None) or \
                       (db_value_list is not None and new_value_list is None):
                        is_different = True
                    elif db_value_list is not None and new_value_list is not None:
                        # Compare as float arrays to handle potential minor precision differences from DB read/write cycles
                        if not np.array_equal(np.array(db_value_list, dtype=float), np.array(new_value_list, dtype=float)):
                            is_different = True
                elif field_key == "price":
                    if (db_value is None and new_value is not None) or \
                       (db_value is not None and new_value is None) or \
                       (db_value is not None and new_value is not None and db_value != new_value):
                        is_different = True
                else:
                    if db_value != new_value:
                        is_different = True
                
                if is_different:
                    needs_update = True
                    log_new_val = str(new_value)[:70] + "..." if isinstance(new_value, (str, list, np.ndarray)) and len(str(new_value)) > 70 else new_value
                    log_db_val = str(db_value)[:70] + "..." if isinstance(db_value, (str, list, np.ndarray)) and len(str(db_value)) > 70 else db_value
                    if field_key == "embedding" and new_value is not None: log_new_val = f"Vector(len={len(new_value)})"
                    if field_key == "embedding" and db_value is not None: log_db_val = f"Vector(len={len(db_value) if isinstance(db_value, list) else 'np.array'})"
                    changed_fields_log_details.append(f"{field_key}: (DB='{log_db_val}' -> New='{log_new_val}')")

            if not needs_update:
                logger.info(f"{log_prefix} No changes detected in comparable fields. Skipping actual DB write.")
                return True, "skipped_no_change"
            
            logger.info(f"{log_prefix} Changes detected in: {'; '.join(changed_fields_log_details)}. Updating entry.")
            for key, value in new_values_map.items():
                setattr(entry, key, value) # 'embedding' key will set the list version
            entry.updated_at = datetime.utcnow()
            
            session.add(entry)
            session.commit()
            logger.info(f"{log_prefix} Entry successfully updated.")
            return True, f"updated (Changes: {', '.join(changed_fields_log_details)})"

        else: 
            logger.info(f"{log_prefix} New product. Adding to DB.")
            new_product_kwargs = {"id": product_id_to_upsert}
            new_product_kwargs.update(new_values_map) # 'embedding' key will provide the list version
            entry = Product(**new_product_kwargs)
            session.add(entry)
            session.commit()
            logger.info(f"{log_prefix} New entry successfully added.")
            return True, "added_new"

    except SQLAlchemyError as db_exc:
        session.rollback()
        logger.error(f"{log_prefix} DB error during add/update: {db_exc}", exc_info=True)
        if "violates unique constraint" in str(db_exc).lower():
             return False, f"db_constraint_violation: {str(db_exc)}"
        return False, f"db_sqlalchemy_error: {str(db_exc)}"
    except Exception as exc:
        session.rollback()
        logger.exception(f"{log_prefix} Unexpected error processing: {exc}")
        return False, f"db_unexpected_error: {str(exc)}"

def get_live_product_details_by_sku(item_code_query: str) -> Optional[List[Dict[str, Any]]]:
    if not item_code_query:
        logger.error("get_live_product_details_by_sku: Missing item_code_query argument.")
        return None
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
            return None
        except Exception as exc:
            logger.exception("Unexpected error fetching product by item_code: %s", exc)
            return None

def get_live_product_details_by_id(composite_id: str) -> Optional[Dict[str, Any]]:
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