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

    # SerpAPI — single key, or comma-separated list for rotation (serp_api_keys)
    serp_api_key: str = ""
    serp_api_keys: str = ""

    # Gemini (LLM) — prompt suggestions + competitor detection (NOT sentiment)
    # gemini_api_key is a single key; gemini_api_keys is a comma-separated rotation list
    gemini_api_key: str = ""
    gemini_api_keys: str = ""
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

    # Celery / Redis — when broker is set, captures run on workers; else inline
    celery_broker_url: str = ""
    celery_result_backend: str = ""

    # Supabase Storage (S3-compatible) — when configured, artifacts go to the
    # bucket instead of local disk. Leave blank to use local ./storage.
    # S3 access keys are generated in Supabase: Storage → Settings → S3 access keys.
    supabase_project_ref: str = ""        # e.g. aeudrluqrzvfiyumnjsf
    supabase_s3_region: str = ""          # e.g. ap-northeast-1 (project region)
    supabase_s3_access_key_id: str = ""
    supabase_s3_secret_access_key: str = ""
    supabase_storage_bucket: str = ""
    supabase_s3_endpoint: str = ""        # override; else derived from project_ref
    supabase_storage_public: bool = False  # public bucket → build public object URLs

    @property
    def supabase_s3_endpoint_url(self) -> str:
        if self.supabase_s3_endpoint:
            return self.supabase_s3_endpoint
        if self.supabase_project_ref:
            return f"https://{self.supabase_project_ref}.storage.supabase.co/storage/v1/s3"
        return ""

    @property
    def storage_enabled(self) -> bool:
        return bool(
            self.supabase_s3_access_key_id
            and self.supabase_s3_secret_access_key
            and self.supabase_storage_bucket
            and self.supabase_s3_region
            and self.supabase_s3_endpoint_url
        )

    @property
    def celery_enabled(self) -> bool:
        return bool(self.celery_broker_url)

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
