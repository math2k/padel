import json
import smtplib
import logging
from email.mime.text import MIMEText
from datetime import datetime
from pathlib import Path
from app import get_available_slots, process_slots, TimeSlot, COURT_NAMES

# --- CONFIGURATION EMAIL (SERVEUR LOCAL) ---
SMTP_SERVER = "localhost"
SMTP_PORT = 25
# L'adresse d'expédition (doit souvent correspondre au domaine du serveur pour éviter le spam)
FROM_EMAIL = "no-reply@padel.math2k.net" 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# Chemin vers le fichier d'abonnements
SUBSCRIPTIONS_FILE = Path('/var/www/vhosts/padel.math2k.net/data/subscriptions.json')

def send_notification(email, slots, date_str):
    subject = f"🎾 Terrain disponible le {date_str} !"
    body = f"Bonne nouvelle ! Des terrains sont disponibles pour le {date_str} :\n\n"
    
    for slot in slots:
        body += f"- {slot.court_name} à {slot.starts_at} ({slot.duration} min)\n"
    
    body += "\nRéservez vite sur : https://app.arenal.be/club/3"

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = FROM_EMAIL
    msg['To'] = email

    try:
        # Connexion au serveur local (généralement sans authentification depuis localhost)
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.send_message(msg)
        logging.info(f"Email envoyé à {email}")
        return True
    except Exception as e:
        logging.error(f"Erreur envoi email: {e}")
        return False

def check_subscriptions():
    # Vérification de l'existence du fichier
    if not SUBSCRIPTIONS_FILE.exists():
        logging.info("Aucun abonnement trouvé.")
        return

    try:
        with SUBSCRIPTIONS_FILE.open('r') as f:
            subs = json.load(f)
    except json.JSONDecodeError:
        logging.error("Erreur de décodage du fichier abonnements.")
        return
    
    if not subs:
        return

    active_subs = []
    
    # Grouper les vérifications par date pour limiter les appels API
    dates_to_check = set(s['date'] for s in subs)
    slots_cache = {} 

    for date_str in dates_to_check:
        # Ignorer les dates passées
        if datetime.strptime(date_str, '%Y-%m-%d').date() < datetime.now().date():
            continue
            
        slots_raw = get_available_slots(date_str)
        slots_cache[date_str] = process_slots(slots_raw)

    for sub in subs:
        date_str = sub['date']
        
        # Nettoyage des dates passées
        if datetime.strptime(date_str, '%Y-%m-%d').date() < datetime.now().date():
            continue

        available = slots_cache.get(date_str, [])
        
        # Filtres utilisateur
        min_time_obj = datetime.strptime(sub['min_time'], '%H:%M').time()
        
        matching_slots = [
            slot for slot in available
            if datetime.strptime(slot.starts_at, '%H:%M').time() >= min_time_obj
            and slot.duration >= sub['min_duration']
        ]

        if matching_slots:
            logging.info(f"Match trouvé pour {sub['email']} le {date_str}")
            sent = send_notification(sub['email'], matching_slots, date_str)
            if sent:
                # Suppression de l'abonnement après notification réussie
                continue 
        
        # On conserve l'abonnement s'il n'a pas été notifié
        active_subs.append(sub)

    # Mise à jour du fichier JSON
    with SUBSCRIPTIONS_FILE.open('w') as f:
        json.dump(active_subs, f, indent=4)

if __name__ == "__main__":
    check_subscriptions()
