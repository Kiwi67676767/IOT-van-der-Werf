from flask import Flask, send_from_directory, request, jsonify, session
import os
import json
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash
import bcrypt as _bcrypt

def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode('utf-8'), _bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    # Bcrypt hashes beginnen met $2b$ of $2a$
    if hashed.startswith('$2b$') or hashed.startswith('$2a$'):
        return _bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    # Fallback voor oude werkzeug-hashes (transparante migratie)
    return check_password_hash(hashed, password)

def is_bcrypt_hash(hashed: str) -> bool:
    return hashed.startswith('$2b$') or hashed.startswith('$2a$')

app = Flask(__name__, static_folder='dist', static_url_path='')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, 'dist')

# Secret key voor sessies
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-verander-dit')

# Database instellen via Railway's DATABASE_URL, fallback naar SQLite lokaal
_db_url = os.environ.get('DATABASE_URL', '')
if _db_url.startswith('postgres://'):
    _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
if not _db_url:
    _db_url = 'sqlite:///' + os.path.join(BASE_DIR, 'metingen.db')

app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# ── MODELLEN ──

class User(db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    name          = db.Column(db.String(100))
    role          = db.Column(db.String(20))   # admin / machinist / stakeholder
    initials      = db.Column(db.String(5))
    label         = db.Column(db.String(50))
    assigned_velden = db.Column(db.Text)       # JSON array met veld-ids
    contract_name   = db.Column(db.String(100))

    def to_dict(self):
        return {
            'username':       self.username,
            'name':           self.name,
            'role':           self.role,
            'initials':       self.initials,
            'label':          self.label,
            'assignedVelden': json.loads(self.assigned_velden) if self.assigned_velden else None,
            'contractName':   self.contract_name,
        }


class Meting(db.Model):
    __tablename__ = 'metingen'
    id            = db.Column(db.Integer, primary_key=True)
    device_id     = db.Column(db.String(50))
    gras_hoogte_cm = db.Column(db.Float)
    latitude      = db.Column(db.Float)
    longitude     = db.Column(db.Float)
    timestamp     = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':            self.id,
            'device_id':     self.device_id,
            'gras_hoogte_cm': self.gras_hoogte_cm,
            'latitude':      self.latitude,
            'longitude':     self.longitude,
            'timestamp':     self.timestamp.isoformat()
        }


# ── STARTUP ──

INITIELE_GEBRUIKERS = [
    {'username': 'admin',        'password': 'admin789',  'name': 'Beheerder',          'role': 'admin',       'initials': 'AD', 'label': 'Beheerder',    'assigned_velden': None,                         'contract_name': None},
    {'username': 'machinist1',   'password': 'groen123',  'name': 'Machinist 1',         'role': 'machinist',   'initials': 'M1', 'label': 'Machinist',    'assigned_velden': None,                         'contract_name': None},
    {'username': 'machinist2',   'password': 'groen456',  'name': 'Machinist 2',         'role': 'machinist',   'initials': 'M2', 'label': 'Machinist',    'assigned_velden': None,                         'contract_name': None},
    {'username': 'stakeholder1', 'password': 'stake123',  'name': 'Gemeente Amsterdam',  'role': 'stakeholder', 'initials': 'GA', 'label': 'Stakeholder',  'assigned_velden': json.dumps([1,2,3,4,5,6,7]),  'contract_name': 'Gemeente Amsterdam'},
    {'username': 'stakeholder2', 'password': 'stake456',  'name': 'Sportpark Noord',     'role': 'stakeholder', 'initials': 'SN', 'label': 'Stakeholder',  'assigned_velden': json.dumps([8,9,10,11,12,13]),'contract_name': 'Sportpark Noord BV'},
]

with app.app_context():
    db.create_all()
    # Seed gebruikers als de tabel leeg is
    if User.query.count() == 0:
        for u in INITIELE_GEBRUIKERS:
            db.session.add(User(
                username      = u['username'],
                password_hash = hash_password(u['password']),
                name          = u['name'],
                role          = u['role'],
                initials      = u['initials'],
                label         = u['label'],
                assigned_velden = u['assigned_velden'],
                contract_name   = u['contract_name'],
            ))
        db.session.commit()
        print("Gebruikers aangemaakt in database.")


# ── AUTH ROUTES ──

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = (data.get('username') or '').strip().lower()
    password = data.get('password') or ''
    user = User.query.filter_by(username=username).first()
    if user and verify_password(password, user.password_hash):
        # Transparante migratie naar bcrypt als het nog een oud werkzeug-hash is
        if not is_bcrypt_hash(user.password_hash):
            user.password_hash = hash_password(password)
            db.session.commit()
        session['user_id'] = user.id
        return jsonify(user.to_dict()), 200
    return jsonify({'error': 'Verkeerde gebruikersnaam of wachtwoord'}), 401


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'status': 'ok'})


@app.route('/api/me', methods=['GET'])
def me():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Niet ingelogd'}), 401
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'Niet ingelogd'}), 401
    return jsonify(user.to_dict())


# ── GEBRUIKERS BEHEER ──

@app.route('/api/users', methods=['GET'])
def get_users():
    if session.get('user_id') is None:
        return jsonify({'error': 'Niet ingelogd'}), 401
    users = User.query.order_by(User.id).all()
    return jsonify([{
        'id': u.id, 'username': u.username,
        'name': u.name, 'role': u.role, 'label': u.label
    } for u in users])


@app.route('/api/users', methods=['POST'])
def create_user():
    me = User.query.get(session.get('user_id'))
    if not me or me.role != 'admin':
        return jsonify({'error': 'Geen toegang'}), 403
    data = request.get_json()
    username = (data.get('username') or '').strip().lower()
    password = data.get('password') or ''
    role     = data.get('role') or 'machinist'
    name     = data.get('name') or username
    if not username or not password:
        return jsonify({'error': 'Gebruikersnaam en wachtwoord zijn verplicht'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Gebruikersnaam bestaat al'}), 400
    initials = ''.join(w[0].upper() for w in name.split()[:2])
    label = {'admin': 'Beheerder', 'machinist': 'Machinist', 'stakeholder': 'Stakeholder'}.get(role, role)
    user = User(
        username=username,
        password_hash=hash_password(password),
        name=name, role=role, initials=initials, label=label,
        contract_name=data.get('contract_name')
    )
    db.session.add(user)
    db.session.commit()
    return jsonify({'status': 'ok', 'id': user.id}), 201


@app.route('/api/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    me = User.query.get(session.get('user_id'))
    if not me or me.role != 'admin':
        return jsonify({'error': 'Geen toegang'}), 403
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'Gebruiker niet gevonden'}), 404
    data = request.get_json()
    if data.get('name'):
        user.name = data['name']
        user.initials = ''.join(w[0].upper() for w in data['name'].split()[:2])
    if data.get('role'):
        user.role = data['role']
        user.label = {'admin': 'Beheerder', 'machinist': 'Machinist', 'stakeholder': 'Stakeholder'}.get(data['role'], data['role'])
    if data.get('contract_name') is not None:
        user.contract_name = data['contract_name'] or None
    if data.get('password'):
        user.password_hash = hash_password(data['password'])
    db.session.commit()
    return jsonify({'status': 'ok'})


@app.route('/api/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    me = User.query.get(session.get('user_id'))
    if not me or me.role != 'admin':
        return jsonify({'error': 'Geen toegang'}), 403
    if me.id == user_id:
        return jsonify({'error': 'Je kan jezelf niet verwijderen'}), 400
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'Gebruiker niet gevonden'}), 404
    db.session.delete(user)
    db.session.commit()
    return jsonify({'status': 'ok'})


# ── SENSOR ROUTE ──

@app.route('/data', methods=['POST'])
def ontvang_meting():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Geen JSON data"}), 400
    meting = Meting(
        device_id     = data.get('device_id'),
        gras_hoogte_cm = data.get('gras_hoogte_cm'),
        latitude      = data.get('latitude'),
        longitude     = data.get('longitude')
    )
    db.session.add(meting)
    db.session.commit()
    print(f"Meting opgeslagen: {data}")
    return jsonify({"status": "ok"}), 200


@app.route('/api/metingen', methods=['GET'])
def get_metingen():
    metingen = Meting.query.order_by(Meting.timestamp.desc()).all()
    return jsonify([m.to_dict() for m in metingen])


# ── STATIC FILES ──

@app.route('/')
def index():
    return send_from_directory(DIST_DIR, 'index.html')


@app.route('/<path:path>')
def serve_file(path):
    # Blokkeer API routes
    if path.startswith('api/'):
        return jsonify({'error': 'Not found'}), 404
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
