# namwoo_app/api/routes.py (NamFulgor Version - Corrected Imports)

import logging
import datetime
import hmac
import hashlib
import json
from datetime import timedelta, timezone

from flask import request, jsonify, current_app, abort
from sqlalchemy import text

# --- CORRECTED IMPORTS ---
# Assuming /usr/src/app/ (your WORKDIR in Docker) is the root for these packages
from utils import db_utils
from services import openai_service
from services import google_service # Keep if used, otherwise remove
from services import support_board_service
from config.config import Config # Assuming Config class is in namwoo_app/config/config.py
from models.conversation_pause import ConversationPause
# ------------------------------

from . import api_bp # This relative import for the blueprint within the same 'api' package is usually fine

logger = logging.getLogger(__name__) # This logger will be 'namwoo_app.api.routes'

# --- Optional: Helper for Webhook Secret Validation ---
def _validate_sb_webhook_secret(request):
    secret = current_app.config.get('SUPPORT_BOARD_WEBHOOK_SECRET')
    if not secret:
        logger.debug("No SB Webhook Secret configured, skipping validation.")
        return True
    signature_header = request.headers.get('X-Sb-Signature')
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
    # ... (The entire logic of this function remains unchanged as it's generic webhook handling)
    # ... (It now calls services that are battery-aware)
    try:
        payload = request.get_json(force=True)
        if not payload:
            logger.warning("Received empty payload on /sb-webhook endpoint.")
            abort(400, description="Invalid payload: Empty body.")
    except Exception as e:
        logger.error(f"Failed to parse request JSON for SB Webhook: {e}", exc_info=True)
        try: raw_data = request.get_data(as_text=True); logger.error(f"Raw request data (first 500 chars): {raw_data[:500]}")
        except Exception: logger.error("Could not get raw request data either.")
        abort(400, description="Invalid JSON payload received.")

    webhook_function = payload.get('function')
    if webhook_function != 'message-sent':
        logger.debug(f"Ignoring webhook function type: {webhook_function}")
        return jsonify({"status": "ok", "message": "Webhook type ignored"}), 200

    data = payload.get('data', {})
    sb_conversation_id = data.get('conversation_id')
    sender_user_id_str_from_payload = data.get('user_id')
    customer_user_id_str = data.get('conversation_user_id')
    triggering_message_id = data.get('message_id')
    new_user_message_text = data.get('message')
    conversation_source = data.get('conversation_source')

    if not all([sb_conversation_id, sender_user_id_str_from_payload, customer_user_id_str]):
        missing_keys = [k for k, v in {'conversation_id': sb_conversation_id, 'user_id': sender_user_id_str_from_payload, 'conversation_user_id': customer_user_id_str}.items() if v is None]
        logger.error(f"Missing critical ID data in SB webhook payload's 'data' section. Missing keys: {missing_keys}. Data received: {data}")
        return jsonify({"status": "error", "message": "Webhook payload missing required ID fields"}), 200

    sb_conversation_id_str = str(sb_conversation_id)
    sender_user_id_str = str(sender_user_id_str_from_payload)
    customer_user_id_str = str(customer_user_id_str)

    DM_BOT_ID_STR = str(Config.SUPPORT_BOARD_DM_BOT_USER_ID) if Config.SUPPORT_BOARD_DM_BOT_USER_ID else None
    COMMENT_BOT_PROXY_USER_ID_STR = str(Config.COMMENT_BOT_PROXY_USER_ID) if Config.COMMENT_BOT_PROXY_USER_ID else None
    HUMAN_AGENT_IDS_SET = Config.SUPPORT_BOARD_AGENT_IDS
    COMMENT_BOT_INITIATION_TAG = Config.COMMENT_BOT_INITIATION_TAG
    pause_minutes = Config.HUMAN_TAKEOVER_PAUSE_MINUTES

    if not DM_BOT_ID_STR:
         logger.critical("FATAL: SUPPORT_BOARD_DM_BOT_USER_ID not configured correctly.")
         return jsonify({"status": "error", "message": "Internal configuration error: DM Bot User ID missing."}), 200
    
    logger.info(f"Processing webhook for SB Conv ID: {sb_conversation_id_str} from Sender: {sender_user_id_str}, Customer: {customer_user_id_str}, Source: {conversation_source}, Trigger Msg ID: {triggering_message_id}")

    if sender_user_id_str == DM_BOT_ID_STR:
        logger.info(f"Ignoring own message echo from DM bot (ID: {sender_user_id_str}) in conversation {sb_conversation_id_str}.")
        return jsonify({"status": "ok", "message": "Bot message echo ignored"}), 200

    if COMMENT_BOT_PROXY_USER_ID_STR and sender_user_id_str == COMMENT_BOT_PROXY_USER_ID_STR:
        is_comment_bot_message = False
        if COMMENT_BOT_INITIATION_TAG:
            if COMMENT_BOT_INITIATION_TAG in (new_user_message_text or ""):
                is_comment_bot_message = True
            else: # Message from proxy ID, tag configured, but tag NOT found in message. Assume human admin.
                logger.info(f"Message from human admin using proxy ID {sender_user_id_str} (tag configured but NOT found) in conv {sb_conversation_id_str}. Pausing DM Bot.")
                db_utils.pause_conversation_for_duration(sb_conversation_id_str, duration_seconds=pause_minutes * 60)
                return jsonify({"status": "ok", "message": "Human admin (using proxy ID, tag mismatch) message, bot paused"}), 200
        elif COMMENT_BOT_PROXY_USER_ID_STR: # No tag configured, so any message from proxy ID is comment bot
            is_comment_bot_message = True
        
        if is_comment_bot_message:
            logger.info(f"Message from Comment Bot's proxy (ID: {sender_user_id_str}) in conv {sb_conversation_id_str}. DM Bot will not reply to this message.")
            return jsonify({"status": "ok", "message": "Comment bot proxy message processed"}), 200

    if sender_user_id_str in HUMAN_AGENT_IDS_SET:
        logger.info(f"Detected message from dedicated human agent (ID: {sender_user_id_str}) in conversation {sb_conversation_id_str}. Pausing DM bot for {pause_minutes} minutes.")
        try:
            db_utils.pause_conversation_for_duration(sb_conversation_id_str, duration_seconds=pause_minutes * 60)
        except Exception as db_err:
            logger.exception(f"Database error while setting pause for conversation {sb_conversation_id_str}: {db_err}")
        return jsonify({"status": "ok", "message": "Human agent message received, bot paused"}), 200

    if sender_user_id_str == customer_user_id_str:
        logger.debug(f"Message from customer {customer_user_id_str}. Checking pause/intervention status for conv {sb_conversation_id_str}.")
        if db_utils.is_conversation_paused(sb_conversation_id_str):
            logger.info(f"Conversation {sb_conversation_id_str} is explicitly paused in DB. DM Bot will not reply.")
            return jsonify({"status": "ok", "message": "Conversation explicitly paused"}), 200

        conversation_data = support_board_service.get_sb_conversation_data(sb_conversation_id_str)
        is_implicitly_human_handled = False
        if conversation_data and conversation_data.get('messages'):
            for msg in reversed(conversation_data['messages']):
                msg_sender_id_history = str(msg.get('user_id'))
                msg_text_history = msg.get('message', '')
                if msg_sender_id_history == customer_user_id_str: continue
                if msg_sender_id_history == DM_BOT_ID_STR: is_implicitly_human_handled = False; break
                is_hist_comment_bot = False
                if COMMENT_BOT_PROXY_USER_ID_STR and msg_sender_id_history == COMMENT_BOT_PROXY_USER_ID_STR:
                    if COMMENT_BOT_INITIATION_TAG and COMMENT_BOT_INITIATION_TAG in msg_text_history: is_hist_comment_bot = True
                    elif not COMMENT_BOT_INITIATION_TAG: is_hist_comment_bot = True
                if is_hist_comment_bot: is_implicitly_human_handled = False; break
                is_implicitly_human_handled = True
                logger.info(f"Implicit human takeover detected in conv {sb_conversation_id_str}. Last non-bot/non-customer message from: {msg_sender_id_history}. DM Bot will not reply.")
                break
        
        if is_implicitly_human_handled:
            return jsonify({"status": "ok", "message": "Implicit human takeover, bot will not reply"}), 200
        
        provider = current_app.config.get('LLM_PROVIDER', 'openai').lower()
        logger.info(f"Conversation {sb_conversation_id_str} is not paused. Triggering LLM Provider: {provider}.")
        process_args = {
            "sb_conversation_id": sb_conversation_id_str,
            "new_user_message": new_user_message_text,
            "conversation_source": conversation_source,
            "sender_user_id": sender_user_id_str,
            "customer_user_id": customer_user_id_str,
            "triggering_message_id": str(triggering_message_id) if triggering_message_id is not None else None
        }
        try:
            if provider == 'google':
                google_service.process_new_message_gemini(**process_args)
            elif provider == 'openai':
                openai_service.process_new_message(**process_args)
            else:
                logger.error(f"Invalid LLM_PROVIDER configured: '{provider}' for conv {sb_conversation_id_str}.")
                support_board_service.send_reply_to_channel(
                    conversation_id=sb_conversation_id_str,
                    message_text=f"Disculpa, hay un problema de configuración interna (Proveedor IA: {provider}).",
                    source=conversation_source, target_user_id=customer_user_id_str,
                    conversation_details=None, triggering_message_id=process_args["triggering_message_id"]
                )
            return jsonify({"status": "ok", "message": f"Customer message processing initiated via {provider}"}), 200
        except Exception as e:
            logger.exception(f"Error triggering {provider}_service processing for SB conv {sb_conversation_id_str}: {e}")
            support_board_service.send_reply_to_channel(
                 conversation_id=sb_conversation_id_str, message_text="Lo siento, ocurrió un error inesperado al intentar procesar tu mensaje.",
                 source=conversation_source, target_user_id=customer_user_id_str,
                 conversation_details=None, triggering_message_id=process_args["triggering_message_id"]
             )
            return jsonify({"status": "error", "message": "Error occurred during message processing trigger"}), 200
    
    logger.warning(f"Received message in conv {sb_conversation_id_str} from unhandled/unidentified agent {sender_user_id_str}. Assuming human intervention and pausing.")
    try:
        db_utils.pause_conversation_for_duration(sb_conversation_id_str, duration_seconds=pause_minutes * 60)
    except Exception as db_err:
        logger.exception(f"Database error while setting pause for unhandled sender in conversation {sb_conversation_id_str}: {db_err}")
    return jsonify({"status": "ok", "message": "Message from unhandled sender type (assumed agent), bot paused"}), 200


# --- Health Check Endpoint ---
@api_bp.route('/health', methods=['GET'])
def health_check():
    logger.debug("Health check endpoint hit.")
    db_ok = False
    try:
        with db_utils.get_db_session() as session:
            if session: # Check if session is not None
                session.execute(text("SELECT 1"))
                db_ok = True
            else:
                logger.error("Database session not available for health check.")
    except Exception as e:
        logger.error(f"Database health check failed: {e}", exc_info=True)
        db_ok = False
    return jsonify({"status": "ok", "database_connected": db_ok}), 200

# --- Test Endpoint ---
@api_bp.route('/supportboard/test', methods=['GET'])
def handle_support_board_test():
    endpoint_name = "/api/supportboard/test"
    logger.info(f"--- TEST HIT --- Endpoint {endpoint_name} was successfully reached via GET request.")
    response_data = {
        "status": "success",
        "message": f"Namwoo (NamFulgor) endpoint {endpoint_name} reached successfully!",
        "timestamp": datetime.datetime.now(timezone.utc).isoformat()
    }
    return jsonify([response_data]), 200

# --- END OF FILE routes.py (NamFulgor Version - Corrected Imports) ---