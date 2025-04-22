import logging
import datetime
import hmac # For webhook signature validation (optional)
import hashlib # For webhook signature validation (optional)
import json # Added for logging payload nicely

from flask import request, jsonify, current_app, abort
from sqlalchemy import text # Keep for health check
from . import api_bp # Import the blueprint instance

# --- Import necessary services and utilities ---
from ..services import openai_service # Assuming this service exists and has process_new_message
# from ..utils import db_utils # db_utils used only in health check below
from ..utils.db_utils import get_db_session # More specific import for health check
from ..config import Config

logger = logging.getLogger(__name__)

# --- Optional: Helper for Webhook Secret Validation ---
def _validate_sb_webhook_secret(request):
    # ... (validation helper code remains the same) ...
    secret = current_app.config.get('SUPPORT_BOARD_WEBHOOK_SECRET')
    if not secret:
        logger.debug("No SB Webhook Secret configured, skipping validation.")
        return True

    signature_header = request.headers.get('X-Sb-Signature') # Example Header Name
    if not signature_header:
        logger.warning("Webhook secret configured, but 'X-Sb-Signature' header missing.")
        return False

    try:
        method, signature_hash = signature_header.split('=', 1)
        if method != 'sha1':
            logger.warning(f"Unsupported webhook signature method: {method}")
            return False
        # Ensure request.data is bytes for hmac
        request_data_bytes = request.get_data()
        mac = hmac.new(secret.encode('utf-8'), msg=request_data_bytes, digestmod=hashlib.sha1)
        expected_signature = mac.hexdigest()
        if hmac.compare_digest(expected_signature, signature_hash):
            logger.debug("Support Board webhook signature validated successfully.")
            return True
        else:
            logger.warning("Invalid Support Board webhook signature.")
            return False
    except ValueError:
        logger.warning(f"Malformed signature header received: {signature_header}")
        return False
    except Exception as e:
        logger.exception(f"Error during webhook signature validation: {e}")
        return False


# --- NEW: Support Board Webhook Receiver ---
@api_bp.route('/sb-webhook', methods=['POST'])
def handle_support_board_webhook():
    """
    Receives incoming 'message-sent' webhooks from Support Board.
    Parses payload, validates sender is not the bot, extracts source info
    AND customer ID, and triggers AI processing. Responds immediately with 200 OK.
    """
    # 1. (Optional) Validate Signature/Secret
    # if not _validate_sb_webhook_secret(request):
    #     logger.warning("Webhook validation failed.")
    #     abort(401, description="Unauthorized: Invalid webhook signature.")

    # 2. Parse Request Body
    try:
        # Use get_data() first if signature validation is active to ensure raw body is read
        # payload = json.loads(request.get_data(as_text=True)) # Alternative if get_json fails
        payload = request.get_json(force=True) # force=True bypasses content-type check
        if not payload:
            logger.warning("Received empty payload on /sb-webhook endpoint.")
            abort(400, description="Invalid payload: Empty body.")
        logger.info(f"Received SB Webhook Payload: {json.dumps(payload, indent=2)}")
    except Exception as e:
        logger.error(f"Failed to parse request JSON for SB Webhook: {e}", exc_info=True)
        # Log raw data if parsing fails
        try:
            raw_data = request.get_data(as_text=True)
            logger.error(f"Raw request data (first 500 chars): {raw_data[:500]}")
        except Exception:
            logger.error("Could not get raw request data either.")
        abort(400, description="Invalid JSON payload received.")

    # 3. Extract Key Information & Validate Webhook Type
    webhook_function = payload.get('function')
    if webhook_function != 'message-sent': # Adapt if SB uses a different identifier
        logger.debug(f"Ignoring webhook function type: {webhook_function}")
        return jsonify({"status": "ok", "message": "Webhook type ignored"}), 200

    data = payload.get('data', {})

    # --- Extract message details (VERIFY THESE KEYS FROM YOUR LOGS) ---
    sb_conversation_id = data.get('conversation_id')
    sender_user_id = data.get('user_id') # Sender's ID (who sent THIS message)
    new_user_message = data.get('message')
    conversation_source = data.get('conversation_source') # Source channel ('wa', 'ig', etc.)

    # --- MODIFICATION START: Extract the CUSTOMER'S User ID ---
    # This ID represents the user the conversation is primarily associated with (the customer).
    customer_user_id = data.get('conversation_user_id')
    # --- MODIFICATION END ---

    # --- MODIFIED VALIDATION: Include customer_user_id ---
    if not all([sb_conversation_id, sender_user_id, new_user_message, customer_user_id]):
        # Note: message can sometimes be None if it's just an attachment/event, handle downstream if needed
        # Main check is for IDs
        missing_keys = []
        if not sb_conversation_id: missing_keys.append('conversation_id')
        if sender_user_id is None: missing_keys.append('user_id') # Check for None explicitly
        if not customer_user_id: missing_keys.append('conversation_user_id')
        # if new_user_message is None: missing_keys.append('message') # Less critical for routing

        logger.error(f"Missing critical data in SB webhook payload's 'data' section. Missing keys: {missing_keys}. Data received: {data}")
        return jsonify({"status": "error", "message": "Webhook payload missing required fields"}), 200
    # --- END MODIFIED VALIDATION ---


    # 4. Check if Message is from the Bot Itself
    sender_user_id_str = str(sender_user_id)
    customer_user_id_str = str(customer_user_id) # Ensure string for comparison/passing
    bot_user_id_str = Config.SUPPORT_BOARD_BOT_USER_ID

    if not bot_user_id_str:
         logger.critical("FATAL: SUPPORT_BOARD_BOT_USER_ID not configured in Namwoo. Cannot process webhooks reliably.")
         # Consider returning 200 OK anyway to avoid SB retries, but log critically
         return jsonify({"status": "error", "message": "Internal configuration error: Bot User ID missing."}), 200
         # abort(500, description="Internal configuration error: Bot User ID missing.") # Abort might cause retries

    # Log processing details including the customer ID
    logger.info(f"Processing webhook for SB Conv ID: {sb_conversation_id} from Sender: {sender_user_id_str}, Customer: {customer_user_id_str}, Source: {conversation_source}")

    # --- MODIFICATION: Check if sender is the bot OR if sender is the customer we intend to reply to ---
    # We only want to trigger AI processing if the message is from the *customer*
    # (i.e., the sender_user_id matches the conversation_user_id/customer_user_id)
    # AND the sender is NOT the bot itself.
    # This prevents loops if the bot message triggers a webhook, or if an agent replies.

    # Check 1: Is the message from the bot? Ignore.
    if sender_user_id_str == bot_user_id_str:
        logger.info(f"Ignoring own message from bot (User ID: {sender_user_id_str}) in conversation {sb_conversation_id}.")
        return jsonify({"status": "ok", "message": "Bot message ignored"}), 200

    # Check 2: Is the message NOT from the primary customer associated with the conversation? Ignore (e.g. agent replied)
    if sender_user_id_str != customer_user_id_str:
        logger.info(f"Ignoring message in conv {sb_conversation_id} because sender ({sender_user_id_str}) is not the conversation's customer ({customer_user_id_str}). Likely an agent reply.")
        return jsonify({"status": "ok", "message": "Non-customer message ignored"}), 200

    # --- If we reach here, the message is from the customer and not the bot ---

    # 5. Trigger Asynchronous Processing (Recommended for Production)
    try:
        # --- MODIFIED CALL: Pass the CUSTOMER ID explicitly ---
        # ASSUMPTION: openai_service.process_new_message needs to be updated
        # to accept 'customer_user_id' and use it when calling send_reply_to_channel
        openai_service.process_new_message(
            sb_conversation_id=str(sb_conversation_id),
            new_user_message=new_user_message,
            conversation_source=conversation_source, # Pass the source ('wa', 'fb', null, etc.)
            sender_user_id=sender_user_id_str, # User who sent THIS message (the customer in this case)
            customer_user_id=customer_user_id_str # <<< Explicitly pass the CUSTOMER ID
        )
        # --- END MODIFIED CALL ---
    except Exception as e:
        logger.exception(f"Error triggering or during openai_service.process_new_message for SB conv {sb_conversation_id}: {e}")
        # Still return 200 OK to prevent SB retries, error is logged
        return jsonify({"status": "error", "message": "Error occurred during message processing"}), 200

    # 6. Acknowledge Webhook Receipt Immediately
    return jsonify({"status": "ok", "message": "Webhook received and processing initiated"}), 200


# --- Health Check Endpoint (Keep as is) ---
@api_bp.route('/health', methods=['GET'])
def health_check():
    """Simple health check endpoint."""
    logger.debug("Health check endpoint hit.")
    db_ok = False
    try:
        # Use the more specific import
        with get_db_session() as session:
            session.execute(text("SELECT 1"))
            db_ok = True
    except Exception as e:
        logger.error(f"Database health check failed: {e}", exc_info=True)
        db_ok = False
    return jsonify({"status": "ok", "database_connected": db_ok}), 200

# --- Test Endpoint (Keep or remove as needed) ---
@api_bp.route('/supportboard/test', methods=['GET'])
def handle_support_board_test():
    """A simple GET endpoint to test basic connectivity."""
    endpoint_name = "/api/supportboard/test"
    logger.info(f"--- TEST HIT --- Endpoint {endpoint_name} was successfully reached via GET request.")
    response_data = {
        "status": "success",
        "message": f"Namwoo endpoint {endpoint_name} reached successfully!",
        "timestamp": datetime.datetime.utcnow().isoformat()
    }
    # Return a JSON list as per original code example, though a single object is more common
    return jsonify([response_data]), 200