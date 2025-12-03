import smtplib
import logging
import sqlite3
from email.mime.text import MIMEText
from datetime import datetime, date
# Import depuis app.py (plus de fonctions de log notifications)
from app import (
    get_available_slots, process_slots, get_db_connection, 
    get_stored_slots, save_slots_snapshot, TimeSlot
)

# --- CONFIGURATION EMAIL ---
SMTP_SERVER = "localhost"
SMTP_PORT = 25
FROM_EMAIL = "padel-monitor@4lunch.eu"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def send_notification(email, new_slots, date_str):
    subject = f"🎾 Nouveaux terrains dispo le {date_str} !"
    body = f"De nouveaux terrains viennent de se libérer pour le {date_str} :\n\n"
    for slot in new_slots:
        body += f"- {slot.court_name} à {slot.starts_at} ({slot.duration} min)\n"
    
    body += "\nRéservez vite sur : https://app.arenal.be/club/3"
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = FROM_EMAIL
    msg['To'] = email

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.send_message(msg)
        logging.info(f"Email envoyé à {email}")
        return True
    except Exception as e:
        logging.error(f"Erreur envoi email à {email}: {e}")
        return False

def check_subscriptions():
    conn = get_db_connection()
    try:
        # 1. Nettoyage des abonnements expirés
        today_str = date.today().strftime('%Y-%m-%d')
        conn.execute("DELETE FROM subscriptions WHERE target_date < ?", (today_str,))
        conn.commit()

        # 2. Récupérer les abonnements
        subs = conn.execute("SELECT * FROM subscriptions").fetchall()
        if not subs:
            logging.info("Aucun abonnement actif.")
            return

        dates_to_check = set(row['target_date'] for row in subs)

        for date_str in dates_to_check:
            # A. Charger l'état "connu"
            previous_slots = get_stored_slots(date_str)
            
            # B. Récupérer l'état actuel (Live)
            slots_raw = get_available_slots(date_str)
            current_slots_list = process_slots(slots_raw)
            current_slots_set = set(current_slots_list)
            
            # C. Détecter les NOUVEAUX créneaux
            newly_found_slots = current_slots_set - previous_slots
            
            # S'il n'y a rien de nouveau, on met à jour le snapshot (si des créneaux ont disparu) et on passe
            if not newly_found_slots:
                if current_slots_set != previous_slots:
                     save_slots_snapshot(current_slots_set, date_str)
                continue

            logging.info(f"Date {date_str}: {len(newly_found_slots)} nouveaux slots détectés.")

            # D. Notifier les abonnés
            relevant_subs = [s for s in subs if s['target_date'] == date_str]
            
            for sub in relevant_subs:
                min_time_obj = datetime.strptime(sub['min_time'], '%H:%M').time()
                
                # Filtrer par critères utilisateur
                matching_slots = [
                    s for s in newly_found_slots
                    if datetime.strptime(s.starts_at, '%H:%M').time() >= min_time_obj
                    and s.duration >= sub['min_duration']
                ]
                
                if matching_slots:
                    matching_slots.sort(key=lambda x: x.starts_at)
                    send_notification(sub['email'], matching_slots, date_str)

            # E. Mise à jour de l'état global APRES les notifications
            # On considère que si on a détecté des nouveaux slots et essayé de notifier,
            # on ne doit plus les considérer comme "nouveaux" au prochain tour.
            save_slots_snapshot(current_slots_set, date_str)
        
    except Exception as e:
        logging.error(f"Erreur monitoring: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    check_subscriptions()
