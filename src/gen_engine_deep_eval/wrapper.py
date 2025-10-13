from typing import Any, Mapping
from urllib.parse import urljoin
from uuid import uuid4

import requests
from langchain_core.language_models.llms import LLM
from loguru import logger

from .helpers import get_model_provider


class GenerativeEngineLLM(LLM):
    """
    Custom wrapper for the Generative Engine so we can use it with langchain
    The Gen Engine API documentation is at: https://generative.engine.capgemini.com/studio/documentation/openapi
    """

    # This is the name of the model you want to run, as it appears in the Gen Engine
    model: str
    provider: str | None = None

    api_base: str | None
    api_key: str | None

    temperature: float
    max_tokens: int
    top_p: float = 0.7
    session_id: str = str(uuid4())

    @property
    def _llm_type(self):
        return "generative-engine-wrapper"

    @property
    def _identifying_params(self) -> Mapping[str, Any]:
        return {
            "model_url": self.api_base,
            "api_token": "<hidden>",
            "model": self.model,
        }

    def _call(self, prompt: str, stop: list[str] | None = None, *args, **kwargs):
        if self.api_base is None:
            raise ValueError("API Base is not available. Update .env file to fix this.")

        url = urljoin(self.api_base, "v2/llm/invoke")
        provider = get_model_provider(self.model)

        headers = {
            "Accept": "application/json",
            "x-api-key": self.api_key,
        }

        data = {
            "action": "run",
            "modelInterface": "langchain",
            "data": {
                "mode": "chain",
                "text": prompt,
                "files": [],
                "modelName": self.model,
                "provider": self.provider or provider,
                # Uncomment this line to override the default system prompt
                # "systemPrompt": "You are a friendly, helpful assistant. Follow the user's instructions carefully.",
                "sessionId": self.session_id,
                "modelKwargs": {
                    # Disable streaming so we get a clean single content string
                    "streaming": False,
                    "maxTokens": self.max_tokens,
                    "temperature": self.temperature,
                    "topP": self.top_p,
                },
            },
        }

        logger.debug(f"Running model {self.model}")
        response = requests.post(url, headers=headers, json=data, timeout=60)
        if response.status_code != 200:
            # Try to log JSON error if possible
            try:
                error_body = response.json()
                logger.error(error_body)
                # If this is a server error (5xx), it might be transient - provide context
                if 500 <= response.status_code < 600:
                    logger.warning("Received 5xx error - this may be due to context length or transient API issues")
            except Exception:
                logger.error(response.text)
            response.raise_for_status()

        # Return only the model content (not the whole JSON) so LangChain agent parsers
        # see clean ReAct text instead of a JSON wrapper that confuses parsing.
        try:
            payload = response.json()
            content = payload.get("content", "")
            if isinstance(content, str) and content.startswith("data: "):
                content = content[6:]
            # Honor stop tokens (LangChain agent parser relies on this)
            if stop:
                for s in stop:
                    if s and s in content:
                        content = content.split(s)[0]
                        break
            return content
        except ValueError:
            # Fallback: raw text
            logger.warning("Non-JSON response; returning raw text")
            return response.text
