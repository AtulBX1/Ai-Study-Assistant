"""Teacher-owned class data endpoints."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth import require_role
from app.models import ClassAssignment, StudyClass, User

router = APIRouter(
    prefix="/classes",
    tags=["classes"],
    dependencies=[Depends(require_role("teacher"))],
)
DatabaseSession = Annotated[Session, Depends(get_db)]
Teacher = Annotated[User, Depends(require_role("teacher"))]


class AssignmentResponse(BaseModel):
    id: int
    class_id: int
    title: str
    instructions: str | None
    due_at: datetime | None


@router.get("")
def list_classes(db: DatabaseSession, teacher: Teacher) -> list[dict[str, object]]:
    """Return only classes created by this teacher."""
    classes = db.scalars(
        select(StudyClass)
        .where(StudyClass.teacher_id == teacher.id)
        .order_by(StudyClass.id)
    )
    return [{"id": item.id, "name": item.name} for item in classes]


@router.get("/{class_id}/assignments", response_model=list[AssignmentResponse])
def list_class_assignments(
    class_id: int,
    db: DatabaseSession,
    teacher: Teacher,
) -> list[ClassAssignment]:
    """Return assignments only for a class owned by this teacher."""
    study_class = db.scalar(
        select(StudyClass).where(
            StudyClass.id == class_id,
            StudyClass.teacher_id == teacher.id,
        )
    )
    if study_class is None:
        raise HTTPException(status_code=404, detail="Class not found.")
    return list(
        db.scalars(
            select(ClassAssignment)
            .where(
                ClassAssignment.class_id == study_class.id,
                ClassAssignment.created_by == teacher.id,
            )
            .order_by(ClassAssignment.id)
        )
    )
