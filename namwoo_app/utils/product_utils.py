# namwoo_app/utils/product_utils.py (NamFulgor - Battery Version)
import re
from typing import Optional, Any
import logging

logger = logging.getLogger(__name__)

def _sanitize_id_component(value: Any) -> str:
    """
    Normalizes and sanitizes a string component for use in a battery product ID.
    - Converts to string, strips whitespace.
    - Replaces multiple spaces and problematic characters with underscores.
    - Converts to lowercase for consistency.
    Returns an empty string if the input is None or results in an empty string after processing.
    """
    if value is None:
        return ""
    s = str(value).strip().lower()    # Convert to lowercase, strip whitespace
    s = re.sub(r'\s+', '_', s)        # Replace one or more spaces with a single underscore
    # Allow lowercase alphanumeric, underscore, hyphen. Remove others.
    s = re.sub(r'[^a-z0-9_-]', '', s)
    return s

def generate_battery_product_id(
    brand_raw: Any,
    model_code_raw: Any,
    max_length: int = 255 # Default max length for the ID, matching typical VARCHAR(255) in BatteryProduct.id
) -> Optional[str]:
    """
    Generates a unique product ID for a battery, based on its brand and model code.
    Example: brand="Fulgor", model_code="NS40 - 670" -> "fulgor_ns40_670"
    Returns None if essential parts (brand AND model_code, or at least one if the other is truly absent)
    are missing after sanitization.
    """
    sanitized_brand = _sanitize_id_component(brand_raw)
    sanitized_model_code = _sanitize_id_component(model_code_raw)

    # Determine the ID based on available sanitized components
    if sanitized_brand and sanitized_model_code:
        product_id = f"{sanitized_brand}_{sanitized_model_code}"
    elif sanitized_brand: # Only brand is usable
        logger.info(f"Generating battery_product_id using only brand ('{brand_raw}' -> '{sanitized_brand}') as model_code ('{model_code_raw}') was empty/invalid.")
        product_id = sanitized_brand
    elif sanitized_model_code: # Only model_code is usable
        logger.info(f"Generating battery_product_id using only model_code ('{model_code_raw}' -> '{sanitized_model_code}') as brand ('{brand_raw}') was empty/invalid.")
        product_id = sanitized_model_code
    else: # Both components resulted in empty strings
        logger.warning(
            f"Cannot generate battery_product_id: both brand ('{brand_raw}') and "
            f"model_code ('{model_code_raw}') are missing/empty after sanitization."
        )
        return None

    # Ensure the ID doesn't exceed the column length
    if len(product_id) > max_length:
        original_id_for_log = product_id # Store before truncation for logging
        product_id = product_id[:max_length]
        logger.warning(
            f"Generated battery_product_id for brand='{brand_raw}', model_code='{model_code_raw}' was truncated "
            f"from {len(original_id_for_log)} to {max_length} chars. Result: '{product_id}', Original: '{original_id_for_log}'"
        )
    
    logger.debug(f"Generated battery_product_id: '{product_id}' from brand='{brand_raw}', model_code='{model_code_raw}'")
    return product_id

# --- End of namwoo_app/utils/product_utils.py ---