"""Runtime configuration. Keys come from the environment, never from source."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

LLM_PRESETS: dict[str, dict[str, str]] = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key_env": "GROQ_API_KEY",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-flash",
        "key_env": "GEMINI_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.1",
        "key_env": "OLLAMA_API_KEY",
    },
    "custom": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_env": "LLM_API_KEY",
    },
}


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass
class Settings:
    data_dir: Path
    database_url: str
    secret_key: str
    host: str
    port: int
    app_base_url: str
    seed_on_startup: bool
    demo_mode: bool
    demo_allow_registration: bool
    demo_trial_enabled: bool
    demo_chat_per_hour: int
    trial_credits: int
    max_trials_per_ip_per_day: int
    admin_email: str
    admin_password: str
    bcrypt_rounds: int
    llm_provider: str
    llm_preset: str
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    embedding_provider: str
    embedding_model: str
    query_translation: str
    credit_cost_per_query: int
    free_monthly_credits: int
    pro_monthly_credits: int
    admin_monthly_credits: int
    free_uploads_per_day: int
    pro_uploads_per_day: int
    max_upload_mb_free: int
    max_upload_mb_pro: int
    ocr_enabled: bool
    stripe_secret_key: str
    stripe_webhook_secret: str
    stripe_price_pro: str
    stripe_success_url: str
    stripe_cancel_url: str

    @property
    def llm_configured(self) -> bool:
        return self.llm_provider != "none" and bool(self.llm_api_key)

    @property
    def stripe_enabled(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_webhook_secret and self.stripe_price_pro)

    def allowance(self, plan: str) -> int:
        if plan == "pro":
            return self.pro_monthly_credits
        if plan == "admin":
            return self.admin_monthly_credits
        if plan == "trial":
            return self.trial_credits
        return self.free_monthly_credits

    def uploads_per_day(self, plan: str) -> int:
        if plan in {"pro", "admin"}:
            return self.pro_uploads_per_day if plan == "pro" else 10_000
        if plan == "trial":
            return 0
        return self.free_uploads_per_day

    def max_upload_mb(self, plan: str) -> int:
        if plan in {"pro", "admin"}:
            return self.max_upload_mb_pro
        return self.max_upload_mb_free


def _normalize_database_url(url: str, data_dir: Path) -> str:
    url = (url or "").strip()
    if not url:
        return f"sqlite:///{(data_dir / 'app.db').resolve()}"
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and "+psycopg" not in url.split("://", 1)[0]:
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("sqlite:///./") or url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        # Leave absolute sqlite URLs alone. Resolve a relative one against cwd.
        raw_path = url.split("sqlite:///", 1)[1]
        if raw_path.startswith("./") or not raw_path.startswith("/"):
            path = Path(raw_path).resolve()
            return f"sqlite:///{path}"
    return url


def get_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
    preset_name = os.getenv("LLM_PRESET", "groq").strip().lower() or "groq"
    preset = LLM_PRESETS.get(preset_name, LLM_PRESETS["groq"])
    key = os.getenv("LLM_API_KEY", "").strip() or os.getenv(preset["key_env"], "").strip()
    if preset_name == "ollama" and not key:
        key = os.getenv("LLM_API_KEY", "").strip() or "ollama"
    base_url = os.getenv("LLM_BASE_URL", "").strip() or preset["base_url"]
    model = os.getenv("LLM_MODEL", "").strip() or preset["model"]
    provider = os.getenv("LLM_PROVIDER", "auto").strip().lower() or "auto"
    embed = os.getenv("EMBEDDING_PROVIDER", "fastembed").strip().lower() or "fastembed"
    app_base = os.getenv("APP_BASE_URL", "http://localhost:7860").rstrip("/")
    return Settings(
        data_dir=data_dir,
        database_url=_normalize_database_url(os.getenv("DATABASE_URL", ""), data_dir),
        secret_key=os.getenv("SECRET_KEY", "dev-secret-change-me"),
        host=os.getenv("HOST", "0.0.0.0"),
        port=_int("PORT", 7860),
        app_base_url=app_base,
        seed_on_startup=_flag("SEED_ON_STARTUP", True),
        demo_mode=_flag("DEMO_MODE", False),
        demo_allow_registration=_flag("DEMO_ALLOW_REGISTRATION", False),
        demo_trial_enabled=_flag("DEMO_TRIAL_ENABLED", True),
        demo_chat_per_hour=_int("DEMO_CHAT_PER_HOUR", 30),
        trial_credits=_int("TRIAL_CREDITS", 5),
        max_trials_per_ip_per_day=_int("MAX_TRIALS_PER_IP_PER_DAY", 3),
        admin_email=os.getenv("ADMIN_EMAIL", "").strip().lower(),
        admin_password=os.getenv("ADMIN_PASSWORD", ""),
        bcrypt_rounds=_int("BCRYPT_ROUNDS", 12),
        llm_provider=provider,
        llm_preset=preset_name,
        llm_base_url=base_url.rstrip("/"),
        llm_model=model,
        llm_api_key=key,
        embedding_provider=embed,
        embedding_model=os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small"),
        query_translation=os.getenv("QUERY_TRANSLATION", "both").strip().lower() or "both",
        credit_cost_per_query=_int("CREDIT_COST_PER_QUERY", 1),
        free_monthly_credits=_int("FREE_MONTHLY_CREDITS", 40),
        pro_monthly_credits=_int("PRO_MONTHLY_CREDITS", 400),
        admin_monthly_credits=_int("ADMIN_MONTHLY_CREDITS", 10000),
        free_uploads_per_day=_int("FREE_UPLOADS_PER_DAY", 8),
        pro_uploads_per_day=_int("PRO_UPLOADS_PER_DAY", 40),
        max_upload_mb_free=_int("MAX_UPLOAD_MB_FREE", 8),
        max_upload_mb_pro=_int("MAX_UPLOAD_MB_PRO", 25),
        ocr_enabled=_flag("OCR_ENABLED", False),
        stripe_secret_key=os.getenv("STRIPE_SECRET_KEY", "").strip(),
        stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET", "").strip(),
        stripe_price_pro=os.getenv("STRIPE_PRICE_PRO", "").strip(),
        stripe_success_url=os.getenv("STRIPE_SUCCESS_URL", f"{app_base}/?billing=success"),
        stripe_cancel_url=os.getenv("STRIPE_CANCEL_URL", f"{app_base}/?billing=cancel"),
    )
