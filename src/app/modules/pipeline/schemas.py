import uuid

from app.shared.schemas import ORMModel


class StageRead(ORMModel):
    id: uuid.UUID
    name: str
    position: int
    probability: int
    is_won: bool
    is_lost: bool
