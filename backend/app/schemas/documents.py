"""Document API response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: str
    progress: int
    error_message: str | None
    page_count: int | None
    language: str | None
    created_at: datetime


class DocumentPageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    page_number: int
    text: str
    headings: list[dict[str, str | float | bool]]
    tables: list[list[list[str | None]]]
    ocr_status: str
