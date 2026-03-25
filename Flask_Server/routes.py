from flask import Blueprint, render_template, request, jsonify
from extensions import db, socketio
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


@routes.route("/api/getfields")
def getFields():
    fields = ['test']

    return fields


@routes.route("/api/postmeting", methods=["POST"])
def post_meting():
    try:
        h = float(request.json['hoogte'])
        
        nieuwe_meting = Meting(hoogte=h)
        db.session.add(nieuwe_meting)
        db.session.commit()
        
        # Update tabel
        socketio.emit('update_tabel', {
            "id": nieuwe_meting.id, 
            "hoogte": nieuwe_meting.hoogte
        })

        return {"id": nieuwe_meting.id, "status": "success"}, 201
    

    except (KeyError, ValueError, TypeError, Exception):
        # Vangt alles op: mist 'hoogte', tekst i.p.v. getal, of geen JSON.
        return {"error": "Ongeldige input"}, 400