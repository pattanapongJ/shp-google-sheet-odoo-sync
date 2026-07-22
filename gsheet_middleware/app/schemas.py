"""Response schemas for the middleware API."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class TaxInvoiceRecord(BaseModel):
    """A single Google Sheet response, normalized for Odoo consumption.

    `customer_name` is the concatenation of title + name + surname; the Odoo
    field `tax_inv_customer_name` is a single Char.
    """

    timestamp: datetime
    order_reference: str
    order_date: date | None = None
    amount: float | None = None
    customer_name: str
    address: str = ""
    tax_id: str = ""
    phone: str = ""
    email: str = ""


class RecordsResponse(BaseModel):
    count: int
    max_age_days: int
    generated_at: datetime
    # Highest sheet row number scanned this call (incl. rows dropped by the
    # age filter). Odoo stores this as the cursor for the next run.
    last_row: int
    records: list[TaxInvoiceRecord]
