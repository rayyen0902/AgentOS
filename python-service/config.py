import os
from typing import Literal

from dotenv import load_dotenv

load_dotenv()


class Settings:
    PORT: int = int(os.getenv("PORT", "8000"))
    ENV: Literal["production", "staging", "development"] = os.getenv("ENV", "development")  # type: ignore
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    REDIS_URL: str = os.getenv("REDIS_URL", "")

    LLM_FLASH_MODEL: str = os.getenv("LLM_FLASH_MODEL", "qwen-turbo")
    LLM_PRO_MODEL: str = os.getenv("LLM_PRO_MODEL", "qwen-max")
    LLM_VL_MODEL: str = os.getenv("LLM_VL_MODEL", "qwen-vl-plus")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")
    EMBEDDING_DIMS: int = int(os.getenv("EMBEDDING_DIMS", "1024"))
    EMBEDDING_CACHE_TTL: int = int(os.getenv("EMBEDDING_CACHE_TTL", "3600"))

    FE_GRPC_HOST: str = os.getenv("FE_GRPC_HOST", "knownot.cc")
    FE_GRPC_PORT: str = os.getenv("FE_GRPC_PORT", "50052")
    FE_GRPC_TIMEOUT: str = os.getenv("FE_GRPC_TIMEOUT", "5s")

    TRACE_ENABLED: bool = os.getenv("TRACE_ENABLED", "true").lower() == "true"
    TRACE_SAMPLE_RATE: float = float(os.getenv("TRACE_SAMPLE_RATE", "1.0"))

    @classmethod
    def validate(cls) -> list[str]:
        errors: list[str] = []
        if not cls.DATABASE_URL:
            errors.append("DATABASE_URL is required")
        if not cls.REDIS_URL:
            errors.append("REDIS_URL is required")
        if not cls.LLM_API_KEY:
            errors.append("LLM_API_KEY is required")
        if cls.ENV not in ("production", "staging", "development"):
            errors.append(f"ENV must be one of production|staging|development, got: {cls.ENV}")
        if cls.EMBEDDING_DIMS != 1024:
            errors.append(f"EMBEDDING_DIMS must be 1024, got: {cls.EMBEDDING_DIMS}")
        return errors


settings = Settings()
