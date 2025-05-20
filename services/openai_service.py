# NAMWOO/services/openai_service.py
# -*- coding: utf-8 -*-
import logging
import json
import time # Keep time if used by retry logic within embedding_utils
from typing import List, Dict, Optional, Tuple, Union, Any
from openai import OpenAI, APIError, RateLimitError, APITimeoutError, BadRequestError
from flask import current_app # For accessing app config like OPENAI_EMBEDDING_MODEL

# Import local services and utils
from . import product_service
from . import support_board_service
from ..config import Config # For SYSTEM_PROMPT, MAX_HISTORY_MESSAGES etc.
from ..utils import embedding_utils # <--- NEW: Import your embedding utility

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Initialise OpenAI client for Chat Completions
# This client instance is primarily for chat. Embeddings can use a fresh call
# or this client if preferred, but embedding_utils handles its own client init.
_chat_client: Optional[OpenAI] = None # Renamed for clarity
try:
    openai_api_key = Config.OPENAI_API_KEY
    if openai_api_key:
        _chat_client = OpenAI(api_key=openai_api_key, timeout=60.0) # Timeout for chat
        logger.info("OpenAI client initialized for Chat Completions service.")
    else:
        _chat_client = None
        logger.error(
            "OpenAI API key not configured during initial load. "
            "Chat functionality will fail."
        )
except Exception:
    logger.exception("Failed to initialize OpenAI client for chat during initial load.")
    _chat_client = None

# ---------------------------------------------------------------------------
# Constants (Keep as is)
MAX_HISTORY_MESSAGES = Config.MAX_HISTORY_MESSAGES
TOOL_CALL_RETRY_LIMIT = 2
DEFAULT_OPENAI_MODEL = getattr(Config, "OPENAI_CHAT_MODEL", "gpt-4o-mini")
DEFAULT_MAX_TOKENS = getattr(Config, "OPENAI_MAX_TOKENS", 1024)

# ---------------------------------------------------------------------------
# NEW: Embedding Generation Function
# ---------------------------------------------------------------------------
def generate_product_embedding(text_to_embed: str) -> Optional[List[float]]:
    """
    Generates an embedding for the given product text using the configured
    OpenAI embedding model via embedding_utils.
    """
    if not text_to_embed or not isinstance(text_to_embed, str):
        logger.warning("openai_service.generate_product_embedding: No valid text provided.")
        return None

    # Get the embedding model from Flask app config (which should load from Config/env)
    # Ensure Config.OPENAI_EMBEDDING_MODEL is defined and loaded correctly
    embedding_model_name = current_app.config.get('OPENAI_EMBEDDING_MODEL', Config.OPENAI_EMBEDDING_MODEL)
    
    if not embedding_model_name:
        logger.error("openai_service.generate_product_embedding: OPENAI_EMBEDDING_MODEL not configured.")
        return None

    logger.debug(f"Requesting embedding for text: '{text_to_embed[:100]}...' using model: {embedding_model_name}")

    # Call the utility function which handles the actual API call and retries
    # embedding_utils.get_embedding already initializes its own client if needed,
    # or you could modify embedding_utils to accept an optional client instance.
    # For simplicity, let embedding_utils manage its client for embeddings.
    embedding_vector = embedding_utils.get_embedding(
        text=text_to_embed,
        model=embedding_model_name
        # Retries and initial_delay will use defaults in embedding_utils.get_embedding
    )

    if embedding_vector is None:
        logger.error(f"openai_service.generate_product_embedding: Failed to get embedding from embedding_utils for text: '{text_to_embed[:100]}...'")
        return None
    
    logger.info(f"Successfully generated embedding for text (first 100 chars): '{text_to_embed[:100]}...'")
    return embedding_vector

# ---------------------------------------------------------------------------
# Tool definitions (Keep as is)
tools_schema = [
    # ... your existing tool schemas ...
    {
        "type": "function",
        "function": {
            "name": "search_local_products",
            "description": (
                "Busca en la base de datos local usando búsqueda semántica y devuelve "
                "TODOS los productos coincidentes como lista JSON. Cada objeto incluye "
                "name, sku, price, stock_status, permalink y metadatos relevantes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query_text": {
                        "type": "string",
                        "description": (
                            "Consulta que describe el producto, por ejemplo "
                            "'televisor 55 pulgadas oled'."
                        ),
                    },
                    "filter_stock": {
                        "type": "boolean",
                        "description": (
                            "Si es true, limita a productos con stock_status='instock'."
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
                "Consulta el inventario en tiempo real de Damasco para precio/stock de un producto "
                "específico identificado por SKU o ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_identifier": {
                        "type": "string",
                        "description": "SKU o ID del producto.",
                    },
                    "identifier_type": {
                        "type": "string",
                        "enum": ["sku", "wc_product_id"], 
                        "description": "Indica si el identificador es SKU o wc_product_id.",
                    },
                },
                "required": ["product_identifier", "identifier_type"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Helper: format Support‑Board history for OpenAI (Keep as is)
def _format_sb_history_for_openai(
    sb_messages: Optional[List],
) -> List[Dict[str, Union[str, List[Dict[str, Union[str, Dict]]]]]]:
    # ... your existing history formatting logic ...
    if not sb_messages:
        return []

    openai_messages: List[Dict[str, Union[str, List[Dict]]]] = []
    bot_user_id_str = Config.SUPPORT_BOARD_BOT_USER_ID
    if not bot_user_id_str:
        logger.error(
            "Cannot format SB history: SUPPORT_BOARD_BOT_USER_ID is not configured."
        )
        return []

    for msg in sb_messages:
        sender_id = msg.get("user_id")
        text_content = msg.get("message", "").strip()
        attachments = msg.get("attachments")
        image_urls: List[str] = []
        if attachments and isinstance(attachments, list):
            for att in attachments:
                if (
                    isinstance(att, dict)
                    and att.get("url")
                    and (
                        att.get("type", "").startswith("image")
                        or any(
                            att["url"].lower().endswith(ext)
                            for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]
                        )
                    )
                ):
                    url = att["url"]
                    if url.startswith(("http://", "https://")):
                        image_urls.append(url)
                    else:
                        logger.warning(
                            "Skipping possible non‑public URL for attachment %s", url
                        )
        if not text_content and not image_urls:
            continue
        if sender_id is None:
            continue
        role = "assistant" if str(sender_id) == bot_user_id_str else "user"
        if image_urls:
            content: List[Dict[str, Union[str, Dict]]] = []
            if text_content:
                content.append({"type": "text", "content": text_content})
            for url in image_urls:
                content.append({"type": "image_url", "image_url": {"url": url}})
        else:
            content = text_content  # type: ignore[assignment]
        openai_messages.append({"role": role, "content": content})
    return openai_messages

# ---------------------------------------------------------------------------
# Helper: format search results (Keep as is)
def _format_search_results_for_llm(results: Optional[List[Dict[str, Any]]]) -> str:
    # ... your existing search results formatting logic ...
    if results is None:
        return (
            "Lo siento, ocurrió un error interno al buscar en el catálogo. "
            "Por favor, intenta de nuevo más tarde."
        )
    if not results:
        return (
            "Lo siento, no pude encontrar productos que coincidan con esa "
            "descripción en nuestro catálogo actual."
        )
    try:
        return json.dumps(results, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as err:
        logger.error("JSON serialisation error: %s", err)
        return (
            "Lo siento, hubo un problema al formatear los resultados de la búsqueda."
        )

# ---------------------------------------------------------------------------
# Helper: live‑detail formatter (Keep as is)
def _format_live_details_for_llm(details: Optional[Dict]) -> str:
    # ... your existing live details formatting logic ...
    if details is None:
        return (
            "Lo siento, no pude recuperar los detalles en tiempo real para ese "
            "producto."
        )

    name = details.get("name", "el producto")
    sku = details.get("sku", "N/A")
    response_parts = [f"Aquí están los detalles actuales para {name} (SKU: {sku}):"]
    price = details.get("price")
    if price not in (None, ""):
        try:
            response_parts.append(f"- Precio Actual: ${float(price):.2f}")
        except (ValueError, TypeError):
            response_parts.append(f"- Precio Actual: {price}")
    else:
        response_parts.append("- Precio Actual: No disponible")
    if details.get("manage_stock") and details.get("stock_quantity") is not None:
        qty = details["stock_quantity"]
        response_parts.append(f"- Cantidad en Stock: {qty}")
        if qty == 0:
            response_parts.append("  (Actualmente agotado)")
        elif 0 < qty <= 5:
            response_parts.append("  (¡Pocas unidades!)")
    else:
        stock_status = (
            details.get("stock_status", "Desconocido")
            .replace("instock", "en stock")
            .replace("outofstock", "agotado")
        )
        response_parts.append(f"- Estado de Stock: {stock_status}")
    if permalink := details.get("permalink"):
        response_parts.append(f"- Ver producto online: {permalink}")
    return "\n".join(response_parts)

# ---------------------------------------------------------------------------
# Main processing entry‑point (Keep as is)
def process_new_message(
    sb_conversation_id: str,
    new_user_message: Optional[str],
    conversation_source: Optional[str],
    sender_user_id: str,
    customer_user_id: str,
    triggering_message_id: Optional[str],
) -> None:
    global _chat_client # Use the initialized chat client
    if not _chat_client: # Check the chat client specifically
        logger.error("OpenAI client for chat not initialized. Cannot process message.")
        # ... (rest of your error handling for no client) ...
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text="Disculpa, el servicio de IA no está disponible en este momento.",
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=None,
            triggering_message_id=None,
        )
        return

    logger.info(
        "Processing message for SB Conv %s (trigger_user=%s, customer=%s, "
        "source=%s, trig_msg_id=%s)",
        sb_conversation_id,
        sender_user_id,
        customer_user_id,
        conversation_source,
        triggering_message_id,
    )
    # ... (rest of your existing process_new_message logic using _chat_client) ...
    # -----------------------------------------------------------------------
    # 1. Fetch full conversation from SB
    conversation_data = support_board_service.get_sb_conversation_data(
        sb_conversation_id
    )
    if conversation_data is None:
        logger.error("Failed to fetch conversation data. Aborting.")
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text=(
                "Lo siento, no pude acceder a los detalles de esta conversación. "
                "¿Podrías repetir tu pregunta?"
            ),
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=None,
            triggering_message_id=triggering_message_id,
        )
        return

    sb_history_list = conversation_data.get("messages", [])
    if not sb_history_list:
        logger.warning("No message history found; cannot proceed effectively.")
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text="Lo siento, no pude cargar el historial de esta conversación.",
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=conversation_data,
            triggering_message_id=triggering_message_id,
        )
        return

    # 2. Format history for OpenAI
    try:
        openai_history = _format_sb_history_for_openai(sb_history_list)
    except Exception as err:
        logger.exception("Error formatting history: %s", err)
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text=(
                "Lo siento, tuve problemas al procesar el historial de la conversación."
            ),
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=conversation_data,
            triggering_message_id=triggering_message_id,
        )
        return

    if not openai_history:
        logger.error("Formatted history is empty. Aborting.")
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text="Lo siento, no pude procesar los mensajes anteriores.",
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=conversation_data,
            triggering_message_id=triggering_message_id,
        )
        return

    # 3. Build messages list (system + history)
    system_prompt = Config.SYSTEM_PROMPT
    messages: List[Dict[str, Union[str, List]]] = [
        {"role": "system", "content": system_prompt}
    ] + openai_history

    # 4. Trim if necessary
    max_hist = current_app.config.get("MAX_HISTORY_MESSAGES", MAX_HISTORY_MESSAGES)
    if len(messages) > max_hist:
        messages = [messages[0]] + messages[-(max_hist - 1) :]

    # -----------------------------------------------------------------------
    # 5. OpenAI loop (handle tool calls)
    final_assistant_response: Optional[str] = None
    try:
        tool_call_count = 0
        while tool_call_count < TOOL_CALL_RETRY_LIMIT:
            openai_model = current_app.config.get("OPENAI_CHAT_MODEL", DEFAULT_OPENAI_MODEL)
            max_tokens = current_app.config.get("OPENAI_MAX_TOKENS", DEFAULT_MAX_TOKENS)

            call_params: Dict[str, Any] = {
                "model": openai_model,
                "messages": messages,
                "max_tokens": max_tokens,
            }
            if tool_call_count == 0: # Only send tools on the first call in a retry loop
                call_params["tools"] = tools_schema
                call_params["tool_choice"] = "auto"

            response = _chat_client.chat.completions.create(**call_params)
            resp_msg = response.choices[0].message
            tool_calls = resp_msg.tool_calls

            if not tool_calls:
                final_assistant_response = resp_msg.content
                break 

            messages.append(resp_msg) 
            tool_outputs: List[Dict[str, str]] = []

            for tc in tool_calls:
                fn_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {} # Default to empty dict if arguments are malformed
                logger.info("OpenAI requested tool call: %s with args: %s", fn_name, args)

                output_txt = f"Error: Tool execution failed for {fn_name}" # Default error
                try:
                    if fn_name == "search_local_products":
                        query = args.get("query_text")
                        filter_stock_flag = args.get("filter_stock", True) # Default to True
                        if query:
                            # product_service.search_local_products now returns List[Dict] or None
                            search_res = product_service.search_local_products(
                                query_text=query,
                                filter_stock=filter_stock_flag,
                                # limit and min_score can use defaults in product_service
                            )
                            output_txt = _format_search_results_for_llm(search_res)
                        else:
                            output_txt = "Error: 'query_text' is a required argument for search_local_products."
                    
                    elif fn_name == "get_live_product_details":
                        ident = args.get("product_identifier")
                        id_type = args.get("identifier_type")
                        if ident and id_type:
                            live_details = None
                            if id_type == "sku":
                                # product_service.get_live_product_details_by_sku now returns List[Dict] or None
                                # The LLM needs to handle multiple locations if a list is returned.
                                # For simplicity in tool call, we might decide to return info for the first one
                                # or a summary if multiple exist.
                                # OR, the LLM should be prompted to ask for location if multiple are found.
                                # Current _format_live_details_for_llm expects a single Dict.
                                # This part needs careful thought on how to present multi-location SKU results.
                                # For now, let's assume it might return a list, and we format the first.
                                # OR better, the product_service.get_live_product_details_by_sku should be adapted
                                # if the tool always expects a single product detail dict.
                                # Given the Damasco data, an SKU (item_code) can have multiple locations.
                                # The tool description says "a producto específico". This is ambiguous now.
                                # Let's assume for now the function needs to return one, or an error if ambiguous.
                                # For this exercise, let's stick to current product_service.py which returns a list.
                                sku_details_list = product_service.get_live_product_details_by_sku(item_code_query=ident)
                                if sku_details_list is None: # Error occurred
                                     output_txt = "Error: No se pudieron obtener los detalles del producto por SKU."
                                elif not sku_details_list: # Empty list, not found
                                     output_txt = f"No se encontró ningún producto con SKU: {ident}."
                                elif len(sku_details_list) == 1:
                                     output_txt = _format_live_details_for_llm(sku_details_list[0])
                                else:
                                     output_txt = (f"Se encontraron múltiples ubicaciones para el SKU {ident}. "
                                                   f"Por favor, especifique una ubicación o pregunte por las disponibilidades.")
                                     # Alternatively, summarize or list them here.
                            elif id_type == "wc_product_id": # This maps to our composite 'id' now
                                live_details = product_service.get_live_product_details_by_id(composite_id=ident)
                                output_txt = _format_live_details_for_llm(live_details)
                            else:
                                output_txt = f"Error: Tipo de identificador '{id_type}' no soportado. Use 'sku' o 'wc_product_id' (para ID compuesto de almacén)."
                        else:
                            output_txt = "Error: Faltan 'product_identifier' o 'identifier_type' para get_live_product_details."
                    else:
                        output_txt = f"Error: Herramienta desconocida '{fn_name}'."
                except Exception as tool_exec_err:
                    logger.exception("Tool execution error for %s: %s", fn_name, tool_exec_err)
                    output_txt = f"Error interno al ejecutar la herramienta {fn_name}."

                tool_outputs.append({
                    "tool_call_id": tc.id,
                    "role": "tool",
                    "name": fn_name,
                    "content": output_txt,
                })

            messages.extend(tool_outputs)
            tool_call_count += 1

            if tool_call_count >= TOOL_CALL_RETRY_LIMIT and not final_assistant_response:
                logger.warning("Tool call retry limit reached for conv %s. Sending fallback.", sb_conversation_id)
                final_assistant_response = (
                    "Lo siento, tuve algunos problemas al intentar obtener la información que necesitas. "
                    "¿Podrías intentar reformular tu pregunta o intentarlo de nuevo un poco más tarde?"
                )
    # ... (rest of your error handling for OpenAI API calls) ...
    except RateLimitError:
        logger.warning("OpenAI RateLimitError for conv %s", sb_conversation_id)
        final_assistant_response = (
            "Estoy experimentando un alto volumen de solicitudes. "
            "Por favor, espera un momento y vuelve a intentarlo."
        )
    # ... and other specific OpenAI exceptions ...
    except BadRequestError as bre: # Example, catch more specific errors
        logger.error("OpenAI BadRequestError for conv %s: %s", sb_conversation_id, bre, exc_info=True)
        final_assistant_response = (
            "Lo siento, hubo un problema con el formato de nuestra conversación. "
            "Por favor, revisa si enviaste alguna imagen que no sea válida."
        )
    except APIError as apie:
        logger.error("OpenAI APIError for conv %s (Status: %s): %s", sb_conversation_id, apie.status_code, apie, exc_info=True)
        final_assistant_response = (
            f"Hubo un error ({apie.status_code}) con el servicio de IA. "
            "Por favor, inténtalo más tarde."
        )
    except Exception as e:
        logger.exception("Unexpected OpenAI interaction error for conv %s: %s", sb_conversation_id, e)
        final_assistant_response = (
            "Ocurrió un error inesperado al procesar tu solicitud. "
            "Por favor, intenta de nuevo."
        )


    # -----------------------------------------------------------------------
    # 6. Send reply via Support Board (Keep as is)
    if final_assistant_response:
        # ... your existing send reply logic ...
        success = support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text=final_assistant_response,
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=conversation_data, # Pass conversation_data
            triggering_message_id=triggering_message_id, # Pass triggering_message_id
        )
        if not success:
            logger.error(
                "Failed to send final reply via SB API "
                "(conv=%s, target=%s, source=%s)",
                sb_conversation_id,
                customer_user_id,
                conversation_source,
            )
    else: # Should ideally not happen if fallback messages are set in error handlers
        logger.error(
            "No final assistant response was generated for conversation %s after all attempts; sending generic fallback.",
            sb_conversation_id,
        )
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text=(
                "Lo siento, no pude generar una respuesta en este momento. "
                "Por favor, intenta de nuevo."
            ),
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=conversation_data, # Pass conversation_data
            triggering_message_id=triggering_message_id, # Pass triggering_message_id
        )

# --- End of NAMWOO/services/openai_service.py ---