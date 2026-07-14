import streamlit as st
import pandas as pd
import datetime
import hashlib
import secrets
import traceback
from sqlalchemy import create_engine, text

# 1. Konfiguration
st.set_page_config(page_title="TuB Orga", page_icon="🏐", layout="wide")

# ==========================================
# DATENBANK-FUNKTIONEN
# ==========================================

def update_db_schema(engine):
    """Initialisiert Tabellen in PostgreSQL."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                user_id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                rolle TEXT NOT NULL,
                dsgvo_akzeptiert INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS teams (
                team_id SERIAL PRIMARY KEY,
                team_name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id SERIAL PRIMARY KEY,
                team_id INTEGER REFERENCES teams(team_id),
                datum_zeit TEXT,
                ort TEXT,
                event_typ TEXT
            );
            CREATE TABLE IF NOT EXISTS tasks (
                task_id SERIAL PRIMARY KEY,
                event_id INTEGER REFERENCES events(event_id),
                kategorie TEXT,
                beschreibung TEXT,
                punkte_wert INTEGER,
                zugewiesen_an INTEGER REFERENCES users(user_id),
                tausch_angefragt INTEGER DEFAULT 0
            );
        """))

# 2. Verbindung aufbauen
try:
    DB_URL = st.secrets["DB_URL"]
    # Option 'gssencmode' und explizite timeouts helfen oft bei "Cannot assign requested address"
    engine = create_engine(
        DB_URL, 
        connect_args={"sslmode": "require", "connect_timeout": 10}
    )
    update_db_schema(engine)
except Exception as e:
    st.error(f"Datenbankfehler: {e}")
    st.text(traceback.format_exc())
    st.stop()

# ==========================================
# HILFSFUNKTIONEN (Passwort)
# ==========================================

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"{salt}${hash_obj.hex()}"

def verify_password(password: str, hashed_password: str) -> bool:
    if "$" not in hashed_password: return password == hashed_password
    salt, hash_hex = hashed_password.split('$')
    hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return hash_obj.hex() == hash_hex

# ==========================================
# LOGIN & AUTHENTIFIZIERUNG
# ==========================================

def authenticate(email, password):
    with engine.connect() as conn:
        query = text("SELECT * FROM users WHERE email = :email")
        result = conn.execute(query, {"email": email}).fetchone()
        if result and verify_password(password, result.password_hash):
            return dict(result._mapping)
    return None

# ==========================================
# LOGIK-FUNKTIONEN
# ==========================================

def get_all_tasks():
    return pd.read_sql("SELECT * FROM tasks", engine)

# ==========================================
# MAIN UI
# ==========================================

st.title("🏐 TuB Helfer-Orga (Cloud-Version)")

if 'logged_in_user' not in st.session_state:
    st.session_state['logged_in_user'] = None

if st.session_state['logged_in_user'] is None:
    with st.form("login_form"):
        email = st.text_input("E-Mail")
        password = st.text_input("Passwort", type="password")
        if st.form_submit_button("Einloggen"):
            user = authenticate(email, password)
            if user:
                st.session_state['logged_in_user'] = user
                st.rerun()
            else:
                st.error("Zugangsdaten ungültig.")
else:
    user = st.session_state['logged_in_user']
    st.write(f"Willkommen zurück, {user['name']}!")
    if st.button("Ausloggen"):
        st.session_state['logged_in_user'] = None
        st.rerun()

    # Beispiel für Datenanzeige
    tasks = get_all_tasks()
    st.dataframe(tasks)
