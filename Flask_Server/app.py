import os
from flask import Flask, render_template
from extensions import db
from models import Meting
from routes import routes

def create_app():
    app = Flask(__name__)

    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'data.sqlite')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    # Blueprint (routes) registreren
    app.register_blueprint(routes)

    # 5. Database tabellen aanmaken
    with app.app_context():
        db.create_all()

    return app

# Start de server alleen als dit bestand direct wordt uitgevoerd
if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)

