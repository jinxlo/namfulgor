import logging

# Logger for this service
logger = logging.getLogger('sync')  # Matches sync_service.py logger

def process_damasco_data(raw_data):
    """
    Cleans and structures raw Damasco product data into a list of dictionaries ready for DB sync.

    Args:
        raw_data: The raw JSON data received from the fetcher (list of product dictionaries).

    Returns:
        A list of cleaned product dictionaries (structured for DB sync).
    """
    if not isinstance(raw_data, list):
        logger.error("Invalid data format: Expected a list of product dictionaries.")
        return []

    cleaned_products = []

    for item in raw_data:
        try:
            # Extract and normalize fields
            product = {
                'item_code': item.get('itemCode', '').strip(),
                'item_name': item.get('itemName', '').strip(),
                'stock': int(item.get('stock', 0)),
                'price': float(item.get('price', 0.0)),
                'category': item.get('category', '').strip(),
                'sub_category': item.get('subCategory', '').strip(),
                'brand': item.get('brand', '').strip(),
                'line': item.get('line', '').strip(),
                'item_group_name': item.get('itemGroupName', '').strip(),
                'warehouse_name': item.get('whsName', '').strip(),
                'branch_name': item.get('branchName', '').strip()
            }

            # Optional: Skip items with missing critical fields
            if not product['item_code'] or not product['item_name']:
                logger.warning(f"Skipping item with missing itemCode or itemName: {item}")
                continue

            cleaned_products.append(product)

        except Exception as e:
            logger.error(f"Failed to process item: {item}. Error: {e}")

    logger.info(f"Processed {len(cleaned_products)} valid products out of {len(raw_data)} received.")

    return cleaned_products
