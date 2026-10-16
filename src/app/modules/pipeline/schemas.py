import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.shared.schemas import ORMModel, reject_null


class StageRead(ORMModel):
    id: uuid.UUID
    name: str
    position: int
    probability: int
    is_won: bool
    is_lost: bool
    deal_count: int = 0  # deals currently in this stage


class StageCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    probability: int = Field(default=0, ge=0, le=100)  # percent
    is_won: bool = False
    is_lost: bool = False


class StageUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    probability: int | None = Field(default=None, ge=0, le=100)
    is_won: bool | None = None
    is_lost: bool | None = None

    _not_null = field_validator("name", "probability", "is_won", "is_lost")(reject_null)


class StageOrder(BaseModel):
    """Every stage id, in the new order."""

    stage_ids: list[uuid.UUID] = Field(min_length=1)
