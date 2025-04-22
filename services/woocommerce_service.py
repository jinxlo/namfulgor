import logging
from typing import Optional, List, Dict, Any, Generator
from woocommerce import API
from requests.exceptions import RequestException, Timeout, ConnectionError
from flask import current_app # Use current_app to access config in service context

logger = logging.getLogger(__name__)

# --- ADDED CONSTANT ---
# Default number of products to fetch per page in API requests for sync
PER_PAGE_DEFAULT = 50
# ----------------------

# Module-level variable for the API client instance
_wcapi = None

def _get_woocommerce_api_client() -> Optional[API]:
    """
    Initializes and returns the WooCommerce API client instance.
    Reads configuration from the Flask app context.
    """
    global _wcapi
    if _wcapi is None:
        if not current_app:
            logger.error("Cannot initialize WooCommerce client: Flask app context not available.")
            return None

        url = current_app.config.get('WOOCOMMERCE_URL')
        key = current_app.config.get('WOOCOMMERCE_KEY')
        secret = current_app.config.get('WOOCOMMERCE_SECRET')
        version = current_app.config.get('WOOCOMMERCE_API_VERSION', 'wc/v3')
        timeout = current_app.config.get('WOOCOMMERCE_TIMEOUT', 30)

        if not all([url, key, secret]):
            logger.error("WooCommerce API credentials (URL, KEY, SECRET) are not fully configured.")
            return None

        try:
            logger.info(f"Initializing WooCommerce API client for URL: {url} (Version: {version}, Timeout: {timeout}s)")
            _wcapi = API(
                url=url,
                consumer_key=key,
                consumer_secret=secret,
                wp_api=True, # Required for standard WP REST API endpoints
                version=version,
                timeout=timeout,
                query_string_auth=True # Sometimes needed depending on server config
            )
            # Test connection by making a simple, low-impact request
            _wcapi.get("system_status").raise_for_status() # Throws HTTPError for bad responses
            logger.info("WooCommerce API client initialized and connection verified.")

        except RequestException as e:
            status_code = e.response.status_code if e.response is not None else 'N/A'
            text = e.response.text if e.response is not None else str(e)
            logger.error(f"Failed to connect or verify WooCommerce API: {status_code} - {text[:200]}...")
            _wcapi = None # Ensure client is None on failure
        except Exception as e:
            logger.exception(f"Unexpected error initializing WooCommerce API client: {e}")
            _wcapi = None

    return _wcapi


def _make_api_request(method: str, endpoint: str, params: Optional[Dict] = None, **kwargs) -> Optional[Any]:
    """
    Helper function to make requests to the WooCommerce API with error handling.

    Args:
        method: HTTP method ('get', 'post', 'put', 'delete').
        endpoint: API endpoint path (e.g., 'products', 'products/123').
        params: Dictionary of query parameters for GET requests.
        **kwargs: Additional keyword arguments passed to the wcapi method (e.g., data for POST/PUT).

    Returns:
        The JSON response data as a dictionary or list, or None on failure.
    """
    wcapi = _get_woocommerce_api_client()
    if not wcapi:
        logger.error(f"Cannot make '{method}' request to '{endpoint}': WooCommerce client not available.")
        return None

    try:
        logger.debug(f"Making WC API request: {method.upper()} {endpoint} | Params: {params} | Data: {kwargs.get('data')}")
        api_method = getattr(wcapi, method)
        response = api_method(endpoint, params=params, **kwargs)
        response.raise_for_status() # Raise HTTPError for 4xx/5xx responses
        return response.json()

    except Timeout:
        logger.error(f"WooCommerce API request timed out: {method.upper()} {endpoint}")
        return None
    except ConnectionError as e:
         logger.error(f"WooCommerce API connection error: {method.upper()} {endpoint} - {e}")
         return None
    except RequestException as e:
        status_code = e.response.status_code if e.response is not None else 'N/A'
        text = e.response.text if e.response is not None else str(e)
        # Log specific errors like 404 differently if needed
        if status_code == 404:
             logger.warning(f"Resource not found ({status_code}): {method.upper()} {endpoint} - {text[:200]}...")
        elif status_code == 401 or status_code == 403:
             logger.error(f"Authentication/Authorization error ({status_code}): {method.upper()} {endpoint}. Check API keys and permissions.")
        else:
             logger.error(f"WooCommerce API request failed ({status_code}): {method.upper()} {endpoint} - {text[:200]}...")
        return None # Indicate failure
    except Exception as e:
        logger.exception(f"Unexpected error during WooCommerce API call: {method.upper()} {endpoint} - {e}")
        return None


def get_live_product_details_by_id(wc_product_id: int) -> Optional[Dict[str, Any]]:
    """
    Fetches live product details directly from WooCommerce using the WC Product ID.
    Designed to be called by the OpenAI service when specific live data is needed.
    """
    logger.info(f"Fetching LIVE details from WooCommerce for Product ID: {wc_product_id}")
    endpoint = f"products/{wc_product_id}"
    product_data = _make_api_request('get', endpoint)

    if product_data:
        # Extract key details needed for the response / LLM context
        live_details = {
            "wc_product_id": product_data.get("id"),
            "name": product_data.get("name"),
            "sku": product_data.get("sku"),
            "price": product_data.get("price"), # Current price
            "stock_status": product_data.get("stock_status"), # Current status
            "stock_quantity": product_data.get("stock_quantity"), # Exact quantity (if managed)
            "manage_stock": product_data.get("manage_stock"),
            "permalink": product_data.get("permalink"),
            # Consider adding variations if needed for user queries:
            # "variations": product_data.get("variations", []), # List of variation IDs
            # "attributes": product_data.get("attributes", []),
        }
        logger.info(f"Successfully fetched LIVE details for WC Product ID: {wc_product_id}")
        return live_details
    else:
        # Error already logged by _make_api_request
        logger.warning(f"Could not fetch LIVE details for WC Product ID: {wc_product_id}")
        return None


def get_live_product_details_by_sku(sku: str) -> Optional[Dict[str, Any]]:
    """
    Fetches live product details directly from WooCommerce using the SKU.
    Note: Assumes SKU is unique in your store. If not, this might return the first match.
    Designed to be called by the OpenAI service.
    """
    if not sku or not isinstance(sku, str):
        logger.warning("Invalid SKU provided for live fetching.")
        return None

    logger.info(f"Fetching LIVE details from WooCommerce for SKU: {sku}")
    endpoint = "products"
    params = {"sku": sku}
    products_list = _make_api_request('get', endpoint, params=params)

    if products_list is not None:
        if len(products_list) == 1:
            product_data = products_list[0]
            # Extract key details (same as by ID)
            live_details = {
                "wc_product_id": product_data.get("id"),
                "name": product_data.get("name"),
                "sku": product_data.get("sku"),
                "price": product_data.get("price"),
                "stock_status": product_data.get("stock_status"),
                "stock_quantity": product_data.get("stock_quantity"),
                "manage_stock": product_data.get("manage_stock"),
                "permalink": product_data.get("permalink"),
                # Add variations/attributes if needed
            }
            logger.info(f"Successfully fetched LIVE details for SKU: {sku} (WC ID: {product_data.get('id')})")
            return live_details
        elif len(products_list) == 0:
            logger.warning(f"No product found with SKU: {sku} in WooCommerce.")
            return None
        else:
             # This case implies non-unique SKUs, which is problematic for this lookup
             logger.warning(f"Multiple products ({len(products_list)}) found with SKU: {sku}. Returning details for the first one (ID: {products_list[0].get('id')}).")
             # Optionally, return an error or a list indicating ambiguity
             product_data = products_list[0] # Return first match for now
             live_details = { # Extract details for the first match
                "wc_product_id": product_data.get("id"), "name": product_data.get("name"), "sku": product_data.get("sku"),
                "price": product_data.get("price"), "stock_status": product_data.get("stock_status"),
                "stock_quantity": product_data.get("stock_quantity"), "manage_stock": product_data.get("manage_stock"),
                "permalink": product_data.get("permalink"),
             }
             return live_details
    else:
         # Error already logged by _make_api_request
         logger.warning(f"Could not fetch LIVE details for SKU: {sku}")
         return None


# --- CORRECTED FUNCTION SIGNATURE ---
def get_all_products_for_sync(per_page=PER_PAGE_DEFAULT) -> Generator[List[Dict[str, Any]], None, None]:
# ------------------------------------
    """
    Generator function to fetch all 'published' products from WooCommerce using pagination.
    Handles potential API errors during fetching. Used by the sync_service.

    Args:
        per_page: Number of products to fetch per API request. Uses module constant as default.

    Yields:
        A list of product data dictionaries for each successful page fetch.
    """
    page = 1
    total_products_yielded = 0
    logger.info(f"Starting fetch of all published products for sync (batch size: {per_page})...")

    while True:
        endpoint = "products"
        params = {
            "per_page": per_page,
            "page": page,
            "status": "publish", # Fetch only published products
        }

        logger.debug(f"Fetching product sync batch: Page {page}")
        product_batch = _make_api_request('get', endpoint, params=params)

        if product_batch is None:
            logger.error(f"Failed to fetch product batch on page {page}. Stopping sync fetch.")
            break # Stop the generator

        if not isinstance(product_batch, list):
             logger.error(f"Received unexpected data type for product batch on page {page}. Expected list, got {type(product_batch)}. Stopping.")
             break

        if not product_batch:
            logger.info(f"No more products found on page {page}. Sync fetching complete.")
            break # Exit the loop gracefully

        num_fetched = len(product_batch)
        total_products_yielded += num_fetched
        logger.info(f"Fetched {num_fetched} products on page {page}. Total yielded so far: {total_products_yielded}.")

        yield product_batch # Yield the current batch of products

        if num_fetched < per_page:
            logger.info("Likely reached the last page of products (fetched count < per_page).")
            break

        page += 1
        # Optional: Add a small delay between pages
        # import time
        # time.sleep(0.5)

    logger.info(f"Finished fetching products for sync. Total products yielded: {total_products_yielded}.")