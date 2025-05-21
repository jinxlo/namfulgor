# --- START OF FILE routes.py ---

import logging
import datetime
import hmac
import hashlib
import json
from datetime import timedelta, timezone

from flask import request, jsonify, current_app, abort
from sqlalchemy import text
# Import necessary SQLAlchemy components for session management
from ..utils.db_utils import get_db_session
# --- Import BOTH LLM Services ---
from ..services import openai_service
from ..services import google_service
# --- Import Support Board service if needed for error replies ---
from ..services import support_board_service
# ------------------------------
from ..config import Config
from ..models.conversation_pause import ConversationPause

from . import api_bp

logger = logging.getLogger(__name__)

# --- Optional: Helper for Webhook Secret Validation ---
# ... (keep _validate_sb_webhook_secret as is - unchanged) ...
def _validate_sb_webhook_secret(request):
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


# --- Support Board Webhook Receiver ---
@api_bp.route('/sb-webhook', methods=['POST'])
def handle_support_board_webhook():
    """
    Receives 'message-sent' webhooks.
    - Ignores bot's own message echoes.
    - If message is from a HUMAN AGENT, pauses bot replies for that convo.
    - If message is from CUSTOMER, checks pause state before triggering AI.
    - Chooses LLM provider based on configuration.
    """
    # 1. (Optional) Validate Signature
    # if not _validate_sb_webhook_secret(request):
    #     abort(401, description="Unauthorized: Invalid webhook signature.")

    # 2. Parse Request Body
    # ... (parsing logic remains unchanged) ...
    try:
        payload = request.get_json(force=True)
        if not payload:
            logger.warning("Received empty payload on /sb-webhook endpoint.")
            abort(400, description="Invalid payload: Empty body.")
        logger.info(f"Received SB Webhook Payload: {json.dumps(payload, indent=2)}")
    except Exception as e:
        logger.error(f"Failed to parse request JSON for SB Webhook: {e}", exc_info=True)
        try: raw_data = request.get_data(as_text=True); logger.error(f"Raw request data (first 500 chars): {raw_data[:500]}")
        except Exception: logger.error("Could not get raw request data either.")
        abort(400, description="Invalid JSON payload received.")


    # 3. Extract Key Information & Validate Type
    # ... (webhook function check remains unchanged) ...
    webhook_function = payload.get('function')
    if webhook_function != 'message-sent':
        logger.debug(f"Ignoring webhook function type: {webhook_function}")
        return jsonify({"status": "ok", "message": "Webhook type ignored"}), 200

    data = payload.get('data', {})

    # --- Extract IDs and other data ---
    # ... (extraction remains unchanged) ...
    sb_conversation_id = data.get('conversation_id')
    sender_user_id = data.get('user_id')
    customer_user_id = data.get('conversation_user_id')
    triggering_message_id = data.get('message_id')
    new_user_message = data.get('message')
    conversation_source = data.get('conversation_source')

    # --- Basic ID Validation ---
    # ... (validation remains unchanged) ...
    if not all([sb_conversation_id, sender_user_id, customer_user_id]):
        missing_keys = [k for k, v in {'conversation_id': sb_conversation_id, 'user_id': sender_user_id, 'conversation_user_id': customer_user_id}.items() if v is None]
        logger.error(f"Missing critical ID data in SB webhook payload's 'data' section. Missing keys: {missing_keys}. Data received: {data}")
        return jsonify({"status": "error", "message": "Webhook payload missing required ID fields"}), 200

    # --- Convert IDs and Get Config ---
    # ... (conversion logic remains unchanged) ...
    try:
        sb_conversation_id_str = str(sb_conversation_id)
        sender_user_id_int = int(sender_user_id)
        customer_user_id_str = str(customer_user_id)
        bot_user_id_int = int(Config.SUPPORT_BOARD_BOT_USER_ID) if Config.SUPPORT_BOARD_BOT_USER_ID else None
        agent_ids_set = Config.SUPPORT_BOARD_AGENT_IDS
        pause_minutes = Config.HUMAN_TAKEOVER_PAUSE_MINUTES
    except (ValueError, TypeError) as e:
        logger.error(f"Error converting IDs/Config to expected types: {e}. Payload data: {data}")
        return jsonify({"status": "error", "message": "Invalid ID or Config format"}), 200

    if bot_user_id_int is None:
         logger.critical("FATAL: SUPPORT_BOARD_BOT_USER_ID not configured correctly.")
         return jsonify({"status": "error", "message": "Internal configuration error: Bot User ID missing."}), 200
    if not agent_ids_set:
         logger.warning("SUPPORT_BOARD_AGENT_IDS is empty. Human takeover pause feature will not activate.")

    logger.info(f"Processing webhook for SB Conv ID: {sb_conversation_id_str} from Sender: {sender_user_id_int}, Customer: {customer_user_id_str}, Source: {conversation_source}, Trigger Msg ID: {triggering_message_id}")

    # --- Check 1: Ignore Bot's Own Message Echo ---
    # ... (logic remains unchanged) ...
    if sender_user_id_int == bot_user_id_int:
        logger.info(f"Ignoring own message echo from bot (User ID: {sender_user_id_int}) in conversation {sb_conversation_id_str}.")
        return jsonify({"status": "ok", "message": "Bot message echo ignored"}), 200

    # --- Check 2: Is the message from a configured HUMAN AGENT? ---
    # ... (pause logic remains unchanged) ...
    if agent_ids_set and sender_user_id_int in agent_ids_set:
        logger.info(f"Detected message from human agent (ID: {sender_user_id_int}) in conversation {sb_conversation_id_str}. Pausing bot for {pause_minutes} minutes.")
        try:
            with get_db_session() as session:
                pause_until_time = datetime.datetime.now(timezone.utc) + timedelta(minutes=pause_minutes)
                pause_record = ConversationPause(conversation_id=sb_conversation_id_str, paused_until=pause_until_time)
                session.merge(pause_record)
                session.commit()
                logger.info(f"Successfully set/updated pause via merge for conversation {sb_conversation_id_str} until {pause_until_time.isoformat()}.")
        except Exception as db_err:
            logger.exception(f"Database error while setting pause for conversation {sb_conversation_id_str}: {db_err}")
            return jsonify({"status": "error", "message": "DB error setting pause"}), 200 # Or 500
        return jsonify({"status": "ok", "message": "Agent message received, bot paused"}), 200

    # --- Check 3: Is the message from the CUSTOMER? Check for active pause ---
    # ... (customer check and pause check logic remains unchanged) ...
    is_customer = False
    try:
        if sender_user_id_int == int(customer_user_id_str):
            is_customer = True
    except (ValueError, TypeError):
         if str(sender_user_id_int) == customer_user_id_str:
             is_customer = True

    if is_customer:
        logger.debug(f"Message appears to be from customer {customer_user_id_str}. Checking pause status for conv {sb_conversation_id_str}.")
        is_paused = False
        try:
            with get_db_session() as session:
                now_utc = datetime.datetime.now(timezone.utc)
                pause_record = session.query(ConversationPause)\
                    .filter(ConversationPause.conversation_id == sb_conversation_id_str)\
                    .filter(ConversationPause.paused_until > now_utc)\
                    .first()
                if pause_record:
                    is_paused = True
                    logger.info(f"Conversation {sb_conversation_id_str} is currently paused by agent interaction until {pause_record.paused_until.isoformat()}. Skipping bot reply.")
        except Exception as db_err:
            logger.exception(f"Database error while checking pause status for conversation {sb_conversation_id_str}: {db_err}")
            is_paused = False
            logger.warning(f"Database error during pause check for conv {sb_conversation_id_str}. Proceeding as if not paused.")

        # --- >>> MODIFICATION START: Choose LLM Provider and Trigger Processing <<< ---
        if not is_paused:
            provider = current_app.config.get('LLM_PROVIDER', 'openai').lower()
            logger.info(f"Conversation {sb_conversation_id_str} is not paused. Triggering processing using LLM Provider: {provider}.")

            # Prepare common arguments
            process_args = {
                "sb_conversation_id": sb_conversation_id_str,
                "new_user_message": new_user_message,
                "conversation_source": conversation_source,
                "sender_user_id": str(sender_user_id_int), # Pass sender ID as string
                "customer_user_id": customer_user_id_str,
                "triggering_message_id": str(triggering_message_id) if triggering_message_id is not None else None
            }

            try:
                if provider == 'google':
                    # Check if Google SDK is actually available (important!)
                    # The google_service module now handles this check internally if needed
                    # or provides a stub if not available. Let's call it directly.
                    # The check below is now less critical here, but kept for defense.
                    if not hasattr(google_service, 'GOOGLE_SDK_AVAILABLE') or not google_service.GOOGLE_SDK_AVAILABLE:
                        logger.error(f"LLM_PROVIDER set to 'google' but Google SDK is not installed or import failed for conv {sb_conversation_id_str}.")
                        # Send error message back to user via SB
                        support_board_service.send_reply_to_channel(
                             conversation_id=sb_conversation_id_str,
                             message_text="Disculpa, hay un problema técnico con el servicio de IA (Google SDK no encontrado).",
                             source=conversation_source,
                             target_user_id=customer_user_id_str,
                             conversation_details=None, # PATCH APPLIED HERE
                             triggering_message_id=process_args["triggering_message_id"]
                         )
                        return jsonify({"status": "error", "message": "Google SDK not available"}), 200 # Return 200 to ACK webhook

                    # Call the Google service function
                    logger.debug(f"Calling google_service.process_new_message_gemini with args: {process_args}")
                    google_service.process_new_message_gemini(**process_args)

                elif provider == 'openai':
                    # Call the OpenAI service function
                    logger.debug(f"Calling openai_service.process_new_message with args: {process_args}")
                    openai_service.process_new_message(**process_args)

                else:
                    logger.error(f"Invalid LLM_PROVIDER configured: '{provider}' for conv {sb_conversation_id_str}.")
                    # Send error message back to user via SB
                    support_board_service.send_reply_to_channel(
                        conversation_id=sb_conversation_id_str,
                        message_text=f"Disculpa, hay un problema de configuración interna (Proveedor IA: {provider}).",
                        source=conversation_source,
                        target_user_id=customer_user_id_str,
                        conversation_details=None, # PATCH APPLIED HERE
                        triggering_message_id=process_args["triggering_message_id"]
                    )
                    return jsonify({"status": "error", "message": f"Invalid LLM provider: {provider}"}), 200 # Return 200 to ACK webhook

                # If either service call was made successfully (doesn't mean processing finished yet)
                return jsonify({"status": "ok", "message": f"Customer message received, not paused, processing initiated via {provider}"}), 200

            except Exception as e:
                logger.exception(f"Error triggering {provider}_service processing for SB conv {sb_conversation_id_str}: {e}")
                # Send generic error message back to user via SB
                support_board_service.send_reply_to_channel(
                     conversation_id=sb_conversation_id_str,
                     message_text="Lo siento, ocurrió un error inesperado al intentar procesar tu mensaje.",
                     source=conversation_source,
                     target_user_id=customer_user_id_str,
                     conversation_details=None, # PATCH APPLIED HERE
                     triggering_message_id=process_args["triggering_message_id"]
                 )
                return jsonify({"status": "error", "message": "Error occurred during message processing trigger"}), 200 # Return 200 to ACK webhook
        else:
             # Conversation is paused
             return jsonify({"status": "ok", "message": "Bot currently paused for this conversation"}), 200
        # --- >>> MODIFICATION END <<< ---

    # --- Handle other sender types ---
    # ... (logic remains unchanged) ...
    else:
        logger.warning(f"Received message in conv {sb_conversation_id_str} from sender {sender_user_id_int} who is not the bot, not a known agent, and not the primary customer {customer_user_id_str}. Ignoring.")
        return jsonify({"status": "ok", "message": "Message from unhandled sender type ignored"}), 200


# --- Health Check Endpoint (Keep as is) ---
# ... (health_check function remains unchanged) ...
@api_bp.route('/health', methods=['GET'])
def health_check():
    """Simple health check endpoint."""
    logger.debug("Health check endpoint hit.")
    db_ok = False
    try:
        with get_db_session() as session:
            session.execute(text("SELECT 1"))
            db_ok = True
    except Exception as e:
        logger.error(f"Database health check failed: {e}", exc_info=True)
        db_ok = False
    return jsonify({"status": "ok", "database_connected": db_ok}), 200

# --- Test Endpoint (Keep or remove as needed) ---
# ... (handle_support_board_test function remains unchanged) ...
@api_bp.route('/supportboard/test', methods=['GET'])
def handle_support_board_test():
    """A simple GET endpoint to test basic connectivity."""
    endpoint_name = "/api/supportboard/test"
    logger.info(f"--- TEST HIT --- Endpoint {endpoint_name} was successfully reached via GET request.")
    response_data = {
        "status": "success",
        "message": f"Namwoo endpoint {endpoint_name} reached successfully!",
        "timestamp": datetime.datetime.now(timezone.utc).isoformat()
    }
    return jsonify([response_data]), 200