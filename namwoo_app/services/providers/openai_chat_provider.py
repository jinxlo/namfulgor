# namwoo_app/services/providers/openai_chat_provider.py
# -*- coding: utf-8 -*-
import logging
import json
from typing import List, Dict, Optional, Any

from openai import OpenAI

# --- CORRECTED IMPORTS ---
# Use absolute imports from the application root directory
from config.config import Config
from services import product_service, support_board_service, lead_api_client
from utils import db_utils
# -------------------------

logger = logging.getLogger(__name__)

class OpenAIChatProvider:
    """
    Provider for handling conversations using OpenAI's Chat Completions API.
    """
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("API key is required for OpenAIChatProvider.")
        
        self.client = OpenAI(
            api_key=api_key,
            timeout=Config.OPENAI_REQUEST_TIMEOUT
        )
        self.model = Config.OPENAI_CHAT_MODEL
        self.max_history_messages = Config.MAX_HISTORY_MESSAGES
        self.tool_call_retry_limit = 2
        logger.info(f"OpenAIChatProvider initialized for model '{self.model}'.")

    def _get_tools_schema(self) -> List[Dict[str, Any]]:
        """Defines the tools available for the Chat Completions API."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search_vehicle_batteries",
                    "description": "Searches for suitable batteries based on vehicle make, model, and year.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "make": {"type": "string", "description": "The make of the vehicle, e.g., 'Toyota'."},
                            "model": {"type": "string", "description": "The model of the vehicle, e.g., 'Corolla'."},
                            "year": {"type": "integer", "description": "The manufacturing year of the vehicle, e.g., 2018."},
                            "engine_details": {"type": "string", "description": "Optional details about the engine, e.g., 'postes gruesos'."}
                        },
                        "required": ["make", "model"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "request_human_agent",
                    "description": "Use this function if the user explicitly asks to speak with a human agent, expresses frustration, or has a complex issue beyond your capabilities.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reason": {"type": "string", "description": "A brief summary of why the human agent is needed."}
                        },
                        "required": ["reason"],
                    },
                },
            }
        ]

        if Config.ENABLE_LEAD_GENERATION_TOOLS:
            tools.append({
                "type": "function",
                "function": {
                    "name": "submit_order_for_processing",
                    "description": "Submits the final, confirmed order details to the sales team for processing.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "conversation_id": {"type": "string", "description": "The current conversation ID."},
                            "user_id": {"type": "string", "description": "The platform-specific user ID of the customer."},
                            "customer_name": {"type": "string", "description": "Customer's full name."},
                            "customer_cedula": {"type": "string", "description": "Customer's ID number (Cédula)."},
                            "customer_phone": {"type": "string", "description": "Customer's phone number."},
                            "chosen_battery_brand": {"type": "string", "description": "The brand of the chosen battery."},
                            "chosen_battery_model": {"type": "string", "description": "The model code of the chosen battery."},
                            "original_list_price": {"type": "number", "description": "The base price of the battery from the database search result (price_full)."},
                            "location_discount_applied_percent": {"type": "integer", "description": "The location-based discount percentage that was already included in the original_list_price (e.g., 25 or 26)."},
                            "product_discount_applied_percent": {"type": "number", "description": "The additional product-specific discount percentage applied (e.g., 0.10 for Fulgor Black, 0.15 for Optima, 0 for others)."},
                            "final_price_paid": {"type": "number", "description": "The final calculated price after all discounts."},
                            "shipping_method": {"type": "string", "description": "How the customer will receive the battery (e.g., 'Entrega a Domicilio', 'Recoger en Tienda')."},
                            "delivery_address": {"type": "string", "description": "Customer's full delivery address, if applicable."},
                            "pickup_store_location": {"type": "string", "description": "The name or location of the store for pickup, if applicable."},
                            "payment_method": {"type": "string", "description": "Chosen payment method (e.g., 'Divisas', 'Cashea', 'Pago Móvil')."},
                            "cashea_level": {"type": "string", "description": "The customer's Cashea level (e.g., 'Nivel 1'), if applicable."},
                            "cashea_initial_payment": {"type": "number", "description": "The calculated initial payment for Cashea, if applicable."},
                            "cashea_installment_amount": {"type": "number", "description": "The calculated amount for each of the 3 Cashea installments, if applicable."},
                            "notes_about_old_battery_fee": {"type": "string", "description": "A note confirming the user was informed about the old battery requirement/fee."},
                        },
                        "required": ["conversation_id", "user_id", "customer_name", "customer_phone", "chosen_battery_brand", "chosen_battery_model", "final_price_paid", "shipping_method", "payment_method"],
                    }
                }
            })
        return tools

    def process_message(
        self,
        sb_conversation_id: str,
        new_user_message: Optional[str],
        conversation_data: Dict[str, Any]
    ) -> Optional[str]:
        """The main processing loop for this provider."""
        logger.info(f"[OpenAIChat Provider] Handling SB Conv {sb_conversation_id}")
        
        sb_history_list = (conversation_data.get("messages", []) if conversation_data else [])
        api_history = self._format_sb_history(sb_history_list)

        if not api_history:
            logger.error(f"[OpenAIChat Provider] No history to process for Conv {sb_conversation_id}.")
            return "Lo siento, no pude procesar tu solicitud."

        messages_for_api = [{"role": "system", "content": Config.SYSTEM_PROMPT}] + api_history
        if len(messages_for_api) > (self.max_history_messages + 1):
            messages_for_api = [messages_for_api[0]] + messages_for_api[-(self.max_history_messages):]

        final_assistant_response: Optional[str] = None
        tool_call_count = 0

        while tool_call_count <= self.tool_call_retry_limit:
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages_for_api,
                    tools=self._get_tools_schema(),
                    tool_choice="auto",
                )
                response_message = response.choices[0].message
                messages_for_api.append(response_message)

                if not response_message.tool_calls:
                    final_assistant_response = response_message.content
                    break
                
                tool_outputs = self._execute_tool_calls(
                    tool_calls=response_message.tool_calls,
                    sb_conversation_id=sb_conversation_id
                )
                messages_for_api.extend(tool_outputs)
                tool_call_count += 1
            
            except Exception as e:
                logger.exception(f"[OpenAIChat Provider] Error during API call for Conv {sb_conversation_id}: {e}")
                final_assistant_response = "Lo siento, ocurrió un error inesperado. Por favor intenta de nuevo."
                break
        
        if not final_assistant_response:
             logger.warning(f"[OpenAIChat Provider] Tool call limit reached or no final response for Conv {sb_conversation_id}.")
             final_assistant_response = "Parece que estoy teniendo dificultades para completar tu solicitud. Por favor, contacta a un agente de soporte."

        return final_assistant_response

    def _execute_tool_calls(self, tool_calls: List[Any], sb_conversation_id: str) -> List[Dict[str, str]]:
        tool_outputs = []
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            logger.info(f"[OpenAIChat Provider] Tool requested: {function_name} for Conv {sb_conversation_id}")
            
            try:
                args = json.loads(tool_call.function.arguments)
                function_response = {}

                if function_name == "search_vehicle_batteries":
                    with db_utils.get_db_session() as session:
                        results = product_service.find_batteries_for_vehicle(
                            db_session=session,
                            vehicle_make=args.get("make"),
                            vehicle_model=args.get("model"),
                            vehicle_year=args.get("year")
                        )
                    formatted_results = []
                    for res in results:
                         formatted_results.append({
                             "brand": res.get("brand"),
                             "model_code": res.get("model_code"),
                             "price_full": res.get("price_regular"),
                             "warranty_info": f"{res.get('warranty_months')} meses",
                             "stock_quantity": res.get("stock")
                         })
                    function_response = {"batteries_found": formatted_results}

                elif function_name == "submit_order_for_processing":
                    lead_intent_res = lead_api_client.call_initiate_lead_intent(
                        conversation_id=args.get("conversation_id"),
                        platform_user_id=args.get("user_id"),
                        products_of_interest=[{
                            "sku": f"{args.get('chosen_battery_brand')}_{args.get('chosen_battery_model')}",
                            "description": f"Batería {args.get('chosen_battery_brand')} {args.get('chosen_battery_model')}",
                            "quantity": 1
                        }],
                        payment_method_preference=args.get("payment_method")
                    )
                    
                    if lead_intent_res.get("success"):
                        lead_id = lead_intent_res.get("data", {}).get("id")
                        details_res = lead_api_client.call_submit_customer_details(
                            lead_id=lead_id,
                            customer_full_name=args.get("customer_name"),
                            customer_email="not_provided@example.com",
                            customer_phone_number=args.get("customer_phone")
                        )
                        function_response = {"status": "success", "lead_id": lead_id, "details_updated": details_res.get("success")}
                    else:
                        function_response = {"status": "error", "message": lead_intent_res.get("error_message")}

                elif function_name == "request_human_agent":
                    db_utils.pause_conversation_for_duration(sb_conversation_id, duration_seconds=3600)
                    function_response = {"status": "success", "message": "Conversation paused for human intervention."}
                
                else:
                    function_response = {"status": "error", "message": f"Unknown tool: {function_name}"}

                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps(function_response)
                })

            except Exception as e:
                logger.exception(f"Error executing tool {function_name}: {e}")
                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": json.dumps({"status": "error", "message": str(e)})
                })
        return tool_outputs

    def _format_sb_history(self, sb_messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Formats Support Board history for the OpenAI Chat API."""
        api_messages: List[Dict[str, Any]] = []
        bot_user_id_str = str(Config.SUPPORT_BOARD_DM_BOT_USER_ID)
        
        for msg in sb_messages:
            role = "assistant" if str(msg.get("user_id")) == bot_user_id_str else "user"
            content = msg.get("message", "").strip()

            if role == "assistant" and msg.get("payload"):
                try:
                    payload_data = json.loads(msg["payload"])
                    if "tool_calls" in payload_data:
                        api_messages.append({"role": "assistant", "tool_calls": payload_data["tool_calls"]})
                        if content:
                            api_messages.append({"role": "assistant", "content": content})
                        continue
                except (json.JSONDecodeError, TypeError):
                    pass
            
            elif role == "user" and msg.get("payload"):
                try:
                    payload_data = json.loads(msg["payload"])
                    if "tool_call_id" in payload_data and "name" in payload_data:
                        api_messages.append({
                            "role": "tool",
                            "tool_call_id": payload_data["tool_call_id"],
                            "name": payload_data["name"],
                            "content": payload_data["content"]
                        })
                        continue
                except (json.JSONDecodeError, TypeError):
                     pass
            
            if content:
                api_messages.append({"role": role, "content": content})
                
        return api_messages