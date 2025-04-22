import requests
import logging
import json # Import json module
from flask import current_app
from typing import Optional, List, Dict, Any

# Assuming Config is correctly imported and loads .env variables including SUPPORT_BOARD_SENDER_USER_ID
from ..config import Config # Corrected import path assumed

logger = logging.getLogger(__name__)

# --- PRIVATE HELPER: Make API Call ---
# (Keep _call_sb_api exactly as provided by user)
def _call_sb_api(payload: Dict) -> Optional[Any]: # Changed return type hint
    """Internal helper to make POST requests to the Support Board API."""
    api_url = current_app.config.get('SUPPORT_BOARD_API_URL')
    api_token = current_app.config.get('SUPPORT_BOARD_API_TOKEN')

    if not api_url or not api_token:
        logger.error("Support Board API URL or Token is not configured.")
        return None

    # Ensure token is always sourced from config for security
    payload['token'] = api_token

    function_name = payload.get('function', 'N/A')
    logger.debug(f"Calling SB API URL: {api_url} with function: {function_name}")
    # Mask token before logging payload for security in production environments
    # sensitive_payload = {k: ('***' if k == 'token' else v) for k, v in payload.items()}
    # logger.debug(f"Payload for {function_name}: {sensitive_payload}")
    logger.debug(f"Payload for {function_name}: {payload}") # Keep full payload for debugging for now

    try:
        # Using 'data' assumes form-encoded, which is standard for Support Board API according to docs
        response = requests.post(api_url, data=payload, timeout=20)
        response.raise_for_status()
        response_json = response.json()
        logger.debug(f"Raw SB API response for {function_name}: {response_json}")

        # Check if the top-level 'success' key exists and is True
        if response_json.get("success") is True:
             # Return the nested 'response' value if success is true
             # This value can be a dict, a list, a boolean, or other types depending on the API function
             return response_json.get("response") # Return the actual content under 'response'
        else:
            # Log the specific failure reason provided by the API if available
            error_detail = response_json.get("response", f"API call failed for function '{function_name}' with success=false or missing")
            logger.error(f"Support Board API reported failure for {function_name}: {error_detail}")
            # Return None to indicate failure that was reported by the API itself
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP error calling Support Board API ({function_name}): {e}", exc_info=True)
        return None
    except requests.exceptions.JSONDecodeError as e:
        raw_text = getattr(response, 'text', 'N/A')
        logger.error(f"Failed to decode JSON response from Support Board API ({function_name}): {e}. Response text: {raw_text[:500]}", exc_info=True)
        return None
    except Exception as e:
        # Catch any other unexpected errors during the API call process
        logger.exception(f"Unexpected error calling SB API ({function_name}): {e}")
        return None


# --- Public Function: Get Conversation Data ---
# (Keep get_sb_conversation_data exactly as provided by user)
def get_sb_conversation_data(conversation_id: str) -> Optional[Dict]:
    """
    Fetches the full conversation data object from the Support Board API,
    including messages and details.
    """
    payload = {
        'function': 'get-conversation',
        'conversation_id': conversation_id
        # token will be added by _call_sb_api
    }
    logger.info(f"Attempting to fetch full conversation data from Support Board API for ID: {conversation_id}")
    response_data = _call_sb_api(payload)

    # The actual response data is now returned directly by _call_sb_api on success
    if isinstance(response_data, dict):
        # Check specifically for the keys expected in a successful 'get-conversation' response
        if "messages" in response_data and "details" in response_data:
            logger.info(f"Successfully fetched conversation data for SB conversation {conversation_id}")
            return response_data
        else:
            # Log even if it's technically successful according to API but missing expected keys
            logger.warning(f"SB API get-conversation success reported, but response for {conversation_id} might be incomplete or malformed. Response: {response_data}")
            # Return the data received, let caller decide if it's usable
            return response_data
    else:
        # This handles None from _call_sb_api (API error or success=false) or unexpected non-dict types
        logger.error(f"Failed to fetch or parse valid conversation data dictionary for SB conversation {conversation_id}. Raw response from _call_sb_api call was not a valid dictionary: {response_data}")
        return None


# --- PRIVATE HELPER: Get User Phone Number ---
# (Keep _get_user_phone exactly as provided by user)
def _get_user_phone(user_id: str) -> Optional[str]:
    """Fetches user details from SB API and extracts the phone number."""
    logger.info(f"Attempting to fetch user details for User ID: {user_id} to get phone number.")
    payload = {'function': 'get-user', 'user_id': user_id, 'extra': 'true'}
    user_data = _call_sb_api(payload) # _call_sb_api now returns the 'response' part directly or None

    if user_data and isinstance(user_data, dict):
        details_list = user_data.get('details', [])
        if isinstance(details_list, list):
            for detail in details_list:
                # Check if detail is a dictionary before accessing keys
                if isinstance(detail, dict) and detail.get('slug') == 'phone':
                    phone_number = detail.get('value')
                    # Check if phone_number is a non-empty string
                    if phone_number and isinstance(phone_number, str) and phone_number.strip():
                        logger.info(f"Found phone number for User ID {user_id}")
                        # Optional: Check for '+' prefix and log warning if missing
                        if not phone_number.startswith('+'):
                            logger.warning(f"Phone number '{phone_number}' for user {user_id} might be missing country code prefix (+).")
                        return phone_number.strip()
                    else:
                        # Log if phone slug found but value is empty/invalid
                        logger.warning(f"Found 'phone' detail slug for user {user_id} but its value is empty or invalid: '{phone_number}'")
            # Log if loop completes without finding the 'phone' slug
            logger.warning(f"Could not find detail with slug 'phone' in the details list for User ID: {user_id}. Details received: {details_list}")
            return None # Explicitly return None if phone slug not found
        else:
            logger.warning(f"User details for {user_id} received, but 'details' key is not a list: {details_list}")
            return None
    else:
        # Handles case where _call_sb_api returned None or non-dict data
        logger.error(f"Failed to fetch or parse valid user details dictionary for User ID: {user_id} needed for phone lookup.")
        return None

# --- PRIVATE HELPER: Get User PSID (Verified Slug Usage) ---
# (Keep _get_user_psid exactly as provided by user)
def _get_user_psid(user_id: str) -> Optional[str]:
    """Fetches user details from SB API and extracts the Facebook/Instagram PSID."""
    logger.info(f"Attempting to fetch user details for User ID: {user_id} to get PSID.")
    payload = {'function': 'get-user', 'user_id': user_id, 'extra': 'true'}
    user_data = _call_sb_api(payload) # _call_sb_api now returns the 'response' part directly or None

    if user_data and isinstance(user_data, dict):
        details_list = user_data.get('details', [])
        # !!! VERIFICATION NEEDED !!!
        # Confirm if 'facebook-id' is the correct slug used by Support Board
        # for BOTH Facebook Messenger PSIDs AND Instagram PSIDs. If they differ,
        # this logic needs adjustment based on the conversation source ('fb' vs 'ig').
        expected_slug = 'facebook-id'
        if isinstance(details_list, list):
            for detail in details_list:
                if isinstance(detail, dict) and detail.get('slug') == expected_slug:
                    psid = detail.get('value')
                    if psid and isinstance(psid, str) and psid.strip():
                        logger.info(f"Found PSID (using slug '{expected_slug}') for User ID {user_id}")
                        return psid.strip()
                    else:
                        logger.warning(f"Found '{expected_slug}' detail slug for user {user_id} but its value is empty or invalid: '{psid}'")
            # Log if loop completes without finding the slug
            logger.warning(f"Could not find PSID using slug '{expected_slug}' in the details list for User ID: {user_id}. Details received: {details_list}")
            return None # Explicitly return None if slug not found
        else:
             logger.warning(f"User details for {user_id} received, but 'details' key is not a list: {details_list}")
             return None
    else:
        logger.error(f"Failed to fetch or parse valid user details dictionary for User ID: {user_id} needed for PSID lookup.")
        return None


# --- PRIVATE HELPER: Send Internal SB Message (Corrected Success Check) ---
# (Keep _send_internal_sb_message exactly as provided by user, using Config.SUPPORT_BOARD_BOT_USER_ID)
def _send_internal_sb_message(conversation_id: str, message_text: str) -> bool:
    """Sends a message internally within Support Board (e.g., to web chat)."""
    bot_user_id = Config.SUPPORT_BOARD_BOT_USER_ID # <--- REMAINS UNCHANGED
    if not bot_user_id:
        logger.error("Cannot send internal SB message: Bot User ID not configured.")
        return False

    logger.info(f"Sending internal SB message to conversation ID: {conversation_id}")
    payload = {
        'function': 'send-message',
        'user_id': bot_user_id, # <--- REMAINS UNCHANGED
        'conversation_id': conversation_id,
        'message': message_text,
        'attachments': json.dumps([]) # Ensure empty attachments are sent as valid JSON array string
    }
    response_data = _call_sb_api(payload) # _call_sb_api returns the 'response' content or None

    # Check the structure of a successful 'send-message' response based on Page 5 docs
    # Expected: {"id": 123, "queue": false, ...} or {"message-id": 123, ...}
    if isinstance(response_data, dict) and ('id' in response_data or 'message-id' in response_data):
        message_id_from_resp = response_data.get('id', response_data.get('message-id', 'N/A'))
        logger.info(f"Internal SB message sent successfully (API Resp Msg ID: {message_id_from_resp}) to conversation {conversation_id}")
        return True
    else:
        # Handle cases where the API might just return boolean `True` (less likely based on docs)
        # Or if the structure is unexpected despite 'success':true from parent call
        if response_data is True:
             logger.info(f"Internal SB message sent successfully (API Reported 'response': True) to conversation {conversation_id}")
             return True
        logger.error(f"Failed to send internal SB message to conversation {conversation_id}. API did not return expected confirmation structure. Response from _call_sb_api: {response_data}")
        return False


# --- MODIFIED PRIVATE HELPER: Send WhatsApp Message (Uses SENDER_USER_ID) ---
def _send_whatsapp_message(message_text: str, conversation_id: str) -> bool:
    """
    Sends a WhatsApp message using the unified Support Board
    messaging-platforms-send-message API. Uses configured SENDER_USER_ID.
    """
    # --- MODIFICATION START ---
    # Use the configured SENDER User ID from .env via Flask app config
    sender_user_id = current_app.config.get('SUPPORT_BOARD_SENDER_USER_ID')
    # Check if the sender ID is configured
    if not sender_user_id:
        logger.error("Cannot send WhatsApp message: SUPPORT_BOARD_SENDER_USER_ID not configured in .env or Flask app config.")
        return False
    # --- MODIFICATION END ---

    # Log which user is sending the message
    logger.info(f"Attempting to send WhatsApp message via unified SB API for Conversation ID: {conversation_id} AS User ID: {sender_user_id}")

    # Keep existing source/attachment formatting logic
    source_payload = {"source": "wa"}
    try:
        source_json_string = json.dumps(source_payload)
        attachments_json_string = json.dumps([])
    except Exception as e:
        logger.error(f"Failed to serialize source or attachments payload for WhatsApp: {e}", exc_info=True)
        return False

    payload = {
        'function': 'messaging-platforms-send-message',
        'conversation_id': conversation_id,
        'message': message_text,
        'user': sender_user_id,  # <--- MODIFIED: Use the configured sender ID
        'source': source_json_string,
        'attachments': attachments_json_string
    }
    response_data = _call_sb_api(payload)

    # Keep existing success check logic
    if response_data is True:
        logger.info(f"WhatsApp message API call acknowledged as successful by SB API for conversation {conversation_id} via messaging-platforms-send-message.")
        return True
    else:
        logger.error(f"Failed to send WhatsApp message via messaging-platforms-send-message for conversation {conversation_id}. Response from _call_sb_api: {response_data}")
        return False

# --- REVISED PRIVATE HELPER: Send Messenger/Instagram Message (Corrected Success Check) ---
# (Keep _send_messenger_message exactly as provided by user, using Config.SUPPORT_BOARD_BOT_USER_ID for error check)
def _send_messenger_message(psid: str, page_id: str, message_text: str, conversation_id: str) -> bool:
    """
    Sends a Messenger/IG message using the specific messenger-send-message API function.
    Includes conversation_id for better logging.
    """
    bot_user_id = Config.SUPPORT_BOARD_BOT_USER_ID # <--- REMAINS UNCHANGED
    if not bot_user_id:
        logger.error(f"Cannot send Messenger/IG message for conv {conversation_id}: Bot User ID not configured.")
        # Return False as sending is impossible without sender context
        return False

    logger.info(f"Attempting to send Messenger/IG message via specific SB API for Conv ID {conversation_id} to PSID: ...{psid[-6:]} on Page ID: {page_id}")
    payload = {
        'function': 'messenger-send-message',
        'psid': psid,
        'facebook_page_id': page_id,
        'message': message_text
        # Attachments are not explicitly listed for this function in docs, assuming basic text send
        # If attachments are needed, verify the required format for this specific function
    }
    response_data = _call_sb_api(payload) # _call_sb_api returns the 'response' content or None

    # FIX 1: Correctly check the response structure for messenger-send-message success (Page 11)
    # Expected: A list containing a dictionary with 'recipient_id' and 'message_id'
    # Example: [{'recipient_id': '...', 'message_id': '...'}]
    if isinstance(response_data, list) and len(response_data) > 0 and isinstance(response_data[0], dict) and \
       'recipient_id' in response_data[0] and 'message_id' in response_data[0]:
        fb_message_id = response_data[0].get('message_id', 'N/A')
        logger.info(f"Messenger/IG message acknowledged as successful by SB API (FB Msg ID: {fb_message_id}) for Conv ID {conversation_id} to PSID ...{psid[-6:]}")
        # NOTE: This *doesn't* guarantee delivery, just that SB processed the request and got a response from Meta.
        return True
    else:
        # Handle other cases (e.g., response might be boolean True if docs are inconsistent/incomplete)
        if response_data is True:
             logger.warning(f"Messenger/IG message API call for Conv ID {conversation_id} returned 'True', which differs from documented structure, but treating as success.")
             return True
        # Log the actual unexpected response
        logger.error(f"Failed to send Messenger/IG message via SB API for Conv ID {conversation_id} to PSID ...{psid[-6:]}. Unexpected response structure from _call_sb_api: {response_data}")
        return False


# --- REVISED PUBLIC FUNCTION: Send Reply via Appropriate Channel ---
# (Keep send_reply_to_channel exactly as provided by user, calling the modified _send_whatsapp_message)
def send_reply_to_channel(
    conversation_id: str,
    message_text: str,
    source: Optional[str],
    target_user_id: str, # This MUST be the CUSTOMER's user ID
    conversation_details: Optional[Dict] # Pass this in if already fetched
) -> bool:
    """
    Routes and sends a reply message to the appropriate channel based on the source.

    Args:
        conversation_id: The Support Board conversation ID.
        message_text: The text message to send.
        source: The source channel ('wa', 'fb', 'ig', 'web', etc.).
        target_user_id: The Support Board User ID of the CUSTOMER receiving the reply.
        conversation_details: Full conversation data including details (optional, fetched if needed).

    Returns:
        True if the message sending API call was acknowledged as successful by SB, False otherwise.
    """
    if not message_text or not message_text.strip():
        logger.warning(f"Attempted to send empty reply to conversation {conversation_id}. Skipping.")
        return False

    # Ensure conversation details are available if needed (for page_id)
    if not conversation_details:
        logger.info(f"Conversation details not provided for {conversation_id}, fetching...")
        conversation_details = get_sb_conversation_data(conversation_id)
        if not conversation_details:
            logger.error(f"Cannot send reply to conv {conversation_id}: Failed to fetch conversation details.")
            # Cannot determine page_id if needed, cannot proceed reliably
            return False # Indicate failure

    # Determine effective source, default to 'web' if missing or invalid
    effective_source = source.strip().lower() if isinstance(source, str) and source.strip() else 'web'

    # FIX 2: LOGIC NOW ASSUMES target_user_id *IS* the customer. The caller (e.g. webhook handler)
    # must ensure this is correct. We proceed based on this assumption.
    logger.info(f"Routing reply for conversation {conversation_id} to target customer User ID {target_user_id} via effective source channel '{effective_source}'")

    if effective_source == 'wa':
        # Attempt to send via the unified API (this now uses the configured SENDER_USER_ID)
        success = _send_whatsapp_message(message_text, conversation_id)
        if not success:
            logger.error(f"Failed to send WhatsApp reply via API for conv {conversation_id}. Falling back to internal message.")
            # Send fallback message internally (uses original Config.SUPPORT_BOARD_BOT_USER_ID)
            _send_internal_sb_message(conversation_id, f"[Info para Agente: Fallo al enviar API a WhatsApp msg: {message_text}]")
            return False # Return failure for the overall operation
        return True # Return success for the overall operation

    elif effective_source in ['fb', 'ig']: # Group FB/IG as they use the same mechanism (PSID)
        psid = _get_user_psid(target_user_id) # Get PSID for the *customer*

        # Get Page ID - Assuming it's stored in 'extra' field of conversation details
        # !!! VERIFICATION NEEDED: Confirm where SB stores the Page ID for FB/IG convos !!!
        page_id = conversation_details.get('details', {}).get('extra')
        page_id_str = str(page_id).strip() if page_id else None

        if psid and page_id_str:
            # Attempt to send via the messenger-specific API (uses original Config.SUPPORT_BOARD_BOT_USER_ID for error check only)
            success = _send_messenger_message(psid, page_id_str, message_text, conversation_id)
            if not success:
                logger.error(f"Failed to send {effective_source.upper()} reply via API for conv {conversation_id}. Falling back to internal message.")
                # Send fallback message internally (uses original Config.SUPPORT_BOARD_BOT_USER_ID)
                _send_internal_sb_message(conversation_id, f"[Info para Agente: Fallo al enviar API a {effective_source.upper()} msg: {message_text}]")
                return False # Return failure for the overall operation
            return True # Return success for the overall operation
        else:
            # Log specific reason for failure (missing PSID or Page ID)
            error_details_list = []
            if not psid: error_details_list.append("PSID not found for user " + target_user_id)
            if not page_id_str: error_details_list.append("Page ID not found in conversation details 'extra' field")
            reason = ", ".join(error_details_list)
            logger.error(f"Cannot send {effective_source.upper()} reply to conv {conversation_id}: {reason}.")
            logger.warning(f"Falling back to internal message for conv {conversation_id}.")
            # Send fallback message internally with reason (uses original Config.SUPPORT_BOARD_BOT_USER_ID)
            _send_internal_sb_message(conversation_id, f"[Info para Agente: No se pudo enviar a {effective_source.upper()} ({reason}) msg: {message_text}]")
            return False # Return failure for the overall operation

    # Handle Web Chat and any other unhandled source
    else:
        if effective_source != 'web':
            logger.warning(f"Unhandled conversation source '{effective_source}' for conv {conversation_id}. Sending reply as internal SB message (web chat).")
        else:
            logger.info(f"Source is 'web' (or None/empty) for conv {conversation_id}. Sending internal SB message.")
        # Send using the internal message function (uses original Config.SUPPORT_BOARD_BOT_USER_ID)
        success = _send_internal_sb_message(conversation_id, message_text)
        # Return the success status of the internal send operation
        return success