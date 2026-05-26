from backend.providers.base import BaseProvider, CaptureResult, ProviderError
from backend.providers.chatgpt.provider import ChatGPTProvider
from backend.providers.gemini.provider import GeminiProvider
from backend.providers.google_ai.provider import GoogleAIOverviewProvider

PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {
    "chatgpt": ChatGPTProvider,
    "gemini": GeminiProvider,
    "google_ai": GoogleAIOverviewProvider,
}

__all__ = [
    "BaseProvider",
    "CaptureResult",
    "ProviderError",
    "ChatGPTProvider",
    "GeminiProvider",
    "GoogleAIOverviewProvider",
    "PROVIDER_REGISTRY",
]
