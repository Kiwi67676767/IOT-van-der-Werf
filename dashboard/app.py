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

# ArcGIS API key — stel in als omgevingsvariabele ARCGIS_KEY op Railway
ARCGIS_KEY = os.environ.get('ARCGIS_KEY', '')

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


class Veld(db.Model):
    __tablename__ = 'velden'
    id         = db.Column(db.Integer, primary_key=True)
    naam       = db.Column(db.String(200), nullable=False)
    loc        = db.Column(db.String(200))
    lat        = db.Column(db.Float)
    lng        = db.Column(db.Float)
    hoogte     = db.Column(db.Integer, default=80)
    status     = db.Column(db.String(50), default='OK')
    prio       = db.Column(db.String(20), default='Laag')
    machinist  = db.Column(db.String(100), default='—')
    stakeholder = db.Column(db.String(100), default='—')
    categorie  = db.Column(db.String(5), default='C')
    rings      = db.Column(db.Text)    # JSON polygoon-rings

    def to_dict(self):
        return {
            'id':         self.id,
            'naam':       self.naam,
            'loc':        self.loc or '',
            'lat':        self.lat or 0,
            'lng':        self.lng or 0,
            'hoogte':     self.hoogte or 0,
            'status':     self.status or 'OK',
            'prio':       self.prio or 'Laag',
            'machinist':  self.machinist or '—',
            'stakeholder': self.stakeholder or '—',
            'categorie':  self.categorie or 'C',
            'rings':      json.loads(self.rings) if self.rings else None,
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
    else:
        # Herstel-migratie: reset seed-wachtwoorden die corrupt zijn geraakt
        gereset = 0
        for u in INITIELE_GEBRUIKERS:
            db_user = User.query.filter_by(username=u['username']).first()
            if db_user and not verify_password(u['password'], db_user.password_hash):
                db_user.password_hash = hash_password(u['password'])
                gereset += 1
                print(f"Wachtwoord gereset voor {u['username']}")
        if gereset:
            db.session.commit()

    # Herstel: zorg dat gebruiker 'admin' altijd de admin-rol heeft + wachtwoord reset
    admin_user = User.query.filter_by(username='admin').first()
    if admin_user:
        if admin_user.role != 'admin':
            admin_user.role = 'admin'
            admin_user.label = 'Beheerder'
            print("Rol van 'admin' hersteld naar beheerder.")
        admin_user.password_hash = hash_password('admin789')
        db.session.commit()
        print("Wachtwoord van 'admin' teruggezet naar admin789.")

    # Seed demo-metingen per veld als er nog geen metingen in de buurt zijn
    import random
    import datetime as dt
    velden_seed = Veld.query.all()
    MAX_DIST_SEED = 0.05
    cat_target_seed = {'A': 4.0, 'B': 7.0, 'C': 9.0, 'D': 14.0}
    geseeded = 0
    for veld in velden_seed:
        if not veld.lat or not veld.lng:
            continue
        heeft_metingen = Meting.query.filter(
            Meting.latitude.between(veld.lat - MAX_DIST_SEED, veld.lat + MAX_DIST_SEED),
            Meting.longitude.between(veld.lng - MAX_DIST_SEED, veld.lng + MAX_DIST_SEED)
        ).first()
        if heeft_metingen:
            continue
        now = datetime.utcnow()
        target_cm = cat_target_seed.get(veld.categorie or 'C', 9.0)
        device_id = 'sensor-{:03d}'.format(veld.id)
        for dag in range(89, -1, -1):
            ts = (now - dt.timedelta(days=dag)).replace(
                hour=random.randint(7, 16),
                minute=random.randint(0, 59),
                second=0, microsecond=0
            )
            fase = dag % 14
            base = target_cm * 0.6 + (target_cm * 0.9 * fase / 14)
            hoogte = round(max(1.0, base + random.gauss(0, target_cm * 0.08)), 1)
            db.session.add(Meting(
                device_id=device_id,
                gras_hoogte_cm=hoogte,
                latitude=veld.lat + random.uniform(-0.001, 0.001),
                longitude=veld.lng + random.uniform(-0.001, 0.001),
                timestamp=ts,
            ))
        geseeded += 1
    if geseeded:
        db.session.commit()
        print('Demo-metingen aangemaakt voor {} veld(en).'.format(geseeded))


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


@app.route('/api/config', methods=['GET'])
def get_config():
    if not session.get('user_id'):
        return jsonify({'error': 'Niet ingelogd'}), 401
    return jsonify({'arcgis_key': ARCGIS_KEY})


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
    if data.get('username'):
        new_username = data['username'].strip().lower()
        if new_username != user.username:
            if User.query.filter_by(username=new_username).first():
                return jsonify({'error': 'Gebruikersnaam is al in gebruik'}), 400
            user.username = new_username
    if data.get('name'):
        user.name = data['name']
        user.initials = ''.join(w[0].upper() for w in data['name'].split()[:2])
    if data.get('role') and data['role'] != user.role:
        # Voorkom dat de laatste admin zijn rol kwijtraakt
        if user.role == 'admin':
            admin_count = User.query.filter_by(role='admin').count()
            if admin_count <= 1:
                return jsonify({'error': 'Er moet altijd minimaal één beheerder zijn.'}), 400
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


# ── VELDEN API ──

@app.route('/api/velden', methods=['GET'])
def get_velden():
    if not session.get('user_id'):
        return jsonify({'error': 'Niet ingelogd'}), 401
    velden = Veld.query.order_by(Veld.id).all()
    return jsonify([v.to_dict() for v in velden])


@app.route('/api/velden', methods=['POST'])
def create_veld():
    if not session.get('user_id'):
        return jsonify({'error': 'Niet ingelogd'}), 401
    data = request.get_json()
    if not data or not data.get('naam'):
        return jsonify({'error': 'naam is verplicht'}), 400
    veld = Veld(
        naam       = data['naam'],
        loc        = data.get('loc', ''),
        lat        = data.get('lat', 0),
        lng        = data.get('lng', 0),
        hoogte     = data.get('hoogte', 80),
        status     = data.get('status', 'OK'),
        prio       = data.get('prio', 'Laag'),
        machinist  = data.get('machinist', '—'),
        stakeholder = data.get('stakeholder', '—'),
        categorie  = data.get('categorie', 'C'),
        rings      = json.dumps(data['rings']) if data.get('rings') else None,
    )
    db.session.add(veld)
    db.session.commit()
    return jsonify(veld.to_dict()), 201


@app.route('/api/velden/bulk', methods=['POST'])
def bulk_velden():
    """Importeer meerdere velden tegelijk; bestaande (zelfde naam+loc) worden overgeslagen."""
    if not session.get('user_id'):
        return jsonify({'error': 'Niet ingelogd'}), 401
    items = request.get_json()
    if not isinstance(items, list):
        return jsonify({'error': 'Verwacht een array'}), 400
    nieuw = 0
    for d in items:
        if not d.get('naam'):
            continue
        bestaat = Veld.query.filter_by(naam=d['naam'], loc=d.get('loc', '')).first()
        if bestaat:
            continue
        v = Veld(
            naam       = d['naam'],
            loc        = d.get('loc', ''),
            lat        = d.get('lat', 0),
            lng        = d.get('lng', 0),
            hoogte     = d.get('hoogte', 80),
            status     = d.get('status', 'OK'),
            prio       = d.get('prio', 'Laag'),
            machinist  = d.get('machinist', '—'),
            stakeholder = d.get('stakeholder', '—'),
            categorie  = d.get('categorie', 'C'),
            rings      = json.dumps(d['rings']) if d.get('rings') else None,
        )
        db.session.add(v)
        nieuw += 1
    db.session.commit()
    return jsonify({'nieuw': nieuw})


@app.route('/api/velden/<int:veld_id>', methods=['PUT'])
def update_veld(veld_id):
    if not session.get('user_id'):
        return jsonify({'error': 'Niet ingelogd'}), 401
    veld = Veld.query.get(veld_id)
    if not veld:
        return jsonify({'error': 'Niet gevonden'}), 404
    data = request.get_json()
    for attr in ('naam', 'loc', 'lat', 'lng', 'hoogte', 'status', 'prio',
                 'machinist', 'stakeholder', 'categorie'):
        if attr in data:
            setattr(veld, attr, data[attr])
    if 'rings' in data:
        veld.rings = json.dumps(data['rings']) if data['rings'] else None
    db.session.commit()
    return jsonify(veld.to_dict())


@app.route('/api/velden/<int:veld_id>', methods=['DELETE'])
def delete_veld(veld_id):
    me = User.query.get(session.get('user_id'))
    if not me or me.role != 'admin':
        return jsonify({'error': 'Geen toegang'}), 403
    veld = Veld.query.get(veld_id)
    if not veld:
        return jsonify({'error': 'Niet gevonden'}), 404
    db.session.delete(veld)
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
