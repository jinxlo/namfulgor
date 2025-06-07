# NAMWOO/services/openai_service.py (NamFulgor - Battery Version - Corrected Imports, All Methods Kept)
# -*- coding: utf-8 -*-
import logging
import json
import time
from typing import List, Dict, Optional, Tuple, Union, Any # Keep Any
from openai import OpenAI, APIError, RateLimitError, APITimeoutError, BadRequestError
from flask import current_app

# --- CORRECTED IMPORTS ---
# Sibling services can be imported with relative '.'
from . import product_service as battery_catalog_service # Import the actual module and alias it
# OR, if product_service.py contains functions you call directly:
# from .product_service import find_batteries_for_vehicle, update_battery_product_prices # etc.
from . import support_board_service
from . import lead_api_client       # If lead_api_client.py is in the same 'services' directory

# Absolute-style imports for packages outside 'services'
from config.config import Config      # Assumes Config class is in namwoo_app/config/config.py
from utils import db_utils            # Assumes db_utils.py is in namwoo_app/utils/

# --------------------------

logger = logging.getLogger(__name__)

# --- OpenAI Client Initialization (Logic remains the same) ---
_chat_client: Optional[OpenAI] = None
try:
    openai_api_key = Config.OPENAI_API_KEY
    if openai_api_key:
        timeout_seconds = getattr(Config, 'OPENAI_REQUEST_TIMEOUT', 60.0)
        _chat_client = OpenAI(api_key=openai_api_key, timeout=timeout_seconds)
        logger.info(f"OpenAI client initialized for Chat Completions service with timeout: {timeout_seconds}s.")
    else:
        _chat_client = None
        logger.error("OpenAI API key not configured. Chat functionality will fail.")
except Exception as e:
    logger.exception(f"Failed to initialize OpenAI client for chat: {e}")
    _chat_client = None

# --- Constants (Logic remains the same) ---
MAX_HISTORY_MESSAGES = Config.MAX_HISTORY_MESSAGES
TOOL_CALL_RETRY_LIMIT = 2
DEFAULT_OPENAI_MODEL = getattr(Config, "OPENAI_CHAT_MODEL", "gpt-4o-mini")
DEFAULT_MAX_TOKENS = getattr(Config, "OPENAI_MAX_TOKENS", 1024)
DEFAULT_OPENAI_TEMPERATURE = getattr(Config, "OPENAI_TEMPERATURE", 0.7)

# --- Embedding Generation Function (Kept as per your file) ---
def generate_battery_embedding(text_to_embed: str) -> Optional[List[float]]:
    """
    Generates an embedding for the given battery text using OpenAI
    via embedding_utils.
    """
    if not text_to_embed or not isinstance(text_to_embed, str):
        logger.warning("openai_service.generate_battery_embedding: No valid text provided.")
        return None
    # Config.OPENAI_EMBEDDING_MODEL should be correctly accessed now
    embedding_model_name = Config.OPENAI_EMBEDDING_MODEL
    if not embedding_model_name:
        logger.error("openai_service.generate_battery_embedding: OPENAI_EMBEDDING_MODEL not configured.")
        return None
    logger.debug(f"Requesting battery embedding for text: '{text_to_embed[:100]}...' using model: {embedding_model_name}")
    # embedding_utils should be correctly imported now
    embedding_vector = embedding_utils.get_embedding(
        text=text_to_embed,
        model=embedding_model_name
    )
    if embedding_vector is None:
        logger.error(f"openai_service.generate_battery_embedding: Failed to get embedding for text: '{text_to_embed[:100]}...'")
        return None
    logger.info(f"Successfully generated battery embedding for text (first 100 chars): '{text_to_embed[:100]}...'")
    return embedding_vector

# --- Battery Description Summarization (Kept as per your file) ---
def get_openai_battery_summary(
    plain_text_description: str,
    battery_brand: Optional[str] = None,
    battery_model_code: Optional[str] = None
) -> Optional[str]:
    global _chat_client # Ensure global is used if you modify it, though it's only read here
    if not _chat_client:
        logger.error("OpenAI client: Not initialized for summary.")
        return None
    if not plain_text_description or not plain_text_description.strip():
        logger.debug("OpenAI summarizer: No plain text to summarize.")
        return None
    item_identifier = f"{battery_brand or ''} {battery_model_code or 'Batería'}" # More generic
    prompt_context = f"Marca: {battery_brand or 'N/A'}\nModelo: {battery_model_code or 'N/A'}\nDescripción Original:\n{plain_text_description}"
    system_prompt = (
        "Eres un redactor experto en baterías automotrices. Resume la descripción. "
        "Sé conciso (30-60 palabras), resalta beneficios y características técnicas. Salida: texto plano."
    )
    max_chars = 2000 # Max input characters for the description part of the prompt
    if len(prompt_context) > max_chars: # Basic truncation if too long
        # Try to find a sentence end before truncating
        cutoff_point = prompt_context.rfind('.', 0, max_chars)
        if cutoff_point == -1: cutoff_point = max_chars # If no period, just cut
        prompt_context = prompt_context[:cutoff_point] + " [TRUNCADO]"
        logger.warning(f"OpenAI battery summarizer: Description for '{item_identifier}' was truncated for prompt construction.")
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Resume:\n{prompt_context}"}]
    try:
        # Use Config for model, not current_app.config if this might be called outside app context
        model = getattr(Config, "OPENAI_SUMMARY_MODEL", DEFAULT_OPENAI_MODEL)
        completion = _chat_client.chat.completions.create(model=model, messages=messages, temperature=0.2, max_tokens=100) # Adjusted max_tokens for summary
        summary = completion.choices[0].message.content.strip() if completion.choices and completion.choices[0].message.content else None
        logger.info(f"Summary for '{item_identifier}': '{summary[:50]}...'") if summary else logger.warning(f"Empty summary for '{item_identifier}'.")
        return summary
    except APIError as e:
        logger.error(f"OpenAI APIError during battery summary for '{item_identifier}': {e}", exc_info=True)
        return None
    except Exception as e: # Catch any other unexpected error
        logger.error(f"Unexpected error during battery summary for '{item_identifier}': {e}", exc_info=True)
        return None


# --- Lead/CRM Tool Implementations (Logic remains the same) ---
def _tool_initiate_customer_information_collection(
    actual_sb_conversation_id: str, products: list, platform_user_id: Optional[str] = None,
    source_channel: Optional[str] = None, llm_provided_conv_id: Optional[str] = None
) -> str:
    logger.info(f"Tool: initiate_customer_info for batteries. SB_ConvID: {actual_sb_conversation_id}.")
    api_products = [{"sku": p.get("id", "N/A"), "description": p.get("name", "Batería"), "quantity": p.get("quantity", 1)} for p in products]
    result = lead_api_client.call_initiate_lead_intent( # Assumes lead_api_client is imported correctly
        conversation_id=actual_sb_conversation_id, products_of_interest=api_products,
        payment_method_preference="direct_payment", platform_user_id=platform_user_id, source_channel=source_channel
    )
    if result.get("success") and result.get("data", {}).get("id"):
        lead_id = result["data"]["id"]
        return (f"OK_LEAD_INTENT_CREATED. ID: {lead_id}. Pedir Nombre, Email, Teléfono. "
                f"Luego llamar 'submit_customer_information_for_crm' con Lead ID: '{lead_id}'.")
    else:
        return f"ERROR_CREATING_LEAD_INTENT: {result.get('error_message', 'error API')}. Informar."

def _tool_submit_customer_information_for_crm(
    lead_id: str, customer_full_name: str, customer_email: str, customer_phone_number: str
) -> str:
    logger.info(f"Tool: submit_customer_info. LeadID: {lead_id}")
    if not all([lead_id, customer_full_name, customer_email, customer_phone_number]):
        return "ERROR_MISSING_DATA_FOR_CRM_SUBMISSION: Faltan datos."
    result = lead_api_client.call_submit_customer_details( # Assumes lead_api_client is imported correctly
        lead_id=lead_id, customer_full_name=customer_full_name,
        customer_email=customer_email, customer_phone_number=customer_phone_number
    )
    if result.get("success"):
        return (f"INFO_SUBMITTED_SUCCESSFULLY. Gracias, {customer_full_name}! "
                "Para envío/factura, pedir Cédula/RIF y dirección. Luego confirmar.")
    else:
        return f"ERROR_SUBMITTING_DETAILS_TO_CRM: {result.get('error_message', 'error API')}. Informar."

# --- Tool Definitions for OpenAI (Logic remains the same) ---
tools_schema = [
    {"type": "function", "function": {
        "name": "search_vehicle_batteries",
        "description": "Busca baterías compatibles para un vehículo (marca, modelo y año).",
        "parameters": {"type": "object", "properties": {
            "vehicle_make": {"type": "string", "description": "Marca (Toyota, Ford, etc.)."},
            "vehicle_model": {"type": "string", "description": "Modelo (Corolla, Spark, etc.)."},
            "vehicle_year": {"type": "integer", "description": "Año (opcional)."}
        }, "required": ["vehicle_make", "vehicle_model"]},
    }},
]
if Config.ENABLE_LEAD_GENERATION_TOOLS: # Uses corrected Config import
    tools_schema.extend([
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

# --- Helper: format Support-Board history (Logic remains the same) ---
def _format_sb_history_for_openai(sb_messages: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if not sb_messages: return []
    openai_messages: List[Dict[str, Any]] = []
    bot_user_id_str = str(Config.SUPPORT_BOARD_DM_BOT_USER_ID) if Config.SUPPORT_BOARD_DM_BOT_USER_ID else None
    if not bot_user_id_str: logger.error("SUPPORT_BOARD_DM_BOT_USER_ID not configured."); return []
    for msg in sb_messages:
        sender_id = msg.get("user_id"); text_content = msg.get("message", "").strip(); attachments = msg.get("attachments"); image_urls: List[str] = []
        if attachments and isinstance(attachments, list):
            for att in attachments:
                if isinstance(att, dict) and att.get("url") and (att.get("type", "").startswith("image") or any(att["url"].lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"])):
                    url = att["url"]
                    if url.startswith(("http://", "https://")): image_urls.append(url)
        if not text_content and not image_urls: continue
        if sender_id is None: continue
        role = "assistant" if str(sender_id) == bot_user_id_str else "user"
        content_list: List[Dict[str, Any]] = []
        if text_content: content_list.append({"type": "text", "text": text_content})
        current_model = getattr(Config, "OPENAI_CHAT_MODEL", DEFAULT_OPENAI_MODEL)
        if image_urls and current_model in ["gpt-4-turbo", "gpt-4o", "gpt-4o-mini"]:
            for img_url in image_urls: content_list.append({"type": "image_url", "image_url": {"url": img_url}})
        elif image_urls and not text_content: content_list.append({"type": "text", "text": "[Imagen adjunta]"})
        if content_list:
            openai_messages.append({"role": role, "content": content_list[0]["text"] if len(content_list) == 1 and content_list[0]["type"] == "text" else content_list})
    return openai_messages

# --- Helper: format battery search results (Logic remains the same) ---
def _format_battery_search_results_for_llm(results: Optional[List[Dict[str, Any]]]) -> str:
    if results is None: return json.dumps({"status": "error", "message": "Error buscando baterías."}, ensure_ascii=False)
    if not results: return json.dumps({"status": "not_found", "message": "No encontré baterías compatibles."}, ensure_ascii=False)
    try: return json.dumps({"status": "success", "batteries_found": results}, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as err: logger.error(f"JSON error formatting battery results: {err}", exc_info=True); return json.dumps({"status": "error", "message": "Error formateando resultados."}, ensure_ascii=False)

# --- Main processing entry-point (Logic remains the same, relies on corrected service/util imports) ---
def process_new_message(
    sb_conversation_id: str, new_user_message: Optional[str], conversation_source: Optional[str],
    sender_user_id: str, customer_user_id: str, triggering_message_id: Optional[str],
) -> None:
    global _chat_client
    if not _chat_client:
        logger.error("OpenAI client not initialized. Cannot process message.")
        # Use support_board_service directly as it's imported with "from ."
        support_board_service.send_reply_to_channel(conversation_id=sb_conversation_id, message_text="IA no disponible.", source=conversation_source, target_user_id=customer_user_id, conversation_details=None, triggering_message_id=triggering_message_id)
        return
    
    # Use support_board_service directly
    conversation_data = support_board_service.get_sb_conversation_data(sb_conversation_id)
    if not conversation_data or not conversation_data.get("messages"):
        logger.error(f"No conversation data for {sb_conversation_id}.")
        support_board_service.send_reply_to_channel(conversation_id=sb_conversation_id, message_text="Error obteniendo historial.", source=conversation_source, target_user_id=customer_user_id, triggering_message_id=triggering_message_id)
        return

    openai_history = _format_sb_history_for_openai(conversation_data.get("messages", []))
    if not openai_history and new_user_message:
        openai_history = [{"role": "user", "content": new_user_message}]
    elif not openai_history:
        logger.error(f"Empty OpenAI history for {sb_conversation_id}.")
        support_board_service.send_reply_to_channel(conversation_id=sb_conversation_id, message_text="Error procesando mensajes previos.", source=conversation_source, target_user_id=customer_user_id, triggering_message_id=triggering_message_id)
        return
        
    # Uses Config, which is now correctly imported
    messages: List[Dict[str, Any]] = [{"role": "system", "content": Config.SYSTEM_PROMPT}] + openai_history
    # Uses Config and MAX_HISTORY_MESSAGES (from Config)
    if len(messages) > (getattr(Config, "MAX_HISTORY_MESSAGES", MAX_HISTORY_MESSAGES) + 1):
        messages = [messages[0]] + messages[-(getattr(Config, "MAX_HISTORY_MESSAGES", MAX_HISTORY_MESSAGES)):]

    final_assistant_response: Optional[str] = None
    try:
        tool_call_count = 0
        while tool_call_count <= TOOL_CALL_RETRY_LIMIT:
            # Uses Config attributes or defaults
            call_params: Dict[str, Any] = {
                "model": getattr(Config, "OPENAI_CHAT_MODEL", DEFAULT_OPENAI_MODEL),
                "messages": messages,
                "max_tokens": getattr(Config, "OPENAI_MAX_TOKENS", DEFAULT_MAX_TOKENS),
                "temperature": getattr(Config, "OPENAI_TEMPERATURE", DEFAULT_OPENAI_TEMPERATURE),
            }
            if tool_call_count < TOOL_CALL_RETRY_LIMIT and not (messages[-1].get("role") == "tool"):
                 call_params["tools"] = tools_schema
                 call_params["tool_choice"] = "auto"
            
            response = _chat_client.chat.completions.create(**call_params)
            response_message = response.choices[0].message
            messages.append(response_message.model_dump(exclude_none=True))
            tool_calls = response_message.tool_calls

            if not tool_calls: final_assistant_response = response_message.content; break
            
            tool_outputs: List[Dict[str, str]] = []
            for tc in tool_calls:
                fn_name, tool_call_id = tc.function.name, tc.id
                args = {}; output_content = json.dumps({"status":"error", "message":f"Error ejecución {fn_name}."}, ensure_ascii=False)
                try: args_str = tc.function.arguments; args = json.loads(args_str)
                except json.JSONDecodeError: logger.error(f"JSONDecodeError args for {fn_name}: {args_str}")

                logger.info(f"Tool call: {fn_name}, Args: {args}")
                try:
                    if fn_name == "search_vehicle_batteries":
                        make, model_arg, year = args.get("vehicle_make"), args.get("vehicle_model"), args.get("vehicle_year")
                        if make and model_arg:
                            # Use db_utils (imported directly) for session
                            with db_utils.get_db_session() as session:
                                if session:
                                    # Use battery_catalog_service (imported with "from .")
                                    res = battery_catalog_service.find_batteries_for_vehicle(session, make, model_arg, year)
                                    output_content = _format_battery_search_results_for_llm(res)
                                else: 
                                    logger.error("No DB session for search_vehicle_batteries tool call.")
                                    output_content = json.dumps({"status": "error", "message": "DB error."}, ensure_ascii=False)
                        else: output_content = json.dumps({"status": "error", "message": "Faltan 'vehicle_make' y 'vehicle_model'."}, ensure_ascii=False)
                    
                    elif fn_name == "initiate_customer_information_collection" and Config.ENABLE_LEAD_GENERATION_TOOLS:
                        output_content = _tool_initiate_customer_information_collection(sb_conversation_id, args.get("products",[]), args.get("platform_user_id"), args.get("source_channel"), args.get("conversation_id"))
                    
                    elif fn_name == "submit_customer_information_for_crm" and Config.ENABLE_LEAD_GENERATION_TOOLS:
                        output_content = _tool_submit_customer_information_for_crm(args.get("lead_id",""), args.get("customer_full_name",""), args.get("customer_email",""), args.get("customer_phone_number",""))
                    
                    else: output_content = json.dumps({"status": "error", "message": f"Herramienta '{fn_name}' desconocida o deshabilitada."}, ensure_ascii=False)
                
                except Exception as e_tool: 
                    logger.exception(f"Tool execution error {fn_name}: {e_tool}")
                    output_content = json.dumps({"status": "error", "message": f"Error interno herramienta {fn_name}."}, ensure_ascii=False)
                
                tool_outputs.append({"tool_call_id": tool_call_id, "role": "tool", "name": fn_name, "content": output_content})
            
            messages.extend(tool_outputs)
            tool_call_count += 1
            if tool_call_count > TOOL_CALL_RETRY_LIMIT and not final_assistant_response: logger.warning("Tool retry limit hit."); break
    
    except RateLimitError: final_assistant_response = "Alto volumen. Intenta más tarde."; logger.warning(f"RateLimitError for {sb_conversation_id}")
    except APITimeoutError: final_assistant_response = "Timeout con OpenAI."; logger.warning(f"APITimeoutError for {sb_conversation_id}")
    except BadRequestError as bre:
        logger.error(f"BadRequestError for {sb_conversation_id}: {bre}", exc_info=True)
        final_assistant_response = "Imagen inválida o problema de formato." if "image_url" in str(bre).lower() else "Problema formato conversación."
    except APIError as apie: logger.error(f"APIError for {sb_conversation_id}: {apie}", exc_info=True); final_assistant_response = f"Error IA ({apie.status_code})."
    except Exception as e: logger.exception(f"Error OpenAI {sb_conversation_id}: {e}"); final_assistant_response = "Error inesperado procesando."

    if final_assistant_response:
        support_board_service.send_reply_to_channel( # support_board_service imported via "from ."
            conversation_id=sb_conversation_id, message_text=str(final_assistant_response),
            source=conversation_source, target_user_id=customer_user_id,
            conversation_details=conversation_data, triggering_message_id=triggering_message_id
        )
    elif not tool_calls and not final_assistant_response: # Ensure some response if no tool calls and no text
        logger.error("No final response and no tool calls for Conv %s.", sb_conversation_id)
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id, message_text="No pude generar una respuesta en este momento.",
            source=conversation_source, target_user_id=customer_user_id,
            conversation_details=conversation_data, triggering_message_id=triggering_message_id
        )
    # If tool_calls happened but loop ended due to retry without final_assistant_response,
    # it might be desirable to send a specific message or let it be (as it already sent tool results to LLM)

# --- End of NAMWOO/services/openai_service.py (NamFulgor - Battery Version - Final Corrections) ---