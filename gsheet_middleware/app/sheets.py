"""Google Sheets access + normalization + 7-day timestamp filtering."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dateutil import parser as dtparser
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from .config import Settings
from .schemas import TaxInvoiceRecord

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


class SheetClient:
    """Thin wrapper around the Google Sheets v4 API using a service account."""

    def __init__(self, settings: Settings):
        self.settings = settings
        creds = Credentials.from_service_account_file(
            settings.google_sa_key_file, scopes=SCOPES
        )
        # cache_discovery=False avoids a noisy warning and filesystem writes.
        self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    @staticmethod
    def _split_range(sheet_range: str) -> tuple[str, str, str]:
        """Split 'Tab'!A:Q into (prefix_incl_bang, start_col, end_col).

        Row numbers, if present (A2:Q), are stripped - only columns are kept.
        """
        prefix = ""
        cols = sheet_range
        if "!" in sheet_range:
            tab, cols = sheet_range.rsplit("!", 1)
            prefix = tab + "!"
        left, _, right = cols.partition(":")
        start_col = re.match(r"[A-Za-z]*", left).group()
        end_col = re.match(r"[A-Za-z]*", right).group()
        return prefix, start_col, end_col

    def _fetch_rows(self, spreadsheet_id: str, sheet_range: str) -> list[list[str]]:
        result = (
            self._service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=sheet_range,
                valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="FORMATTED_STRING",
            )
            .execute()
        )
        return result.get("values", [])

    def _fetch_header_and_data(
        self, spreadsheet_id: str, sheet_range: str,
        start_row: int, end_row: int | None = None,
    ) -> tuple[list, list[list], int]:
        """Return (header_row, data_rows, first_data_row_number).

        When start_row > 2 (or end_row is set) only the header (row 1) + the
        bounded window start_row..end_row is fetched, so we never re-download
        already-synced rows. end_row=start_row fetches a single row.
        """
        if (not start_row or start_row <= 2) and not end_row:
            rows = self._fetch_rows(spreadsheet_id, sheet_range)
            if not rows:
                return [], [], 2
            return rows[0], rows[1:], 2

        start = max(int(start_row or 2), 2)
        prefix, start_col, end_col = self._split_range(sheet_range)
        header_range = f"{prefix}{start_col}1:{end_col}1"
        data_range = f"{prefix}{start_col}{start}:{end_col}{end_row or ''}"
        result = (
            self._service.spreadsheets()
            .values()
            .batchGet(
                spreadsheetId=spreadsheet_id,
                ranges=[header_range, data_range],
                valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="FORMATTED_STRING",
            )
            .execute()
        )
        value_ranges = result.get("valueRanges", [])
        header_vals = value_ranges[0].get("values", []) if value_ranges else []
        header = header_vals[0] if header_vals else []
        data = value_ranges[1].get("values", []) if len(value_ranges) > 1 else []
        return header, data, start

    def get_recent_records(
        self,
        *,
        spreadsheet_id: str | None = None,
        sheet_range: str | None = None,
        max_age_days: int | None = None,
        timezone_name: str | None = None,
        column_map: dict[str, str] | None = None,
        start_row: int | None = None,
        end_row: int | None = None,
    ) -> tuple[list[TaxInvoiceRecord], int]:
        """Return (records, last_row) within the max-age window.

        Any argument left as None falls back to the middleware's env default,
        so Odoo (which owns this config) can override per request. `start_row`
        is the first sheet data row to read (cursor); `end_row` bounds it (a
        single row when start_row == end_row); `last_row` is the highest row
        number scanned (incl. age-filtered rows) for Odoo to store next.
        """
        spreadsheet_id = spreadsheet_id or self.settings.spreadsheet_id
        sheet_range = sheet_range or self.settings.sheet_range
        max_age = max_age_days if max_age_days is not None else self.settings.max_age_days
        tz_name = timezone_name or self.settings.sheet_timezone
        col_map = column_map or self.settings.column_map
        if not spreadsheet_id:
            raise ValueError(
                "No spreadsheet id: set it in Odoo (Sales > Settings > Tax "
                "Invoice GSheet Sync) or as SPREADSHEET_ID in the middleware .env"
            )

        header_row, data_rows, first_row = self._fetch_header_and_data(
            spreadsheet_id, sheet_range, start_row or 0, end_row
        )
        # last_row is the highest existing data row; if none, cursor stays put.
        last_row = first_row + len(data_rows) - 1 if data_rows else first_row - 1
        if not header_row:
            return [], last_row

        header = [str(h).strip() for h in header_row]
        # header column index -> normalized field name
        idx_to_field: dict[int, str] = {
            i: col_map[h] for i, h in enumerate(header) if h in col_map
        }

        tz = ZoneInfo(tz_name)
        cutoff = datetime.now(tz) - timedelta(days=max_age)

        records: list[TaxInvoiceRecord] = []
        for row_num, row in enumerate(data_rows, start=first_row):
            raw: dict[str, str] = {}
            for i, field in idx_to_field.items():
                raw[field] = str(row[i]).strip() if i < len(row) else ""

            ts = self._parse_dt(raw.get("timestamp", ""), tz)
            if ts is None:
                logger.warning("Row %s: unparseable timestamp %r, skipped",
                               row_num, raw.get("timestamp"))
                continue
            if ts < cutoff:
                continue  # older than the allowed window -> filter out

            try:
                records.append(self._normalize(raw, ts))
            except Exception:  # noqa: BLE001 - one bad row must not kill the batch
                logger.exception("Row %s: failed to normalize, skipped", row_num)

        return records, last_row

    def _normalize(self, raw: dict[str, str], ts: datetime) -> TaxInvoiceRecord:
        name = " ".join(
            p for p in (raw.get("name"),) if p
        ).strip()
        return TaxInvoiceRecord(
            timestamp=ts,
            order_reference=raw.get("order_reference", ""),
            order_date=self._parse_date(raw.get("order_date", "")),
            amount=self._parse_amount(raw.get("amount", "")),
            customer_name=name,
            address=raw.get("address", ""),
            tax_id=raw.get("tax_id", ""),
            phone=raw.get("phone", ""),
            email=raw.get("email", ""),
        )

    @staticmethod
    def _parse_dt(value: str, tz: ZoneInfo) -> datetime | None:
        if not value:
            return None
        try:
            dt = dtparser.parse(value, dayfirst=False)
        except (ValueError, OverflowError):
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _parse_date(value: str):
        if not value:
            return None
        try:
            return dtparser.parse(value, dayfirst=False).date()
        except (ValueError, OverflowError):
            return None

    @staticmethod
    def _parse_amount(value):
        if value in ("", None):
            return None
        try:
            return float(str(value).replace(",", "").strip())
        except ValueError:
            return None
