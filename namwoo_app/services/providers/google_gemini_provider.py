# namwoo_app/services/providers/google_gemini_provider.py
# -*- coding: utf-8 -*-
import logging
import json
from typing import List, Dict, Optional, Any

from openai import OpenAI

# --- CORRECTED IMPORTS ---
from config.config import Config
from services.providers import openai_chat_provider
# -------------------------

logger = logging.getLogger(__name__)

class GoogleGeminiProvider:
    """
    Provider for handling conversations using Google's Gemini models,
    accessed via the OpenAI-compatible client interface.
    """
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("API key is required for GoogleGeminiProvider.")
        
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            timeout=Config.GOOGLE_REQUEST_TIMEOUT
        )
        self.model = Config.GOOGLE_GEMINI_MODEL
        self.tool_call_retry_limit = 2
        logger.info(f"GoogleGeminiProvider initialized for model '{self.model}'.")

    def _get_tools_schema(self) -> List[Dict[str, Any]]:
        """Mirrors the tools from OpenAIChatProvider for Gemini compatibility."""
        chat_provider = openai_chat_provider.OpenAIChatProvider(api_key="temp-dummy-key")
        return chat_provider._get_tools_schema()

    def process_message(
        self,
        sb_conversation_id: str,
        new_user_message: Optional[str],
        conversation_data: Dict[str, Any]
    ) -> Optional[str]:
        """The main processing loop for this provider."""
        logger.info(f"[GoogleGemini Provider] Handling SB Conv {sb_conversation_id}")
        
        sb_history_list = (conversation_data.get("messages", []) if conversation_data else [])
        chat_provider = openai_chat_provider.OpenAIChatProvider(api_key="temp-dummy-key")
        api_history = chat_provider._format_sb_history(sb_history_list)

        if not api_history:
            logger.error(f"[GoogleGemini Provider] No history to process for Conv {sb_conversation_id}.")
            return "Lo siento, no pude procesar tu solicitud."

        messages_for_api = [{"role": "system", "content": Config.SYSTEM_PROMPT}] + api_history
        
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
                messages_for_api.append(response_message.model_dump(exclude_none=True))

                if not response_message.tool_calls:
                    final_assistant_response = response_message.content
                    break
                
                tool_outputs = chat_provider._execute_tool_calls(
                    tool_calls=response_message.tool_calls,
                    sb_conversation_id=sb_conversation_id
                )
                messages_for_api.extend(tool_outputs)
                tool_call_count += 1
            
            except Exception as e:
                logger.exception(f"[GoogleGemini Provider] Error during API call for Conv {sb_conversation_id}: {e}")
                final_assistant_response = "Lo siento, ocurrió un error con el servicio de Google AI. Por favor intenta de nuevo."
                break
        
        if not final_assistant_response:
             final_assistant_response = "No pude generar una respuesta final. Por favor, contacta a un agente."

        return final_assistant_response