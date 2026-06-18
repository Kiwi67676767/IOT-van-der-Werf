from flask import Flask, send_from_directory, request, jsonify, session, redirect
import os
import io
import json
import zipfile
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect as _sa_inspect, text as _sa_text
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
    device_id       = db.Column(db.String(50))   # Pico-ID van de gekoppelde sensor (alleen machinist)
    actieve_veld_id = db.Column(db.Integer, db.ForeignKey('velden.id'), nullable=True)  # veld waarvoor nu gemeten wordt

    def to_dict(self):
        return {
            'id':              self.id,
            'username':        self.username,
            'name':            self.name,
            'role':            self.role,
            'initials':        self.initials,
            'label':           self.label,
            'assignedVelden':  json.loads(self.assigned_velden) if self.assigned_velden else None,
            'contractName':    self.contract_name,
            'deviceId':        self.device_id,
            'actieveVeldId':   self.actieve_veld_id,
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
    # Legacy: losse naam-string. Blijft bestaan als fallback voor oude/niet-gemigreerde
    # records, maar is NIET meer de bron van waarheid — zie machinist_id/stakeholder_id.
    machinist  = db.Column(db.String(100), default='—')
    stakeholder = db.Column(db.String(100), default='—')
    # Echte koppeling op user-ID. Dit voorkomt dat een toewijzing "kwijt" raakt
    # zodra een gebruiker hernoemd wordt, of dat twee gebruikers met dezelfde
    # naam door elkaar gehaald worden.
    machinist_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    stakeholder_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    categorie  = db.Column(db.String(5), default='C')
    rings      = db.Column(db.Text)    # JSON polygoon-rings

    def to_dict(self):
        mach_naam = self.machinist or '—'
        if self.machinist_id:
            u = db.session.get(User, self.machinist_id)
            if u:
                mach_naam = u.name or u.username
        stake_naam = self.stakeholder or '—'
        if self.stakeholder_id:
            u = db.session.get(User, self.stakeholder_id)
            if u:
                stake_naam = u.contract_name or u.name or u.username
        return {
            'id':            self.id,
            'naam':          self.naam,
            'loc':           self.loc or '',
            'lat':           self.lat or 0,
            'lng':           self.lng or 0,
            'hoogte':        self.hoogte or 0,
            'status':        self.status or 'OK',
            'prio':          self.prio or 'Laag',
            'machinistId':   self.machinist_id,
            'machinist':     mach_naam,
            'stakeholderId': self.stakeholder_id,
            'stakeholder':   stake_naam,
            'categorie':     self.categorie or 'C',
            'rings':         json.loads(self.rings) if self.rings else None,
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
    veld_id       = db.Column(db.Integer, db.ForeignKey('velden.id'), nullable=True)
    timestamp     = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':            self.id,
            'device_id':     self.device_id,
            'gras_hoogte_cm': self.gras_hoogte_cm,
            'latitude':      self.latitude,
            'longitude':     self.longitude,
            'veldId':        self.veld_id,
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


class MeldingDismiss(db.Model):
    """Onthoudt welke melding (per stabiele 'key') een gebruiker heeft weggeklikt,
       zodat weggeklikte meldingen niet steeds terugkomen."""
    __tablename__ = 'melding_dismiss'
    id        = db.Column(db.Integer, primary_key=True)
    user_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    key       = db.Column(db.String(150), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


# ── STARTUP ──

INITIELE_GEBRUIKERS = [
    {'username': 'admin',        'password': 'admin789',  'name': 'Beheerder',          'role': 'admin',       'initials': 'AD', 'label': 'Beheerder',    'assigned_velden': None,                         'contract_name': None,                'device_id': None},
    {'username': 'machinist1',   'password': 'groen123',  'name': 'Machinist 1',         'role': 'machinist',   'initials': 'M1', 'label': 'Machinist',    'assigned_velden': None,                         'contract_name': None,                'device_id': 'maaier_01'},
    {'username': 'machinist2',   'password': 'groen456',  'name': 'Machinist 2',         'role': 'machinist',   'initials': 'M2', 'label': 'Machinist',    'assigned_velden': None,                         'contract_name': None,                'device_id': None},
    {'username': 'stakeholder1', 'password': 'stake123',  'name': 'Gemeente Amsterdam',  'role': 'stakeholder', 'initials': 'GA', 'label': 'Stakeholder',  'assigned_velden': json.dumps([1,2,3,4,5,6,7]),  'contract_name': 'Gemeente Amsterdam', 'device_id': None},
    {'username': 'stakeholder2', 'password': 'stake456',  'name': 'Sportpark Noord',     'role': 'stakeholder', 'initials': 'SN', 'label': 'Stakeholder',  'assigned_velden': json.dumps([8,9,10,11,12,13]),'contract_name': 'Sportpark Noord BV', 'device_id': None},
]

def _kolom_toevoegen_indien_nodig(tabel, kolom, sql_type):
    """Lichte 'migratie': voegt een kolom toe aan een bestaande tabel als die nog
       ontbreekt. db.create_all() raakt bestaande tabellen namelijk niet aan,
       dus bij een upgrade van een oudere database moeten nieuwe kolommen
       (zoals machinist_id/stakeholder_id) hier alsnog worden toegevoegd."""
    insp = _sa_inspect(db.engine)
    if not insp.has_table(tabel):
        return
    bestaande_kolommen = [c['name'] for c in insp.get_columns(tabel)]
    if kolom not in bestaande_kolommen:
        with db.engine.begin() as conn:
            conn.execute(_sa_text(f'ALTER TABLE {tabel} ADD COLUMN {kolom} {sql_type}'))
        print(f"Migratie: kolom '{kolom}' toegevoegd aan tabel '{tabel}'.")


with app.app_context():
    db.create_all()
    _kolom_toevoegen_indien_nodig('velden', 'machinist_id', 'INTEGER')
    _kolom_toevoegen_indien_nodig('velden', 'stakeholder_id', 'INTEGER')
    _kolom_toevoegen_indien_nodig('users', 'device_id', 'VARCHAR(50)')
    _kolom_toevoegen_indien_nodig('users', 'actieve_veld_id', 'INTEGER')
    _kolom_toevoegen_indien_nodig('metingen', 'veld_id', 'INTEGER')

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
                device_id       = u.get('device_id'),
            ))
        db.session.commit()
        print("Gebruikers aangemaakt in database.")
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

    # Verwijder oude demo-shapefile als die er nog in zit
    npl = ShapeLayer.query.filter_by(naam='Noorderplantsoen').first()
    if npl:
        db.session.delete(npl)
        db.session.commit()
        print('Noorderplantsoen demo-shapefile verwijderd.')

    # Verwijder demo/OSM-velden (herkenbaar aan machinist='—')
    demo_velden = Veld.query.filter_by(machinist='—').all()
    if demo_velden:
        for v in demo_velden:
            db.session.delete(v)
        db.session.commit()
        print(f'{len(demo_velden)} demo-velden verwijderd.')

    # Migratie: koppel bestaande machinist/stakeholder naam-strings aan user-ID's.
    # Dit repareert oude toewijzingen die nog geen machinist_id/stakeholder_id
    # hebben (bv. velden die zijn aangemaakt voordat deze kolommen bestonden).
    alle_machinisten = User.query.filter_by(role='machinist').all()
    alle_stakeholders = User.query.filter_by(role='stakeholder').all()
    gekoppeld = 0
    for veld in Veld.query.all():
        if not veld.machinist_id and veld.machinist and veld.machinist != '—':
            match = next((u for u in alle_machinisten if (u.name or '').strip().lower() == veld.machinist.strip().lower()), None)
            if match:
                veld.machinist_id = match.id
                gekoppeld += 1
        if not veld.stakeholder_id and veld.stakeholder and veld.stakeholder != '—':
            match = next((u for u in alle_stakeholders if (u.contract_name or '').strip().lower() == veld.stakeholder.strip().lower()), None)
            if not match:
                match = next((u for u in alle_stakeholders if (u.name or '').strip().lower() == veld.stakeholder.strip().lower()), None)
            if match:
                veld.stakeholder_id = match.id
                gekoppeld += 1
    if gekoppeld:
        db.session.commit()
        print(f'Migratie: {gekoppeld} machinist/stakeholder-toewijzing(en) gekoppeld aan user-ID.')

    # Migratie: koppel de standaard device-ID's uit INITIELE_GEBRUIKERS aan bestaande
    # accounts die nog geen device_id hebben (voor databases die al bestonden
    # voordat dit veld werd toegevoegd).
    device_aangepast = 0
    for u in INITIELE_GEBRUIKERS:
        if not u.get('device_id'):
            continue
        db_user = User.query.filter_by(username=u['username']).first()
        if db_user and not db_user.device_id:
            db_user.device_id = u['device_id']
            device_aangepast += 1
    if device_aangepast:
        db.session.commit()
        print(f'Migratie: device-ID gekoppeld aan {device_aangepast} gebruiker(s).')

    # Verwijder alle verzonnen/nooit-gemeten demo-metingen. Deze zijn altijd herkenbaar
    # aan het device_id-voorvoegsel 'sensor-' (gebruikt door de oude demo-seed-functies),
    # wat nooit overeenkomt met een echt Pico-device (dat heet bv. 'maaier_01').
    # Dit is een eenmalige opschoning zodat grafieken alleen echte metingen tonen.
    nep_metingen = Meting.query.filter(Meting.device_id.like('sensor-%')).delete(synchronize_session=False)
    if nep_metingen:
        db.session.commit()
        print(f'{nep_metingen} verzonnen demo-meting(en) verwijderd.')


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
        'name': u.name, 'role': u.role, 'label': u.label,
        'contractName': u.contract_name,
        'deviceId': u.device_id,
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
        contract_name=data.get('contract_name'),
        device_id=(data.get('device_id') or '').strip() or None,
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
    if 'device_id' in data:
        user.device_id = (data['device_id'] or '').strip() or None
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

    # Maak velden los die nog aan deze gebruiker gekoppeld waren
    for veld in Veld.query.filter_by(machinist_id=user.id).all():
        veld.machinist_id = None
        veld.machinist = '—'
    for veld in Veld.query.filter_by(stakeholder_id=user.id).all():
        veld.stakeholder_id = None
        veld.stakeholder = '—'

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
        machinist_id   = data.get('machinist_id'),
        stakeholder_id = data.get('stakeholder_id'),
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
            machinist_id   = d.get('machinist_id'),
            stakeholder_id = d.get('stakeholder_id'),
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
    for attr in ('naam', 'loc', 'lat', 'lng', 'hoogte', 'status', 'prio', 'categorie'):
        if attr in data:
            setattr(veld, attr, data[attr])
    # Toewijzing op user-ID is de bron van waarheid. De legacy naam-string wordt
    # alleen nog meegeschreven als cache/fallback (bv. voor demo-herkenning).
    if 'machinist_id' in data:
        nieuwe_id = data['machinist_id'] or None
        veld.machinist_id = nieuwe_id
        if nieuwe_id:
            u = db.session.get(User, nieuwe_id)
            veld.machinist = (u.name or u.username) if u else '—'
        else:
            veld.machinist = '—'
    elif 'machinist' in data:
        # Oude clients die nog op naam toewijzen: zoek de bijbehorende user op
        # zodat machinist_id ook meteen klopt.
        veld.machinist = data['machinist']
        if data['machinist'] and data['machinist'] != '—':
            match = User.query.filter_by(role='machinist').filter(
                db.func.lower(User.name) == data['machinist'].strip().lower()
            ).first()
            veld.machinist_id = match.id if match else veld.machinist_id
        else:
            veld.machinist_id = None
    if 'stakeholder_id' in data:
        nieuwe_id = data['stakeholder_id'] or None
        veld.stakeholder_id = nieuwe_id
        if nieuwe_id:
            u = db.session.get(User, nieuwe_id)
            veld.stakeholder = (u.contract_name or u.name or u.username) if u else '—'
        else:
            veld.stakeholder = '—'
    elif 'stakeholder' in data:
        veld.stakeholder = data['stakeholder']
        if data['stakeholder'] and data['stakeholder'] != '—':
            match = User.query.filter_by(role='stakeholder').filter(
                db.func.lower(User.contract_name) == data['stakeholder'].strip().lower()
            ).first()
            if not match:
                match = User.query.filter_by(role='stakeholder').filter(
                    db.func.lower(User.name) == data['stakeholder'].strip().lower()
                ).first()
            veld.stakeholder_id = match.id if match else veld.stakeholder_id
        else:
            veld.stakeholder_id = None
    if 'rings' in data:
        veld.rings = json.dumps(data['rings']) if data['rings'] else None
    db.session.commit()
    return jsonify(veld.to_dict())


@app.route('/api/velden/all', methods=['DELETE'])
def delete_all_velden():
    me = User.query.get(session.get('user_id'))
    if not me or me.role != 'admin':
        return jsonify({'error': 'Geen toegang'}), 403
    aantal = Veld.query.count()
    Veld.query.delete()
    db.session.commit()
    return jsonify({'status': 'ok', 'verwijderd': aantal})


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


@app.route('/api/shapefiles/<int:laag_id>/naar-veld/<int:veld_id>', methods=['POST'])
def shapefile_naar_veldgrens(laag_id, veld_id):
    """Gebruik de polygoon van een geüploade shapefile-feature als de echte
       grens (rings) van een bestaand veld. Zo kan een ingeladen shapefile
       direct de veldgrenzen op de kaart leveren."""
    me = db.session.get(User, session.get('user_id'))
    if not me or me.role != 'admin':
        return jsonify({'error': 'Geen toegang'}), 403
    laag = db.session.get(ShapeLayer, laag_id)
    veld = db.session.get(Veld, veld_id)
    if not laag or not veld:
        return jsonify({'error': 'Niet gevonden'}), 404
    data = request.get_json() or {}
    feature_index = data.get('feature_index', 0)
    geojson = json.loads(laag.geojson) if laag.geojson else None
    if not geojson or not geojson.get('features'):
        return jsonify({'error': 'Deze shapefile bevat geen vormen'}), 400
    features = geojson['features']
    if feature_index < 0 or feature_index >= len(features):
        return jsonify({'error': 'Ongeldige feature-index'}), 400
    geometrie = features[feature_index].get('geometry') or {}
    rings = geometrie.get('coordinates')
    if geometrie.get('type') != 'Polygon' or not rings:
        return jsonify({'error': 'Alleen een polygoon-vorm kan als veldgrens gebruikt worden'}), 400
    veld.rings = json.dumps(rings)
    # Middelpunt van de buitenste ring herberekenen, zodat lat/lng bij de nieuwe vorm past
    buitenring = rings[0]
    if buitenring:
        veld.lng = sum(p[0] for p in buitenring) / len(buitenring)
        veld.lat = sum(p[1] for p in buitenring) / len(buitenring)
    db.session.commit()
    return jsonify(veld.to_dict())


# ── SENSOR ROUTE ──

@app.route('/data', methods=['POST'])
def ontvang_meting():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Geen JSON data"}), 400
    hoogte = data.get('gras_hoogte_cm')
    device = data.get('device_id') or 'onbekend'

    # Koppel de meting aan het veld waarvoor dit device momenteel actief aan het
    # meten is (gezet via /api/meting/start). Zo weten we precies bij welk veld
    # een meting hoort, in plaats van te gokken op basis van GPS-afstand.
    veld_id = None
    gebruiker = User.query.filter_by(device_id=device, role='machinist').first()
    if gebruiker and gebruiker.actieve_veld_id:
        veld_id = gebruiker.actieve_veld_id

    meting = Meting(
        device_id      = device,
        gras_hoogte_cm = hoogte,
        latitude       = data.get('latitude'),
        longitude      = data.get('longitude'),
        veld_id        = veld_id,
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


@app.route('/api/meting/start', methods=['POST'])
def start_meting():
    """Machinist start een meting voor één van zijn toegewezen velden.
       De Pico van deze machinist (gekoppeld via device_id) gaat hierna
       echt meten zodra hij /api/pico/status opvraagt."""
    me = db.session.get(User, session.get('user_id'))
    if not me or me.role != 'machinist':
        return jsonify({'error': 'Geen toegang'}), 403
    if not me.device_id:
        return jsonify({'error': 'Er is nog geen sensor (Pico) aan jouw account gekoppeld. Vraag de beheerder dit in te stellen bij Instellingen.'}), 400
    data = request.get_json() or {}
    veld = db.session.get(Veld, data.get('veld_id'))
    if not veld or veld.machinist_id != me.id:
        return jsonify({'error': 'Dit veld is niet aan jou toegewezen.'}), 403
    me.actieve_veld_id = veld.id
    db.session.add(ActivityLog(
        user=me.name or me.username,
        type='meting_start',
        message=f'Meting gestart voor veld "{veld.naam}"',
    ))
    db.session.commit()
    return jsonify({'status': 'ok', 'deviceId': me.device_id, 'veldId': veld.id})


@app.route('/api/meting/stop', methods=['POST'])
def stop_meting():
    me = db.session.get(User, session.get('user_id'))
    if not me or me.role != 'machinist':
        return jsonify({'error': 'Geen toegang'}), 403
    veld = db.session.get(Veld, me.actieve_veld_id) if me.actieve_veld_id else None
    me.actieve_veld_id = None
    db.session.add(ActivityLog(
        user=me.name or me.username,
        type='meting_stop',
        message='Meting gestopt' + (f' voor veld "{veld.naam}"' if veld else ''),
    ))
    db.session.commit()
    return jsonify({'status': 'ok'})


@app.route('/api/meting/status', methods=['GET'])
def meting_status():
    """Voor de machinist-dashboard: laat zien of er nu een meting actief is
       (bv. na een pagina-herlaad), zodat de knoppen meteen de juiste status tonen."""
    me = db.session.get(User, session.get('user_id'))
    if not me or me.role != 'machinist':
        return jsonify({'error': 'Geen toegang'}), 403
    return jsonify({
        'actief':   bool(me.actieve_veld_id),
        'veldId':   me.actieve_veld_id,
        'deviceId': me.device_id,
    })


@app.route('/api/pico/status', methods=['GET'])
def pico_status():
    """Wordt zonder login opgevraagd door de Pico zelf (over wifi), op basis van
       zijn eigen device_id. Geeft aan of hij nu moet meten en voor welk veld."""
    device_id = request.args.get('device_id', '')
    gebruiker = User.query.filter_by(device_id=device_id, role='machinist').first()
    if not gebruiker or not gebruiker.actieve_veld_id:
        return jsonify({'actief': False})
    return jsonify({'actief': True, 'veld_id': gebruiker.actieve_veld_id})


@app.route('/api/activiteiten', methods=['GET'])
def get_activiteiten():
    if not session.get('user_id'):
        return jsonify({'error': 'Niet ingelogd'}), 401
    limit = min(int(request.args.get('limit', 50)), 200)
    items = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(limit).all()
    return jsonify([a.to_dict() for a in items])


@app.route('/api/metingen', methods=['GET'])
def get_metingen():
    if not session.get('user_id'):
        return jsonify({'error': 'Niet ingelogd'}), 401
    q = Meting.query
    veld_id = request.args.get('veld_id', type=int)
    device_id = request.args.get('device_id')
    if veld_id is not None:
        q = q.filter(Meting.veld_id == veld_id)
    if device_id:
        q = q.filter(Meting.device_id == device_id)
    metingen = q.order_by(Meting.timestamp.desc()).all()
    return jsonify([m.to_dict() for m in metingen])


@app.route('/api/meldingen/dismissed', methods=['GET'])
def get_dismissed_meldingen():
    if not session.get('user_id'):
        return jsonify({'error': 'Niet ingelogd'}), 401
    items = MeldingDismiss.query.filter_by(user_id=session['user_id']).all()
    return jsonify([m.key for m in items])


@app.route('/api/meldingen/dismiss', methods=['POST'])
def dismiss_melding():
    if not session.get('user_id'):
        return jsonify({'error': 'Niet ingelogd'}), 401
    data = request.get_json() or {}
    key = (data.get('key') or '').strip()
    if not key:
        return jsonify({'error': 'key is verplicht'}), 400
    bestaat = MeldingDismiss.query.filter_by(user_id=session['user_id'], key=key).first()
    if not bestaat:
        db.session.add(MeldingDismiss(user_id=session['user_id'], key=key))
        db.session.commit()
    return jsonify({'status': 'ok'})


# ── STATIC FILES ──

# Rol-specifieke HTML bestanden die alleen via beschermde routes mogen worden geserved
_PROTECTED_ROLE_FILES = {'admin.html', 'machinist.html', 'stakeholder.html'}


@app.route('/')
def index():
    return send_from_directory(DIST_DIR, 'index.html')


@app.route('/dashboard')
def dashboard_redirect():
    user_id = session.get('user_id')
    if not user_id:
        return redirect('/')
    user = User.query.get(user_id)
    if not user:
        return redirect('/')
    return redirect('/' + user.role)


@app.route('/admin')
def serve_admin():
    user_id = session.get('user_id')
    if not user_id:
        return redirect('/')
    user = User.query.get(user_id)
    if not user or user.role != 'admin':
        return redirect('/')
    return send_from_directory(DIST_DIR, 'admin.html')


@app.route('/machinist')
def serve_machinist():
    user_id = session.get('user_id')
    if not user_id:
        return redirect('/')
    user = User.query.get(user_id)
    if not user or user.role != 'machinist':
        return redirect('/')
    return send_from_directory(DIST_DIR, 'machinist.html')


@app.route('/stakeholder')
def serve_stakeholder():
    user_id = session.get('user_id')
    if not user_id:
        return redirect('/')
    user = User.query.get(user_id)
    if not user or user.role != 'stakeholder':
        return redirect('/')
    return send_from_directory(DIST_DIR, 'stakeholder.html')


@app.route('/<path:path>')
def serve_file(path):
    # Blokkeer API routes
    if path.startswith('api/'):
        return jsonify({'error': 'Not found'}), 404
    # Blokkeer directe toegang tot rol-specifieke HTML bestanden
    if path in _PROTECTED_ROLE_FILES:
        return redirect('/')
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
