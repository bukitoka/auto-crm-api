from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models import Base, UUIDPrimaryKeyMixin


class PipelineStage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "pipeline_stages"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    position: Mapped[int]
    probability: Mapped[int] = mapped_column(default=0)  # percent, 0-100
    is_won: Mapped[bool] = mapped_column(default=False)
    is_lost: Mapped[bool] = mapped_column(default=False)
