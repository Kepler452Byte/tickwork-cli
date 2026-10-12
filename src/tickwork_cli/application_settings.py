from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApplicationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TICKWORK_", env_file=None, extra="ignore")
    home: Path = Field(default_factory=lambda: Path.home() / ".tickwork")

    success_days: int = Field(default=7, ge=0)
    failure_days: int = Field(default=30, ge=0)
    success_limit: int = Field(default=100, ge=1)
    failure_limit: int = Field(default=100, ge=1)
    failure_keep: int = Field(default=10, ge=0)

    @classmethod
    def load(cls, home: Path | None = None) -> "ApplicationSettings":
        settings = cls() if home is None else cls(home=home)
        settings.home = settings.home.expanduser().resolve()
        return settings

    @property
    def database_path(self) -> Path:
        return self.home / "tickwork.db"
