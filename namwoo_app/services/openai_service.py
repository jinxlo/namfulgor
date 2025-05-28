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
from ..utils import embedding_utils

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Initialise OpenAI client for Chat Completions
# This client instance is primarily for chat. Embeddings can use a fresh call
# or this client if preferred, but embedding_utils handles its own client init.
_chat_client: Optional[OpenAI] = None
try:
    openai_api_key = Config.OPENAI_API_KEY
    if openai_api_key:
        # Use configured timeout if available, otherwise default to 60.0
        timeout_seconds = getattr(Config, 'OPENAI_REQUEST_TIMEOUT', 60.0)
        _chat_client = OpenAI(api_key=openai_api_key, timeout=timeout_seconds)
        logger.info(f"OpenAI client initialized for Chat Completions service with timeout: {timeout_seconds}s.")
    else:
        _chat_client = None
        logger.error(
            "OpenAI API key not configured during initial load. "
            "Chat functionality will fail."
        )
except Exception as e: # Keep original less specific Exception catch, added 'e' for logging
    logger.exception(f"Failed to initialize OpenAI client for chat during initial load: {e}")
    _chat_client = None

# ---------------------------------------------------------------------------
# Constants
MAX_HISTORY_MESSAGES = Config.MAX_HISTORY_MESSAGES # Assumes this exists in Config
TOOL_CALL_RETRY_LIMIT = 2
DEFAULT_OPENAI_MODEL = getattr(Config, "OPENAI_CHAT_MODEL", "gpt-4o-mini")
DEFAULT_MAX_TOKENS = getattr(Config, "OPENAI_MAX_TOKENS", 1024)
DEFAULT_OPENAI_TEMPERATURE = getattr(Config, "OPENAI_TEMPERATURE", 0.7) # Added for consistency

# ---------------------------------------------------------------------------
# Embedding Generation Function
# ---------------------------------------------------------------------------
def generate_product_embedding(text_to_embed: str) -> Optional[List[float]]:
    """
    Generates an embedding for the given product text using the configured
    OpenAI embedding model via embedding_utils.
    """
    if not text_to_embed or not isinstance(text_to_embed, str):
        logger.warning("openai_service.generate_product_embedding: No valid text provided.")
        return None

    # Get the embedding model from Config (preferred over current_app.config for directness)
    embedding_model_name = Config.OPENAI_EMBEDDING_MODEL # Assuming this exists in Config

    if not embedding_model_name:
        logger.error("openai_service.generate_product_embedding: OPENAI_EMBEDDING_MODEL not configured in Config.")
        return None

    logger.debug(f"Requesting embedding for text: '{text_to_embed[:100]}...' using model: {embedding_model_name}")

    embedding_vector = embedding_utils.get_embedding(
        text=text_to_embed,
        model=embedding_model_name
    )

    if embedding_vector is None:
        logger.error(f"openai_service.generate_product_embedding: Failed to get embedding from embedding_utils for text: '{text_to_embed[:100]}...'")
        return None

    logger.info(f"Successfully generated embedding for text (first 100 chars): '{text_to_embed[:100]}...'")
    return embedding_vector

# ---------------------------------------------------------------------------
# FUNCTION FOR PRODUCT DESCRIPTION SUMMARIZATION (using OpenAI)
# ---------------------------------------------------------------------------
def get_openai_product_summary(
    plain_text_description: str,
    item_name: Optional[str] = None
) -> Optional[str]:
    global _chat_client
    if not _chat_client:
        logger.error("OpenAI client for chat not initialized. Cannot summarize description with OpenAI.")
        return None

    if not plain_text_description or not plain_text_description.strip(): # Added strip() check
        logger.debug("OpenAI summarizer: No plain text description provided to summarize.")
        return None

    prompt_context_parts = []
    if item_name:
        prompt_context_parts.append(f"Nombre del Producto: {item_name}")
    prompt_context_parts.append(f"Descripción Original (texto plano):\n{plain_text_description}")
    prompt_context = "\n".join(prompt_context_parts)

    system_prompt = ( # Your original system prompt for summarization
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
        logger.warning(f"OpenAI summarizer: Description for '{item_name or 'Unknown'}' was truncated for prompt construction.")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Por favor, resume la siguiente información del producto:\n\n{prompt_context}"}
    ]

    try:
        # Use a specific summary model if configured, else the default chat model
        summarization_model = getattr(Config, "OPENAI_SUMMARY_MODEL", DEFAULT_OPENAI_MODEL)
        logger.debug(f"Requesting summary from OpenAI model '{summarization_model}' for item '{item_name or 'Unknown'}'")
        completion = _chat_client.chat.completions.create(
            model=summarization_model,
            messages=messages,
            temperature=0.2,
            max_tokens=150,
            n=1,
            stop=None,
        )
        summary = completion.choices[0].message.content.strip() if completion.choices and completion.choices[0].message.content else None


        if summary:
            logger.info(f"OpenAI summary generated for '{item_name or 'Unknown'}'. Preview: '{summary[:100]}...'")
        else:
            logger.warning(f"OpenAI returned an empty or null summary for '{item_name or 'Unknown'}'. Original text length: {len(plain_text_description)}")
        return summary

    except APIError as e:
        logger.error(f"OpenAI APIError during description summarization for '{item_name or 'Unknown'}': {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Unexpected error calling OpenAI for description summarization for '{item_name or 'Unknown'}': {e}", exc_info=True)
        return None

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------
tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "search_local_products",
            "description": ( # MODIFIED
                "Busca en el catálogo de productos de la tienda utilizando una consulta en lenguaje natural. "
                "Esta herramienta es ideal cuando el usuario pregunta por tipos de productos, características específicas, o si hay 'algo como...'. "
                "Devuelve una lista de productos que coinciden semánticamente con la consulta. "
                "Cada producto devuelto incluye nombre, marca, precio, stock, y una descripción lista para el usuario (llm_formatted_description) que ya contiene la información más relevante."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query_text": {
                        "type": "string",
                        "description": (
                            "La consulta del usuario que describe el producto o característica deseada. "
                            "Por ejemplo: 'televisor inteligente de 55 pulgadas con buen sonido', 'neveras marca Samsung', 'aires acondicionados de ventana'."
                        ),
                    },
                    "filter_stock": {
                        "type": "boolean",
                        "description": (
                            "Opcional. Si es true (defecto), filtra los resultados para mostrar solo productos con stock disponible. "
                            "Establecer en false si el usuario pregunta por productos independientemente de si hay stock o si se quiere verificar si un producto existe en el catálogo."
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
            "description": ( # MODIFIED
                "Obtiene información detallada y actualizada de un producto específico, incluyendo precio exacto y disponibilidad de stock por almacén/sucursal. "
                "Utiliza esta herramienta cuando el usuario pregunta por un producto muy específico (por su código/SKU o ID único si se conoce) o después de que `search_local_products` haya devuelto un producto y el usuario quiera más detalles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_identifier": {
                        "type": "string",
                        "description": "El código de item (SKU) del producto o el ID compuesto (itemCode_warehouseName) del producto en una ubicación específica.",
                    },
                    "identifier_type": {
                        "type": "string",
                        "enum": ["sku", "composite_id"], # MODIFIED from wc_product_id
                        "description": "Especifica si 'product_identifier' es un 'sku' (para buscar en todas las ubicaciones) o un 'composite_id' (para una ubicación específica).",
                    },
                },
                "required": ["product_identifier", "identifier_type"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Helper: format Support‑Board history for OpenAI
# ---------------------------------------------------------------------------
def _format_sb_history_for_openai(
    sb_messages: Optional[List[Dict[str, Any]]], # Using your original type List (implies List[Dict[str,Any]])
) -> List[Dict[str, Any]]: # Using your original return type List[Dict[str, Union[str, List[Dict[str, Union[str, Dict]]]]]]
    if not sb_messages:
        return []

    openai_messages: List[Dict[str, Any]] = []
    # --- MODIFICATION START: Use SUPPORT_BOARD_DM_BOT_USER_ID ---
    bot_user_id_str = str(Config.SUPPORT_BOARD_DM_BOT_USER_ID) if Config.SUPPORT_BOARD_DM_BOT_USER_ID else None
    # --- MODIFICATION END ---

    if not bot_user_id_str:
        logger.error(
            "Cannot format SB history: SUPPORT_BOARD_DM_BOT_USER_ID is not configured." # MODIFIED: Updated error message
        )
        return []

    for msg in sb_messages:
        sender_id = msg.get("user_id")
        text_content = msg.get("message", "").strip()
        attachments = msg.get("attachments")
        image_urls: List[str] = []
        if attachments and isinstance(attachments, list): # Your original attachment handling
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
        if sender_id is None: # Your original check
            continue
            
        role = "assistant" if str(sender_id) == bot_user_id_str else "user"
        
        # Your original multimodal content construction
        content_list_for_openai: List[Dict[str, Any]] = []
        if text_content:
            content_list_for_openai.append({"type": "text", "text": text_content})
        
        current_openai_model = getattr(Config, "OPENAI_CHAT_MODEL", DEFAULT_OPENAI_MODEL)
        vision_capable_models = ["gpt-4-turbo", "gpt-4o", "gpt-4o-mini"] 
        
        if image_urls and current_openai_model in vision_capable_models:
            for img_url in image_urls:
                content_list_for_openai.append({"type": "image_url", "image_url": {"url": img_url}})
        elif image_urls: 
            logger.warning(f"Image URLs found but current model {current_openai_model} may not support vision. Images not explicitly sent to LLM in structured format.")
            if not text_content:
                 content_list_for_openai.append({"type": "text", "text": "[Usuario envió una imagen]"})

        if content_list_for_openai:
            if len(content_list_for_openai) == 1 and content_list_for_openai[0]["type"] == "text":
                openai_messages.append({"role": role, "content": content_list_for_openai[0]["text"]})
            else:
                openai_messages.append({"role": role, "content": content_list_for_openai})
    return openai_messages

# ---------------------------------------------------------------------------
# Helper: format search results
# ---------------------------------------------------------------------------
def _format_search_results_for_llm(results: Optional[List[Dict[str, Any]]]) -> str:
    # MODIFIED: Return structured JSON (This was your existing code, kept as is)
    if results is None:
        return json.dumps({
            "status": "error",
            "message": "Lo siento, ocurrió un error interno al buscar en el catálogo. Por favor, intenta de nuevo más tarde."
        }, ensure_ascii=False)
    if not results:
        return json.dumps({
            "status": "not_found",
            "message": "Lo siento, no pude encontrar productos que coincidan con esa descripción en nuestro catálogo actual."
        }, ensure_ascii=False)
    try:
        return json.dumps({"status": "success", "products": results}, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as err:
        logger.error(f"JSON serialisation error for search results: {err}", exc_info=True)
        return json.dumps({
            "status": "error",
            "message": "Lo siento, hubo un problema al formatear los resultados de la búsqueda."
        }, ensure_ascii=False)

# ---------------------------------------------------------------------------
# Helper: live‑detail formatter
# ---------------------------------------------------------------------------
def _format_live_details_for_llm(details: Optional[Dict[str, Any]], identifier_type: str = "ID") -> str: # Added identifier_type to provide context in error messages
    # MODIFIED: Return structured JSON (This was your existing code, kept as is)
    if details is None: # Error occurred during fetch
        return json.dumps({
            "status": "error",
            "message": f"Lo siento, no pude recuperar los detalles en tiempo real para ese producto ({identifier_type})."
        }, ensure_ascii=False)
    if not details: # Empty dict if product not found by specific ID/SKU
         return json.dumps({
            "status": "not_found",
            "message": f"No se encontraron detalles para el producto con el {identifier_type} proporcionado."
        }, ensure_ascii=False)

    # Construct the product details for the JSON output
    # The 'details' dict is from product_service.Product.to_dict()
    product_info = {
        "name": details.get("item_name", "Producto Desconocido"),
        "item_code": details.get("item_code", "N/A"),
        "id": details.get("id"),
        "description": details.get("llm_formatted_description") or details.get("llm_summarized_description") or details.get("plain_text_description_derived", "Descripción no disponible."),
        "brand": details.get("brand", "N/A"),
        "category": details.get("category", "N/A"),
        "price": details.get("price"),
        "stock": details.get("stock"),
        "warehouse_name": details.get("warehouse_name"),
        "branch_name": details.get("branch_name")
    }
    return json.dumps({"status": "success", "product": product_info}, indent=2, ensure_ascii=False)

# ---------------------------------------------------------------------------
# Main processing entry‑point
# ---------------------------------------------------------------------------
def process_new_message(
    sb_conversation_id: str,
    new_user_message: Optional[str], # Your original signature
    conversation_source: Optional[str],
    sender_user_id: str,
    customer_user_id: str,
    triggering_message_id: Optional[str],
) -> None:
    global _chat_client
    if not _chat_client:
        logger.error("OpenAI client for chat not initialized. Cannot process message.")
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text="Disculpa, el servicio de IA no está disponible en este momento.",
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=None,
            triggering_message_id=triggering_message_id, # Used passed value
        )
        return

    logger.info(
        "Processing message for SB Conv %s (trigger_user=%s, customer=%s, source=%s, trig_msg_id=%s)",
        sb_conversation_id, sender_user_id, customer_user_id, conversation_source, triggering_message_id,
    )

    conversation_data = support_board_service.get_sb_conversation_data(sb_conversation_id)
    if conversation_data is None or not conversation_data.get("messages"): # Your original check
        logger.error(f"Failed to fetch conversation data or no messages found for SB Conv {sb_conversation_id}. Aborting.")
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text="Lo siento, tuve problemas para acceder al historial de esta conversación. ¿Podrías intentarlo de nuevo?",
            source=conversation_source, target_user_id=customer_user_id,
            conversation_details=None, triggering_message_id=triggering_message_id
        )
        return

    sb_history_list = conversation_data.get("messages", []) # Your original
    try:
        openai_history = _format_sb_history_for_openai(sb_history_list)
    except Exception as err:
        logger.exception(f"Error formatting SB history for Conv {sb_conversation_id}: {err}")
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id, message_text="Lo siento, tuve problemas al procesar el historial de la conversación.",
            source=conversation_source, target_user_id=customer_user_id, conversation_details=conversation_data, triggering_message_id=triggering_message_id
        )
        return

    if not openai_history: # Your original check
        # If history formatting resulted in empty but new_user_message exists (e.g., first message of a lead)
        if new_user_message and not sb_history_list: # Only consider new_user_message if sb_history_list was truly empty
            logger.info(f"Formatted OpenAI history is empty for Conv {sb_conversation_id}, using new_user_message as initial prompt.")
            openai_history = [{"role": "user", "content": new_user_message}]
        else:
            logger.error(f"Formatted OpenAI history is empty for Conv {sb_conversation_id}, and no new message to process or history was present. Aborting.")
            support_board_service.send_reply_to_channel(
                conversation_id=sb_conversation_id, message_text="Lo siento, no pude procesar los mensajes anteriores adecuadamente.",
                source=conversation_source, target_user_id=customer_user_id, conversation_details=conversation_data, triggering_message_id=triggering_message_id
            )
            return

    system_prompt_content = Config.SYSTEM_PROMPT
    # Your original type hint for messages:
    messages: List[Dict[str, Union[str, List[Dict[str, Union[str, Dict]]]]]] = [
        {"role": "system", "content": system_prompt_content}
    ] + openai_history # type: ignore

    # Your original history trimming logic
    max_hist_current = getattr(Config, "MAX_HISTORY_MESSAGES", MAX_HISTORY_MESSAGES)
    if len(messages) > (max_hist_current +1 ): # +1 for system prompt
        messages = [messages[0]] + messages[-(max_hist_current):]


    final_assistant_response: Optional[str] = None
    try:
        tool_call_count = 0
        # Your original loop condition
        while tool_call_count < TOOL_CALL_RETRY_LIMIT:
            # Your original logic for fetching config values inside the loop
            openai_model = current_app.config.get("OPENAI_CHAT_MODEL", DEFAULT_OPENAI_MODEL)
            max_tokens = current_app.config.get("OPENAI_MAX_TOKENS", DEFAULT_MAX_TOKENS)
            temperature = current_app.config.get("OPENAI_TEMPERATURE", DEFAULT_OPENAI_TEMPERATURE)


            call_params: Dict[str, Any] = {
                "model": openai_model,
                "messages": messages, # messages list is updated in each iteration
                "max_tokens": max_tokens,
                "temperature": temperature, # Added temperature
            }
            # Only add tools parameter on the first attempt or if the LLM is expected to make subsequent tool calls
            if tool_call_count == 0 or (messages[-1].get("role") == "assistant" and messages[-1].get("tool_calls")):
                 call_params["tools"] = tools_schema
                 call_params["tool_choice"] = "auto"
            else: # If the last message was from a tool, don't offer tools again, let LLM respond
                call_params.pop("tools", None)
                call_params.pop("tool_choice", None)


            logger.debug(f"OpenAI API call attempt {tool_call_count + 1} for Conv {sb_conversation_id}. Message count: {len(messages)}. Tools offered: {'tools' in call_params}")
            response = _chat_client.chat.completions.create(**call_params)
            response_message = response.choices[0].message # This is an ChatCompletionMessage object

            if response.usage:
                 logger.info(f"OpenAI Tokens (Conv {sb_conversation_id}, Attempt {tool_call_count+1}): Prompt={response.usage.prompt_tokens}, Completion={response.usage.completion_tokens}, Total={response.usage.total_tokens}")

            # Append the assistant's response (which might be content or tool_calls) to messages
            messages.append(response_message.model_dump(exclude_none=True))

            tool_calls = response_message.tool_calls

            if not tool_calls:
                final_assistant_response = response_message.content
                logger.info(f"OpenAI response for Conv {sb_conversation_id} (no tool call this turn): '{str(final_assistant_response)[:200]}...'")
                break

            # Process tool calls
            tool_outputs_for_llm: List[Dict[str, str]] = [] # Your original variable name and type
            for tc in tool_calls:
                fn_name = tc.function.name
                tool_call_id = tc.id # Your original way to get tool_call_id
                try:
                    function_args_str = tc.function.arguments # Your original way
                    args = json.loads(function_args_str)
                except json.JSONDecodeError as json_err: # Your original error handling
                    logger.error(f"JSONDecodeError for tool {fn_name} args: {function_args_str}. Error: {json_err}")
                    args = {}
                    output_txt = json.dumps({"status": "error", "message": f"Error: Argumentos para {fn_name} no son JSON válido: {function_args_str}"}, ensure_ascii=False)

                logger.info(f"OpenAI requested tool call: {fn_name} with args: {args} (Conv {sb_conversation_id})")

                output_txt = json.dumps({"status":"error", "message":f"Error: Falló la ejecución de la herramienta {fn_name}."}, ensure_ascii=False) # Default JSON error
                try:
                    if fn_name == "search_local_products":
                        query = args.get("query_text")
                        filter_stock_flag = args.get("filter_stock", True)
                        if query:
                            search_res = product_service.search_local_products(
                                query_text=query,
                                filter_stock=filter_stock_flag,
                                # limit=Config.PRODUCT_SEARCH_LIMIT # Consider adding a limit if not already in product_service default
                            )
                            output_txt = _format_search_results_for_llm(search_res)
                        else:
                            # Consistent JSON error
                            output_txt = json.dumps({"status": "error", "message": "Error: 'query_text' es un argumento requerido para search_local_products."}, ensure_ascii=False)

                    elif fn_name == "get_live_product_details":
                        ident = args.get("product_identifier")
                        id_type = args.get("identifier_type")
                        if ident and id_type:
                            details_result: Union[Optional[Dict[str, Any]], Optional[List[Dict[str, Any]]]] = None
                            if id_type == "sku":
                                details_result = product_service.get_live_product_details_by_sku(item_code_query=ident)
                                # _format_live_details_for_llm now handles list for multi-location SKUs
                                output_txt = _format_live_details_for_llm(details_result, identifier_type="SKU")
                            elif id_type == "composite_id": # Your original was wc_product_id
                                details_result_dict = product_service.get_live_product_details_by_id(composite_id=ident) # Expects dict
                                output_txt = _format_live_details_for_llm(details_result_dict, identifier_type="ID Compuesto")
                            else:
                                output_txt = json.dumps({"status": "error", "message": f"Error: Tipo de identificador '{id_type}' no soportado. Use 'sku' o 'composite_id'."}, ensure_ascii=False)
                        else:
                            output_txt = json.dumps({"status": "error", "message": "Error: Faltan 'product_identifier' o 'identifier_type' para get_live_product_details."}, ensure_ascii=False)
                    else:
                        output_txt = json.dumps({"status": "error", "message": f"Error: Herramienta desconocida '{fn_name}'."}, ensure_ascii=False)

                except Exception as tool_exec_err:
                    logger.exception(f"Tool execution error for {fn_name} (Conv {sb_conversation_id}): {tool_exec_err}")
                    output_txt = json.dumps({"status": "error", "message": f"Error interno al ejecutar la herramienta {fn_name}."}, ensure_ascii=False)

                tool_outputs_for_llm.append({ # Your original structure
                    "tool_call_id": tool_call_id,
                    "role": "tool",
                    "name": fn_name,
                    "content": output_txt,
                })

            messages.extend(tool_outputs_for_llm) # Add tool results to messages for the next LLM call
            tool_call_count += 1

            # Your original condition for breaking if limit reached and no final response
            if tool_call_count >= TOOL_CALL_RETRY_LIMIT and not final_assistant_response:
                logger.warning(f"Tool call retry limit ({TOOL_CALL_RETRY_LIMIT}) reached for conv {sb_conversation_id}. Sending fallback.")
                # The loop will make one more call if tool_call_count == TOOL_CALL_RETRY_LIMIT
                # That call should not have tools, forcing a natural response
                # If it still doesn't produce content, the outer logic handles it.
                # If after this iteration (tool_call_count will be TOOL_CALL_RETRY_LIMIT + 1),
                # and final_assistant_response is still None, the fallback after loop will trigger.
                # Let's add a more proactive attempt to get a final response here.
                if tool_call_count >= TOOL_CALL_RETRY_LIMIT: # If limit strictly met or exceeded
                    final_call_params = {
                        "model": openai_model,
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                    } # No tools, no tool_choice
                    logger.info(f"Attempting to force final natural language response for Conv {sb_conversation_id}.")
                    try:
                        final_resp_attempt = _chat_client.chat.completions.create(**final_call_params)
                        final_assistant_response = final_resp_attempt.choices[0].message.content
                        if not final_assistant_response:
                             logger.warning(f"Forced final response attempt yielded no content for Conv {sb_conversation_id}.")
                             final_assistant_response = ("Lo siento, estoy teniendo algunas dificultades para procesar completamente tu solicitud. "
                                                         "¿Podrías intentarlo de nuevo o reformular tu pregunta?")
                    except Exception as e_final:
                        logger.error(f"Error during forced final response generation for Conv {sb_conversation_id}: {e_final}", exc_info=True)
                        final_assistant_response = ("Lo siento, tuve un problema al intentar generar una respuesta final. "
                                                    "Por favor, inténtalo de nuevo.")
                    break # Break from the while loop as we've tried to get a final response

    # Exception handling is preserved from your original
    except RateLimitError:
        logger.warning(f"OpenAI RateLimitError for Conv {sb_conversation_id}")
        final_assistant_response = ("Estoy experimentando un alto volumen de solicitudes. "
                                    "Por favor, espera un momento y vuelve a intentarlo.")
    except APITimeoutError:
        logger.warning(f"OpenAI APITimeoutError for Conv {sb_conversation_id}")
        final_assistant_response = "No pude obtener respuesta del servicio de IA (OpenAI) a tiempo. Por favor, intenta más tarde."
    except BadRequestError as bre:
        logger.error(f"OpenAI BadRequestError for Conv {sb_conversation_id}: {bre}", exc_info=True)
        final_assistant_response = ("Lo siento, hubo un problema con el formato de nuestra conversación. "
                                    "Por favor, revisa si enviaste alguna imagen que no sea válida.")
    except APIError as apie:
        logger.error(f"OpenAI APIError for Conv {sb_conversation_id} (Status: {apie.status_code}): {apie}", exc_info=True)
        final_assistant_response = (
            f"Hubo un error ({apie.status_code}) con el servicio de IA. "
            "Por favor, inténtalo más tarde."
        )
    except Exception as e:
        logger.exception(f"Unexpected OpenAI interaction error for Conv {sb_conversation_id}: {e}")
        final_assistant_response = ("Ocurrió un error inesperado al procesar tu solicitud. "
                                    "Por favor, intenta de nuevo.")

    if final_assistant_response:
        logger.info(f"Final assistant response for Conv {sb_conversation_id}: '{str(final_assistant_response)[:200]}...'")
        success = support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text=str(final_assistant_response),
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=conversation_data,
            triggering_message_id=triggering_message_id,
        )
        if not success:
            logger.error(
                "Failed to send final reply via SB API "
                "(conv=%s, target=%s, source=%s)",
                sb_conversation_id,
                customer_user_id,
                conversation_source,
            )
    else:
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
            conversation_details=conversation_data,
            triggering_message_id=triggering_message_id,
        )

# --- End of NAMWOO/services/openai_service.py ---