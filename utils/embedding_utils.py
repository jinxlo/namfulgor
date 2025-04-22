import logging
import time
from typing import List, Optional
from openai import OpenAI, APIError, RateLimitError, APITimeoutError
from ..config import Config

logger = logging.getLogger(__name__)

# Initialize OpenAI client globally or manage through app context if preferred
_openai_client = None

def _get_openai_client() -> Optional[OpenAI]:
    """Initializes and returns the OpenAI client, ensuring API key is set."""
    global _openai_client
    if _openai_client is None:
        api_key = Config.OPENAI_API_KEY
        if api_key:
            try:
                _openai_client = OpenAI(api_key=api_key, timeout=20.0) # Set a reasonable timeout
                logger.info("OpenAI client initialized for embedding generation.")
            except Exception as e:
                 logger.exception(f"Failed to initialize OpenAI client: {e}")
                 _openai_client = None # Ensure it remains None on failure
        else:
            logger.error("OpenAI API key not configured. Embedding generation will fail.")
            _openai_client = None
    return _openai_client

def get_embedding(text: str, model: str = Config.OPENAI_EMBEDDING_MODEL, retries: int = 2, initial_delay: float = 1.0) -> Optional[List[float]]:
    """
    Generates an embedding for the given text using the configured OpenAI model.
    Includes basic retry logic for transient errors like rate limits.

    Args:
        text: The input text string to embed.
        model: The OpenAI embedding model ID to use.
        retries: Number of times to retry on specific API errors.
        initial_delay: Initial delay in seconds before the first retry (exponential backoff).

    Returns:
        A list of floats representing the embedding vector, or None if generation fails.
    """
    client = _get_openai_client()
    if not client:
        logger.error("Cannot generate embedding: OpenAI client not available.")
        return None

    if not text or not isinstance(text, str):
        logger.warning("Invalid or empty text provided for embedding generation. Returning None.")
        return None

    # OpenAI API best practice: Replace newlines with spaces for embedding models
    processed_text = text.replace("\n", " ").strip()
    if not processed_text:
        logger.warning("Text became empty after processing newlines. Returning None.")
        return None

    current_retries = 0
    delay = initial_delay
    while current_retries <= retries:
        try:
            response = client.embeddings.create(
                input=[processed_text], # API expects a list of strings
                model=model
                )
            embedding = response.data[0].embedding
            logger.debug(f"Successfully generated embedding for text snippet: '{processed_text[:50]}...'")
            return embedding
        except RateLimitError as e:
            logger.warning(f"OpenAI rate limit hit. Retrying in {delay:.2f} seconds... (Attempt {current_retries + 1}/{retries + 1})")
        except APITimeoutError as e:
             logger.warning(f"OpenAI API timeout. Retrying in {delay:.2f} seconds... (Attempt {current_retries + 1}/{retries + 1})")
        except APIError as e:
             # Handle other potentially retryable API errors (e.g., 5xx server errors)
             if e.status_code >= 500:
                 logger.warning(f"OpenAI server error ({e.status_code}). Retrying in {delay:.2f} seconds... (Attempt {current_retries + 1}/{retries + 1})")
             else:
                 # Non-retryable API error (e.g., 4xx client error)
                 logger.error(f"OpenAI API error during embedding generation: {e} (Status: {e.status_code})")
                 return None # Do not retry client errors
        except Exception as e:
            # Catch unexpected errors during the API call or response processing
            logger.exception(f"Unexpected error during embedding generation: {e}")
            return None # Do not retry unexpected errors

        # If retry is needed:
        current_retries += 1
        if current_retries <= retries:
             time.sleep(delay)
             delay *= 2 # Exponential backoff

    logger.error(f"Failed to generate embedding for text snippet: '{processed_text[:50]}...' after {retries} retries.")
    return None

# Optional: Add a function for batch embedding if needed for sync optimization
# def get_embeddings_batch(texts: List[str], model: str = Config.OPENAI_EMBEDDING_MODEL, ...) -> List[Optional[List[float]]]:
#     # ... implementation using batch requests to OpenAI API ...
#     pass