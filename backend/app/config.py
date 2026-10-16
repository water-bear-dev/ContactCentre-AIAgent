from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"
    business_config_path: Path = Path(__file__).resolve().parents[1] / "config.json"
    knowledge_path: Path = Path(__file__).resolve().parents[2] / "knowledge"
    cors_origins: str = "http://localhost:5173"

    @field_validator("ollama_base_url")
    @classmethod
    def validate_ollama_base_url(cls, value: str) -> str:
        parsed = urlsplit(value.strip())
        if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("OLLAMA_BASE_URL must be an HTTP loopback URL without credentials.")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("OLLAMA_BASE_URL must be the Ollama server root, without a path, query, or fragment.")
        try:
            parsed.port
        except ValueError as exc:
            raise ValueError("OLLAMA_BASE_URL contains an invalid port.") from exc
        try:
            is_loopback = ip_address(parsed.hostname).is_loopback
        except ValueError:
            is_loopback = parsed.hostname.lower() == "localhost"
        if not is_loopback:
            raise ValueError("OLLAMA_BASE_URL must use localhost or a loopback IP address.")
        return f"http://{parsed.netloc}"

    @field_validator("ollama_model")
    @classmethod
    def validate_ollama_model(cls, value: str) -> str:
        model = value.strip()
        if not model:
            raise ValueError("OLLAMA_MODEL cannot be empty.")
        return model

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
