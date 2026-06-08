from flask import Flask, send_from_directory, request, jsonify
import os
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__, static_folder='dist', static_url_path='')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, 'dist')

# Database instellen via Railway's DATABASE_URL, fallback naar SQLite lokaal
_db_url = os.environ.get('DATABASE_URL', '')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
if not _db_url:
    _db_url = 'sqlite:///' + os.path.join(BASE_DIR, 'metingen.db')

app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# Database model
class Meting(db.Model):
    __tablename__ = 'metingen'
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(50))
    gras_hoogte_cm = db.Column(db.Float)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'device_id': self.device_id,
            'gras_hoogte_cm': self.gras_hoogte_cm,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'timestamp': self.timestamp.isoformat()
        }


# Tabellen aanmaken als ze nog niet bestaan
with app.app_context():
    db.create_all()


@app.route('/data', methods=['POST'])
def ontvang_meting():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Geen JSON data"}), 400

    meting = Meting(
        device_id=data.get('device_id'),
        gras_hoogte_cm=data.get('gras_hoogte_cm'),
        latitude=data.get('latitude'),
        longitude=data.get('longitude')
    )
    db.session.add(meting)
    db.session.commit()
    print(f"Meting opgeslagen: {data}")
    return jsonify({"status": "ok"}), 200


@app.route('/api/metingen', methods=['GET'])
def get_metingen():
    metingen = Meting.query.order_by(Meting.timestamp.desc()).all()
    return jsonify([m.to_dict() for m in metingen])


@app.route('/')
def index():
    return send_from_directory(DIST_DIR, 'index.html')


@app.route('/<path:path>')
def serve_file(path):
    full_path = os.path.join(DIST_DIR, path)

    if os.path.isfile(full_path):
        return send_from_directory(DIST_DIR, path)

    if os.path.isdir(full_path):
        index_path = os.path.join(full_path, 'index.html')
        if os.path.isfile(index_path):
            return send_from_directory(full_path, 'index.html')

    return send_from_directory(DIST_DIR, 'index.html'), 404


if __name__ == '__main__':
    print("=" * 40)
    print("  Van der Werf IoT Dashboard")
    print("  http://localhost:5000")
    print("  Ctrl+C om te stoppen")
    print("=" * 40)
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)
