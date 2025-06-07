# namwoo_app/services/lead_api_client.py (NamFulgor Version - Type Hints Corrected)
import requests
import json
import logging # Added logging import for consistency
from flask import current_app
from typing import Optional, List, Dict, Any # Ensure Optional and Dict are imported

# Assuming Config is correctly imported and loads .env variables
# This file does not directly import Config, but relies on current_app.config which is populated by it.

logger = logging.getLogger(__name__) # Logger for this module

# --- Private Helper Functions ---

def _get_api_headers() -> Optional[Dict[str, str]]: # MODIFIED TYPE HINT
    """
    Constructs the necessary headers for API calls, including the API key.
    Returns None if the API key is not configured.
    """
    api_key = current_app.config.get('LEAD_CAPTURE_API_KEY')
    if not api_key:
        current_app.logger.error("LEAD_CAPTURE_API_KEY is not configured for Lead API Client.")
        return None
    
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": api_key
    }
    # current_app.logger.debug(f"Lead API Headers prepared: {json.dumps(headers)}")
    return headers

def _get_api_base_url() -> Optional[str]: # MODIFIED TYPE HINT
    """
    Retrieves the base URL for the Lead Capture API service.
    Returns None if the URL is not configured.
    """
    base_url = current_app.config.get('LEAD_CAPTURE_API_URL')
    if not base_url:
        current_app.logger.error("LEAD_CAPTURE_API_URL is not configured for Lead API Client.")
        return None
    return base_url.rstrip('/')

# --- Public Client Functions ---
# (The rest of your functions: call_initiate_lead_intent, call_submit_customer_details
#  remain EXACTLY THE SAME as in your provided code, as their internal logic and
#  type hints for parameters/return values were already compatible or didn't use the new syntax)

def call_initiate_lead_intent(
    conversation_id: str,
    products_of_interest: list, # List of dicts: [{"sku": "...", "description": "...", "quantity": ...}]
    payment_method_preference: str, # e.g., "direct_payment"
    platform_user_id: Optional[str] = None, # Used Optional here
    source_channel: Optional[str] = None    # Used Optional here
) -> dict: # This type hint is fine
    """
    Calls the namdamasco_api service to create an initial lead intent.
    (Function body as you provided)
    """
    base_url = _get_api_base_url()
    headers = _get_api_headers()

    if not base_url or not headers:
        return {"success": False, "data": None, "error_message": "Lead API client is not properly configured (URL or Key missing)."}

    endpoint = f"{base_url}/leads/intent"
    payload = {
        "conversation_id": conversation_id,
        "platform_user_id": platform_user_id,
        "source_channel": source_channel,
        "payment_method_preference": payment_method_preference,
        "products_of_interest": products_of_interest
    }
    
    current_app.logger.info(f"Calling Lead API (Initiate Intent): POST {endpoint}")
    current_app.logger.debug(f"Payload for POST {endpoint}: {json.dumps(payload)}")
    current_app.logger.debug(f"Headers for POST {endpoint}: {json.dumps(headers)}")

    response = None
    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        
        response_data = response.json()
        lead_id = response_data.get("id")
        current_app.logger.info(f"Lead API (Initiate Intent) successful. Lead ID: {lead_id}. Full response: {response_data}")
        return {"success": True, "data": response_data, "error_message": None}
    
    except requests.exceptions.HTTPError as http_err:
        error_details = "No response body"
        status_code_for_error = "N/A"
        if response is not None:
            status_code_for_error = response.status_code
            try: error_details = response.text
            except Exception: current_app.logger.warning("Could not get text from HTTPError response.")
        current_app.logger.error(f"HTTP error calling Lead API (Initiate Intent): {http_err} - Status: {status_code_for_error} - Response: {error_details}")
        return {"success": False, "data": None, "error_message": f"API Error ({status_code_for_error}): {error_details}"}
    except requests.exceptions.RequestException as req_err:
        current_app.logger.error(f"Request exception calling Lead API (Initiate Intent): {req_err}")
        return {"success": False, "data": None, "error_message": f"Connection Error: {req_err}"}
    except Exception as e:
        current_app.logger.error(f"Unexpected error in call_initiate_lead_intent: {e}", exc_info=True)
        return {"success": False, "data": None, "error_message": "An unexpected error occurred creating lead intent."}


def call_submit_customer_details(
    lead_id: str,
    customer_full_name: str,
    customer_email: str,
    customer_phone_number: str
) -> dict: # This type hint is fine
    """
    Calls the namdamasco_api service to submit/update customer contact details for an existing lead.
    (Function body as you provided)
    """
    base_url = _get_api_base_url()
    headers = _get_api_headers()

    if not base_url or not headers:
        return {"success": False, "data": None, "error_message": "Lead API client not configured (URL or Key missing)."}
    if not lead_id:
        current_app.logger.error("call_submit_customer_details called without a lead_id.")
        return {"success": False, "data": None, "error_message": "Lead ID is required to submit customer details."}

    endpoint = f"{base_url}/leads/{lead_id}/customer-details"
    payload = {
        "customer_full_name": customer_full_name,
        "customer_email": customer_email,
        "customer_phone_number": customer_phone_number
    }

    current_app.logger.info(f"Calling Lead API (Submit Details): PUT {endpoint}")
    current_app.logger.debug(f"Payload for PUT {endpoint}: {json.dumps(payload)}")
    current_app.logger.debug(f"Headers for PUT {endpoint}: {json.dumps(headers)}")

    response = None
    try:
        response = requests.put(endpoint, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        
        response_data = response.json()
        current_app.logger.info(f"Lead API (Submit Details) successful for lead {lead_id}. Response: {response_data}")
        return {"success": True, "data": response_data, "error_message": None}

    except requests.exceptions.HTTPError as http_err:
        error_details = "No response body"
        status_code_for_error = "N/A"
        if response is not None:
            status_code_for_error = response.status_code
            try: error_details = response.text
            except Exception: current_app.logger.warning("Could not get text from HTTPError response.")
        current_app.logger.error(f"HTTP error calling Lead API (Submit Details) for lead {lead_id}: {http_err} - Status: {status_code_for_error} - Response: {error_details}")
        return {"success": False, "data": None, "error_message": f"API Error ({status_code_for_error}): {error_details}"}
    except requests.exceptions.RequestException as req_err:
        current_app.logger.error(f"Request exception calling Lead API (Submit Details) for lead {lead_id}: {req_err}")
        return {"success": False, "data": None, "error_message": f"Connection Error: {req_err}"}
    except Exception as e:
        current_app.logger.error(f"Unexpected error in call_submit_customer_details for lead {lead_id}: {e}", exc_info=True)
        return {"success": False, "data": None, "error_message": "An unexpected error occurred submitting customer details."}

# --- End of namwoo_app/services/lead_api_client.py (NamFulgor Version - Type Hints Corrected) ---