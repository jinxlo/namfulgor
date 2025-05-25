# NAMWOO/services/damasco_service.py
import logging

# Logger for this service
logger = logging.getLogger('sync')  # Matches sync_service.py logger (or a dedicated one)

def process_damasco_data(raw_data_list: list) -> list: # Changed 'raw_data' to 'raw_data_list' for clarity
    """
    Cleans and structures raw Damasco product data into a list of dictionaries
    with snake_case keys, ready for further processing (e.g., Celery tasks, DB sync).

    Args:
        raw_data_list: The raw JSON data received from the fetcher 
                       (list of product dictionaries, assumed to have camelCase keys
                        including 'description' with HTML content).

    Returns:
        A list of cleaned product dictionaries with snake_case keys.
    """
    if not isinstance(raw_data_list, list):
        logger.error("Invalid data format: Expected a list of product dictionaries.")
        return []

    cleaned_products = []

    for item in raw_data_list:
        if not isinstance(item, dict): # Basic check for each item
            logger.warning(f"Skipping non-dictionary item in raw_data_list: {item}")
            continue
        try:
            # Extract and normalize fields, converting to snake_case
            product = {
                'item_code': str(item.get('itemCode', '')).strip(),
                'item_name': str(item.get('itemName', '')).strip(),
                # Get the raw HTML description and store it with a snake_case key
                'description': item.get('description'), # Keep as is (raw HTML), don't strip here
                'stock': int(item.get('stock', 0)),
                'price': float(item.get('price', 0.0)), # Ensure this is float or Decimal as needed downstream
                'category': str(item.get('category', '')).strip(),
                'sub_category': str(item.get('subCategory', '')).strip(),
                'brand': str(item.get('brand', '')).strip(),
                'line': str(item.get('line', '')).strip(),
                'item_group_name': str(item.get('itemGroupName', '')).strip(),
                'warehouse_name': str(item.get('whsName', '')).strip(),
                'branch_name': str(item.get('branchName', '')).strip()
            }

            # Ensure essential keys are not empty after stripping
            if not product['item_code']: # was: or not product['item_name']
                logger.warning(f"Skipping item with missing or empty itemCode: {item}")
                continue
            if not product['warehouse_name']: # warehouse_name is crucial for composite ID
                logger.warning(f"Skipping item {product.get('item_code')} due to missing or empty whsName: {item}")
                continue


            cleaned_products.append(product)

        except (ValueError, TypeError) as e: # More specific exceptions for type conversion
            logger.error(f"Error processing item (likely type conversion issue for stock/price): {item}. Error: {e}")
        except Exception as e:
            logger.error(f"Failed to process item: {item}. Error: {e}", exc_info=True)

    logger.info(f"Processed {len(cleaned_products)} valid products out of {len(raw_data_list)} received by damasco_service.")
    return cleaned_products