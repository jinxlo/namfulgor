# -*- coding: utf-8 -*-
import logging
import json
import time
from typing import List, Dict, Optional, Union, Tuple

from openai import (
    OpenAI,
    APIError,
    RateLimitError,
    APITimeoutError,
    BadRequestError,
)
from flask import current_app

# ── Local services ──────────────────────────────────────────────────────────────
from . import product_service, woocommerce_service, support_board_service
from ..config import Config

logger = logging.getLogger(__name__)

# ── Initialise OpenAI‑compatible client that talks to Google Gemini ────────────
google_gemini_client_via_openai_lib: Optional[OpenAI] = None
GOOGLE_SDK_AVAILABLE = False  # default

try:
    google_api_key = Config.GOOGLE_API_KEY
    google_base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"

    if google_api_key:
        google_gemini_client_via_openai_lib = OpenAI(
            api_key=google_api_key,
            base_url=google_base_url,
            timeout=60.0,
        )
        logger.info(
            "OpenAI‑lib client initialised for Google Gemini at %s", google_base_url
        )
        # ── NEW LINE (router flag) ──────────────────────────────────────────────
        GOOGLE_SDK_AVAILABLE = True  # routes.py guard now passes
    else:
        logger.error("GOOGLE_API_KEY not configured. Gemini service disabled.")
except Exception:
    logger.exception("Failed to initialise Google Gemini client (OpenAI lib).")
    google_gemini_client_via_openai_lib = None
    GOOGLE_SDK_AVAILABLE = False

# ── Constants ───────────────────────────────────────────────────────────────────
MAX_HISTORY_MESSAGES = Config.MAX_HISTORY_MESSAGES
TOOL_CALL_RETRY_LIMIT = 2
DEFAULT_GEMINI_MODEL_NAME = Config.GOOGLE_GEMINI_MODEL
DEFAULT_MAX_TOKENS = Config.GOOGLE_MAX_TOKENS

# ── Tool schema (re‑used from openai_service.py) ────────────────────────────────
tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "search_local_products",
            "description": (
                "Busca en la base de datos local de productos usando búsqueda "
                "semántica (vectorial) basada en la consulta o una imagen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query_text": {
                        "type": "string",
                        "description": (
                            "Consulta del usuario — descripción del producto o "
                            "lo visto en la imagen."
                        ),
                    },
                    "filter_stock": {
                        "type": "boolean",
                        "description": (
                            "Si es True, solo devuelve productos con stock "
                            "disponible."
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
                "Obtiene detalles **en tiempo real** de un producto (precio, "
                "stock) desde WooCommerce, dada su SKU o ID."
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
                        "description": "Indica si es ‘sku’ o ‘wc_product_id’.",
                    },
                },
                "required": ["product_identifier", "identifier_type"],
            },
        },
    },
]

# ── Helper functions to format Support‑Board messages for the API ──────────────
def _format_sb_history_for_openai_compatible_api(
    sb_messages: Optional[List],
) -> List[Dict[str, Union[str, List[Dict[str, Union[str, Dict]]]]]]:
    if not sb_messages:
        return []

    openai_messages = []
    bot_user_id_str = Config.SUPPORT_BOARD_BOT_USER_ID
    if not bot_user_id_str:
        logger.error(
            "SUPPORT_BOARD_BOT_USER_ID not set; cannot format SB history."
        )
        return []

    for msg in sb_messages:
        sender_id = msg.get("user_id")
        text_content = msg.get("message", "").strip()
        attachments = msg.get("attachments")
        image_urls = []

        if attachments and isinstance(attachments, list):
            for attachment in attachments:
                url = attachment.get("url", "")
                if (
                    url
                    and attachment.get("type", "").startswith("image")
                    or url.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))
                ):
                    if url.startswith(("http://", "https://")):
                        image_urls.append(url)
                    else:
                        logger.warning(
                            "Skipping non‑public image URL for Gemini: %s",
                            url,
                        )

        # skip empty messages
        if not text_content and not image_urls:
            continue
        if sender_id is None:
            logger.warning("Skipping message with no sender_id.")
            continue

        role = "assistant" if str(sender_id) == bot_user_id_str else "user"
        if image_urls:
            content: Union[str, List[Dict[str, Union[str, Dict]]]] = []
            if text_content:
                content.append({"type": "text", "content": text_content})
            for url in image_urls:
                content.append({"type": "image_url", "image_url": {"url": url}})
        else:
            content = text_content

        openai_messages.append({"role": role, "content": content})

    return openai_messages


def _format_search_results_for_llm(results: Optional[List]) -> str:
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

    limit = current_app.config.get("PRODUCT_SEARCH_LIMIT", 5)
    lines = ["Claro, encontré estos productos basados en tu consulta:"]
    for prod in results[:limit]:
        name = prod.get("name", "N/A")
        sku = prod.get("sku", "N/A")
        price = prod.get("price", "N/A")
        stock = (
            prod.get("stock_status", "Desconocido")
            .replace("instock", "en stock")
            .replace("outofstock", "agotado")
        )
        link = prod.get("permalink", "")
        sku_part = f" (SKU: {sku})" if sku and sku != "N/A" else ""
        link_part = f" Puedes verlo aquí: {link}" if link else ""
        lines.append(
            f"- Nombre: {name}{sku_part}, Precio: ${price}, "
            f"Estado: {stock}.{link_part}"
        )
    return "\n".join(lines)


def _format_live_details_for_llm(details: Optional[Dict]) -> str:
    if details is None:
        return (
            "Lo siento, no pude recuperar los detalles en tiempo real para ese "
            "producto en este momento."
        )

    name = details.get("name", "el producto")
    sku = details.get("sku", "N/A")
    lines = [f"Aquí están los detalles actuales para {name} (SKU: {sku}):"]

    price = details.get("price")
    if price not in (None, ""):
        try:
            price_val = float(price)
            lines.append(f"- Precio Actual: ${price_val:.2f}")
        except (ValueError, TypeError):
            lines.append(f"- Precio Actual: {price}")
    else:
        lines.append("- Precio Actual: No disponible")

    if details.get("manage_stock") and details.get("stock_quantity") is not None:
        qty = details["stock_quantity"]
        lines.append(f"- Cantidad en Stock: {qty}")
        if qty == 0:
            lines.append("  (Actualmente agotado)")
        elif 0 < qty <= 5:
            lines.append("  (¡Pocas unidades!)")
    else:
        stock = (
            details.get("stock_status", "Desconocido")
            .replace("instock", "en stock")
            .replace("outofstock", "agotado")
        )
        lines.append(f"- Estado de Stock: {stock}")

    if permalink := details.get("permalink"):
        lines.append(f"- Ver producto online: {permalink}")
    return "\n".join(lines)


# ── Main entry point ────────────────────────────────────────────────────────────
def process_new_message_gemini_via_openai_lib(
    sb_conversation_id: str,
    new_user_message: Optional[str],
    conversation_source: Optional[str],
    sender_user_id: str,
    customer_user_id: str,
    triggering_message_id: Optional[str],
):
    """
    Handles a single incoming Support‑Board message with Google Gemini (OpenAI‑compatible).
    """
    if not google_gemini_client_via_openai_lib:
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text=(
                "Disculpa, el servicio de IA (Google) no está disponible en este momento."
            ),
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=None,
            triggering_message_id=triggering_message_id,
        )
        return

    logger.info(
        "[Gemini‑OAI] Processing SB conv %s (trigger %s)",
        sb_conversation_id,
        triggering_message_id,
    )

    conversation_data = support_board_service.get_sb_conversation_data(
        sb_conversation_id
    )
    if conversation_data is None:
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text="Lo siento, no pude acceder a los detalles de esta conversación.",
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=None,
            triggering_message_id=triggering_message_id,
        )
        return

    # ── Build message list for the API ──────────────────────────────────────────
    try:
        api_history = _format_sb_history_for_openai_compatible_api(
            conversation_data.get("messages", [])
        )
    except Exception:
        logger.exception("Error formateando historial SB para Gemini‑OAI.")
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text="Lo siento, tuve problemas al procesar el historial.",
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=conversation_data,
            triggering_message_id=triggering_message_id,
        )
        return

    if not api_history:
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text=(
                "Lo siento, no pude procesar los mensajes anteriores "
                "(historial vacío o inválido)."
            ),
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=conversation_data,
            triggering_message_id=triggering_message_id,
        )
        return

    messages_for_api = [
        {"role": "system", "content": Config.SYSTEM_PROMPT},
        *api_history,
    ]
    if len(messages_for_api) > MAX_HISTORY_MESSAGES:
        messages_for_api = [messages_for_api[0]] + messages_for_api[-MAX_HISTORY_MESSAGES + 1 :]

    # ── Interaction with Gemini ────────────────────────────────────────────────
    final_assistant_response: Optional[str] = None
    try:
        tool_call_count = 0
        while tool_call_count <= TOOL_CALL_RETRY_LIMIT:
            logger.debug(
                "[Gemini‑OAI] API attempt %d/%d",
                tool_call_count + 1,
                TOOL_CALL_RETRY_LIMIT + 1,
            )

            api_call_params = {
                "model": Config.GOOGLE_GEMINI_MODEL,
                "messages": messages_for_api,
                "max_tokens": DEFAULT_MAX_TOKENS,
            }
            if tool_call_count == 0:
                api_call_params["tools"] = tools_schema
                api_call_params["tool_choice"] = "auto"

            response = (
                google_gemini_client_via_openai_lib.chat.completions.create(
                    **api_call_params
                )
            )
            response_msg = response.choices[0].message
            tool_calls = response_msg.tool_calls

            # log token usage
            if response.usage:
                logger.info(
                    "[Gemini‑OAI] Tokens — prompt: %d, completion: %d, total: %d",
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                    response.usage.total_tokens,
                )

            if not tool_calls:
                final_assistant_response = response_msg.content
                break  # done ‑ no tools requested

            # ── Execute tool calls ───────────────────────────────────────────────
            messages_for_api.append(response_msg)
            tool_outputs = []

            for tool_call in tool_calls:
                fname = tool_call.function.name
                logger.info("[Gemini‑OAI] Executing tool %s", fname)
                try:
                    args = json.loads(tool_call.function.arguments)
                    result: str

                    if fname == "search_local_products":
                        q = args.get("query_text")
                        fs = args.get("filter_stock", True)
                        result = (
                            _format_search_results_for_llm(
                                product_service.search_local_products(q, fs)
                            )
                            if q
                            else "Error: query_text missing."
                        )

                    elif fname == "get_live_product_details":
                        ident = args.get("product_identifier")
                        idt = args.get("identifier_type")
                        if not ident or not idt:
                            result = (
                                "Error: faltan 'product_identifier' o "
                                "'identifier_type'."
                            )
                        else:
                            details = None
                            if idt == "sku":
                                details = woocommerce_service.get_live_product_details_by_sku(
                                    sku=ident
                                )
                            elif idt == "wc_product_id":
                                try:
                                    details = (
                                        woocommerce_service.get_live_product_details_by_id(
                                            wc_product_id=int(ident)
                                        )
                                    )
                                except ValueError:
                                    result = f"Error: ID inválido '{ident}'."
                            result = _format_live_details_for_llm(details)

                    else:
                        result = f"Error: herramienta desconocida '{fname}'."

                except Exception:
                    logger.exception(
                        "Error ejecutando herramienta %s (Gemini‑OAI)", fname
                    )
                    result = f"Error interno con herramienta {fname}."

                tool_outputs.append(
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": fname,
                        "content": result,
                    }
                )

            messages_for_api.extend(tool_outputs)
            tool_call_count += 1

        # ── Exception handlers ─────────────────────────────────────────────────
    except RateLimitError:
        final_assistant_response = (
            "El servicio de IA de Google (Gemini) está experimentando un alto "
            "volumen de solicitudes. Por favor, intenta más tarde."
        )
    except APITimeoutError:
        final_assistant_response = (
            "No pude obtener respuesta del servicio de IA de Google (Gemini) a tiempo."
        )
    except BadRequestError as e:
        body = str(getattr(e, "body", e)).lower()
        if "user location" in body and "not supported" in body:
            final_assistant_response = (
                "Lo siento, tu ubicación no es compatible con el servicio de IA "
                "de Google por ahora."
            )
        elif "image" in body or "url" in body:
            final_assistant_response = (
                "Lo siento, parece que una imagen proporcionada no es válida o "
                "accesible para Google."
            )
        else:
            final_assistant_response = (
                "Lo siento, hubo un problema con el formato de nuestra conversación."
            )
    except APIError as e:
        status = getattr(e, "status_code", "N/A")
        final_assistant_response = (
            f"Hubo un error ({status}) con el servicio de IA de Google (Gemini). "
            "Por favor, inténtalo más tarde."
        )
    except Exception:
        logger.exception("Error inesperado con Gemini‑OAI.")
        final_assistant_response = (
            "Ocurrió un error inesperado al procesar tu solicitud con Google AI."
        )

    # ── Send reply back to Support Board ────────────────────────────────────────
    if final_assistant_response:
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text=final_assistant_response,
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=conversation_data,
            triggering_message_id=triggering_message_id,
        )

# ── Back‑compat alias expected by routes.py ─────────────────────────────────────
process_new_message_gemini = process_new_message_gemini_via_openai_lib
