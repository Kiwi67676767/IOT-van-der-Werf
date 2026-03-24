from flask import Flask, render_template, flash, redirect, url_for
import os
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import Mapped, mapped_column

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'data.sqlite')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class Meting(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True) # De id's worden automatisch gegenereerd (autoincrement)
    hoogte: Mapped[float | None]
    tijd_van_meting: Mapped[datetime] = mapped_column(default=datetime.utcnow) # Dit is een kolom van het type datetime die automatisch wordt ingesteld op de huidige tijd (default=datetime.utcnow).

    def __init__(self, hoogte: float):
        self.hoogte = hoogte

    def __repr__(self) -> str:
        """String representatie voor debugging."""
        return f"Meting(id={self.id}, hoogte={self.hoogte}, tijd_van_meting={self.tijd_van_meting})"


@app.route("/")
def index() -> str:
    """Homepage route"""
    metingen = db.session.execute(db.select(Meting)).scalars().all()
    return render_template("index.html", metingen=metingen) # betekent dat de data die hier binnenkomt "metingen" ook weer worden gegeven in de "index.html" als "metingen"


if __name__ == "__main__":
    app.run(debug=True)