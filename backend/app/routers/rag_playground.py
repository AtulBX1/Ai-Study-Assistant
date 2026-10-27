"""Authenticated local-only generation decoding playground."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies.auth import get_current_user
from app.models import User
from app.services.rag.local_generation import MAX_NEW_TOKENS


def _generate_side_by_side(
    prompt: str, settings: list[dict[str, Any]]
) -> dict[str, Any]:
    """Late import keeps a tiny fake generator injectable in CI."""
    from app.services.rag.local_generation import generate_side_by_side

    return generate_side_by_side(prompt, settings)


def _calculate_perplexity(text: str) -> dict[str, Any]:
    """Late import lets tests and minimal installations use the CI-safe route."""
    from app.services.rag.local_generation import calculate_perplexity

    return calculate_perplexity(text)


router = APIRouter(prefix="/lab", tags=["generation lab"])
AuthenticatedUser = Annotated[User, Depends(get_current_user)]


class GenerationSetting(BaseModel):
    """One local decoding configuration; sampling settings are bounded."""

    model_config = ConfigDict(extra="forbid")
    strategy: Literal["greedy", "beam", "top_k", "top_p"]
    max_new_tokens: int = Field(default=24, ge=1, le=MAX_NEW_TOKENS)
    num_beams: int = Field(default=3, ge=1, le=8)
    top_k: int = Field(default=40, ge=1, le=100)
    top_p: float = Field(default=0.9, gt=0, le=1)
    temperature: float = Field(default=1.0, gt=0.05, le=2.0)
    repetition_penalty: float = Field(default=1.0, ge=1.0, le=2.0)


class GenerationRequest(BaseModel):
    """Prompt with 1-6 side-by-side generation configurations."""

    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=4_000)
    settings: list[GenerationSetting] = Field(min_length=1, max_length=6)


class PerplexityRequest(BaseModel):
    """Bounded text for local causal language-model perplexity."""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4_000)


def _model_error(error: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=str(error))


@router.post("/generate")
def generate(request: GenerationRequest, user: AuthenticatedUser) -> dict[str, Any]:
    """Run selected greedy, beam, top-k, or top-p settings on local small GPT only."""
    try:
        output = _generate_side_by_side(
            request.prompt,
            [setting.model_dump() for setting in request.settings],
        )
    except FileNotFoundError as error:
        raise _model_error(error) from error
    except ImportError as error:
        raise _model_error(
            FileNotFoundError(
                "Local generation needs cached weights plus torch and transformers."
            )
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return output


@router.post("/perplexity")
def perplexity(request: PerplexityRequest, user: AuthenticatedUser) -> dict[str, Any]:
    """Compute next-token perplexity using the same local-only small GPT model."""
    try:
        return _calculate_perplexity(request.text)
    except FileNotFoundError as error:
        raise _model_error(error) from error
    except ImportError as error:
        raise _model_error(
            FileNotFoundError(
                "Local generation needs cached weights plus torch and transformers."
            )
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
