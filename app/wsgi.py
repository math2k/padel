import sys
import logging
import locale

locales_to_try = ['fr_FR.utf8']
locale_set = False
for loc in locales_to_try:
    try:
        locale.setlocale(locale.LC_TIME, loc)
        locale_set = True
        break  # Sort de la boucle si la locale est définie avec succès
    except locale.Error:
        continue # Essaie la locale suivante

# Configuration du logging pour le débogage
logging.basicConfig(stream=sys.stderr)

# Ajoute le chemin du projet au path Python
sys.path.insert(0, '/var/www/vhosts/padel.math2k.net/app')
sys.path.append('/var/www/vhosts/padel.math2k.net/venv/lib/python3.10/site-packages')

# Importe l'objet 'app' depuis votre fichier app.py
from app import app as application
