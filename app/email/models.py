from datetime import datetime
from typing import Any

from email_validator import validate_email
from pydantic import BaseModel, Field, ConfigDict, field_validator


class EmailAddress(BaseModel):
    name: str | None = None
    email: str

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        try:
            validate_email(v, check_deliverability=False)
        except Exception as e:
            raise ValueError(f"Invalid email address: {e}")
        return v


class Email(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message_id: str
    thread_id: str | None = None
    from_: EmailAddress = Field(alias="from")
    to: list[EmailAddress]
    cc: list[EmailAddress] = Field(default_factory=list)
    subject: str
    body: str
    timestamp: datetime
    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list)
    attachments: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)


def parse_email(raw: dict[str, Any]) -> Email:
    return Email.model_validate(raw)
