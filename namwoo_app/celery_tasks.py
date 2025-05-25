# /home/ec2-user/namwoo_app/namwoo_app/celery_tasks.py

import logging
from typing import List, Optional, Dict, Any
import re
import numpy as np # Ensure numpy is imported

from pydantic import BaseModel, ValidationError # Field is not used directly here
from celery.exceptions import Ignore

from .celery_app import celery_app, FlaskTask
from .services import product_service, openai_service
from .services import llm_processing_service
from .utils import db_utils, text_utils
from .models.product import Product
from .config import Config

logger = logging.getLogger(__name__)

# --- Pydantic Model for Validating Incoming Snake_Case Product Data ---
class DamascoProductDataSnake(BaseModel):
    item_code: str
    item_name: str
    description: Optional[str] = None
    stock: int
    price: float
    category: Optional[str] = None
    sub_category: Optional[str] = None
    brand: Optional[str] = None
    line: Optional[str] = None
    item_group_name: Optional[str] = None
    warehouse_name: str
    branch_name: Optional[str] = None
    original_input_data: Optional[Dict[str, Any]] = None
    class Config:
        extra = 'allow'

def _convert_snake_to_camel_case(data_snake: Dict[str, Any]) -> Dict[str, Any]:
    if not data_snake:
        return {}
    key_map = {
        "item_code": "itemCode",
        "item_name": "itemName",
        "description": "description",
        "stock": "stock",
        "price": "price",
        "category": "category",
        "sub_category": "subCategory",
        "brand": "brand",
        "line": "line",
        "item_group_name": "itemGroupName",
        "warehouse_name": "whsName",
        "branch_name": "branchName",
    }
    data_camel = {}
    for snake_key, value in data_snake.items():
        camel_key = key_map.get(snake_key)
        if camel_key:
            data_camel[camel_key] = value
    return data_camel

def _normalize_string_for_id_parts(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None

def _generate_product_location_id(item_code: str, warehouse_name: str) -> Optional[str]:
    norm_item_code = _normalize_string_for_id_parts(item_code)
    norm_whs_name = _normalize_string_for_id_parts(warehouse_name)

    if not norm_item_code or not norm_whs_name:
        logger.warning(f"Cannot generate product_location_id: item_code ('{item_code}') or whs_name ('{warehouse_name}') is empty after normalization.")
        return None
    
    sanitized_whs_name = re.sub(r'[^a-zA-Z0-9_-]', '_', norm_whs_name)
    product_location_id = f"{norm_item_code}_{sanitized_whs_name}"
    
    max_len = 512 
    if len(product_location_id) > max_len:
        logger.warning(f"Generated product_location_id '{product_location_id}' exceeds max length {max_len}. Truncating.")
        product_location_id = product_location_id[:max_len]
        
    return product_location_id

# --- TASKS ---

@celery_app.task(
    bind=True,
    base=FlaskTask,
    name='namwoo_app.celery_tasks.process_product_item_task',
    max_retries=3,
    default_retry_delay=300,
    acks_late=True
)
def process_product_item_task(self, product_data_dict_snake: Dict[str, Any]):
    task_id = self.request.id
    item_code_log = product_data_dict_snake.get('item_code', 'N/A')
    whs_name_log = product_data_dict_snake.get('warehouse_name', 'N/A')
    item_identifier_for_log = f"{item_code_log}_{whs_name_log}"
    
    logger.info(f"Task {task_id}: Starting processing for item identifier: {item_identifier_for_log}")

    processing_summary_logs = {
        "task_id": str(task_id),
        "item_identifier": item_identifier_for_log,
        "status": "pending",
        "validation": "pending",
        "summarization_action": "not_applicable",
        "embedding_action": "not_applicable",
        "db_operation": "pending",
        "final_message": ""
    }

    try:
        try:
            validated_product_snake = DamascoProductDataSnake(**product_data_dict_snake)
            validated_product_snake.original_input_data = product_data_dict_snake.copy() 
            data_for_conversion_snake = validated_product_snake.model_dump(exclude_unset=True)
            logger.debug(f"Task {task_id} ({item_identifier_for_log}): Pydantic validation successful.")
            processing_summary_logs["validation"] = "success"
        except ValidationError as val_err:
            error_details = val_err.errors()
            logger.error(f"Task {task_id} ({item_identifier_for_log}): Pydantic validation error: {error_details}")
            processing_summary_logs["validation"] = f"failed: {error_details}"
            processing_summary_logs["status"] = "ignored_validation_error"
            raise Ignore()

        product_data_camel = _convert_snake_to_camel_case(data_for_conversion_snake)
        if "description" in data_for_conversion_snake and "description" not in product_data_camel:
            product_data_camel["description"] = data_for_conversion_snake["description"]
        logger.debug(f"Task {task_id} ({item_identifier_for_log}): Converted data to camelCase keys: {list(product_data_camel.keys())}")

        item_code_camel = product_data_camel.get("itemCode")
        whs_name_camel = product_data_camel.get("whsName")
        product_location_id = _generate_product_location_id(item_code_camel, whs_name_camel)

        if not product_location_id:
            logger.error(f"Task {task_id} ({item_identifier_for_log}): Failed to generate product_location_id. Cannot proceed.")
            processing_summary_logs["status"] = "ignored_id_generation_failed"
            raise Ignore()
        
        processing_summary_logs["product_location_id"] = product_location_id

        existing_product_details = None
        with db_utils.get_db_session() as read_session:
            try:
                existing_product_db_entry = read_session.query(
                    Product.description, 
                    Product.llm_summarized_description,
                    Product.searchable_text_content,
                    Product.embedding
                ).filter_by(id=product_location_id).first()

                if existing_product_db_entry:
                    existing_product_details = {
                        "description": existing_product_db_entry.description,
                        "llm_summarized_description": existing_product_db_entry.llm_summarized_description,
                        "searchable_text_content": existing_product_db_entry.searchable_text_content,
                        "embedding": existing_product_db_entry.embedding 
                    }
                    logger.debug(f"Task {task_id} ({product_location_id}): Found existing entry details.")
                else:
                    logger.debug(f"Task {task_id} ({product_location_id}): No existing entry found in DB.")
            except Exception as e_read:
                logger.error(f"Task {task_id} ({product_location_id}): Error reading existing entry: {e_read}", exc_info=True)
                raise self.retry(exc=e_read, countdown=60) 

        llm_summary_to_use: Optional[str] = None
        raw_html_incoming = product_data_camel.get("description")
        item_name_for_log = product_data_camel.get("itemName", "N/A")

        needs_new_summary = False
        if existing_product_details:
            llm_summary_to_use = existing_product_details["llm_summarized_description"]
            if raw_html_incoming != existing_product_details["description"]:
                logger.info(f"Task {task_id} ({product_location_id}): Raw HTML description changed for '{item_name_for_log}'. New summary needed.")
                needs_new_summary = True
                processing_summary_logs["summarization_action"] = "needed_html_changed"
            elif not existing_product_details["llm_summarized_description"] and raw_html_incoming:
                logger.info(f"Task {task_id} ({product_location_id}): LLM summary missing for '{item_name_for_log}' (and incoming HTML exists). New summary needed.")
                needs_new_summary = True
                processing_summary_logs["summarization_action"] = "needed_summary_missing"
            else:
                logger.info(f"Task {task_id} ({product_location_id}): Re-using stored LLM summary for '{item_name_for_log}' (HTML unchanged or no new HTML, and summary exists).")
                processing_summary_logs["summarization_action"] = "reused_existing"
        elif raw_html_incoming:
            logger.info(f"Task {task_id} ({product_location_id}): New product with HTML description for '{item_name_for_log}'. New summary needed.")
            needs_new_summary = True
            processing_summary_logs["summarization_action"] = "needed_new_product_with_html"
        else:
            logger.info(f"Task {task_id} ({product_location_id}): No HTML description for '{item_name_for_log}'. Summarization not applicable.")
            processing_summary_logs["summarization_action"] = "skipped_no_html"

        if needs_new_summary and raw_html_incoming:
            logger.info(f"Task {task_id} ({product_location_id}): Attempting LLM summarization for '{item_name_for_log}'.")
            try:
                llm_summary_to_use = llm_processing_service.generate_llm_product_summary(
                    html_description=raw_html_incoming,
                    item_name=item_name_for_log
                )
                if llm_summary_to_use:
                    logger.info(f"Task {task_id} ({product_location_id}): New LLM summary generated. Preview: '{llm_summary_to_use[:100]}...'")
                    processing_summary_logs["summarization_action"] += "_success"
                else:
                    logger.warning(f"Task {task_id} ({product_location_id}): LLM summarization returned no content for '{item_name_for_log}'.")
                    llm_summary_to_use = None
                    processing_summary_logs["summarization_action"] += "_failed_empty_result"
            except Exception as e_summ:
                logger.error(f"Task {task_id} ({product_location_id}): LLM summarization failed for '{item_name_for_log}'. Error: {e_summ}", exc_info=True)
                processing_summary_logs["summarization_action"] += f"_exception: {e_summ}"
                if existing_product_details: 
                    llm_summary_to_use = existing_product_details["llm_summarized_description"] 
        elif not raw_html_incoming: 
            llm_summary_to_use = None

        text_to_embed = Product.prepare_text_for_embedding(
            damasco_product_data=product_data_camel,
            llm_generated_summary=llm_summary_to_use,
            raw_html_description_for_fallback=raw_html_incoming
        )

        if not text_to_embed:
            logger.warning(f"Task {task_id} ({product_location_id}): No text content could be prepared for embedding. Skipping embedding and DB update for this item.")
            processing_summary_logs["embedding_action"] = "skipped_no_text_to_embed"
            processing_summary_logs["status"] = "ignored_no_text_for_embedding"
            raise Ignore() 
        logger.debug(f"Task {task_id} ({product_location_id}): Text prepared for embedding (first 100 chars): '{text_to_embed[:100]}...'")

        embedding_vector_to_pass: Optional[List[float]] = None # This will be a list or None
        if existing_product_details and \
           existing_product_details["searchable_text_content"] == text_to_embed and \
           existing_product_details["embedding"] is not None:
            
            # Ensure it's a list before assigning
            if isinstance(existing_product_details["embedding"], np.ndarray):
                embedding_vector_to_pass = existing_product_details["embedding"].tolist()
            elif isinstance(existing_product_details["embedding"], list):
                embedding_vector_to_pass = existing_product_details["embedding"]
            else:
                # This case should be rare if pgvector returns np.ndarray or list
                logger.warning(f"Task {task_id} ({product_location_id}): Existing embedding is of unexpected type {type(existing_product_details['embedding'])}. Attempting to generate new one.")
                # Fall through to generate new embedding
                
            if embedding_vector_to_pass is not None: # If conversion was successful or it was already a list
                logger.info(f"Task {task_id} ({product_location_id}): Re-using existing embedding (searchable text unchanged and embedding exists).")
                processing_summary_logs["embedding_action"] = "reused_existing"
            else: # If type conversion failed or it was None, force regeneration
                logger.info(f"Task {task_id} ({product_location_id}): Existing embedding was None or of unexpected type, proceeding to generate new embedding.")
                # Fall through to generate new embedding logic
                pass # Explicitly do nothing here to fall through

        if embedding_vector_to_pass is None: # If not re-used, generate new
            reason = "new_product_or_no_existing_embedding"
            if existing_product_details:
                if existing_product_details["searchable_text_content"] != text_to_embed:
                    reason = "searchable_text_changed"
                elif existing_product_details["embedding"] is None:
                    reason = "existing_embedding_missing"
                # Added check if existing_product_details["embedding"] was not None but failed type conversion
                elif existing_product_details["embedding"] is not None and not (isinstance(existing_product_details["embedding"], list) or isinstance(existing_product_details["embedding"], np.ndarray)):
                    reason = "existing_embedding_invalid_type"


            logger.info(f"Task {task_id} ({product_location_id}): Generating new embedding. Reason: {reason}.")
            try:
                # openai_service.generate_product_embedding should return List[float] or None
                newly_generated_embedding = openai_service.generate_product_embedding(text_to_embed)
                if newly_generated_embedding is None:
                    logger.error(f"Task {task_id} ({product_location_id}): Embedding generation service returned None.")
                    processing_summary_logs["embedding_action"] = f"generated_failed_service_returned_none ({reason})"
                    raise self.retry(exc=Exception("Embedding generation service returned None"), countdown=120)
                
                embedding_vector_to_pass = newly_generated_embedding # This is already a List[float]
                logger.info(f"Task {task_id} ({product_location_id}): New embedding generated successfully.")
                processing_summary_logs["embedding_action"] = f"generated_new ({reason})"
            except Exception as e_embed:
                logger.error(f"Task {task_id} ({product_location_id}): Embedding generation failed. Error: {e_embed}", exc_info=True)
                processing_summary_logs["embedding_action"] = f"generated_exception ({reason}): {e_embed}"
                raise self.retry(exc=e_embed)

        # At this point, embedding_vector_to_pass is either a List[float] or None
        with db_utils.get_db_session() as write_session:
            success, op_type_or_error_msg = product_service.add_or_update_product_in_db(
                session=write_session,
                product_id_to_upsert=product_location_id,
                damasco_product_data_camel=product_data_camel, 
                embedding_vector=embedding_vector_to_pass, # Pass the list or None
                text_used_for_embedding=text_to_embed,
                llm_summarized_description_to_store=llm_summary_to_use,
                raw_html_description_to_store=raw_html_incoming,
                original_input_data_snake=validated_product_snake.original_input_data
            )

            processing_summary_logs["db_operation"] = op_type_or_error_msg
            if success:
                logger.info(f"Task {task_id} ({product_location_id}): Successfully {op_type_or_error_msg}.")
                processing_summary_logs["status"] = "success"
                processing_summary_logs["final_message"] = f"Operation: {op_type_or_error_msg}."
            else:
                logger.error(f"Task {task_id} ({product_location_id}): DB operation failed. Reason: {op_type_or_error_msg}")
                processing_summary_logs["status"] = f"failed_db_operation"
                processing_summary_logs["final_message"] = f"DB Error: {op_type_or_error_msg}"
                if "Missing" in op_type_or_error_msg or \
                   "dimension mismatch" in op_type_or_error_msg or \
                   "ConstraintViolation" in op_type_or_error_msg or \
                   "Invalid embedding vector type" in op_type_or_error_msg: # Check for this explicit error from service
                    raise Ignore() 
                raise self.retry(exc=Exception(f"DB operation failed: {op_type_or_error_msg}"))
        
        logger.info(f"Task {task_id} ({product_location_id}) Processing Summary: {processing_summary_logs}")
        return processing_summary_logs

    except Ignore as e:
        logger.warning(f"Task {task_id} ({item_identifier_for_log}): Task ignored. Reason: {getattr(e, 'args', [None])[0] if e.args else 'Unknown Ignore reason'}")
        processing_summary_logs["status"] = processing_summary_logs.get("status", "ignored")
        processing_summary_logs["final_message"] = f"Task Ignored: {getattr(e, 'args', [None])[0] if e.args else 'Unknown Ignore reason'}"
        logger.info(f"Task {task_id} ({item_identifier_for_log}) Processing Summary (Ignored): {processing_summary_logs}")
        return processing_summary_logs
    except Exception as exc:
        logger.exception(f"Task {task_id} ({item_identifier_for_log}): Unhandled exception: {exc}")
        processing_summary_logs["status"] = "failed_unhandled_exception"
        processing_summary_logs["final_message"] = f"Unhandled Exception: {exc}"
        if not self.request.called_directly:
            try:
                raise self.retry(exc=exc, countdown= (self.request.retries + 1) * 300)
            except Exception as retry_exc:
                 logger.error(f"Task {task_id} ({item_identifier_for_log}): Max retries exceeded. Error: {retry_exc}")
                 processing_summary_logs["final_message"] += " Max retries exceeded."

        logger.info(f"Task {task_id} ({item_identifier_for_log}) Processing Summary (Failed Exception): {processing_summary_logs}")
        return processing_summary_logs


@celery_app.task(
    bind=True,
    base=FlaskTask,
    name='namwoo_app.celery_tasks.deactivate_product_task',
    max_retries=3,
    default_retry_delay=60,
    acks_late=True
)
def deactivate_product_task(self, product_id: str):
    task_id = self.request.id
    logger.info(f"Task {task_id}: Starting deactivation for product_id: {product_id}")
    processing_summary_logs = {
        "task_id": str(task_id),
        "product_id": product_id,
        "status": "pending",
        "db_operation_status": "pending",
        "final_message": ""
    }
    try:
        with db_utils.get_db_session() as session:
            entry = session.query(Product).filter_by(id=product_id).first()
            if entry:
                if entry.stock != 0:
                    entry.stock = 0
                    session.add(entry)
                    session.commit() # Explicit commit after add
                    logger.info(f"Task {task_id}: Product_id: {product_id} stock set to 0 for deactivation.")
                    processing_summary_logs["db_operation_status"] = "stock_set_to_0"
                else:
                    logger.info(f"Task {task_id}: Product_id: {product_id} already has stock 0. No change needed for deactivation.")
                    processing_summary_logs["db_operation_status"] = "already_stock_0"
                
                processing_summary_logs["status"] = "success"
                processing_summary_logs["final_message"] = "Deactivation processed."
                logger.info(f"Task {task_id} Deactivation Summary: {processing_summary_logs}")
                return processing_summary_logs
            else:
                logger.warning(f"Task {task_id}: Product_id {product_id} not found for deactivation. No action taken.")
                processing_summary_logs["status"] = "ignored_not_found"
                processing_summary_logs["final_message"] = "Product not found."
                raise Ignore("Product not found for deactivation")
    except Ignore as e_ignore: # Catch the Ignore exception explicitly
        logger.warning(f"Task {task_id}: Deactivation task for {product_id} ignored. Reason: {e_ignore.args[0] if e_ignore.args else 'Unknown reason'}")
        processing_summary_logs["final_message"] = processing_summary_logs.get("final_message", f"Ignored: {e_ignore.args[0] if e_ignore.args else 'Unknown reason'}")
        processing_summary_logs["status"] = "ignored" # Ensure status is set if it wasn't
        logger.info(f"Task {task_id} Deactivation Summary (Ignored): {processing_summary_logs}")
        return processing_summary_logs
    except Exception as exc:
        logger.exception(f"Task {task_id}: Error during deactivation of product_id {product_id}: {exc}")
        processing_summary_logs["status"] = "failed_exception"
        processing_summary_logs["final_message"] = f"Exception: {exc}"
        if not self.request.called_directly:
            try:
                raise self.retry(exc=exc)
            except Exception as retry_exc:
                 logger.error(f"Task {task_id} (deactivate_product_task): Max retries exceeded for {product_id}. Error: {retry_exc}")
                 processing_summary_logs["final_message"] += " Max retries exceeded."
        logger.info(f"Task {task_id} Deactivation Summary (Failed Exception): {processing_summary_logs}")
        return processing_summary_logs