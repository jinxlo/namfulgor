# NAMWOO/services/google_service.py (NamFulgor Version - STRICTLY ONLY IMPORT CHANGED)
# -*- coding: utf-8 -*-
import logging
import json
import time # Kept as it was in your original file
from typing import List, Dict, Optional, Tuple, Union, Any

from openai import ( # This lib is used for the OpenAI-compatible Gemini endpoint
    OpenAI,
    APIError,
    RateLimitError,
    APITimeoutError,
    BadRequestError,
)
from flask import current_app # Kept as it was in your original file

# ── Local services ──────────────────────────────────────────────────────────────
# These sibling imports are correct and remain unchanged
from . import product_service # This is your refactored battery catalog service
from . import support_board_service
# from . import lead_api_client # Assuming lead_api_client.py is also a sibling in services/

# --- CORRECTED IMPORT ---
# Assuming Config class is defined in namwoo_app/config/config.py
from config.config import Config
# --------------------------
# from ..utils.text_utils import strip_html_to_text # This was already commented out in your version

logger = logging.getLogger(__name__) # Logger will be 'namwoo_app.services.google_service'

# ── Initialise OpenAI‑compatible client that talks to Google Gemini ────────────
# (All subsequent code in this file remains EXACTLY as you provided it)
# (It correctly uses the Config object that is now imported correctly)
google_gemini_client_via_openai_lib: Optional[OpenAI] = None
GOOGLE_SDK_AVAILABLE = False

try:
    google_api_key = Config.GOOGLE_API_KEY
    google_base_url_for_openai_lib = "https://generativelanguage.googleapis.com/v1beta/openai/"

    if google_api_key:
        timeout_seconds = getattr(Config, 'GOOGLE_REQUEST_TIMEOUT', 60.0)
        google_gemini_client_via_openai_lib = OpenAI(
            api_key=google_api_key,
            base_url=google_base_url_for_openai_lib,
            timeout=timeout_seconds,
        )
        logger.info(
            "OpenAI-lib client initialised for Google Gemini at %s with timeout %s.",
            google_base_url_for_openai_lib, timeout_seconds
        )
        GOOGLE_SDK_AVAILABLE = True
    else:
        logger.error("GOOGLE_API_KEY not configured. Gemini service (via OpenAI lib) disabled.")
        GOOGLE_SDK_AVAILABLE = False
except Exception as e:
    logger.exception(f"Failed to initialise Google Gemini client (via OpenAI lib): {e}")
    google_gemini_client_via_openai_lib = None
    GOOGLE_SDK_AVAILABLE = False

# ── Constants ───────────────────────────────────────────────────────────────────
MAX_HISTORY_MESSAGES = Config.MAX_HISTORY_MESSAGES if hasattr(Config, 'MAX_HISTORY_MESSAGES') else 10
TOOL_CALL_RETRY_LIMIT = 2
DEFAULT_GOOGLE_MODEL = Config.GOOGLE_GEMINI_MODEL if hasattr(Config, 'GOOGLE_GEMINI_MODEL') else "gemini-1.5-flash-latest"
DEFAULT_MAX_TOKENS = Config.GOOGLE_MAX_TOKENS if hasattr(Config, 'GOOGLE_MAX_TOKENS') else 1024
DEFAULT_GOOGLE_TEMPERATURE = getattr(Config, "GOOGLE_TEMPERATURE", 0.7)

# --- PRODUCT DESCRIPTION SUMMARIZATION (using Google Gemini via OpenAI lib) ---
def get_google_product_summary(
    plain_text_description: str,
    item_name: Optional[str] = None
) -> Optional[str]:
    global google_gemini_client_via_openai_lib
    if not GOOGLE_SDK_AVAILABLE or not google_gemini_client_via_openai_lib:
        logger.error("Google Gemini client not available. Cannot summarize description with Google.")
        return None
    if not plain_text_description or not plain_text_description.strip():
        logger.debug("Google summarizer: No plain text description provided to summarize.")
        return None

    prompt_context_parts = []
    if item_name:
        prompt_context_parts.append(f"Nombre del Producto: {item_name}")
    prompt_context_parts.append(f"Descripción Original (texto plano):\n{plain_text_description}")
    prompt_context = "\n".join(prompt_context_parts)

    system_prompt_for_gemini = (
        "Eres un redactor experto en comercio electrónico. Resume la siguiente descripción de producto. "
        "El resumen debe ser conciso (objetivo: 50-75 palabras, 2-3 frases clave), resaltar los principales beneficios y características, y ser factual. "
        "Evita la jerga de marketing, la repetición y frases como 'este producto es'. "
        "La salida debe ser texto plano adecuado para una base de datos de productos y un asistente de IA. "
        "No incluyas etiquetas HTML."
    )

    max_input_chars_for_summary = 3000
    if len(prompt_context) > max_input_chars_for_summary:
        cutoff_point = prompt_context.rfind('.', 0, max_input_chars_for_summary)
        if cutoff_point == -1: cutoff_point = max_input_chars_for_summary
        prompt_context = prompt_context[:cutoff_point] + " [DESCRIPCIÓN TRUNCADA]"
        logger.warning(f"Google summarizer: Description for '{item_name or 'Unknown'}' was truncated for prompt construction.")

    messages_for_api = [
        {"role": "system", "content": system_prompt_for_gemini},
        {"role": "user", "content": f"Por favor, resume la siguiente información del producto:\n\n{prompt_context}"}
    ]

    gemini_model_name = getattr(Config, "GOOGLE_SUMMARY_MODEL", DEFAULT_GOOGLE_MODEL)

    try:
        logger.debug(f"Requesting summary from Google model '{gemini_model_name}' for item '{item_name or 'Unknown'}'")
        response = google_gemini_client_via_openai_lib.chat.completions.create(
            model=gemini_model_name,
            messages=messages_for_api,
            temperature=0.2,
            max_tokens=150,
        )
        summary = response.choices[0].message.content.strip() if response.choices and response.choices[0].message.content else None

        if summary:
            logger.info(f"Google summary generated for '{item_name or 'Unknown'}'. Preview: '{summary[:100]}...'")
        else:
            logger.warning(f"Google returned an empty or null summary for '{item_name or 'Unknown'}'. Original text length: {len(plain_text_description)}")
        return summary

    except APIError as e:
        logger.error(f"Google APIError (via OpenAI lib) during description summarization for '{item_name or 'Unknown'}': {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Unexpected error calling Google for description summarization for '{item_name or 'Unknown'}': {e}", exc_info=True)
        return None

# ── Tool schema (mirrors openai_service, descriptions updated) ───────────────────────────────────
tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "search_local_products", # For NamFulgor, this should be search_vehicle_batteries
            "description": (
                "Busca en el catálogo de baterías utilizando una consulta en lenguaje natural sobre el vehículo. "
                "Ideal cuando el usuario pregunta qué batería necesita su carro (marca, modelo, año)."
                "Devuelve una lista de baterías compatibles con sus detalles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "vehicle_make": { # Parameter for battery search by vehicle
                        "type": "string",
                        "description": "La marca del vehículo (ej: Toyota, Ford, Chevrolet, Alfa Romeo).",
                    },
                    "vehicle_model": { # Parameter for battery search by vehicle
                        "type": "string",
                        "description": "El modelo del vehículo (ej: Corolla, Fiesta, Spark, 145).",
                    },
                    "vehicle_year": { # Parameter for battery search by vehicle
                        "type": "integer",
                        "description": "El año de fabricación del vehículo (ej: 2015, 1998). Opcional.",
                    },
                    # "query_text" and "filter_stock" from original schema might be less relevant here
                    # if search is primarily by vehicle fitment.
                },
                "required": ["vehicle_make", "vehicle_model"], # Adjusted for battery search
            },
        },
    },
    # The get_live_product_details tool was for the old product structure.
    # For batteries, we might need a get_specific_battery_details if search_vehicle_batteries isn't enough.
    # {
    #     "type": "function",
    #     "function": {
    #         "name": "get_specific_battery_details",
    #         "description": "Obtiene detalles de una batería específica por su ID.",
    #         "parameters": {
    #             "type": "object",
    #             "properties": { "battery_id": { "type": "string", "description": "ID único de la batería."}},
    #             "required": ["battery_id"],
    #         },
    #     },
    # },
]
# Add lead generation tools if Config.ENABLE_LEAD_GENERATION_TOOLS is True (logic is fine)
if Config.ENABLE_LEAD_GENERATION_TOOLS:
    tools_schema.extend([
        # ... (Your existing lead generation tool schemas)
        {"type": "function", "function": {
            "name": "initiate_customer_information_collection",
            "description": "Registra interés en baterías y solicita Nombre, Email, Teléfono.",
            "parameters": {"type": "object", "properties": {
                "products": {"type": "array", "description": "Lista de baterías (id, name, quantity, price).", "items": {
                    "type": "object", "properties": {
                        "id": {"type": "string"}, "name": {"type": "string"},
                        "quantity": {"type": "integer"}, "price": {"type": "number"}
                    }, "required": ["id", "name", "quantity", "price"]}},
                "platform_user_id": {"type": "string", "description": "ID usuario plataforma (opcional)."},
                "source_channel": {"type": "string", "description": "Canal origen (opcional)."}
            }, "required": ["products"]}}},
        {"type": "function", "function": {
            "name": "submit_customer_information_for_crm",
            "description": "Envía Nombre, Email, Teléfono para un prospecto.",
            "parameters": {"type": "object", "properties": {
                "lead_id": {"type": "string"}, "customer_full_name": {"type": "string"},
                "customer_email": {"type": "string"}, "customer_phone_number": {"type": "string"}
            }, "required": ["lead_id", "customer_full_name", "customer_email", "customer_phone_number"]}}}
    ])


# ── Helper functions ────────────────────────────────────────────────────────────
def _format_sb_history_for_openai_compatible_api(
    sb_messages: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    # ... (This function's internal logic is fine, uses Config) ...
    if not sb_messages: return []
    openai_messages: List[Dict[str, Any]] = []
    bot_user_id_str = str(Config.SUPPORT_BOARD_DM_BOT_USER_ID) if Config.SUPPORT_BOARD_DM_BOT_USER_ID else None
    if not bot_user_id_str: logger.error("SUPPORT_BOARD_DM_BOT_USER_ID not configured for history formatting."); return []
    for msg in sb_messages:
        sender_id = msg.get("user_id"); text_content = msg.get("message","").strip(); attachments = msg.get("attachments"); image_urls: List[str] = []
        if attachments and isinstance(attachments, list):
            for att in attachments:
                url=att.get("url","")
                if url and (att.get("type","").startswith("image") or any(url.lower().endswith(ext) for ext in [".jpg",".jpeg",".png",".gif",".webp"])):
                    if url.startswith(("http://","https://")): image_urls.append(url)
        if not text_content and not image_urls: continue
        if sender_id is None: logger.warning("Skipping msg with no sender_id: %s", msg.get("id")); continue
        role="assistant" if str(sender_id)==bot_user_id_str else "user"
        content_list_for_api: List[Dict[str, Any]] = []
        if text_content: content_list_for_api.append({"type":"text","text":text_content})
        if image_urls:
            for img_url in image_urls: content_list_for_api.append({"type":"image_url","image_url":{"url":img_url}})
            if not text_content: logger.debug("Message for Gemini contains only images.")
        if content_list_for_api:
            if len(content_list_for_api) == 1 and content_list_for_api[0]["type"] == "text":
                openai_messages.append({"role":role, "content": content_list_for_api[0]["text"]})
            else:
                openai_messages.append({"role":role, "content": content_list_for_api})
    return openai_messages

# MODIFIED: This function should now use battery_catalog_service (aliased product_service)
# and the formatter should be for battery results.
def _format_battery_search_results_for_llm(results: Optional[List[Dict[str, Any]]]) -> str:
    if results is None: return json.dumps({"status": "error", "message": "Error buscando baterías."}, ensure_ascii=False)
    if not results: return json.dumps({"status": "not_found", "message": "No encontré baterías compatibles."}, ensure_ascii=False)
    try: return json.dumps({"status": "success", "batteries_found": results}, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as err: logger.error(f"JSON error: {err}", exc_info=True); return json.dumps({"status": "error", "message": "Error formateando resultados."}, ensure_ascii=False)

# REMOVED: _format_live_details_for_llm, as its corresponding tool is removed for batteries.
# If you add a get_specific_battery_details tool, you will need a formatter.

# ── Main entry point ────────────────────────────────────────────────────────────
def process_new_message_gemini_via_openai_lib( # Renamed from your process_new_message_gemini
    sb_conversation_id: str, new_user_message: Optional[str], conversation_source: Optional[str],
    sender_user_id: str, customer_user_id: str, triggering_message_id: Optional[str],
):
    logger.info(f"[NamFulgor-Gemini] Handling SB Conv {sb_conversation_id}") # Updated log prefix

    if not GOOGLE_SDK_AVAILABLE or not google_gemini_client_via_openai_lib:
        logger.error("[NamFulgor-Gemini] Google Gemini client not available.")
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id, message_text="IA (Google) no disponible.",
            source=conversation_source, target_user_id=customer_user_id,
            conversation_details=None, triggering_message_id=triggering_message_id)
        return

    conversation_data = support_board_service.get_sb_conversation_data(sb_conversation_id)
    if not conversation_data or not conversation_data.get("messages"):
        logger.error(f"[NamFulgor-Gemini] No conv data for {sb_conversation_id}.")
        support_board_service.send_reply_to_channel(conversation_id=sb_conversation_id, message_text="Error historial.", source=conversation_source, target_user_id=customer_user_id, triggering_message_id=triggering_message_id); return
    
    api_history = _format_sb_history_for_openai_compatible_api(conversation_data.get("messages", []))
    if not api_history and new_user_message: api_history = [{"role": "user", "content": new_user_message}]
    elif not api_history: logger.error(f"[NamFulgor-Gemini] Empty history for {sb_conversation_id}."); support_board_service.send_reply_to_channel(conversation_id=sb_conversation_id, message_text="Error mensajes previos.", source=conversation_source, target_user_id=customer_user_id, triggering_message_id=triggering_message_id); return

    messages_for_api = [{"role": "system", "content": Config.SYSTEM_PROMPT}] + api_history # Uses Config
    current_max_history = getattr(Config, "MAX_HISTORY_MESSAGES", MAX_HISTORY_MESSAGES) # Uses Config
    if len(messages_for_api) > (current_max_history + 1): messages_for_api = [messages_for_api[0]] + messages_for_api[-(current_max_history):]

    final_assistant_response: Optional[str] = None
    try:
        tool_call_count = 0
        # api_call_params was not defined before the loop, define it as current_call_params
        current_call_params: Dict[str, Any] = { # Use current_call_params
            "model": DEFAULT_GOOGLE_MODEL, "messages": messages_for_api,
            "max_tokens": DEFAULT_MAX_TOKENS, "temperature": DEFAULT_GOOGLE_TEMPERATURE,
        }

        while tool_call_count <= TOOL_CALL_RETRY_LIMIT:
            if tool_call_count == 0 or (current_call_params["messages"][-1].get("role") == "assistant" and current_call_params["messages"][-1].get("tool_calls")):
                current_call_params["tools"] = tools_schema # Use current_call_params
                current_call_params["tool_choice"] = "auto"
            else:
                current_call_params.pop("tools", None) # Use current_call_params
                current_call_params.pop("tool_choice", None)

            logger.debug(f"[NamFulgor-Gemini] Sending request (Attempt {tool_call_count + 1}). Tools: {'tools' in current_call_params}")
            response = google_gemini_client_via_openai_lib.chat.completions.create(**current_call_params) # Use current_call_params
            response_msg_obj = response.choices[0].message
            messages_for_api.append(response_msg_obj.model_dump(exclude_none=True))
            tool_calls = response_msg_obj.tool_calls
            if response.usage: logger.info(f"[NamFulgor-Gemini] Tokens: P={response.usage.prompt_tokens}, C={response.usage.completion_tokens}")

            if not tool_calls: final_assistant_response = response_msg_obj.content; break
            
            tool_outputs_for_api: List[Dict[str, str]] = []
            for tc in tool_calls:
                fname, tool_call_id = tc.function.name, tc.id
                args = {}; tool_content_str = json.dumps({"status":"error", "message":f"Error ejecución {fname}."}, ensure_ascii=False)
                try: args = json.loads(tc.function.arguments)
                except json.JSONDecodeError: logger.error(f"[NamFulgor-Gemini] Invalid JSON args for {fname}: {tc.function.arguments}")
                
                logger.info(f"[NamFulgor-Gemini] Tool: {fname}, Args: {args}")
                try:
                    # MODIFIED: Tool name for batteries
                    if fname == "search_vehicle_batteries": # Changed from search_local_products
                        make, model_arg, year = args.get("vehicle_make"), args.get("vehicle_model"), args.get("vehicle_year")
                        if make and model_arg:
                            with db_utils.get_db_session() as session: # db_utils is now correctly imported
                                if session:
                                    # product_service is now correctly imported as a sibling
                                    search_results_list = product_service.find_batteries_for_vehicle(session, make, model_arg, year)
                                    tool_content_str = _format_battery_search_results_for_llm(search_results_list) # Use new formatter
                                else:
                                    logger.error("[NamFulgor-Gemini] No DB session for battery search.")
                                    tool_content_str = json.dumps({"status": "error", "message": "DB error."}, ensure_ascii=False)
                        else: tool_content_str = json.dumps({"status": "error", "message": "Faltan 'vehicle_make' y 'vehicle_model'."}, ensure_ascii=False)
                    
                    # REMOVED: get_live_product_details tool handler
                    # Add handler for get_specific_battery_details if that tool is defined

                    elif fname == "initiate_customer_information_collection" and Config.ENABLE_LEAD_GENERATION_TOOLS:
                        # This tool's internal call to lead_api_client is fine as lead_api_client is a sibling import
                        tool_content_str = _tool_initiate_customer_information_collection(
                            sb_conversation_id, args.get("products",[]), args.get("platform_user_id"), 
                            args.get("source_channel"), args.get("conversation_id")
                        )
                    elif fname == "submit_customer_information_for_crm" and Config.ENABLE_LEAD_GENERATION_TOOLS:
                        tool_content_str = _tool_submit_customer_information_for_crm(
                            args.get("lead_id",""), args.get("customer_full_name",""), 
                            args.get("customer_email",""), args.get("customer_phone_number","")
                        )
                    else: logger.warning(f"[NamFulgor-Gemini] Unknown tool: {fname}"); tool_content_str = json.dumps({"status": "error", "message": f"Herramienta desconocida '{fname}'."}, ensure_ascii=False)
                except Exception as e_tool: logger.exception(f"[NamFulgor-Gemini] Error tool {fname}: {e_tool}"); tool_content_str = json.dumps({"status": "error", "message": f"Error interno herramienta {fname}."}, ensure_ascii=False)
                tool_outputs_for_api.append({"tool_call_id": tool_call_id, "role": "tool", "name": fname, "content": tool_content_str})
            
            messages_for_api.extend(tool_outputs_for_api) # Use the correct variable name
            tool_call_count += 1
            if tool_call_count > TOOL_CALL_RETRY_LIMIT: logger.warning(f"[NamFulgor-Gemini] Retry limit for {sb_conversation_id}."); current_call_params.pop("tools", None); current_call_params.pop("tool_choice", None); # Adjust for final call

        if final_assistant_response is None: # Check after loop if still None
            if tool_calls and tool_call_count > TOOL_CALL_RETRY_LIMIT : # Ended on tool call after retries
                final_assistant_response = "Dificultades técnicas con herramientas. Intenta otra pregunta."
            elif not tool_calls and not response_msg_obj.content: # Ended with no tool call AND no content
                 final_assistant_response = "No pude generar una respuesta clara. ¿Puedes reformular?"


    except RateLimitError: final_assistant_response = "Alto volumen (Google). Intenta más tarde."; logger.warning("[NamFulgor-Gemini] RateLimitError conv %s", sb_conversation_id)
    except APITimeoutError: final_assistant_response = "Timeout con Google. Intenta más tarde."; logger.warning("[NamFulgor-Gemini] APITimeoutError conv %s", sb_conversation_id)
    except BadRequestError as br_err:
        err_body_str = str(getattr(br_err, "body", br_err)).lower()
        if "user location" in err_body_str: final_assistant_response = "Ubicación no compatible (Google)."
        elif "image" in err_body_str: final_assistant_response = "Imagen inválida (Google)."
        else: final_assistant_response = "Error formato o imagen (Google)."
        logger.warning("[NamFulgor-Gemini] BadRequestError conv %s: %s", sb_conversation_id, br_err)
    except APIError as api_err: final_assistant_response = f"Error IA Google ({getattr(api_err, 'status_code', 'N/A')})."; logger.error(f"[NamFulgor-Gemini] APIError conv %s: {api_err}", exc_info=True)
    except Exception as e: logger.exception(f"[NamFulgor-Gemini] Error Gemini conv {sb_conversation_id}: {e}"); final_assistant_response = "Error inesperado con Google AI."

    if final_assistant_response:
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id, message_text=str(final_assistant_response),
            source=conversation_source, target_user_id=customer_user_id,
            conversation_details=conversation_data, triggering_message_id=triggering_message_id)
    else: 
        logger.error("[NamFulgor-Gemini] No final response for conv %s.", sb_conversation_id)
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id, message_text="No pude generar respuesta.",
            source=conversation_source, target_user_id=customer_user_id,
            conversation_details=conversation_data, triggering_message_id=triggering_message_id)

process_new_message_gemini = process_new_message_gemini_via_openai_lib # Alias if you want to call it by the shorter name

# --- End of NAMWOO/services/google_service.py (NamFulgor Version - STRICTLY ONLY IMPORT CHANGED) ---