# -*- coding: utf-8 -*-
import logging
import json
import time
from typing import List, Dict, Optional, Tuple, Union
from openai import OpenAI, APIError, RateLimitError, APITimeoutError, BadRequestError
from flask import current_app

# Import local services
from . import product_service, woocommerce_service
from . import support_board_service # Import the SB service
from ..config import Config # To get SYSTEM_PROMPT and BOT_USER_ID etc

logger = logging.getLogger(__name__)

# --- Initialize OpenAI Client Directly ---
# (Keep OpenAI client initialization exactly as provided)
try:
    openai_api_key = Config.OPENAI_API_KEY
    if openai_api_key:
        # Increased timeout slightly, vision models can sometimes take longer
        client = OpenAI(api_key=openai_api_key, timeout=60.0)
        logger.info("OpenAI client initialized for Chat Completions service.")
    else:
        client = None
        logger.error("OpenAI API key not configured during initial load. Chat functionality will fail.")
except Exception as e:
    logger.exception("Failed to initialize OpenAI client during initial load.")
    client = None

# --- Constants (Load from Config where possible) ---
# (Keep Constants section exactly as provided)
MAX_HISTORY_MESSAGES = Config.MAX_HISTORY_MESSAGES
TOOL_CALL_RETRY_LIMIT = 2
DEFAULT_OPENAI_MODEL = getattr(Config, 'OPENAI_CHAT_MODEL', 'gpt-4o-mini')
DEFAULT_MAX_TOKENS = getattr(Config, 'OPENAI_MAX_TOKENS', 1024)

# --- Tool Definitions Schema ---
# (Keep Tool Definitions Schema exactly as provided)
tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "search_local_products",
            "description": "Busca en la base de datos local de productos usando búsqueda semántica (vectorial) basada en la consulta, descripción o una imagen proporcionada por el usuario. Usar para búsquedas generales como '¿Tienen chaquetas de invierno?', 'neumáticos de moto', 'filtros de aceite para honda civic', preguntar por tipos de productos, o si el usuario pregunta por productos similares a una imagen. Devuelve una lista de posibles productos coincidentes con información en caché (Nombre, SKU, Precio, Estado de Stock, Link).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_text": {
                        "type": "string",
                        "description": "La consulta en lenguaje natural del usuario describiendo el/los producto(s) que busca, o una descripción del producto visto en una imagen si el usuario proporcionó una. Debe ser descriptiva (ej: 'chaqueta impermeable cálida', 'ropa de bebé de algodón orgánico', 'pastillas de freno para toyota camry 2018', 'camiseta roja como la de la foto'). Incluir marca o detalles si los menciona el usuario.",
                    },
                    "filter_stock": {
                        "type": "boolean",
                        "description": "Indica si filtrar los resultados para incluir solo productos marcados como 'instock' (en stock) en la caché. Por defecto es true.",
                        "default": True
                    }
                },
                "required": ["query_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_live_product_details",
            "description": "Obtiene detalles específicos y EN TIEMPO REAL (como cantidad exacta de stock, precio actual, variaciones) para UN producto identificado directamente desde WooCommerce usando su SKU o ID de Producto. Usar SOLO cuando el usuario pregunte por datos específicos en tiempo real sobre un producto YA IDENTIFICADO (ej: '¿Cuántos del SKU XYZ hay en stock?', '¿Cuál es el precio exacto del producto ID 12345 ahora mismo?'). NO usar para búsquedas generales.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_identifier": {
                        "type": "string",
                        "description": "El identificador único para el producto específico. DEBE ser el SKU (ej: 'TSHIRT-ROJO-L') o el ID de Producto de WooCommerce (ej: '12345').",
                    },
                     "identifier_type": {
                        "type": "string",
                        "enum": ["sku", "wc_product_id"],
                        "description": "Especifica si el 'product_identifier' proporcionado es el 'sku' o el 'wc_product_id'.",
                    }
                },
                "required": ["product_identifier", "identifier_type"],
            },
        },
    }
]


# --- Helper: Format SB History ---
# (Keep _format_sb_history_for_openai exactly as provided)
def _format_sb_history_for_openai(sb_messages: Optional[List]) -> List[Dict[str, Union[str, List[Dict[str, Union[str, Dict]]]]]]:
    """
    Formats Support Board message history for the OpenAI API,
    handling both text and image content.
    """
    if not sb_messages:
        return []

    openai_messages = []
    bot_user_id_str = Config.SUPPORT_BOARD_BOT_USER_ID
    if not bot_user_id_str:
        logger.error("Cannot format SB history: SUPPORT_BOARD_BOT_USER_ID is not configured.")
        return []

    for msg in sb_messages:
        sender_id = msg.get('user_id')
        text_content = msg.get('message', '').strip() # Get text content, default to empty string
        # --- Check for attachments (ADAPT THIS based on actual SB payload) ---
        attachments = msg.get('attachments')
        image_urls = []
        if attachments and isinstance(attachments, list):
            for attachment in attachments:
                # Assuming attachment is a dict with 'url' and maybe 'type' or 'filename'
                # Check if it's likely an image (you might need stricter checks based on type/extension)
                if isinstance(attachment, dict) and attachment.get('url') and \
                   (attachment.get('type', '').startswith('image') or \
                    any(attachment.get('url', '').lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp'])):
                     # Ensure the URL is accessible
                     img_url = attachment['url']
                     if img_url.startswith('http://') or img_url.startswith('https://'):
                         image_urls.append(img_url)
                     else:
                         logger.warning(f"Skipping potentially non-public URL for image attachment in message {msg.get('id')}: {img_url}")

        # -----------------------------------------------------------------------

        if not text_content and not image_urls:
            logger.debug(f"Skipping empty message (no text or image): {msg.get('id')}")
            continue

        if sender_id is None:
            logger.warning(f"Skipping message with no sender_id: {msg.get('id')}")
            continue

        sender_id_str = str(sender_id)
        role = "assistant" if sender_id_str == bot_user_id_str else "user"

        # --- Construct OpenAI message content (using the list format for images) ---
        openai_content: Union[str, List[Dict[str, Union[str, Dict]]]]
        if image_urls:
            # Message has images, use list format for content
            openai_content = []
            # Add text first if it exists
            if text_content:
                # Using the format {"type": "text", "content": ...} which aligns with current docs
                openai_content.append({"type": "text", "content": text_content})
            # Add image URLs
            for img_url in image_urls:
                openai_content.append({
                    "type": "image_url",
                    "image_url": {"url": img_url} # Add detail='low'/'high' if needed later
                })
            logger.debug(f"Formatted message ID {msg.get('id')} with role '{role}' including {len(image_urls)} image(s).")
        elif text_content:
            # Message only has text
            openai_content = text_content
            logger.debug(f"Formatted message ID {msg.get('id')} with role '{role}' (text only).")
        else:
            logger.warning(f"Message ID {msg.get('id')} has neither text nor valid image URLs after processing. Skipping.")
            continue

        openai_messages.append({"role": role, "content": openai_content})
        # --------------------------------------

    return openai_messages


# --- Helper: Format Tool Results ---
# (Keep _format_search_results_for_llm exactly as provided)
def _format_search_results_for_llm(results: Optional[List]) -> str:
    if results is None: return "Lo siento, ocurrió un error interno al buscar en el catálogo. Por favor, intenta de nuevo más tarde."
    if not results: return "Lo siento, no pude encontrar productos que coincidan con esa descripción en nuestro catálogo actual."
    response_parts = ["Claro, encontré estos productos basados en tu consulta:"]
    limit = current_app.config.get('PRODUCT_SEARCH_LIMIT', 5)
    for product_dict in results[:limit]:
        name = product_dict.get("name", "N/A"); sku = product_dict.get("sku", "N/A"); price = product_dict.get("price", "N/A"); status = product_dict.get("stock_status", "Desconocido").replace('instock', 'en stock').replace('outofstock', 'agotado'); permalink = product_dict.get("permalink")
        sku_str = f" (SKU: {sku})" if sku and sku != "N/A" else ""; status_str = f"Estado: {status}"; link_str = f" Puedes verlo aquí: {permalink}" if permalink else ""
        response_parts.append(f"- Nombre: {name}{sku_str}, Precio: ${price}, {status_str}.{link_str}")
    return "\n".join(response_parts)

# --- Helper: Format Live Details ---
# (Keep _format_live_details_for_llm exactly as provided, including syntax correction)
def _format_live_details_for_llm(details: Optional[Dict]) -> str:
    """Formats live product details into a Spanish string for the LLM."""
    if details is None:
        return "Lo siento, no pude recuperar los detalles en tiempo real para ese producto específico en este momento. Podría no estar disponible o haber un problema de conexión."

    name = details.get('name', 'el producto')
    sku = details.get('sku', 'N/A')
    response_parts = [f"Aquí están los detalles actuales para {name} (SKU: {sku}):"]

    price = details.get('price')
    if price is not None and price != '':
        try:
            response_parts.append(f"- Precio Actual: ${float(price):.2f}")
        except (ValueError, TypeError):
            response_parts.append(f"- Precio Actual: {price}")
    else:
        response_parts.append("- Precio Actual: No disponible")

    if details.get('manage_stock') and details.get('stock_quantity') is not None:
        qty = details['stock_quantity']
        response_parts.append(f"- Cantidad en Stock: {qty}")
        # --- CORRECTED SYNTAX ---
        if qty == 0:
            response_parts.append("  (Actualmente agotado)")
        elif qty > 0 and qty <= 5:
             response_parts.append("  (¡Pocas unidades!)")
        # --- END CORRECTED SYNTAX ---
    else:
        stock_status = details.get('stock_status', 'Desconocido').replace('instock', 'en stock').replace('outofstock', 'agotado')
        response_parts.append(f"- Estado de Stock: {stock_status}")

    if permalink := details.get('permalink'):
        response_parts.append(f"- Ver producto online: {permalink}")

    return "\n".join(response_parts)


# --- Main Processing Function ---
# >>> CHANGE 1: Add triggering_message_id parameter to signature <<<
def process_new_message(
    sb_conversation_id: str,
    new_user_message: Optional[str], # Allow None as message might be just attachment/event
    conversation_source: Optional[str],
    sender_user_id: str, # The user who sent the message triggering the webhook
    customer_user_id: str, # The primary customer associated with the conversation
    triggering_message_id: Optional[str] # Add this new parameter
):
# --- END CHANGE 1 ---
    """
    Processes a new message from Support Board using OpenAI.
    Fetches history, calls OpenAI (handles tool calls), determines reply channel,
    and sends reply via the appropriate SB API function TO THE CUSTOMER.
    """
    global client
    if not client:
        logger.error("OpenAI client not initialized. Cannot process message.")
        # Reply to the CUSTOMER that there's an issue
        # >>> CHANGE 2a: Add triggering_message_id=None to fallback call <<<
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text="Disculpa, el servicio de IA no está disponible en este momento.",
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=None,
            triggering_message_id=None # Add parameter
        )
        # --- END CHANGE 2a ---
        return

    # Update initial log to show trigger ID
    logger.info(f"Processing message for SB Conv ID: {sb_conversation_id} (Triggered by User: {sender_user_id}, Target Cust: {customer_user_id}, Src: {conversation_source}, Trigger Msg ID: {triggering_message_id})")
    if new_user_message:
        logger.debug(f"Received raw new_user_message: {new_user_message[:100]}...")
    else:
        logger.debug("Received webhook trigger with no text message (likely attachment/event).")


    # 1. Fetch FULL Conversation Data from Support Board
    # (Fetching logic remains the same)
    conversation_data = support_board_service.get_sb_conversation_data(sb_conversation_id)
    if conversation_data is None:
        logger.error(f"Failed to fetch conversation data for SB conversation {sb_conversation_id}. Aborting processing.")
        # Reply to the CUSTOMER
        # >>> CHANGE 2b: Add triggering_message_id=triggering_message_id to fallback call <<<
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text="Lo siento, no pude acceder a los detalles de esta conversación. ¿Podrías repetir tu pregunta?",
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=None,
            triggering_message_id=triggering_message_id # Add parameter
        )
        # --- END CHANGE 2b ---
        return

    # Extract message history from the fetched data
    sb_history_list = conversation_data.get('messages', [])
    if not sb_history_list:
         logger.warning(f"No message history found in fetched data for SB conversation {sb_conversation_id}. Cannot proceed effectively.")
         # Reply to the CUSTOMER
         # >>> CHANGE 2c: Add triggering_message_id=triggering_message_id to fallback call <<<
         support_board_service.send_reply_to_channel(
             conversation_id=sb_conversation_id,
             message_text="Lo siento, no pude cargar el historial de esta conversación.",
             source=conversation_source,
             target_user_id=customer_user_id,
             conversation_details=conversation_data,
             triggering_message_id=triggering_message_id # Add parameter
         )
         # --- END CHANGE 2c ---
         return

    # --- Format History for OpenAI (Handles images and includes the latest message) ---
    # (Formatting logic remains the same)
    try:
        openai_history = _format_sb_history_for_openai(sb_history_list)
    except Exception as format_err:
        logger.exception(f"Error formatting SB history for OpenAI (Conv ID: {sb_conversation_id}): {format_err}")
        # Reply to the CUSTOMER
        # >>> CHANGE 2d: Add triggering_message_id=triggering_message_id to fallback call <<<
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text="Lo siento, tuve problemas al procesar el historial de la conversación.",
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=conversation_data,
            triggering_message_id=triggering_message_id # Add parameter
        )
        # --- END CHANGE 2d ---
        return

    if not openai_history:
        logger.error(f"Formatted OpenAI history is empty for SB conversation {sb_conversation_id}. Aborting.")
        # Reply to the CUSTOMER
        # >>> CHANGE 2e: Add triggering_message_id=triggering_message_id to fallback call <<<
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text="Lo siento, no pude procesar los mensajes anteriores.",
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=conversation_data,
            triggering_message_id=triggering_message_id # Add parameter
        )
        # --- END CHANGE 2e ---
        return

    # 3. Prepare messages list for OpenAI
    # (Preparation logic remains the same)
    system_prompt = Config.SYSTEM_PROMPT
    messages = [{"role": "system", "content": system_prompt}] + openai_history

    # 4. Trim History
    # (Trimming logic remains the same)
    max_hist = current_app.config.get('MAX_HISTORY_MESSAGES', MAX_HISTORY_MESSAGES)
    if len(messages) > max_hist:
        logger.debug(f"Message history ({len(messages)}) exceeds limit ({max_hist}). Trimming.")
        messages = [messages[0]] + messages[-(max_hist - 1):]
        logger.debug(f"Trimmed history to {len(messages)} messages.")

    # 5. Call OpenAI (Loop to handle potential tool calls)
    # (OpenAI call loop, tool handling, and error handling remain the same)
    final_assistant_response = None
    try:
        tool_call_count = 0
        while tool_call_count < TOOL_CALL_RETRY_LIMIT:
            logger.debug(f"--- OpenAI Call Attempt {tool_call_count + 1} ---")
            # (Logging preview code remains the same)
            try:
                log_msgs_preview = [] # Initialize here
                for m in messages:
                    if m.get("role") == "system": continue
                    content = m.get("content"); preview = ""
                    if isinstance(content, str): preview = content[:100] + ("..." if len(content) > 100 else "")
                    elif isinstance(content, list):
                        parts = []
                        for item in content:
                            if item.get("type") == "text": text = item.get("content", ""); parts.append("Text: " + text[:50] + ("..." if len(text) > 50 else ""))
                            elif item.get("type") == "image_url": parts.append(f"Image: {item.get('image_url', {}).get('url', 'Invalid URL')[:50]}...")
                        preview = ", ".join(parts)
                    else: preview = f"Unknown content type: {type(content)}"
                    log_msgs_preview.append({"role": m["role"], "content_preview": preview})
                log_msgs_json = json.dumps(log_msgs_preview, indent=2, ensure_ascii=False)
                logger.debug(f"Sending messages to OpenAI ({len(messages)}): System Prompt + \n{log_msgs_json}")
            except Exception as log_ex: logger.warning(f"Error generating detailed log preview: {log_ex}. Logging simplified."); logger.debug(f"Sending messages to OpenAI ({len(messages)}) - simplified log.")

            # (Model selection logic remains the same)
            openai_model = current_app.config.get('OPENAI_CHAT_MODEL', DEFAULT_OPENAI_MODEL)
            max_tokens = current_app.config.get('OPENAI_MAX_TOKENS', DEFAULT_MAX_TOKENS)
            logger.info(f"Using OpenAI model: {openai_model}, Max Tokens: {max_tokens}")

            openai_call_params = {
                 "model": openai_model,
                 "messages": messages,
                 "max_tokens": max_tokens,
            }
            # (Tools logic remains the same)
            if tool_call_count == 0:
                 openai_call_params["tools"] = tools_schema
                 openai_call_params["tool_choice"] = "auto"

            response = client.chat.completions.create(**openai_call_params)
            response_message = response.choices[0].message
            tool_calls = response_message.tool_calls

            # (Usage logging remains the same)
            usage = response.usage
            if usage: logger.info(f"OpenAI API Usage: Prompt={usage.prompt_tokens}, Completion={usage.completion_tokens}, Total={usage.total_tokens}")

            if not tool_calls:
                final_assistant_response = response_message.content
                logger.info("OpenAI responded directly (no tool calls).")
                break # Exit loop

            # --- Handle Tool Calls (Logic remains the same) ---
            logger.info(f"OpenAI requested tool calls: {[tc.function.name for tc in tool_calls]}")
            messages.append(response_message) # Append assistant's request
            tool_outputs = []
            for tool_call in tool_calls:
                # (Inner tool execution loop is unchanged)
                function_name = tool_call.function.name; tool_call_id = tool_call.id; logger.info(f"Executing function call: {function_name} (Call ID: {tool_call_id})")
                try:
                    arguments = json.loads(tool_call.function.arguments); logger.debug(f"Function arguments: {arguments}"); function_response_content = f"Error: Tool '{function_name}' execution failed."
                    if function_name == "search_local_products": query = arguments.get("query_text"); filter_stock = arguments.get("filter_stock", True); function_response_content = _format_search_results_for_llm(product_service.search_local_products(query, filter_stock=filter_stock)) if query else "Error: Falta el argumento 'query_text' para search_local_products."
                    elif function_name == "get_live_product_details":
                        identifier = arguments.get("product_identifier"); id_type = arguments.get("identifier_type"); live_details = None; error_msg = None
                        if identifier and id_type:
                            if id_type == "sku": live_details = woocommerce_service.get_live_product_details_by_sku(sku=identifier)
                            elif id_type == "wc_product_id":
                                try: live_details = woocommerce_service.get_live_product_details_by_id(wc_product_id=int(identifier))
                                except ValueError: error_msg = f"Error: ID de producto inválido '{identifier}' para wc_product_id."
                                except Exception as wc_err: logger.error(f"WooCommerce API error in get_live_product_details_by_id: {wc_err}", exc_info=True); error_msg = "Lo siento, hubo un problema al contactar la tienda para obtener detalles en vivo."
                            else: error_msg = f"Error: Tipo de identificador inválido '{id_type}'."
                            if error_msg: function_response_content = error_msg
                            else: function_response_content = _format_live_details_for_llm(live_details)
                        else: function_response_content = "Error: Faltan 'product_identifier' o 'identifier_type' para get_live_product_details."
                    else: logger.warning(f"Unknown function requested: {function_name}"); function_response_content = f"Error: Herramienta desconocida '{function_name}' solicitada."
                    logger.debug(f"Function '{function_name}' executed. Result snippet: {function_response_content[:100]}...")
                except json.JSONDecodeError: logger.error(f"Failed to decode JSON arguments for tool {function_name}: {tool_call.function.arguments}"); function_response_content = f"Error: Formato de argumentos inválido para {function_name}."
                except Exception as e: logger.exception(f"Unexpected error executing tool {function_name}: {e}"); function_response_content = f"Error interno al ejecutar la herramienta {function_name}."
                tool_outputs.append({"tool_call_id": tool_call_id, "role": "tool", "name": function_name, "content": function_response_content})

            messages.extend(tool_outputs) # Append tool results
            tool_call_count += 1
            logger.debug(f"Appended {len(tool_outputs)} tool results. Preparing for next OpenAI call (if needed).")

            if tool_call_count >= TOOL_CALL_RETRY_LIMIT:
                logger.warning(f"Reached tool call retry limit ({TOOL_CALL_RETRY_LIMIT}). Sending error message.")
                final_assistant_response = "Lo siento, encontré un problema al intentar usar mis herramientas de búsqueda después de varios intentos. Por favor, intenta de nuevo."
                break # Exit loop

    # --- Error Handling for OpenAI API Calls (remains the same) ---
    # (Error handling block remains unchanged)
    except RateLimitError as e: final_assistant_response = "Estoy experimentando un alto volumen de solicitudes. Por favor, espera un momento y vuelve a intentarlo."; logger.warning(f"OpenAI Rate Limit Error: {e}. Sending fallback message.")
    except APITimeoutError as e: final_assistant_response = "No pude obtener una respuesta del servicio de IA a tiempo. Por favor, intenta de nuevo."; logger.warning(f"OpenAI API Timeout Error: {e}. Sending fallback message.")
    except BadRequestError as e: final_assistant_response = "Lo siento, hubo un problema con el formato de nuestra conversación o con una imagen proporcionada. ¿Podrías reformular tu pregunta o verificar la imagen?"; logger.error(f"OpenAI Bad Request Error (400): {e}. Check history/content/image URLs.", exc_info=True)
    except APIError as e:
        if "invalid image url" in str(e).lower(): final_assistant_response = "Lo siento, parece que una de las imágenes proporcionadas no es accesible o válida. Por favor, verifica el enlace o intenta con otra imagen."; logger.error(f"OpenAI API Error potentially related to image URL (Status: {e.status_code}): {e}")
        else: final_assistant_response = f"Hubo un error ({e.status_code}) con el servicio de IA. Por favor, inténtalo más tarde."; logger.error(f"OpenAI API Error (Status: {e.status_code}): {e}. Sending fallback message.")
    except Exception as e: final_assistant_response = "Ocurrió un error inesperado al procesar tu solicitud. Por favor, intenta de nuevo."; logger.exception(f"Unexpected error during OpenAI interaction for SB conv {sb_conversation_id}: {e}")


    # 6. Send Reply via Support Board API
    if final_assistant_response:
        logger.info(f"Sending final reply to SB Conversation {sb_conversation_id} for Customer User {customer_user_id} via Source {conversation_source}")
        # >>> CHANGE 3: Pass triggering_message_id in the main send call <<<
        success = support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text=final_assistant_response,
            source=conversation_source,
            target_user_id=customer_user_id, # Use the actual customer's ID
            conversation_details=conversation_data, # Pass fetched data for context (e.g., page_id)
            triggering_message_id=triggering_message_id # Pass it along
        )
        # --- END CHANGE 3 ---
        if not success:
            logger.error(f"Failed to send final reply via SB API to conversation {sb_conversation_id}, target {customer_user_id}, source {conversation_source}")
    else:
        logger.error(f"No final assistant response was generated for SB conversation {sb_conversation_id}. Sending fallback.")
        # Send fallback to the CUSTOMER
        # >>> CHANGE 4: Pass triggering_message_id in the fallback send call <<<
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text="Lo siento, no pude generar una respuesta después de procesar tu mensaje. Por favor, intenta de nuevo.",
            source=conversation_source,
            target_user_id=customer_user_id, # Use the actual customer's ID
            conversation_details=conversation_data,
            triggering_message_id=triggering_message_id # Pass it along here too
        )
        # --- END CHANGE 4 ---