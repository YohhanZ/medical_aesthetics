"""Structured booking input is local business data, never model input."""

from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

CONFIRMATION_TEXT = "确认提交预约申请，等待门店确认"


class BookingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftInput(BookingInput):
    request_key: UUID
    trigger_run_id: UUID
    name: str = Field(min_length=1, max_length=40)
    phone: str = Field(pattern=r"^1[3-9]\d{9}$")
    desired_at: AwareDatetime
    intention: str = Field(min_length=1, max_length=300)
    project_version_id: UUID | None = None

    @field_validator("name", "intention")
    @classmethod
    def trim_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("nonempty text required")
        return value.strip()


class VerificationInput(BookingInput):
    request_key: UUID
    sms_consent: bool


class CodeInput(BookingInput):
    code: str = Field(pattern=r"^\d{6}$")


class ConfirmInput(BookingInput):
    request_key: UUID
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    verification_id: UUID
    accepted: bool
    confirmation_text: str = Field(max_length=100)
