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
