import streamlit as st
import pandas as pd
import datetime
import hashlib
import secrets
import uuid
from sqlalchemy import create_engine, text

# Paket für Cookies: Muss in requirements.txt stehen!
try:
    from streamlit_cookies_manager import EncryptedCookieManager
except ImportError:
    st.error("📦 **Fehlendes Paket!** Bitte füge `streamlit-cookies-manager` zu deiner `requirements.txt` auf GitHub hinzu.")
    st.stop()

# ==========================================
# 1. KONFIGURATION & DATENBANK
# ==========================================
st.set_page_config(page_title="TuB Orga", page_icon="🏐", layout="wide")

try:
    DB_URL = st.secrets["DB_URL"]
    engine = create_engine(DB_URL, connect_args={"sslmode": "require", "connect_timeout": 15}, pool_pre_ping=True)
except Exception as e:
    st.error(f"Datenbankfehler: {e}")
    st.stop()

cookies = EncryptedCookieManager(prefix="tub_orga", password=DB_URL)
if not cookies.ready(): st.stop()

# ==========================================
# 2. DB-SCHEMA & MIGRATION
# ==========================================
def update_db_schema():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                user_id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, rolle TEXT NOT NULL, team TEXT
            );
            CREATE TABLE IF NOT EXISTS parent_child (
                parent_id INTEGER REFERENCES users(user_id),
                child_id INTEGER REFERENCES users(user_id),
                PRIMARY KEY (parent_id, child_id)
            );
            CREATE TABLE IF NOT EXISTS tasks (
                task_id SERIAL PRIMARY KEY, kategorie TEXT, beschreibung TEXT,
                start_zeit TEXT, ende_zeit TEXT, betroffene_teams TEXT,
                erstellt_von INTEGER REFERENCES users(user_id),
                max_helfer INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS task_assignments (
                assignment_id SERIAL PRIMARY KEY,
                task_id INTEGER REFERENCES tasks(task_id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(user_id)
            );
        """))
        # Sicherstellen, dass Spalten existieren
        try:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS max_helfer INTEGER DEFAULT 1"))
            conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS erstellt_von INTEGER"))
        except Exception: pass

update_db_schema()

# ==========================================
# 3. FUNKTIONEN
# ==========================================
def verify_password(password, hashed):
    salt, hash_hex = hashed.split('$')
    hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return hash_obj.hex() == hash_hex

# ==========================================
# 4. UI LOGIK
# ==========================================
st.title("🏐 TuB Helfer-Orga")
TEAM_LISTE = ["U12", "U13", "U14", "U16", "U18", "U20", "Herren 1", "Herren 2", "Herren 3", "Herren 4"]

if 'logged_in_user' not in st.session_state:
    sid = cookies.get("logged_in_user_id")
    if sid:
        with engine.connect() as conn:
            user = conn.execute(text("SELECT * FROM users WHERE user_id=:id"), {"id": int(sid)}).fetchone()
            st.session_state['logged_in_user'] = dict(user._mapping) if user else None
    else:
        st.session_state['logged_in_user'] = None

if st.session_state['logged_in_user'] is None:
    # ... (Login/Registrierung Logik hier belassen)
    st.info("Bitte einloggen.")
else:
    user = st.session_state['logged_in_user']
    tab1, tab2 = st.tabs(["📋 Aufgaben", "👥 Admin"])
    
    with tab1:
        tasks = pd.read_sql(text("SELECT * FROM tasks"), engine)
        for _, row in tasks.iterrows():
            # Hier explizit auf 'max_helfer' zugreifen
            max_h = row.get('max_helfer', 1) 
            st.write(f"**{row['kategorie']}**")
            st.write(f"Helfer: [Abfrage läuft...] / {max_h}")
            st.divider()

    with tab2:
        st.write("Admin Bereich")
