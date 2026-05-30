from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = f"sqlite:///{ROOT / 'ai_tracker.db'}"
    storage_dir: Path = ROOT / "storage"
    browser_user_data_dir: Path = ROOT / ".browser_profiles"

    provider_timeout_seconds: int = 180
    stream_settle_seconds: int = 3
    headless: bool = False

    serp_api_key: str = ""

    # Gemini (LLM) — prompt suggestions + competitor detection (NOT sentiment)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"

    # Sentiment/framing runs locally via a HuggingFace model (no API cost).
    enable_sentiment: bool = True
    sentiment_model: str = "cardiffnlp/twitter-roberta-base-sentiment-latest"

    # Default geo for SerpAPI location-aware results (overridable per project/run)
    default_geo_location: str = "United States"

    # Artifact lifecycle: purge raw JSON + screenshots + HTML older than this
    artifact_ttl_days: int = 7
    cleanup_interval_hours: int = 24

    # Result cache: reuse a recent (project, provider, prompt, geo) capture
    cache_ttl_hours: int = 24

    # Rate limiting / resilience
    provider_min_delay_seconds: float = 3.0
    provider_max_retries: int = 2
    provider_backoff_base: float = 2.0
    circuit_breaker_threshold: int = 3

    # Optional proxy (server URL) used for browser providers — proxy rotation hook
    proxy_url: str = ""

    api_host: str = "127.0.0.1"
    api_port: int = 8000

    @property
    def raw_dir(self) -> Path:
        return self.storage_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.storage_dir / "processed"

    @property
    def screenshots_dir(self) -> Path:
        return self.storage_dir / "screenshots"

    @property
    def html_dir(self) -> Path:
        return self.storage_dir / "html"

    def ensure_dirs(self) -> None:
        for d in (
            self.raw_dir,
            self.processed_dir,
            self.screenshots_dir,
            self.html_dir,
            self.browser_user_data_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
