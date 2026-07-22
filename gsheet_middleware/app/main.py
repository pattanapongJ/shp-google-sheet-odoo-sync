"""FastAPI middleware exposing 7-day-filtered Google Sheet records to Odoo."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status

from .config import Settings, get_settings
from .logging_config import setup_logging
from .schemas import RecordsResponse
from .sheets import SheetClient

setup_logging(get_settings())
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Odoo ⇄ Google Sheet Tax-Invoice Middleware",
    version="1.0.0",
    description="Serves Google Form / Sheet tax-invoice requests to Odoo.",
)


def require_api_key(
    x_api_key: str = Header(default=""),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.api_key or x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key"
        )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get(
    "/records",
    response_model=RecordsResponse,
    dependencies=[Depends(require_api_key)],
)
def records(
    settings: Settings = Depends(get_settings),
    spreadsheet_id: str | None = Query(default=None),
    sheet_range: str | None = Query(default=None),
    max_age_days: int | None = Query(default=None, ge=0),
    timezone_name: str | None = Query(default=None, alias="timezone"),
    column_map: str | None = Query(default=None),
    start_row: int | None = Query(default=None, ge=2),
    end_row: int | None = Query(default=None, ge=2),
) -> RecordsResponse:
    """Return tax-invoice-request records from the sheet, filtered to the last
    N days by their Google Form timestamp.

    The sheet/business config (spreadsheet id, range, max age, timezone, column
    map) is owned by Odoo and passed as query params; each falls back to the
    middleware's env/default when omitted. `column_map` is a JSON object string
    of {sheet header: field name}.
    """
    col_map_override = None
    if column_map:
        try:
            col_map_override = json.loads(column_map)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="column_map is not valid JSON")
        if not isinstance(col_map_override, dict):
            raise HTTPException(status_code=400, detail="column_map must be a JSON object")

    try:
        client = SheetClient(settings)
        items, last_row = client.get_recent_records(
            spreadsheet_id=spreadsheet_id,
            sheet_range=sheet_range,
            max_age_days=max_age_days,
            timezone_name=timezone_name,
            column_map=col_map_override,
            start_row=start_row,
            end_row=end_row,
        )
    except FileNotFoundError as exc:
        logger.error("Service-account key file missing: %s", exc)
        raise HTTPException(status_code=500, detail="Sheets credentials misconfigured")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to read spreadsheet")
        raise HTTPException(status_code=502, detail=f"Sheets read failed: {exc}")

    return RecordsResponse(
        count=len(items),
        max_age_days=max_age_days if max_age_days is not None else settings.max_age_days,
        last_row=last_row,
        generated_at=datetime.now(timezone.utc),
        records=items,
    )
