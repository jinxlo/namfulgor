# NAMWOO/services/google_service.py
# -*- coding: utf-8 -*-
import logging
import json
# import time # Not directly used in this file after embedding moved
from typing import List, Dict, Optional, Union, Any # Added Any

from openai import ( # This lib is used for the OpenAI-compatible Gemini endpoint
    OpenAI,
    APIError,
    RateLimitError,
    APITimeoutError,
    BadRequestError,
)
from flask import current_app # If needed for config, though Config object is mostly used

# ── Local services ──────────────────────────────────────────────────────────────
from . import product_service, support_board_service
from ..config import Config

logger = logging.getLogger(__name__)

# ── Initialise OpenAI‑compatible client that talks to Google Gemini ────────────
google_gemini_client_via_openai_lib: Optional[OpenAI] = None
GOOGLE_SDK_AVAILABLE = False

try:
    google_api_key = Config.GOOGLE_API_KEY
    # Using the OpenAI library to connect to Google's OpenAI-compatible endpoint
    google_base_url = "https://generativelanguage.googleapis.com/v1beta" # Standard base
    # The library appends /models, /embeddings, etc.
    # If you use client.chat.completions.create, it will hit /models/gemini-model:generateContent
    # For OpenAI compatibility mode, often it's /v1beta/models/gemini-model:generateContent or similar.
    # The library might also construct it as /v1beta/chat/completions for OpenAI compatibility.
    # The key is that the OpenAI library is configured to talk to this base_url.
    # A common pattern for OpenAI-compatible endpoints is just the base, e.g.,
    # google_base_url = "https://generativelanguage.googleapis.com/v1beta"
    # And then the model name in the call would be "models/gemini-1.5-flash-latest"
    # OR, the library expects something like: "https://generativelanguage.googleapis.com/v1beta/openai" (as you had)
    # if the library itself appends /chat/completions. This depends on the lib version & Google's endpoint.
    # Let's stick to your original base URL for now assuming it worked.
    google_base_url_for_openai_lib = "https://generativelanguage.googleapis.com/v1beta/openai/"


    if google_api_key:
        google_gemini_client_via_openai_lib = OpenAI(
            api_key=google_api_key,
            base_url=google_base_url_for_openai_lib, # Use the specific URL for OpenAI lib compatibility
            timeout=60.0,
        )
        logger.info(
            "OpenAI-lib client initialised for Google Gemini at %s", google_base_url_for_openai_lib
        )
        GOOGLE_SDK_AVAILABLE = True
    else:
        logger.error("GOOGLE_API_KEY not configured. Gemini service (via OpenAI lib) disabled.")
except Exception:
    logger.exception("Failed to initialise Google Gemini client (via OpenAI lib).")
    google_gemini_client_via_openai_lib = None
    GOOGLE_SDK_AVAILABLE = False

# ── Constants ───────────────────────────────────────────────────────────────────
MAX_HISTORY_MESSAGES = Config.MAX_HISTORY_MESSAGES
TOOL_CALL_RETRY_LIMIT = 2 # Allow 3 attempts total (0, 1, 2)
DEFAULT_GOOGLE_MODEL = Config.GOOGLE_GEMINI_MODEL # Ensure this is the model ID, e.g., "gemini-1.5-flash-latest" not "models/gemini..."
DEFAULT_MAX_TOKENS = Config.GOOGLE_MAX_TOKENS

# ── Tool schema (mirrors openai_service) ────────────────────────────────────────
# Ensure descriptions are clear for Gemini.
tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "search_local_products",
            "description": (
                "Busca en la base de datos local de productos usando búsqueda "
                "semántica (vectorial) basada en la consulta de texto. "
                "Devuelve una lista de productos encontrados, cada uno con detalles de ubicación y stock."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query_text": {
                        "type": "string",
                        "description": (
                            "Consulta del usuario describiendo el producto deseado, por ejemplo, "
                            "'televisor LG 55 pulgadas inteligente' o 'lavadora carga frontal'."
                        ),
                    },
                    "filter_stock": {
                        "type": "boolean",
                        "description": (
                            "Si es True (predeterminado), solo devuelve productos con stock disponible (>0) "
                            "en alguna de sus ubicaciones." # Clarify stock filter behavior
                        ),
                        "default": True,
                    },
                },
                "required": ["query_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_live_product_details",
            "description": (
                "Consulta el inventario para precio y stock de un producto específico. "
                "Un SKU puede tener múltiples ubicaciones; si es así, se listarán todas. "
                "Para una ubicación específica, usa el 'ID Compuesto'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_identifier": {
                        "type": "string",
                        "description": "El SKU (item_code) del producto o el ID Compuesto (item_code + '_WAREHOUSENAME').",
                    },
                    "identifier_type": {
                        "type": "string",
                        "enum": ["sku", "composite_id"], # Changed 'wc_product_id' to 'composite_id'
                        "description": "Indica si el identificador es 'sku' (para buscar en todas las ubicaciones) o 'composite_id' (para una ubicación específica).",
                    },
                },
                "required": ["product_identifier", "identifier_type"],
            },
        },
    },
]

# ── Helper functions ────────────────────────────────────────────────────────────
def _format_sb_history_for_openai_compatible_api(
    sb_messages: Optional[List],
) -> List[Dict[str, Union[str, List[Dict[str, Union[str, Dict]]]]]]:
    # ... (Keep your existing _format_sb_history_for_openai_compatible_api function as is) ...
    if not sb_messages: return []
    openai_messages = []
    bot_user_id_str = Config.SUPPORT_BOARD_BOT_USER_ID
    if not bot_user_id_str: logger.error("SUPPORT_BOARD_BOT_USER_ID not set..."); return []
    for msg in sb_messages:
        sender_id = msg.get("user_id"); text_content = msg.get("message","").strip()
        attachments = msg.get("attachments"); image_urls: List[str] = []
        if attachments and isinstance(attachments, list):
            for att in attachments:
                url=att.get("url","")
                if url and (att.get("type","").startswith("image") or url.lower().endswith((".jpg",".jpeg",".png",".gif",".webp"))):
                    if url.startswith(("http://","https://")): image_urls.append(url)
                    else: logger.warning("Skipping non-public image URL: %s",url)
        if not text_content and not image_urls: continue
        if sender_id is None: logger.warning("Skipping msg with no sender_id."); continue
        role="assistant" if str(sender_id)==bot_user_id_str else "user"
        content_payload: Union[str, List[Dict[str, Union[str, Dict]]]]
        if image_urls:
            content_payload = []
            if text_content: content_payload.append({"type":"text","content":text_content})
            for url in image_urls: content_payload.append({"type":"image_url","image_url":{"url":url}})
        else: content_payload = text_content
        openai_messages.append({"role":role,"content":content_payload})
    return openai_messages


def _format_search_results_for_llm(results: Optional[List[Dict[str, Any]]]) -> str: # Changed type hint
    """Returns search results as raw JSON."""
    if results is None: # Error occurred during search
        return json.dumps({"error": "Ocurrió un error interno al buscar en el catálogo. Intenta más tarde."}, ensure_ascii=False)
    if not results: # No products found
        return json.dumps({"message": "No se encontraron productos que coincidan con esa descripción."}, ensure_ascii=False)
    try:
        # 'results' is already List[Dict[str, Any]] from product_service.search_local_products
        return json.dumps(results, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Error serialising search results to JSON for LLM.")
        return json.dumps({"error": f"Error al formatear los resultados de búsqueda: {str(e)}"}, ensure_ascii=False)


def _format_live_details_for_llm(details_input: Union[Optional[Dict[str, Any]], Optional[List[Dict[str, Any]]]]) -> str:
    """
    Formats live product details for LLM. Handles single entry or list of entries (for SKU with multiple locations).
    """
    if details_input is None: # Error occurred during fetch
        return json.dumps({"error": "No se pudieron recuperar los detalles en tiempo real para ese producto."}, ensure_ascii=False)

    if isinstance(details_input, dict) and not details_input: # Empty dict means not found for composite_id
        return json.dumps({"message": "No se encontró ningún producto con el ID especificado."}, ensure_ascii=False)
    if isinstance(details_input, list) and not details_input: # Empty list means not found for SKU
        return json.dumps({"message": "No se encontró ningún producto con el SKU especificado."}, ensure_ascii=False)

    # If it's a single dictionary (from composite_id search) or a list with one item
    if isinstance(details_input, dict):
        items_to_format = [details_input]
    elif isinstance(details_input, list):
        items_to_format = details_input
    else: # Should not happen
        return json.dumps({"error": "Formato de detalles inesperado."}, ensure_ascii=False)

    # The product_service now returns dicts from Product.to_dict(), which are already suitable for JSON.
    # The LLM should be good at parsing this structured JSON directly.
    try:
        return json.dumps(items_to_format, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Error serialising live details to JSON for LLM.")
        return json.dumps({"error": f"Error al formatear los detalles del producto: {str(e)}"}, ensure_ascii=False)


# ── Main entry point ────────────────────────────────────────────────────────────
def process_new_message_gemini_via_openai_lib(
    sb_conversation_id: str,
    # ... (other parameters remain the same) ...
    new_user_message: Optional[str],
    conversation_source: Optional[str],
    sender_user_id: str,
    customer_user_id: str,
    triggering_message_id: Optional[str],
):
    logger.info(
        f"[Namwoo-Gemini] Handling SB Conv {sb_conversation_id} (User: {customer_user_id}, TriggerMsg: {triggering_message_id})"
    )

    if not GOOGLE_SDK_AVAILABLE or not google_gemini_client_via_openai_lib:
        logger.error("[Namwoo-Gemini] Google Gemini client not available.")
        # ... (send error reply to SB) ...
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text="Disculpa, el servicio de IA (Google) no está disponible en este momento.",
            source=conversation_source, target_user_id=customer_user_id,
            conversation_details=None, triggering_message_id=triggering_message_id,
        )
        return

    # --- Fetch and format conversation history (Keep your existing logic) ---
    conversation_data = support_board_service.get_sb_conversation_data(sb_conversation_id)
    if conversation_data is None: # ... handle error ...
        support_board_service.send_reply_to_channel(conversation_id=sb_conversation_id, message_text="Lo siento, no pude acceder a los detalles de esta conversación.", source=conversation_source, target_user_id=customer_user_id, conversation_details=None, triggering_message_id=triggering_message_id); return
    
    try:
        api_history = _format_sb_history_for_openai_compatible_api(conversation_data.get("messages", []))
        if not api_history: # ... handle error if history is empty after formatting ...
            logger.warning(f"[Namwoo-Gemini] Formatted history is empty for Conv {sb_conversation_id}.")
            support_board_service.send_reply_to_channel(conversation_id=sb_conversation_id, message_text="Lo siento, no pude procesar los mensajes anteriores.", source=conversation_source, target_user_id=customer_user_id, conversation_details=conversation_data, triggering_message_id=triggering_message_id); return
    except Exception as e: # ... handle error ...
        logger.exception(f"[Namwoo-Gemini] Error formatting SB history for Conv {sb_conversation_id}: {e}")
        support_board_service.send_reply_to_channel(conversation_id=sb_conversation_id, message_text="Lo siento, tuve problemas al procesar el historial.", source=conversation_source, target_user_id=customer_user_id, conversation_details=conversation_data, triggering_message_id=triggering_message_id); return

    # Model name for Gemini via OpenAI lib is usually just the model ID like "gemini-1.5-flash-latest"
    # The base_url handles the "models/" prefix.
    gemini_model_name = Config.GOOGLE_GEMINI_MODEL # e.g., "gemini-1.5-flash-latest"

    messages_for_api = [{"role": "system", "content": Config.SYSTEM_PROMPT}] + api_history
    if len(messages_for_api) > MAX_HISTORY_MESSAGES:
        messages_for_api = [messages_for_api[0]] + messages_for_api[-MAX_HISTORY_MESSAGES + 1 :]

    # --- Interaction with Gemini (Tool Call Loop) ---
    final_assistant_response: Optional[str] = None
    try:
        tool_call_count = 0
        # Allow up to TOOL_CALL_RETRY_LIMIT additional attempts after the first one
        while tool_call_count <= TOOL_CALL_RETRY_LIMIT: 
            api_call_params: Dict[str, Any] = {
                "model": gemini_model_name, # Use the model ID
                "messages": messages_for_api,
                "max_tokens": DEFAULT_MAX_TOKENS,
            }
            if tool_call_count == 0: # Only send tools on the first function-calling attempt
                api_call_params["tools"] = tools_schema
                api_call_params["tool_choice"] = "auto" # Let Gemini decide

            logger.debug(f"[Namwoo-Gemini] Sending request to Gemini (Attempt {tool_call_count + 1}): Model={gemini_model_name}, Tools Sent={tool_call_count==0}")

            response = google_gemini_client_via_openai_lib.chat.completions.create(**api_call_params)
            response_msg = response.choices[0].message
            tool_calls = response_msg.tool_calls

            if response.usage:
                logger.info(
                    "[Namwoo-Gemini] Tokens usage - Prompt: %d, Completion: %d, Total: %d",
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                    response.usage.total_tokens,
                )

            if not tool_calls:
                final_assistant_response = response_msg.content
                logger.debug(f"[Namwoo-Gemini] Received final response from Gemini: '{str(final_assistant_response)[:200]}...'")
                break # Exit loop, we have a final response

            # --- Execute tool requests ---
            messages_for_api.append(response_msg) # Add assistant's message asking for tool calls
            tool_outputs_for_api: List[Dict[str, str]] = []

            for tc in tool_calls:
                fname = tc.function.name
                tool_call_id = tc.id
                logger.info("[Namwoo-Gemini] Gemini requested tool: %s with ID %s, Args: %s", fname, tool_call_id, tc.function.arguments)
                
                tool_content_str: str
                try:
                    args = json.loads(tc.function.arguments)

                    if fname == "search_local_products":
                        query = args.get("query_text")
                        filter_stock_flag = args.get("filter_stock", True)
                        if query:
                            search_results_list = product_service.search_local_products(
                                query_text=query,
                                limit=Config.PRODUCT_SEARCH_LIMIT, # Use configured limit
                                filter_stock=filter_stock_flag
                            )
                            tool_content_str = _format_search_results_for_llm(search_results_list)
                        else:
                            tool_content_str = json.dumps({"error": "Argumento 'query_text' es requerido para search_local_products."}, ensure_ascii=False)
                    
                    elif fname == "get_live_product_details":
                        identifier = args.get("product_identifier")
                        id_type = args.get("identifier_type")
                        if not identifier or not id_type:
                            tool_content_str = json.dumps({"error": "Argumentos 'product_identifier' e 'identifier_type' son requeridos."}, ensure_ascii=False)
                        else:
                            details_result: Union[Optional[Dict[str, Any]], Optional[List[Dict[str, Any]]]] = None
                            if id_type == "sku":
                                # product_service.get_live_product_details_by_sku now returns a list
                                details_result = product_service.get_live_product_details_by_sku(item_code_query=identifier)
                            elif id_type == "composite_id": # Changed from wc_product_id
                                details_result = product_service.get_live_product_details_by_id(composite_id=identifier)
                            else:
                                tool_content_str = json.dumps({"error": f"Tipo de identificador '{id_type}' no soportado. Use 'sku' o 'composite_id'."}, ensure_ascii=False)
                            
                            if details_result is not None or (isinstance(details_result, list) and details_result): # Check if result is not None or an empty list
                                tool_content_str = _format_live_details_for_llm(details_result)
                            elif details_result is None: # Error during fetch
                                 tool_content_str = _format_live_details_for_llm(None)
                            else: # Empty list/dict, meaning not found
                                 tool_content_str = _format_live_details_for_llm([])


                    else:
                        logger.warning(f"[Namwoo-Gemini] Unknown tool requested: {fname}")
                        tool_content_str = json.dumps({"error": f"Herramienta desconocida '{fname}'."}, ensure_ascii=False)

                except json.JSONDecodeError:
                    logger.error("[Namwoo-Gemini] Invalid JSON arguments for tool %s: %s", fname, tc.function.arguments)
                    tool_content_str = json.dumps({"error": f"Argumentos JSON inválidos para la herramienta {fname}."}, ensure_ascii=False)
                except Exception as e_tool:
                    logger.exception("[Namwoo-Gemini] Error executing tool %s", fname)
                    tool_content_str = json.dumps({"error": f"Error interno ejecutando la herramienta {fname}: {str(e_tool)}"}, ensure_ascii=False)
                
                tool_outputs_for_api.append({
                    "tool_call_id": tool_call_id,
                    "role": "tool",
                    "name": fname,
                    "content": tool_content_str,
                })

            messages_for_api.extend(tool_outputs_for_api) # Add tool results to messages for next API call
            tool_call_count += 1
            
            if tool_call_count > TOOL_CALL_RETRY_LIMIT and not final_assistant_response:
                logger.warning("[Namwoo-Gemini] Tool call retry limit (%s) reached for conv %s. Sending fallback message.", TOOL_CALL_RETRY_LIMIT, sb_conversation_id)
                final_assistant_response = ("Lo siento, tuve algunos problemas al intentar obtener la información que necesitas usando mis herramientas internas. "
                                            "¿Podrías intentar reformular tu pregunta o intentarlo de nuevo un poco más tarde?")
                break # Exit retry loop

    # --- Error Handling for Gemini API calls (Keep your existing handlers, adjust messages if needed) ---
    except RateLimitError:
        logger.warning("[Namwoo-Gemini] RateLimitError for conv %s", sb_conversation_id)
        final_assistant_response = "El servicio de IA (Google) está experimentando un alto volumen de solicitudes. Por favor, intenta más tarde."
    except APITimeoutError:
        logger.warning("[Namwoo-Gemini] APITimeoutError for conv %s", sb_conversation_id)
        final_assistant_response = "No pude obtener respuesta del servicio de IA (Google) a tiempo. Por favor, intenta más tarde."
    except BadRequestError as br_err:
        err_body_str = str(getattr(br_err, "body", br_err)).lower()
        if "user location" in err_body_str and "not supported" in err_body_str:
            logger.warning("[Namwoo-Gemini] User location not supported for conv %s.", sb_conversation_id)
            final_assistant_response = "Lo siento, tu ubicación actual no es compatible con el servicio de IA de Google en este momento."
        elif "image" in err_body_str or "url" in err_body_str:
            logger.warning("[Namwoo-Gemini] Invalid image error for conv %s: %s", sb_conversation_id, err_body_str)
            final_assistant_response = "Lo siento, parece que una imagen proporcionada no es válida o accesible para Google."
        else:
            logger.warning("[Namwoo-Gemini] BadRequestError for conv %s: %s", sb_conversation_id, br_err, exc_info=True)
            final_assistant_response = "Lo siento, hubo un problema con el formato de nuestra conversación o con una imagen proporcionada."
    except APIError as api_err: # Catch other OpenAI library / API errors
        status_code = getattr(api_err, "status_code", "N/A")
        logger.error("[Namwoo-Gemini] APIError (Status: %s) for conv %s: %s", status_code, sb_conversation_id, api_err, exc_info=True)
        final_assistant_response = f"Hubo un error general ({status_code}) con el servicio de IA de Google. Por favor, inténtalo más tarde."
    except Exception as e: # Catch-all for other unexpected errors
        logger.exception("[Namwoo-Gemini] Unexpected error during Gemini interaction for conv %s", sb_conversation_id)
        final_assistant_response = "Ocurrió un error inesperado al procesar tu solicitud con Google AI. Por favor, intenta de nuevo."

    # --- Send reply back to Support Board ---
    if final_assistant_response:
        logger.info(f"[Namwoo-Gemini] Sending final response to SB for conv {sb_conversation_id}: '{final_assistant_response[:100]}...'")
        # ... (your existing support_board_service.send_reply_to_channel logic) ...
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id, message_text=final_assistant_response,
            source=conversation_source, target_user_id=customer_user_id,
            conversation_details=conversation_data, triggering_message_id=triggering_message_id,
        )
    elif not tool_calls: # This case should be rare if errors above set a final_assistant_response
        logger.error("[Namwoo-Gemini] No final response and no tool calls were made for conv %s. Sending generic fallback.", sb_conversation_id)
        # ... (send generic fallback) ...
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id, message_text="Lo siento, no pude generar una respuesta en este momento.",
            source=conversation_source, target_user_id=customer_user_id,
            conversation_details=conversation_data, triggering_message_id=triggering_message_id,
        )
    # If tool_calls happened but loop ended due to retries without a final_assistant_response, 
    # the fallback inside the loop should have already set final_assistant_response.

# ── Back‑compat alias expected by routes.py ────────────────────────────────────
process_new_message_gemini = process_new_message_gemini_via_openai_lib