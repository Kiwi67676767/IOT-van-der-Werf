import os
from flask import Flask
from extensions import db, socketio
from routes import routes

def create_app():
    app = Flask(__name__)

    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'data.sqlite')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    socketio.init_app(app, cors_allowed_origins="*")

    app.register_blueprint(routes)

    with app.app_context():
        db.create_all()

    return app

if __name__ == "__main__":
    app = create_app()
    socketio.run(app, debug=True, host='127.0.0.1', port=5000)
