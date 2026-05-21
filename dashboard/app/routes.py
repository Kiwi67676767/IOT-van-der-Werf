from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from .models import User, Meting
from . import db


main = Blueprint('main', __name__)


@main.route('/')
def index():
    return render_template('index.html')


@main.route('/velden')
def fields():
    return render_template('fields.html')


# Inloggen
@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        # We pakken voor nu de eerste gebruiker die we vinden of maken er een
        user = User.query.filter_by(username=username).first()
        if user:
            login_user(user)
            return redirect(url_for('main.index'))
    return render_template('login.html')


# Uitloggen
@main.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.index'))


@main.route('/data', methods=['POST'])
def ontvang_data():
    data = request.json
    if not data:
        return jsonify({"error": "Geen data ontvangen"}), 400

    meting = Meting(
        device_id=data.get('device_id', 'onbekend'),
        gras_hoogte_cm=data.get('gras_hoogte_cm'),
        latitude=data.get('latitude'),
        longitude=data.get('longitude')
    )
    db.session.add(meting)
    db.session.commit()
    return jsonify({"status": "ok"}), 200


@main.route('/metingen')
def toon_metingen():
    metingen = Meting.query.order_by(Meting.timestamp.desc()).limit(20).all()
    return jsonify([{
        "id": m.id,
        "device_id": m.device_id,
        "gras_hoogte_cm": m.gras_hoogte_cm,
        "latitude": m.latitude,
        "longitude": m.longitude,
        "timestamp": str(m.timestamp)
    } for m in metingen])