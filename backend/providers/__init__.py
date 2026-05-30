from backend.providers.base import BaseProvider, CaptureResult, ProviderError
from backend.providers.chatgpt.provider import ChatGPTProvider
from backend.providers.gemini.provider import GeminiProvider
from backend.providers.google_ai.provider import GoogleAIOverviewProvider
from backend.providers.google_ai_mode.provider import GoogleAIModeProvider
from backend.providers.perplexity.provider import PerplexityProvider

PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {
    "chatgpt": ChatGPTProvider,
    "gemini": GeminiProvider,
    "perplexity": PerplexityProvider,
    "google_ai": GoogleAIOverviewProvider,
    "google_ai_mode": GoogleAIModeProvider,
}

__all__ = [
    "BaseProvider",
    "CaptureResult",
    "ProviderError",
    "ChatGPTProvider",
    "GeminiProvider",
    "PerplexityProvider",
    "GoogleAIOverviewProvider",
    "GoogleAIModeProvider",
    "PROVIDER_REGISTRY",
]
