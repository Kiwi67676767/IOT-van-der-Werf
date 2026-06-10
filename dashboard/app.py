from flask import Flask, send_from_directory, request, jsonify, session
import os
import io
import json
import zipfile
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


class ShapeLayer(db.Model):
    __tablename__ = 'shape_layers'
    id        = db.Column(db.Integer, primary_key=True)
    naam      = db.Column(db.String(200), nullable=False)
    bestand   = db.Column(db.String(200))
    geojson   = db.Column(db.Text)        # GeoJSON FeatureCollection als string
    kleur     = db.Column(db.String(20), default='#2196f3')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':        self.id,
            'naam':      self.naam,
            'bestand':   self.bestand,
            'geojson':   json.loads(self.geojson) if self.geojson else None,
            'kleur':     self.kleur,
            'timestamp': self.timestamp.isoformat(),
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


class ActivityLog(db.Model):
    __tablename__ = 'activity_log'
    id        = db.Column(db.Integer, primary_key=True)
    user      = db.Column(db.String(100))
    type      = db.Column(db.String(50))
    message   = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':        self.id,
            'user':      self.user,
            'type':      self.type,
            'message':   self.message,
            'timestamp': self.timestamp.isoformat(),
        }


# ── SENSOR HELPER ──

def _seed_sensor_voor_machinist(username):
    """Maak 30 dagen aan demo-metingen voor een nieuw machinist-device."""
    import random
    import datetime as dt
    device_id = 'sensor-' + username
    if Meting.query.filter_by(device_id=device_id).first():
        return
    now = datetime.utcnow()
    for dag in range(29, -1, -1):
        ts = (now - dt.timedelta(days=dag)).replace(
            hour=random.randint(7, 16),
            minute=random.randint(0, 59),
            second=0, microsecond=0
        )
        fase = dag % 14
        hoogte = round(max(1.0, 5.0 + (7.0 * fase / 14) + random.gauss(0, 0.6)), 1)
        db.session.add(Meting(
            device_id=device_id,
            gras_hoogte_cm=hoogte,
            latitude=53.2194 + random.uniform(-0.02, 0.02),
            longitude=6.5665 + random.uniform(-0.02, 0.02),
            timestamp=ts,
        ))
    db.session.commit()
    print(f'Sensor aangemaakt voor machinist: {device_id}')


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
        # Seed sensoren voor de initiele machinisten
        for u in INITIELE_GEBRUIKERS:
            if u['role'] == 'machinist':
                _seed_sensor_voor_machinist(u['username'])
    else:
        # Migratie: fix alleen hashes die leeg of aantoonbaar corrupt zijn
        # (NIET resetten als het wachtwoord gewoon gewijzigd is door de gebruiker)
        gereset = 0
        for db_user in User.query.all():
            h = db_user.password_hash or ''
            hash_ongeldig = not h or (not h.startswith('$2b$') and not h.startswith('$2a$') and not h.startswith('pbkdf2:'))
            if hash_ongeldig:
                # Zoek eventueel standaard-wachtwoord op voor seed-gebruikers
                seed = next((u for u in INITIELE_GEBRUIKERS if u['username'] == db_user.username), None)
                if seed:
                    db_user.password_hash = hash_password(seed['password'])
                    gereset += 1
                    print(f"Corrupt hash hersteld voor {db_user.username}")
        if gereset:
            db.session.commit()

    # Zorg dat admin altijd de admin-rol heeft (maar raak het wachtwoord NIET aan)
    admin_user = User.query.filter_by(username='admin').first()
    if admin_user and admin_user.role != 'admin':
        admin_user.role = 'admin'
        admin_user.label = 'Beheerder'
        db.session.commit()
        print("Rol van 'admin' hersteld naar beheerder.")

    # Seed Noorderplantsoen shapefile als er nog geen lagen zijn
    if ShapeLayer.query.count() == 0:
        npl_geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[6.5605,53.2228],[6.5648,53.2235],[6.5685,53.2232],[6.5705,53.2218],[6.5708,53.22],[6.5695,53.2185],[6.5672,53.2178],[6.5648,53.218],[6.5628,53.2188],[6.5612,53.22],[6.56,53.2214],[6.5605,53.2228]]]
                },
                "properties": {"naam": "Noorderplantsoen", "plaats": "Groningen", "type": "stadspark"}
            }]
        }
        db.session.add(ShapeLayer(
            naam='Noorderplantsoen',
            bestand='Noorderplantsoen.shp',
            geojson=json.dumps(npl_geojson),
            kleur='#2e7d32',
        ))
        db.session.commit()
        print('Noorderplantsoen shapefile geseed.')

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
        # Activiteitenlog
        db.session.add(ActivityLog(
            user=user.name or user.username,
            type='login',
            message=f'Ingelogd op systeem',
        ))
        db.session.commit()
        return jsonify(user.to_dict()), 200
    return jsonify({'error': 'Verkeerde gebruikersnaam of wachtwoord'}), 401


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    resp = jsonify({'status': 'ok'})
    # Verwijder de sessie-cookie expliciet zodat de browser hem niet hergebruikt
    resp.delete_cookie(app.session_cookie_name)
    return resp


@app.route('/api/config', methods=['GET'])
def get_config():
    if not session.get('user_id'):
        return jsonify({'error': 'Niet ingelogd'}), 401
    return jsonify({'arcgis_key': ARCGIS_KEY})


@app.route('/api/me', methods=['GET'])
def me():
    user_id = session.get('user_id')
    if not user_id:
        resp = jsonify({'error': 'Niet ingelogd'})
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        return resp, 401
    user = User.query.get(user_id)
    if not user:
        resp = jsonify({'error': 'Niet ingelogd'})
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        return resp, 401
    resp = jsonify(user.to_dict())
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    return resp


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

    # Koppel automatisch een sensor aan nieuwe machinisten
    if role == 'machinist':
        _seed_sensor_voor_machinist(username)

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

    # Verwijder gekoppelde sensor-metingen als het een machinist is
    if user.role == 'machinist':
        device_id = 'sensor-' + user.username
        Meting.query.filter_by(device_id=device_id).delete()

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


# ── SHAPEFILE API ──

def _shapefile_zip_naar_geojson(zip_bytes, kleur_hint=None):
    """Parse een zip met shapefile → GeoJSON FeatureCollection.
       Geeft (naam, geojson_dict) terug of gooit een Exception."""
    import shapefile as shp_mod

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        namen = zf.namelist()
        shp_file = next((n for n in namen if n.lower().endswith('.shp')), None)
        shx_file = next((n for n in namen if n.lower().endswith('.shx')), None)
        dbf_file = next((n for n in namen if n.lower().endswith('.dbf')), None)
        if not shp_file:
            raise ValueError('Geen .shp bestand gevonden in de zip.')

        shp_bytes = io.BytesIO(zf.read(shp_file))
        shx_bytes = io.BytesIO(zf.read(shx_file)) if shx_file else None
        dbf_bytes = io.BytesIO(zf.read(dbf_file)) if dbf_file else None

        sf = shp_mod.Reader(shp=shp_bytes, shx=shx_bytes, dbf=dbf_bytes)

        features = []
        for shape, rec in zip(sf.shapes(), sf.records()):
            parts = list(shape.parts) + [len(shape.points)]
            rings = [[[p[0], p[1]] for p in shape.points[parts[i]:parts[i+1]]]
                     for i in range(len(parts) - 1)]
            features.append({
                'type': 'Feature',
                'geometry': {'type': 'Polygon', 'coordinates': rings},
                'properties': rec.as_dict(),
            })

        naam = os.path.splitext(os.path.basename(shp_file))[0]
        geojson = {'type': 'FeatureCollection', 'features': features}
        return naam, geojson


@app.route('/api/shapefiles', methods=['GET'])
def get_shapefiles():
    if not session.get('user_id'):
        return jsonify({'error': 'Niet ingelogd'}), 401
    lagen = ShapeLayer.query.order_by(ShapeLayer.id).all()
    return jsonify([l.to_dict() for l in lagen])


@app.route('/api/shapefiles', methods=['POST'])
def upload_shapefile():
    if not session.get('user_id'):
        return jsonify({'error': 'Niet ingelogd'}), 401
    me = db.session.get(User, session['user_id'])
    if not me or me.role != 'admin':
        return jsonify({'error': 'Alleen beheerders mogen shapefiles uploaden'}), 403

    if 'file' not in request.files:
        return jsonify({'error': 'Geen bestand meegestuurd'}), 400
    f = request.files['file']
    if not f.filename.lower().endswith('.zip'):
        return jsonify({'error': 'Upload een .zip bestand met de shapefile'}), 400

    kleur = request.form.get('kleur', '#2196f3')

    try:
        naam, geojson = _shapefile_zip_naar_geojson(f.read(), kleur)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    laag = ShapeLayer(
        naam=naam,
        bestand=f.filename,
        geojson=json.dumps(geojson),
        kleur=kleur,
    )
    db.session.add(laag)
    db.session.commit()
    return jsonify(laag.to_dict()), 201


@app.route('/api/shapefiles/<int:laag_id>', methods=['DELETE'])
def delete_shapefile(laag_id):
    me = db.session.get(User, session.get('user_id'))
    if not me or me.role != 'admin':
        return jsonify({'error': 'Geen toegang'}), 403
    laag = db.session.get(ShapeLayer, laag_id)
    if not laag:
        return jsonify({'error': 'Niet gevonden'}), 404
    db.session.delete(laag)
    db.session.commit()
    return jsonify({'status': 'ok'})


# ── SENSOR ROUTE ──

@app.route('/data', methods=['POST'])
def ontvang_meting():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Geen JSON data"}), 400
    hoogte = data.get('gras_hoogte_cm')
    device = data.get('device_id') or 'onbekend'
    meting = Meting(
        device_id      = device,
        gras_hoogte_cm = hoogte,
        latitude       = data.get('latitude'),
        longitude      = data.get('longitude')
    )
    db.session.add(meting)
    # Activiteitenlog
    hoogte_str = f'{hoogte} cm' if hoogte is not None else 'onbekend'
    db.session.add(ActivityLog(
        user='Systeem',
        type='meting',
        message=f'Meting ontvangen van {device}: {hoogte_str}',
    ))
    db.session.commit()
    print(f"Meting opgeslagen: {data}")
    return jsonify({"status": "ok"}), 200


@app.route('/api/activiteiten', methods=['GET'])
def get_activiteiten():
    if not session.get('user_id'):
        return jsonify({'error': 'Niet ingelogd'}), 401
    limit = min(int(request.args.get('limit', 50)), 200)
    items = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(limit).all()
    return jsonify([a.to_dict() for a in items])


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
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=False, host="0.0.0.0", port=port)
