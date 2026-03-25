from flask import Blueprint, render_template, request, jsonify
from extensions import db
from models import Meting

routes = Blueprint('routes', __name__)

@routes.route("/")
def index() -> str:
    """Homepage route"""
    metingen = db.session.execute(db.select(Meting)).scalars().all()
    return render_template("index.html", metingen=metingen) # betekent dat de data die hier binnenkomt "metingen" ook weer worden gegeven in de "index.html" als "metingen"

@routes.route("/api/metingen", methods=["GET"])
def api_metingen():
    """API route to get all measurements"""
    metingen = db.session.execute(db.select(Meting)).scalars().all()
    return [{"id": m.id, "hoogte": m.hoogte, "tijd_van_meting": m.tijd_van_meting.isoformat()} for m in metingen]


@routes.route("api/getfields")
def getFields():
    fields = ['test']

    return fields
