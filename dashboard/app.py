from flask import Flask, send_from_directory
import os

app = Flask(__name__, static_folder='dist', static_url_path='')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(BASE_DIR, 'dist')


@app.route('/')
def index():
    return send_from_directory(DIST_DIR, 'index.html')


@app.route('/<path:path>')
def serve_file(path):
    full_path = os.path.join(DIST_DIR, path)

    # Als het bestand bestaat, stuur het op
    if os.path.isfile(full_path):
        return send_from_directory(DIST_DIR, path)

    # Als het een map is, zoek naar index.html erin
    if os.path.isdir(full_path):
        index_path = os.path.join(full_path, 'index.html')
        if os.path.isfile(index_path):
            return send_from_directory(full_path, 'index.html')

    # Terugval: stuur de hoofdpagina
    return send_from_directory(DIST_DIR, 'index.html'), 404


if __name__ == '__main__':
    print("=" * 40)
    print("  Van der Werf IoT Dashboard")
    print("  http://localhost:5000")
    print("  Ctrl+C om te stoppen")
    print("=" * 40)
    app.run(debug=True, host='0.0.0.0', port=5000)
