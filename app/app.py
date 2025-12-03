import requests
import sqlite3
from datetime import datetime, date
from typing import Dict, List, Set
import pytz
from dataclasses import dataclass
import logging
from pathlib import Path
# Ajout de redirect et url_for aux imports
from flask import Flask, render_template, request, redirect, url_for

# --- Initialisation de l'application Flask ---
app = Flask(__name__)

# --- Configuration Chemins & DB ---
DATA_DIR = Path('/var/www/vhosts/padel.math2k.net/padel/data')
DB_PATH = DATA_DIR / 'padel.db'

# --- Classes et Fonctions Métier ---
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

# --- GESTION BASE DE DONNEES (SQLite) ---

def get_db_connection():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    try:
        with get_db_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL,
                    target_date TEXT NOT NULL,
                    min_time TEXT NOT NULL,
                    min_duration INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    notified INTEGER DEFAULT 0
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS known_slots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    booking_date TEXT NOT NULL,
                    court_id INTEGER NOT NULL,
                    court_name TEXT NOT NULL,
                    starts_at TEXT NOT NULL,
                    duration INTEGER NOT NULL
                )
            ''')
            
            conn.execute('CREATE INDEX IF NOT EXISTS idx_slots_date ON known_slots(booking_date)')
            conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_sub ON subscriptions(email, target_date, min_time, min_duration)')
            
    except Exception as e:
        logging.error(f"Erreur initialisation DB: {e}")

def get_stored_slots(date_str: str) -> Set[TimeSlot]:
    with get_db_connection() as conn:
        rows = conn.execute('SELECT * FROM known_slots WHERE booking_date = ?', (date_str,)).fetchall()
        return {
            TimeSlot(
                court_name=row['court_name'],
                starts_at=row['starts_at'],
                duration=row['duration'],
                court_id=row['court_id']
            ) for row in rows
        }

def save_slots_snapshot(slots: Set[TimeSlot], date_str: str):
    with get_db_connection() as conn:
        conn.execute('DELETE FROM known_slots WHERE booking_date = ?', (date_str,))
        if slots:
            data = [
                (date_str, s.court_id, s.court_name, s.starts_at, s.duration)
                for s in slots
            ]
            conn.executemany('''
                INSERT INTO known_slots (booking_date, court_id, court_name, starts_at, duration)
                VALUES (?, ?, ?, ?, ?)
            ''', data)
        conn.commit()

def add_subscription(data: Dict):
    with get_db_connection() as conn:
        conn.execute('''
            INSERT INTO subscriptions (email, target_date, min_time, min_duration, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (data['email'], data['date'], data['min_time'], data['min_duration'], data['created_at']))
        conn.commit()

# --- Initialisation au chargement ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
init_db()

# --- Routes Flask ---
@app.route('/', methods=['GET'])
def index():
    check_date_str = date.today().strftime('%Y-%m-%d')
    min_time_str = '20:00'
    min_duration_str = '90'
    display_date = ""
    
    slots_by_time = {}
    newly_found_slots = set()
    
    # Récupération des messages passés en paramètres GET (suite au redirect)
    error_message = request.args.get('error')
    success_message = request.args.get('success_message')
    
    if 'date' in request.args:
        check_date_str = request.args.get('date', check_date_str)
        min_time_str = request.args.get('min_time', min_time_str)
        min_duration_str = request.args.get('min_duration', min_duration_str)
        check_date_obj = datetime.strptime(check_date_str, '%Y-%m-%d').date()
        display_date = check_date_obj.strftime('%A %d %B %Y')
        
        try:
            min_duration = int(min_duration_str)
            min_time_obj = datetime.strptime(min_time_str, '%H:%M').time()

            previous_slots = get_stored_slots(check_date_str)
            available_slots_raw = get_available_slots(check_date_str)
            all_slots = process_slots(available_slots_raw)

            filtered_slots = [
                slot for slot in all_slots
                if datetime.strptime(slot.starts_at, '%H:%M').time() >= min_time_obj
                and slot.duration >= min_duration
            ]
            
            current_slots_set = set(filtered_slots)
            newly_found_slots = current_slots_set - previous_slots
            
            save_slots_snapshot(current_slots_set, check_date_str)

            for slot in sorted(filtered_slots, key=lambda s: (s.starts_at, s.court_name)):
                slots_by_time.setdefault(slot.starts_at, []).append(slot)
        
        except ValueError:
            error_message = "Veuillez entrer une durée valide."
        except Exception as e:
            error_message = f"Une erreur est survenue: {e}"
            logging.error(f"Error in GET: {e}")

    return render_template('index.html', 
                           check_date=check_date_str, 
                           min_time=min_time_str,
                           min_duration=min_duration_str,
                           slots_by_time=slots_by_time,
                           newly_found_slots=newly_found_slots,
                           error=error_message,
                           success_message=success_message, # On passe le message à la vue
                           searched=('date' in request.args),
                           display_date=display_date)

@app.route('/subscribe', methods=['POST'])
def subscribe():
    email = request.form.get('email')
    date_req = request.form.get('date')
    min_time = request.form.get('min_time')
    min_duration = request.form.get('min_duration')
    
    if email and date_req:
        try:
            sub_data = {
                "email": email,
                "date": date_req,
                "min_time": min_time,
                "min_duration": int(min_duration),
                "created_at": datetime.now().isoformat()
            }
            add_subscription(sub_data)
            
            # REDIRECTION avec message de succès
            return redirect(url_for('index', 
                                    success_message="Alerte enregistrée !",
                                    date=date_req, 
                                    min_time=min_time, 
                                    min_duration=min_duration))
                                    
        except sqlite3.IntegrityError:
            # REDIRECTION avec message d'erreur (doublon)
            return redirect(url_for('index', 
                                    error="Vous avez déjà une alerte active pour cette date et ces critères.",
                                    date=date_req, 
                                    min_time=min_time, 
                                    min_duration=min_duration))
        except Exception as e:
            logging.error(f"Erreur inscription DB: {e}")
            return redirect(url_for('index', error="Erreur technique lors de l'enregistrement."))
    
    return redirect(url_for('index', error="Champs manquants."))

if __name__ == "__main__":
    app.run(debug=True)
