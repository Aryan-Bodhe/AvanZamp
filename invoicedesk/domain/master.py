"""Validated procurement inputs. Money stays Decimal through persistence."""
from datetime import date
from decimal import Decimal
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Vendor(BaseModel):
    model_config = ConfigDict(extra='forbid')
    vendor_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=255)
    aliases_json: str = '[]'
    status: Literal['approved', 'blocked']
    notes: str = ''

    @field_validator('aliases_json')
    @classmethod
    def aliases(cls, value):
        parsed = json.loads(value)
        if not isinstance(parsed, list) or any(not isinstance(v, str) for v in parsed):
            raise ValueError('Aliases must be a JSON array of names.')
        return value


class PurchaseOrder(BaseModel):
    model_config = ConfigDict(extra='forbid')
    po_number: str = Field(min_length=1, max_length=80)
    vendor_id: str = Field(min_length=1, max_length=80)
    description: str
    net_amount: Decimal = Field(gt=0, max_digits=24, decimal_places=6)
    tax_rate: Decimal = Field(ge=0, le=1)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    status: Literal['open', 'closed']
    issue_date: date

    @field_validator('net_amount', 'tax_rate', mode='before')
    @classmethod
    def decimal_text(cls, value):
        if isinstance(value, float):
            raise ValueError('Money and rates must be decimal strings.')
        return value
