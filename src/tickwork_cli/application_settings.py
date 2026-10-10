from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApplicationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TICKWORK_", env_file=None, extra="ignore")
    home: Path = Field(default_factory=lambda: Path.home() / ".tickwork")

    @classmethod
    def load(cls, home: Path | None = None) -> "ApplicationSettings":
        settings = cls() if home is None else cls(home=home)
        settings.home = settings.home.expanduser().resolve()
        return settings

    @property
    def database_path(self) -> Path:
        return self.home / "tickwork.db"
