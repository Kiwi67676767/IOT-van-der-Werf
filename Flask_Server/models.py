from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column


db = SQLAlchemy()

class Meting(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True) # De id's worden automatisch gegenereerd (autoincrement)
    hoogte: Mapped[float | None]
    tijd_van_meting: Mapped[datetime] = mapped_column(default=datetime.utcnow) # Dit is een kolom van het type datetime die automatisch wordt ingesteld op de huidige tijd (default=datetime.utcnow).

    def __init__(self, hoogte: float):
        self.hoogte = hoogte

    def __repr__(self) -> str:
        """String representatie voor debugging."""
        return f"Meting(id={self.id}, hoogte={self.hoogte}, tijd_van_meting={self.tijd_van_meting})"
