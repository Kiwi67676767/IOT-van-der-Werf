import os
from flask import Flask, render_template
from datetime import datetime
from extensions import db
from sqlalchemy.orm import Mapped, mapped_column
from models import Meting

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'data.sqlite')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False




@app.route("/")
def index() -> str:
    """Homepage route"""
    metingen = db.session.execute(db.select(Meting)).scalars().all()
    return render_template("index.html", metingen=metingen) # betekent dat de data die hier binnenkomt "metingen" ook weer worden gegeven in de "index.html" als "metingen"


if __name__ == "__main__":
    app.run(debug=True)

@app.route("/api/metingen", methods=["GET"])
def api_metingen():
    """API route to get all measurements"""
    metingen = db.session.execute(db.select(Meting)).scalars().all()
    return [{"id": m.id, "hoogte": m.hoogte, "tijd_van_meting": m.tijd_van_meting.isoformat()} for m in metingen]