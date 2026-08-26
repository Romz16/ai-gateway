from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: Literal["local", "test", "production"] = "local"
    database_url: SecretStr = SecretStr("postgresql+asyncpg://gateway:local@localhost/gateway")
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    catalog_path: Path = Path("config/models.json")
    openai_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    gemini_api_key: SecretStr = SecretStr("")
    ollama_url: str = "http://localhost:11434"
    fake_provider_url: str = "http://localhost:8001"
    enable_fake_provider: bool = True
    max_retries: int = Field(2, ge=0, le=5)
    retry_budget_per_minute: int = Field(100, ge=1)
    retry_base_seconds: float = Field(0.05, gt=0, le=10)
    circuit_threshold: int = Field(3, ge=1)
    circuit_recovery_seconds: int = Field(20, ge=1)
    provider_timeout_seconds: float = Field(2, gt=0, le=60)
    max_deadline_ms: int = Field(30000, ge=100, le=60000)
    max_body_bytes: int = Field(65536, ge=1024, le=1048576)
    max_inflight: int = Field(100, ge=1)
    cache_ttl_seconds: int = Field(120, ge=1, le=3600)
    idempotency_ttl_seconds: int = Field(3600, ge=120, le=86400)
    enable_prompt_security: bool = True
    otel_endpoint: str = ""

    @model_validator(mode="after")
    def production_guards(self) -> "Settings":
        if self.app_env == "production":
            if self.enable_fake_provider:
                raise ValueError("Disable the fake provider in production.")
            if not self.database_url.get_secret_value().startswith("postgresql+asyncpg://"):
                raise ValueError("Production requires PostgreSQL.")
            if not self.redis_url.get_secret_value().startswith("rediss://"):
                raise ValueError("Production requires Redis TLS.")
        return self
