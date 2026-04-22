from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user
from .models import User
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