import requests
import json
from datetime import datetime, date
import smtplib
from email.mime.text import MIMEText
from typing import Dict, List, Set
import pytz
from dataclasses import dataclass
import logging
import sys
from pathlib import Path
from flask import Flask, render_template, request

# --- Initialisation de l'application Flask ---
app = Flask(__name__)

# --- Classes et Fonctions (logique du script original) ---
@dataclass
class TimeSlot:
    court_name: str
    starts_at: str
    duration: int
    court_id: int

    def __hash__(self):
        return hash((self.court_id, self.starts_at, self.duration))

    def to_dict(self):
        return {
            'court_name': self.court_name,
            'starts_at': self.starts_at,
            'duration': self.duration,
            'court_id': self.court_id
        }

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

COURT_NAMES = {
    18: {"name": "0 | CUPRA (Grimbergen)", "indoor": True}, 19: {"name": "1 | ACT Sports (Grimbergen)", "indoor": True},
    20: {"name": "2 | Vandelanotte (Grimbergen)", "indoor": True}, 21: {"name": "3 | JP TRUCKS (Grimbergen)", "indoor": True},
    22: {"name": "4 | Dalia Products (Grimbergen)", "indoor": True}, 23: {"name": "5 | RealDev (Grimbergen)", "indoor": True},
    24: {"name": "6 | Padel (Grimbergen)", "indoor": False}, 70: {"name": "1 | ACT Sports (Meise)", "indoor": True},
    71: {"name": "2 | CUPRA (Meise)", "indoor": True}, 72: {"name": "3 | Vandelanotte (Meise)", "indoor": True},
    73: {"name": "4 | Padel (Meise)", "indoor": True}, 74: {"name": "5 | Padel (Meise)", "indoor": True},
    75: {"name": "6 | Padel (Meise)", "indoor": False}, 76: {"name": "7 | Padel (Meise)", "indoor": False},
    77: {"name": "8 | Padel (Meise)", "indoor": False}
}

def setup_headers() -> Dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
        "Referer": "https://app.arenal.be/club/3", "Accept": "application/json, text/plain, */*", "accept-language": "en",
        "cache-control": "no-cache", "pragma": "no-cache", "priority": "u=1, i", "sec-ch-ua": "\"Chromium\";v=\"128\", \"Not;A=Brand\";v=\"24\", \"Google Chrome\";v=\"128\"",
        "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": "\"macOS\"", "sec-fetch-dest": "empty", "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site", "x-api-version": "1.2.0", "x-timezone": "Europe/Brussels", "referrer": "https://app.arenal.be/",
        "referrerPolicy": "strict-origin-when-cross-origin"
    }

def get_available_slots(check_date: str) -> List[Dict]:
    logging.info(f"Fetching available slots for {check_date}")
    url = f"https://api.arenal.be/api/bookable-clubs?date={check_date}&ids=3,5&sport=padel"
    try:
        response = requests.get(url, headers=setup_headers())
        response.raise_for_status()
        data = response.json()
        if not data.get('data') or not data['data'][0].get('timeslots'):
            logging.info("No timeslots found in response")
            return []
        all_timeslots = data['data'][0]['timeslots']
        if len(data['data']) > 1:
            all_timeslots += data['data'][1]['timeslots']
        return all_timeslots
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching data: {e}")
        return []

def process_slots(slots: List[Dict]) -> List[TimeSlot]:
    brussels_tz = pytz.timezone('Europe/Brussels')
    processed_slots = []
    for slot in slots:
        court_info = COURT_NAMES.get(slot['court_id'])
        if not court_info or not court_info['indoor']:
            continue
        starts_at = datetime.fromisoformat(slot['starts_at'].replace('Z', '+00:00'))
        starts_at_local = starts_at.astimezone(brussels_tz)
        duration = (datetime.fromisoformat(slot['ends_at'].replace('Z', '+00:00')) -
                    datetime.fromisoformat(slot['starts_at'].replace('Z', '+00:00'))).total_seconds() / 60
        processed_slots.append(TimeSlot(
            court_name=court_info['name'],
            starts_at=starts_at_local.strftime('%H:%M'),
            duration=int(duration),
            court_id=slot['court_id']
        ))
    return sorted(processed_slots, key=lambda x: (x.starts_at, x.court_id))

def load_previous_slots(state_file: Path) -> Set[TimeSlot]:
    if not state_file.exists():
        return set()
    try:
        with state_file.open('r') as f:
            data = json.load(f)
            return {TimeSlot.from_dict(slot_data) for slot_data in data}
    except (json.JSONDecodeError, TypeError) as e:
        logging.error(f"Error loading or parsing state file: {e}")
        return set()

def save_current_slots(slots: Set[TimeSlot], state_file: Path):
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        with state_file.open('w') as f:
            json.dump([slot.to_dict() for slot in slots], f, indent=4)
    except IOError as e:
        logging.error(f"Error saving state file: {e}")

# --- Configuration et Routes Flask ---
state_dir = Path('/var/www/vhosts/padel.math2k.net//data')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Nouvelle gestion des abonnements ---
SUBSCRIPTIONS_FILE = state_dir / "subscriptions.json"

def load_subscriptions() -> List[Dict]:
    if not SUBSCRIPTIONS_FILE.exists():
        return []
    try:
        with SUBSCRIPTIONS_FILE.open('r') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Erreur lecture abonnements: {e}")
        return []

def save_subscription(data: Dict):
    subs = load_subscriptions()
    subs.append(data)
    SUBSCRIPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SUBSCRIPTIONS_FILE.open('w') as f:
        json.dump(subs, f, indent=4)

@app.route('/', methods=['GET'])
def index():
    # Définir les valeurs par défaut
    check_date_str = date.today().strftime('%Y-%m-%d')
    min_time_str = '20:00'
    min_duration_str = '90'
    display_date = ""
    
    slots_by_time = {}
    newly_found_slots = set()
    error_message = None
    
    # Vérifier si des arguments sont dans l'URL (signifie que le formulaire a été soumis)
    if 'date' in request.args:
        check_date_str = request.args.get('date', check_date_str)
        min_time_str = request.args.get('min_time', min_time_str)
        min_duration_str = request.args.get('min_duration', min_duration_str)
        check_date_obj = datetime.strptime(check_date_str, '%Y-%m-%d').date()
        display_date = check_date_obj.strftime('%A %d %B %Y')
        
        try:
            min_duration = int(min_duration_str)
            min_time_obj = datetime.strptime(min_time_str, '%H:%M').time()
            state_file = state_dir / f"slots_{check_date_str}.json"

            previous_slots = load_previous_slots(state_file)
            available_slots_raw = get_available_slots(check_date_str)
            all_slots = process_slots(available_slots_raw)

            filtered_slots = [
                slot for slot in all_slots
                if datetime.strptime(slot.starts_at, '%H:%M').time() >= min_time_obj
                and slot.duration >= min_duration
            ]
            
            current_slots_set = set(filtered_slots)
            newly_found_slots = current_slots_set - previous_slots
            
            save_current_slots(current_slots_set, state_file)

            for slot in sorted(filtered_slots, key=lambda s: (s.starts_at, s.court_name)):
                slots_by_time.setdefault(slot.starts_at, []).append(slot)
        
        except ValueError:
            error_message = "Veuillez entrer une durée valide (nombre entier)."
        except Exception as e:
            error_message = f"Une erreur est survenue: {e}"
            logging.error(f"An error occurred in GET request: {e}")

    return render_template('index.html', 
                           check_date=check_date_str, 
                           min_time=min_time_str,
                           min_duration=min_duration_str,
                           slots_by_time=slots_by_time,
                           newly_found_slots=newly_found_slots,
                           error=error_message,
                           searched=('date' in request.args),
                           display_date = display_date)

@app.route('/subscribe', methods=['POST'])
def subscribe():
    email = request.form.get('email')
    date_req = request.form.get('date')
    min_time = request.form.get('min_time')
    min_duration = request.form.get('min_duration')
    
    if email and date_req:
        sub_data = {
            "email": email,
            "date": date_req,
            "min_time": min_time,
            "min_duration": int(min_duration),
            "created_at": datetime.now().isoformat()
        }
        save_subscription(sub_data)
        # On retourne la template avec un message de succès
        return render_template('index.html', 
                               success_message="Alerte enregistrée ! Vous recevrez un email si un terrain se libère.",
                               check_date=date_req, 
                               min_time=min_time, 
                               min_duration=min_duration,
                               searched=False) # On ne relance pas la recherche visuelle
    
    return render_template('index.html', error="Email et date requis pour l'alerte.")

if __name__ == "__main__":
    app.run(debug=True)
