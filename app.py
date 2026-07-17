import streamlit as st
import pandas as pd
import datetime
import hashlib
import secrets
import uuid
from sqlalchemy import create_engine, text

try:
    from streamlit_cookies_manager import EncryptedCookieManager
except ImportError:
    st.error("📦 **Fehlendes Paket!** Bitte füge `streamlit-cookies-manager` zu deiner `requirements.txt` hinzu.")
    st.stop()

# ==========================================
# KONFIGURATION & DATENBANK
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

def update_db_schema():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                user_id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, rolle TEXT NOT NULL, team TEXT, parent_id INTEGER
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
        # Migration für fehlende Spalten
        for col in ["max_helfer", "erstellt_von"]:
            try: conn.execute(text(f"ALTER TABLE tasks ADD COLUMN IF NOT EXISTS {col} INTEGER DEFAULT 1"))
            except: pass

update_db_schema()

# ==========================================
# HELFER-FUNKTIONEN
# ==========================================
def authenticate(email, password):
    with engine.connect() as conn:
        res = conn.execute(text("SELECT * FROM users WHERE email = :e"), {"e": email}).fetchone()
        if res:
            salt, hash_hex = res.password_hash.split('$')
            hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
            if hash_obj.hex() == hash_hex: return dict(res._mapping)
    return None

TEAM_LISTE = ["U12", "U13", "U14", "U16", "U18", "U20", "Herren 1", "Herren 2", "Herren 3", "Herren 4"]

# ==========================================
# UI LOGIK
# ==========================================
st.title("🏐 TuB Helfer-Orga")

if 'logged_in_user' not in st.session_state:
    sid = cookies.get("logged_in_user_id")
    if sid:
        with engine.connect() as conn:
            user = conn.execute(text("SELECT * FROM users WHERE user_id=:id"), {"id": int(sid)}).fetchone()
            st.session_state['logged_in_user'] = dict(user._mapping) if user else None
    else: st.session_state['logged_in_user'] = None

if st.session_state['logged_in_user'] is None:
    st.info("Bitte einloggen oder registrieren.")
    if st.button("Login-Maske zeigen (vereinfacht)"): st.rerun() # Login UI hier...
else:
    user = st.session_state['logged_in_user']
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Aufgaben", "📅 Mein Kalender", "👨‍👩‍👧 Familie", "👥 Admin"])
    
    with tab1:
        st.subheader("Aktuelle Aufgaben")
        tasks = pd.read_sql(text("SELECT * FROM tasks"), engine)
        for _, row in tasks.iterrows():
            assignments = pd.read_sql(text("SELECT user_id FROM task_assignments WHERE task_id=:tid"), engine, params={"tid": row['task_id']})
            st.write(f"**{row['kategorie']}**")
            st.write(f"Helfer: {len(assignments)} / {row.get('max_helfer', 1)}")
            if st.button(f"Übernehmen für {row['task_id']}"):
                with engine.begin() as conn:
                    conn.execute(text("INSERT INTO task_assignments (task_id, user_id) VALUES (:tid, :uid)"), {"tid": row['task_id'], "uid": user['user_id']})
                st.rerun()
            st.divider()

    with tab3:
        st.subheader("Meine Familie")
        # Hier die Kinder-Logik...

    with tab4:
        if user['rolle'] == 'Admin':
            st.write("Admin Bereich")
