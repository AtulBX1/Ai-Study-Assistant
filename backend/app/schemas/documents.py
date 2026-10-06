"""Document API response schemas."""

from datetime import datetime

from pydantic import BaseModel


class DocumentResponse(BaseModel):
    id: int
    title: str
    status: str
    page_count: int | None
    language: str | None
    created_at: datetime
