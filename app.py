import streamlit as st
import pandas as pd
import datetime
import hashlib
import secrets
import traceback
import uuid
from sqlalchemy import create_engine, text

# Versuch, den Cookie-Manager zu importieren
try:
    from streamlit_cookies_manager import EncryptedCookieManager
except ImportError:
    st.error("📦 **Fehlendes Paket!** Bitte füge `streamlit-cookies-manager` zu deiner `requirements.txt` auf GitHub hinzu.")
    st.stop()

# ==========================================
# 1. KONFIGURATION & DATENBANK-VERBINDUNG
# ==========================================
st.set_page_config(page_title="TuB Orga", page_icon="🏐", layout="wide")

try:
    DB_URL = st.secrets["DB_URL"]
    engine = create_engine(
        DB_URL, 
        connect_args={"sslmode": "require", "connect_timeout": 15},
        pool_pre_ping=True
    )
except Exception as e:
    st.error(f"Datenbankfehler: {e}")
    st.stop()

cookies = EncryptedCookieManager(prefix="tub_orga", password=DB_URL)
if not cookies.ready(): st.stop()

# ==========================================
# 2. DATENBANK-FUNKTIONEN
# ==========================================
def update_db_schema(engine):
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (user_id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, rolle TEXT NOT NULL, dsgvo_akzeptiert INTEGER DEFAULT 0, parent_id INTEGER REFERENCES users(user_id), team TEXT);
            CREATE TABLE IF NOT EXISTS parent_child (parent_id INTEGER REFERENCES users(user_id), child_id INTEGER REFERENCES users(user_id), PRIMARY KEY (parent_id, child_id));
            CREATE TABLE IF NOT EXISTS tasks (task_id SERIAL PRIMARY KEY, kategorie TEXT, beschreibung TEXT, punkte_wert INTEGER, zugewiesen_an INTEGER REFERENCES users(user_id), start_zeit TEXT, ende_zeit TEXT, betroffene_teams TEXT);
        """))

update_db_schema(engine)

# (Hier kommen deine bewährten Funktionen: hash_password, verify_password, etc. - gekürzt für die Übersicht, im Original-Code beibehalten)
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"{salt}${hash_obj.hex()}"

def verify_password(password: str, hashed_password: str) -> bool:
    if "$" not in hashed_password: return password == hashed_password
    salt, hash_hex = hashed_password.split('$')
    hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return hash_obj.hex() == hash_hex

# ... [Alle anderen Helper-Funktionen wie get_user_count, register_new_user, add_child, etc. bleiben exakt gleich] ...
def get_user_count():
    try:
        with engine.connect() as conn: return conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
    except: return 0

def create_initial_admin(name, email, password):
    hashed = hash_password(password)
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, team) VALUES (:n, :e, :h, 'Admin', 1, 'Kein Team')"), {"n": name, "e": email, "h": hashed})
        return True
    except: return False

def register_new_user(name, email, password, rolle, team_list):
    hashed = hash_password(password)
    team_str = ", ".join(team_list) if team_list else "Kein Team"
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, team) VALUES (:n, :e, :h, :r, 1, :t)"), {"n": name, "e": email, "h": hashed, "r": rolle, "t": team_str})
        return True, "Registrierung erfolgreich!"
    except: return False, "Fehler bei der Registrierung."

def add_child(parent_id, child_name, child_team_list):
    dummy_email = f"kind_{uuid.uuid4().hex[:8]}@tub.lokal"
    dummy_pass = hash_password(secrets.token_hex(16)) 
    team_str = ", ".join(child_team_list) if child_team_list else "Kein Team"
    try:
        with engine.begin() as conn:
            result = conn.execute(text("INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, parent_id, team) VALUES (:n, :e, :h, 'Kind', 1, :p, :t) RETURNING user_id"), {"n": child_name, "e": dummy_email, "h": dummy_pass, "p": parent_id, "t": team_str})
            child_id = result.scalar()
            conn.execute(text("INSERT INTO parent_child (parent_id, child_id) VALUES (:p, :c)"), {"p": parent_id, "c": child_id})
        return True, "Kind hinzugefügt!"
    except: return False, "Fehler."

def get_children(parent_id):
    try:
        with engine.connect() as conn:
            return pd.read_sql(text("SELECT DISTINCT u.user_id, u.name, u.team FROM users u LEFT JOIN parent_child pc ON u.user_id = pc.child_id WHERE u.parent_id = :p OR pc.parent_id = :p"), conn, params={"p": parent_id})
    except: return pd.DataFrame()

def get_all_tasks_with_assignees():
    try: return pd.read_sql(text("SELECT t.*, u.name as assignee_name FROM tasks t LEFT JOIN users u ON t.zugewiesen_an = u.user_id"), engine)
    except: return pd.DataFrame()

def create_task(kategorie, beschreibung, punkte_wert, start_zeit, ende_zeit, betroffene_teams):
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO tasks (kategorie, beschreibung, punkte_wert, start_zeit, ende_zeit, betroffene_teams) VALUES (:k, :b, :p, :s, :e, :t)"), {"k": kategorie, "b": beschreibung, "p": punkte_wert, "s": start_zeit, "e": ende_zeit, "t": betroffene_teams})
        return True, "Gespeichert!"
    except: return False, "Fehler."

def accept_task(task_id, user_id):
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE tasks SET zugewiesen_an = :u WHERE task_id = :t"), {"u": user_id, "t": task_id})
        return True, "Übernommen!"
    except: return False, "Fehler."

def authenticate(email, password):
    with engine.connect() as conn:
        res = conn.execute(text("SELECT * FROM users WHERE email = :e AND rolle != 'Kind'"), {"e": email}).fetchone()
        if res and verify_password(password, res.password_hash): return dict(res._mapping)
    return None

# ==========================================
# 5. UI MIT TABS
# ==========================================
st.title("🏐 TuB Helfer-Orga")
TEAM_LISTE = ["U12", "U13", "U14", "U16", "U18", "U20", "Herren 1", "Herren 2", "Herren 3", "Herren 4"]

# (Login-Logik hier wie gehabt...)
if 'logged_in_user' not in st.session_state:
    saved_id = cookies.get("logged_in_user_id")
    st.session_state['logged_in_user'] = get_user_by_id(int(saved_id)) if saved_id else None

if st.session_state['logged_in_user'] is None:
    # Login / Register Code... (Hier dein Login-Bereich)
    st.write("Bitte logge dich ein.")
else:
    user = st.session_state['logged_in_user']
    st.write(f"Willkommen, {user['name']}!")
    
    # HIER DIE TABS:
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Aufgaben", "📅 Mein Kalender", "👨‍👩‍👧 Familie", "👥 Admin"])
    
    with tab1:
        # Aufgabenliste & Admin-Anlage-Formular
        if user['rolle'] in ['Admin', 'Organisator']:
            # ... (Formular zum Anlegen) ...
            pass
        # ... (Anzeige Aufgabenliste) ...
        st.write("Aufgabenliste hier anzeigen.")

    with tab2:
        st.subheader("Kalender")
        # ... (Dein Kalender-Logik-Code hier) ...

    with tab3:
        st.subheader("Familie")
        # ... (Deine Familien-Verwaltung hier) ...

    with tab4:
        if user['rolle'] == 'Admin':
            st.subheader("Admin-Bereich")
            # ... (Deine Admin-Tabelle hier) ...
        else:
            st.warning("Nur für Admins zugänglich.")
```

**Wie du das finalisierst:**
Ich habe den Code oben strukturell so aufgebaut, dass du die jeweiligen Funktionen (die wir in den letzten Schritten erstellt haben) einfach unter die jeweiligen `tab`-Blöcke kopieren kannst. So erhältst du ein sauberes Dashboard, in dem alles am richtigen Platz ist. 

Brauchst du Hilfe beim Einsetzen der spezifischen Logik-Blöcke in die Tabs oder klappt das für dich?
