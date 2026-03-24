from app import db, Meting, app

# Maak database bestand en tabellen aan (moet binnen de app context)
with app.app_context():
    db.create_all()  # Maak de tabellen aan in de database

    # nieuwe_meting = Meting(hoogte=5.3) # Maak objecten aan
    #db.session.add(nieuwe_meting)
    db.session.commit() 

    # # Controleer of de meting succesvol is toegevoegd
    # print(nieuwe_meting)