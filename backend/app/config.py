from typing import Literal, Self

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MA_", env_file=".env", extra="ignore", populate_by_name=True
    )
    environment: Literal["development", "test", "production"] = "development"
    agent_runtime: Literal["docker", "inprocess"] = "docker"
    sandbox_image: str = Field(default="medical-consultation-sandbox:local", max_length=200)
    sandbox_timeout: float = Field(default=45, ge=10, le=60)
    sandbox_memory_mb: int = Field(default=512, ge=256, le=1024)
    sandbox_cpus: float = Field(default=1, ge=0.25, le=2)
    sandbox_max_concurrency: int = Field(default=2, ge=1, le=8)
    database_url: str
    allow_simulated_data: bool = False
    demo_medical_education: bool = False
    cookie_secure: bool = True
    customer_login_required: bool = True
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://127.0.0.1:5175"]
    )
    session_hours: int = Field(default=24, ge=1, le=168)
    booking_encryption_key: SecretStr = SecretStr("")
    booking_hmac_key: SecretStr = SecretStr("")
    booking_sms_provider: Literal["disabled", "simulated", "aliyun"] = "disabled"
    booking_policy_key: str = "faq-online-application"
    sms_access_key_id: SecretStr = SecretStr("")
    sms_access_key_secret: SecretStr = SecretStr("")
    sms_sign_name: str = ""
    sms_template_code: str = ""
    neo4j_uri: str = "bolt://127.0.0.1:57689"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("")
    neo4j_database: str = "neo4j"
    model_base_url: Literal["https://dashscope.aliyuncs.com/compatible-mode/v1"] = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        validation_alias=AliasChoices("LLM_URL", "MA_MODEL_BASE_URL"),
    )
    model_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("LLM_API_KEY", "MA_MODEL_API_KEY")
    )
    chat_model: Literal["qwen3.7-plus"] = Field(
        default="qwen3.7-plus", validation_alias=AliasChoices("LLM_MODEL", "MA_CHAT_MODEL")
    )
    model_use_env_proxy: bool = True
    marketing_image_api_key: SecretStr = SecretStr("")
    marketing_video_api_key: SecretStr = SecretStr("")
    marketing_video_enabled: bool = False
    marketing_video_model: Literal["wan3.0-video", "wan3.0-video-prime", "wan2.2-t2v-plus"] = (
        "wan3.0-video"
    )
    marketing_video_workspace_id: str = Field(
        default="", max_length=63, pattern=r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)?$"
    )
    marketing_daily_limit: int = Field(default=10, ge=1, le=100)
    marketing_media_root: str = "runtime/marketing"
    marketing_max_asset_mb: int = Field(default=24, ge=1, le=100)
    marketing_asset_hosts: list[str] = Field(
        default_factory=lambda: [
            "aliyuncs.com",
            "siliconflow.cn",
            "siliconflow.com",
            "siliconflow.net",
            "scdn.cn",
        ]
    )
    embedding_model: Literal["text-embedding-v4"] = "text-embedding-v4"
    model_export_hashes: list[str] = Field(default_factory=list)
    milvus_uri: str = "http://127.0.0.1:59531"
    milvus_collection: str = Field(
        default="ma_knowledge_256", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$"
    )
    milvus_read_token: SecretStr = SecretStr("")
    milvus_write_token: SecretStr = SecretStr("")
    milvus_admin_token: SecretStr = SecretStr("")
    milvus_timeout: float = Field(default=5.0, ge=1, le=30)

    @property
    def marketing_video_ready(self) -> bool:
        return (
            self.marketing_video_enabled
            and bool(self.marketing_video_api_key.get_secret_value())
            and (
                self.marketing_video_model == "wan2.2-t2v-plus"
                or bool(self.marketing_video_workspace_id)
            )
        )

    @field_validator("model_base_url", mode="before")
    @classmethod
    def normalize_model_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if value in ("dashscope.aliyuncs.com", "https://dashscope.aliyuncs.com"):
            return "https://dashscope.aliyuncs.com/compatible-mode/v1"
        return value

    @model_validator(mode="after")
    def production_guard(self) -> Self:
        if self.demo_medical_education and (
            self.environment == "production" or not self.allow_simulated_data
        ):
            raise ValueError("demo medical education requires explicit nonproduction simulation")
        if self.booking_sms_provider == "simulated" and (
            self.environment == "production" or not self.allow_simulated_data
        ):
            raise ValueError(
                "simulated verification requires an explicit non-production environment"
            )
        if self.booking_encryption_key.get_secret_value():
            from cryptography.fernet import Fernet

            Fernet(self.booking_encryption_key.get_secret_value().encode())
        if self.booking_sms_provider != "disabled":
            if (
                not self.booking_encryption_key.get_secret_value()
                or len(self.booking_hmac_key.get_secret_value()) < 32
            ):
                raise ValueError("booking requires encryption and HMAC keys")
        if self.booking_sms_provider == "aliyun" and not all(
            (
                self.sms_access_key_id.get_secret_value(),
                self.sms_access_key_secret.get_secret_value(),
                self.sms_sign_name,
                self.sms_template_code,
            )
        ):
            raise ValueError("Aliyun verification requires approved sign/template and credentials")
        if self.environment == "production":
            if self.agent_runtime != "docker":
                raise ValueError("production requires the isolated agent runtime")
            if self.booking_sms_provider != "aliyun":
                raise ValueError("production requires real contact verification")
            if self.allow_simulated_data or not self.cookie_secure:
                raise ValueError("production forbids simulated data and insecure cookies")
            if any(not origin.startswith("https://") for origin in self.allowed_origins):
                raise ValueError("production requires HTTPS origins")
            if not self.milvus_uri.startswith("https://"):
                raise ValueError("production requires TLS for Milvus")
            if (
                not self.milvus_read_token.get_secret_value()
                or not self.milvus_write_token.get_secret_value()
            ):
                raise ValueError("production requires separate Milvus service credentials")
            if self.milvus_read_token == self.milvus_write_token:
                raise ValueError("production requires distinct Milvus read/write credentials")
        return self

    @property
    def demo_medical_enabled(self) -> bool:
        return (
            self.demo_medical_education
            and self.allow_simulated_data
            and self.environment != "production"
        )
