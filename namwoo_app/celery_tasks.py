# /home/ec2-user/namwoo_app/namwoo_app/celery_tasks.py
import logging
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, ValidationError, Field # For data validation
from celery.exceptions import Ignore # To tell Celery not to retry certain failures

from .celery_app import celery_app
from .services import product_service, openai_service # Your existing services
from .utils import db_utils # For SessionLocal
from .models.product import Product # For Product.prepare_text_for_embedding
from .config import Config # For EMBEDDING_DIMENSION if needed

logger = logging.getLogger(__name__)

# --- Pydantic Model for Validating Incoming Snake_Case Product Data ---
# This model assumes the Celery task receives data with snake_case keys,
# typically after being processed by damasco_service.py.
class DamascoProductDataSnake(BaseModel):
    item_code: str
    item_name: str
    stock: int
    price: float # Damasco data might send price as string, ensure conversion if so
    category: Optional[str] = None
    sub_category: Optional[str] = None
    brand: Optional[str] = None
    line: Optional[str] = None
    item_group_name: Optional[str] = None
    warehouse_name: str
    branch_name: Optional[str] = None

    # Store the original raw dictionary that was passed to the Pydantic model.
    # This is useful if you need to pass the exact original (snake_case) structure
    # to some part of the process, e.g., for the 'source_data_json' field if you
    # decide to store the original snake_case input there.
    original_input_data: Optional[Dict[str, Any]] = None

    class Config:
        extra = 'allow' # Allow other fields not explicitly defined

    # Pydantic v2 style model_post_init or root_validator for Pydantic v1
    # to capture the original input data.
    # For Pydantic v1, you'd use a @root_validator(pre=True) or pass it around.
    # For simplicity here, we'll assume it's handled if needed or that
    # damasco_product_data in add_or_update_product_in_db gets the camel_case version
    # for its source_data_json field, which is also fine.

def _convert_snake_to_camel_case(data_snake: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converts a dictionary with snake_case keys to camelCase keys.
    Only converts known keys relevant for downstream services.
    """
    if not data_snake:
        return {}

    # Mapping from snake_case (Pydantic model fields) to camelCase
    key_map = {
        "item_code": "itemCode",
        "item_name": "itemName",
        "sub_category": "subCategory",
        "item_group_name": "itemGroupName",
        "warehouse_name": "whsName",
        "branch_name": "branchName",
        # Keys that are the same in snake_case and camelCase (or already camelCase)
        "stock": "stock",
        "price": "price",
        "category": "category",
        "brand": "brand",
        "line": "line",
    }

    data_camel = {}
    for snake_key, value in data_snake.items():
        camel_key = key_map.get(snake_key)
        if camel_key: # Only map known keys that need conversion or are directly used
            data_camel[camel_key] = value
        elif snake_key in key_map.values(): # If key is already camelCase and in target map values
            data_camel[snake_key] = value
        # If a key is not in the map and not a target camelCase key, it's ignored for the camelCase dict.
        # This makes the camelCase dict specific to what downstream functions expect.
        # If you want to pass all other keys as-is:
        # else:
        # data_camel[snake_key] = value # This would pass through unmapped keys

    # Ensure all core camelCase keys expected by Product.prepare_text_for_embedding are present,
    # even if None, if the original snake_case key was missing and not required by Pydantic.
    # Product.prepare_text_for_embedding uses .get() so it handles missing keys gracefully.
    # So, explicit filling with None is not strictly necessary here.
    return data_camel


@celery_app.task(bind=True, name='namwoo_app.celery_tasks.process_product_item_task',
                  max_retries=3, default_retry_delay=300, acks_late=True)
def process_product_item_task(self, product_data_dict_snake: Dict[str, Any]):
    """
    Celery task to process a single product item.
    Input `product_data_dict_snake` is assumed to have snake_case keys.
    """
    session = None
    # Log identifier using the incoming snake_case keys
    item_identifier_for_log = f"{product_data_dict_snake.get('item_code', 'N/A')}_{product_data_dict_snake.get('warehouse_name', 'N/A')}"
    logger.info(f"Task {self.request.id}: Starting processing for item {item_identifier_for_log}")

    try:
        # 1. Validate incoming snake_case data (Optional but recommended)
        try:
            # Pydantic expects keyword arguments, so unpack the dictionary
            validated_product_snake = DamascoProductDataSnake(**product_data_dict_snake)
            # Use the validated data (still snake_case) for the conversion
            data_for_conversion_snake = validated_product_snake.model_dump(exclude_unset=True)
        except ValidationError as val_err:
            logger.error(f"Task {self.request.id}: Pydantic validation error for item {item_identifier_for_log}: {val_err.errors()}")
            raise Ignore() # Do not retry validation errors

        # 2. Convert data to camelCase for downstream services
        # Product.prepare_text_for_embedding and product_service.add_or_update_product_in_db
        # expect camelCase keys for the core product data.
        product_data_camel = _convert_snake_to_camel_case(data_for_conversion_snake)
        logger.debug(f"Task {self.request.id}: Converted data to camelCase: {product_data_camel}")


        # 3. Prepare text for embedding (expects camelCase keys)
        text_to_embed = Product.prepare_text_for_embedding(product_data_camel)
        if not text_to_embed:
            logger.warning(f"Task {self.request.id}: No text to embed for item {item_identifier_for_log} from camelCase data. Skipping.")
            raise Ignore()
        logger.debug(f"Task {self.request.id}: Text prepared for embedding: '{text_to_embed[:100]}...'")

        # 4. Generate embedding
        embedding_vector = openai_service.generate_product_embedding(text_to_embed)
        if embedding_vector is None:
            logger.error(f"Task {self.request.id}: Embedding generation ultimately failed for {item_identifier_for_log}.")
            raise self.retry(exc=Exception("Embedding generation ultimately failed after internal retries"))
        logger.debug(f"Task {self.request.id}: Embedding generated successfully.")

        # 5. Upsert to DB
        # product_service.add_or_update_product_in_db expects damasco_product_data in camelCase
        session = db_utils.SessionLocal()
        success, op_type_or_error_msg = product_service.add_or_update_product_in_db(
            session=session,
            damasco_product_data=product_data_camel, # Pass the camelCase version
            embedding_vector=embedding_vector,
            text_used_for_embedding=text_to_embed
        )

        if success:
            session.commit()
            logger.info(f"Task {self.request.id}: Successfully {op_type_or_error_msg} item {item_identifier_for_log}")
            return {"status": "success", "operation": op_type_or_error_msg, "item_id": item_identifier_for_log}
        else:
            session.rollback()
            logger.error(f"Task {self.request.id}: DB operation failed for item {item_identifier_for_log}. Reason: {op_type_or_error_msg}")
            # Check if the error message indicates a non-retryable DB issue from product_service
            # For example, if product_service returns "Missing Damasco product data."
            if "Missing" in op_type_or_error_msg or "dimension mismatch" in op_type_or_error_msg:
                raise Ignore() # Don't retry these types of data errors
            raise self.retry(exc=Exception(f"DB operation failed: {op_type_or_error_msg}"))

    except Ignore:
        logger.warning(f"Task {self.request.id}: Task for item {item_identifier_for_log} ignored due to non-retryable error.")
        if session:
            session.rollback()
        return {"status": "ignored", "item_id": item_identifier_for_log, "reason": "Data issue or non-retryable error"}
    except Exception as exc:
        logger.exception(f"Task {self.request.id}: Unhandled exception for item {item_identifier_for_log}: {exc}")
        if session:
            session.rollback()
        if not self.request.called_directly: # Avoid retry if called directly (e.g., in tests)
            raise self.retry(exc=exc) # Re-raise to allow Celery to handle retries based on task decorator
        return {"status": "failed_exception", "item_id": item_identifier_for_log, "error": str(exc)}
    finally:
        if session:
            session.close()
            logger.debug(f"Task {self.request.id}: DB session closed for item {item_identifier_for_log}")


@celery_app.task(bind=True, name='namwoo_app.celery_tasks.deactivate_product_task',
                  max_retries=3, default_retry_delay=60, acks_late=True)
def deactivate_product_task(self, product_id: str):
    """
    Celery task to deactivate a product (e.g., set stock to 0).
    product_id is the composite ID like "D0007277_Almacen_San_Martin_1".
    """
    session = None
    logger.info(f"Task {self.request.id}: Starting deactivation for product_id: {product_id}")
    try:
        session = db_utils.SessionLocal()

        entry = session.query(Product).filter_by(id=product_id).first()
        if entry:
            entry.stock = 0
            # If you add an 'is_active' column to your Product model and DB table:
            # entry.is_active = False
            session.commit()
            logger.info(f"Task {self.request.id}: Successfully deactivated product_id: {product_id} (stock set to 0).")
            return {"status": "success", "operation": "deactivated", "item_id": product_id}
        else:
            logger.warning(f"Task {self.request.id}: Product_id {product_id} not found for deactivation. No action taken.")
            # This is not an error that needs retrying if the product simply doesn't exist.
            raise Ignore()

    except Ignore:
        logger.warning(f"Task {self.request.id}: Deactivation task for {product_id} ignored (e.g., product not found).")
        if session:
            session.rollback() # Should be no changes if not found, but safe.
        return {"status": "ignored", "item_id": product_id, "reason": "Product not found for deactivation"}
    except Exception as exc:
        logger.exception(f"Task {self.request.id}: Error during deactivation of product_id {product_id}: {exc}")
        if session:
            session.rollback()
        if not self.request.called_directly:
            raise self.retry(exc=exc)
        return {"status": "failed_exception_deactivation", "item_id": product_id, "error": str(exc)}
    finally:
        if session:
            session.close()
            logger.debug(f"Task {self.request.id}: DB session closed for deactivation of product_id: {product_id}")