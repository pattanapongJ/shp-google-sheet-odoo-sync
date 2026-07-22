"""Application configuration, loaded from environment / .env file."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path to gsheet_middleware/.env so it loads no matter the CWD.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # API security
    api_key: str = Field(..., alias="API_KEY")

    # Google Sheets. The service-account file is host-level (stays here);
    # spreadsheet id / range / age / tz are normally supplied by Odoo per
    # request and these values act only as fallback defaults.
    google_sa_key_file: str = Field(..., alias="GOOGLE_SA_KEY_FILE")
    spreadsheet_id: str = Field("", alias="SPREADSHEET_ID")
    sheet_range: str = Field("Form Responses 1!A:K", alias="SHEET_RANGE")

    # Business-rule fallbacks (Odoo overrides these per request)
    max_age_days: int = Field(7, alias="MAX_AGE_DAYS")
    sheet_timezone: str = Field("Asia/Bangkok", alias="SHEET_TIMEZONE")

    # Logging. LOG_FILE empty -> console only (dev). Set a path in production
    # for a rotating file; console output is always kept as well.
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    log_file: str = Field("", alias="LOG_FILE")
    log_max_bytes: int = Field(10_000_000, alias="LOG_MAX_BYTES")   # ~10 MB
    log_backup_count: int = Field(5, alias="LOG_BACKUP_COUNT")

    # Column mapping: sheet header text -> normalized field name
    column_map: dict[str, str] = Field(
        default_factory=lambda: {
            "ประทับเวลา": "timestamp",
            "หมายเลขคำสั่งซื้อ / Order Number": "order_reference",
            "วันที่สั่งซื้อ  / Order Date": "order_date",
            "ยอดเงินที่ชำระ / Amount paid": "amount",
            "ชื่อผู้เสียภาษี": "name",
            "ที่อยู่ (Address)": "address",
            "เลขประจำตัวผู้เสียภาษี หรือเลขบัตรประชาชน (Tax ID)": "tax_id",
            "เบอร์โทรศัพท์ (Telephone Number)": "phone",
            "E-Mail": "email",
        },
        alias="COLUMN_MAP",
    )

    @field_validator("column_map", mode="before")
    @classmethod
    def _parse_column_map(cls, v):
        if isinstance(v, str):
            return json.loads(v)
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
