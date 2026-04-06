import hashlib
import json
from enum import StrEnum
from functools import lru_cache
from typing import Any, TypeVar

import anthropic
import structlog
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from observatory.core.config import get_settings

logger = structlog.get_logger()
T = TypeVar("T", bound=BaseModel)


class ModelTier(StrEnum):
    CLASSIFICATION = "classification"
    SYNTHESIS = "synthesis"
    DEFAULT = "default"


# System prompt modifiers for the three analytical lenses
LENS_PROMPTS = {
    "academic": (
        "Apply an academic research perspective. Ground your analysis in published research "
        "from peer-reviewed journals, cite relevant theories from consumer behaviour, decision "
        "psychology, and market dynamics. Reference specific studies where applicable. Use "
        "frameworks from Google Scholar, SSRN, and academic databases to support your reasoning."
    ),
    "business": (
        "Apply a business pragmatism perspective. Frame everything in terms of ROI, velocity, "
        "and commercial viability. Push for what is actionable within real-world constraints — "
        "engineering capacity, budget, competitive timing. Prioritise speed-to-value over "
        "theoretical perfection. Quantify impact where possible."
    ),
    "ux": (
        "Apply a UX and design research perspective. Ground recommendations in established "
        "usability heuristics (Nielsen's 10), conversion optimisation principles, and published "
        "usability research from sources like Nielsen Norman Group and Baymard Institute. "
        "Reference proven interaction patterns and accessibility guidelines."
    ),
}


class LLMService:
    def __init__(self):
        self.settings = get_settings()
        self.client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        self._cache: dict[str, Any] = {}

    def _get_model(self, tier: ModelTier) -> str:
        match tier:
            case ModelTier.CLASSIFICATION:
                return self.settings.llm_classification_model
            case ModelTier.SYNTHESIS:
                return self.settings.llm_synthesis_model
            case ModelTier.DEFAULT:
                return self.settings.llm_default_model

    def _cache_key(self, model: str, system: str, prompt: str) -> str:
        content = f"{model}:{system}:{prompt}"
        return hashlib.sha256(content.encode()).hexdigest()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
    async def complete(
        self,
        prompt: str,
        system: str = "",
        tier: ModelTier = ModelTier.DEFAULT,
        lens: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        use_cache: bool = True,
    ) -> str:
        model = self._get_model(tier)

        if lens and lens in LENS_PROMPTS:
            system = f"{system}\n\n{LENS_PROMPTS[lens]}" if system else LENS_PROMPTS[lens]

        if use_cache:
            key = self._cache_key(model, system, prompt)
            if key in self._cache:
                logger.info("llm_cache_hit", model=model)
                return self._cache[key]

        logger.info("llm_request", model=model, tier=tier, lens=lens)

        messages = [{"role": "user", "content": prompt}]
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        response = self.client.messages.create(**kwargs)
        result = response.content[0].text

        if use_cache:
            self._cache[key] = result

        logger.info(
            "llm_response",
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return result

    async def classify(
        self,
        text: str,
        categories: list[str],
        system: str = "",
    ) -> dict[str, Any]:
        category_list = ", ".join(categories)
        prompt = (
            f"Classify the following text into one or more of these categories: {category_list}\n\n"
            f"Text: {text}\n\n"
            f"Respond with valid JSON only: {{\"categories\": [...], \"confidence\": 0.0-1.0}}"
        )
        result = await self.complete(
            prompt=prompt, system=system, tier=ModelTier.CLASSIFICATION, temperature=0.1
        )
        return json.loads(result)

    async def extract_structured(
        self,
        text: str,
        schema_description: str,
        system: str = "",
        tier: ModelTier = ModelTier.CLASSIFICATION,
    ) -> dict[str, Any]:
        prompt = (
            f"Extract structured data from the following text.\n\n"
            f"Expected output schema:\n{schema_description}\n\n"
            f"Text: {text}\n\n"
            f"Respond with valid JSON only matching the schema above."
        )
        result = await self.complete(prompt=prompt, system=system, tier=tier, temperature=0.1)
        return json.loads(result)

    async def synthesize(
        self,
        context: list[str],
        prompt: str,
        system: str = "",
        lens: str | None = None,
    ) -> str:
        context_block = "\n\n---\n\n".join(context)
        full_prompt = (
            f"Context:\n{context_block}\n\n---\n\nTask:\n{prompt}"
        )
        return await self.complete(
            prompt=full_prompt, system=system, tier=ModelTier.SYNTHESIS, lens=lens, use_cache=False
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Using Anthropic's Voyage embeddings or fallback to a simple hash-based approach
        # In production, this would use voyage-3 or text-embedding-3-large
        logger.info("embedding_request", count=len(texts))
        # Placeholder: in production wire up voyage AI or OpenAI embeddings
        # For now we return empty vectors to unblock development
        return [[0.0] * 1536 for _ in texts]


@lru_cache
def get_llm_service() -> LLMService:
    return LLMService()
