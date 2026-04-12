"""
Custom LLM client for local models (LM Studio, Ollama) that don't support
OpenAI's responses.parse() API.

Falls back to chat.completions with JSON schema in the system prompt.
"""

import json
import logging

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_client import OpenAIClient

logger = logging.getLogger(__name__)


class LocalLLMClient(OpenAIClient):
    """OpenAI-compatible client that uses chat.completions instead of responses.parse."""

    def __init__(self, config: LLMConfig | None = None, **kwargs):
        super().__init__(config=config, **kwargs)
        # Override the async client to use chat completions endpoint
        self.client = AsyncOpenAI(
            api_key=self.config.api_key or "not-needed",
            base_url=self.config.base_url,
        )

    async def _create_structured_completion(
        self,
        model: str,
        messages: list[ChatCompletionMessageParam],
        temperature: float | None,
        max_tokens: int,
        response_model: type[BaseModel],
        reasoning: str | None = None,
        verbosity: str | None = None,
    ):
        """Use chat.completions with JSON schema instruction instead of responses.parse."""
        schema = response_model.model_json_schema()
        schema_str = json.dumps(schema, indent=2)

        # Inject JSON schema instruction into system message
        system_instruction = (
            f"\n\nYou MUST respond with valid JSON matching this exact schema:\n"
            f"```json\n{schema_str}\n```\n"
            f"Do NOT include any text before or after the JSON. "
            f"Do NOT use markdown formatting. "
            f"Output ONLY the raw JSON object."
        )

        # Modify messages to include schema
        modified_messages = []
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "system":
                modified_messages.append({
                    **msg,
                    "content": str(msg.get("content", "")) + system_instruction,
                })
            else:
                modified_messages.append(msg)

        # If no system message, prepend one
        if not any(
            isinstance(m, dict) and m.get("role") == "system" for m in modified_messages
        ):
            modified_messages.insert(0, {
                "role": "system",
                "content": f"You are a structured data extraction assistant. {system_instruction}",
            })

        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=modified_messages,
                temperature=temperature or 0.0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        except Exception:
            # Some local servers don't support response_format, retry without it
            response = await self.client.chat.completions.create(
                model=model,
                messages=modified_messages,
                temperature=temperature or 0.0,
                max_tokens=max_tokens,
            )

        import re

        msg = response.choices[0].message
        content = msg.content or ""

        # Qwen 3.5 thinking models: content is empty, reasoning_content has everything
        reasoning = getattr(msg, "reasoning_content", "") or ""

        # Try content first, then reasoning_content
        candidates = [content, reasoning]

        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate:
                continue

            # Strip <think>...</think> blocks
            if "<think>" in candidate:
                think_end = candidate.find("</think>")
                if think_end != -1:
                    candidate = candidate[think_end + len("</think>"):].strip()

            # Strip markdown fences
            if "```" in candidate:
                fenced = re.findall(r"```(?:json)?\s*\n?([\s\S]*?)```", candidate)
                if fenced:
                    candidate = fenced[-1].strip()  # Use last fenced block

            # Try direct parse
            try:
                parsed = response_model.model_validate_json(candidate)
                return _MockParsedResponse(parsed, response)
            except Exception:
                pass

            # Try to find JSON object in the text
            json_matches = re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", candidate)
            for match in reversed(json_matches):  # Try last match first
                try:
                    parsed = response_model.model_validate_json(match)
                    return _MockParsedResponse(parsed, response)
                except Exception:
                    continue

            # Try to find JSON with nested arrays
            deep_matches = re.findall(
                r'\{\s*"extracted_entities"\s*:\s*\[[\s\S]*?\]\s*\}', candidate
            )
            for match in reversed(deep_matches):
                try:
                    parsed = response_model.model_validate_json(match)
                    return _MockParsedResponse(parsed, response)
                except Exception:
                    continue

        # All candidates exhausted — construct a minimal valid response
        logger.warning(
            f"Could not extract JSON from LLM. Content: {content[:100]}, "
            f"Reasoning: {reasoning[:200]}"
        )
        # Return empty but valid response to avoid blocking the pipeline
        try:
            empty = response_model.model_validate_json('{"extracted_entities": []}')
            return _MockParsedResponse(empty, response)
        except Exception:
            pass
        try:
            empty = response_model.model_validate_json('{"edges": []}')
            return _MockParsedResponse(empty, response)
        except Exception:
            pass
        try:
            empty = response_model.model_validate_json("{}")
            return _MockParsedResponse(empty, response)
        except Exception as e:
            raise e

        # Create a mock response object that matches what Graphiti expects
        return _MockParsedResponse(parsed, response)


class _MockParsedResponse:
    """Mimics the structure of openai.responses.parse() return value."""

    def __init__(self, parsed_output, raw_response):
        self.output = [_MockOutputItem(parsed_output)]
        self.output_text = parsed_output.model_dump_json()
        self.usage = raw_response.usage
        self.id = "local-response"
        self.model = "local"


class _MockOutputItem:
    def __init__(self, parsed):
        self.type = "message"
        self.content = [_MockContent(parsed)]


class _MockContent:
    def __init__(self, parsed):
        self.type = "output_text"
        self.text = parsed.model_dump_json()
        self.parsed = parsed
