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
# 2. DB-SCHEMA
# ==========================================
def update_db_schema():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                user_id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL, rolle TEXT NOT NULL, dsgvo_akzeptiert INTEGER DEFAULT 0,
                parent_id INTEGER, team TEXT
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

update_db_schema()

# ==========================================
# 3. HELFERFUNKTIONEN (Hashing, Auth, DB)
# ==========================================
def hash_password(password):
    salt = secrets.token_hex(16)
    hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"{salt}${hash_obj.hex()}"

def verify_password(password, hashed):
    salt, hash_hex = hashed.split('$')
    hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return hash_obj.hex() == hash_hex

def register_new_user(name, email, password, rolle, team_list):
    hashed = hash_password(password)
    team_str = ", ".join(team_list) if team_list else "Kein Team"
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, team) VALUES (:name, :email, :hash, :rolle, 1, :team)"),
                         {"name": name, "email": email, "hash": hashed, "rolle": rolle, "team": team_str})
        return True, "Erfolgreich registriert."
    except Exception as e:
        return False, str(e)

def add_child(parent_id, child_name, child_team_list):
    dummy_email = f"kind_{uuid.uuid4().hex[:8]}@tub.lokal"
    dummy_pass = hash_password(secrets.token_hex(16))
    team_str = ", ".join(child_team_list) if child_team_list else "Kein Team"
    try:
        with engine.begin() as conn:
            res = conn.execute(text("INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, team) VALUES (:name, :email, :hash, 'Kind', 1, :team) RETURNING user_id"),
                               {"name": child_name, "email": dummy_email, "hash": dummy_pass, "team": team_str})
            child_id = res.scalar()
            conn.execute(text("INSERT INTO parent_child (parent_id, child_id) VALUES (:p, :c)"), {"p": parent_id, "c": child_id})
        return True, "Kind hinzugefügt."
    except Exception as e:
        return False, str(e)

def delete_user(user_id):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM parent_child WHERE parent_id=:id OR child_id=:id"), {"id": user_id})
        conn.execute(text("DELETE FROM task_assignments WHERE user_id=:id"), {"id": user_id})
        conn.execute(text("DELETE FROM users WHERE user_id=:id"), {"id": user_id})
    return True, "User gelöscht."

# ==========================================
# 4. UI LOGIK
# ==========================================
st.title("🏐 TuB Helfer-Orga")
TEAM_LISTE = ["U12", "U13", "U14", "U16", "U18", "U20", "Herren 1", "Herren 2", "Herren 3", "Herren 4"]

# Login-Logik
if 'logged_in_user' not in st.session_state:
    sid = cookies.get("logged_in_user_id")
    if sid:
        with engine.connect() as conn:
            user = conn.execute(text("SELECT * FROM users WHERE user_id=:id"), {"id": int(sid)}).fetchone()
            st.session_state['logged_in_user'] = dict(user._mapping) if user else None
    else:
        st.session_state['logged_in_user'] = None

# Fall: Nicht eingeloggt
if st.session_state['logged_in_user'] is None:
    t1, t2 = st.tabs(["🔑 Einloggen", "📝 Neu Registrieren"])
    with t1:
        with st.form("login"):
            e = st.text_input("E-Mail")
            p = st.text_input("Passwort", type="password")
            if st.form_submit_button("Einloggen"):
                with engine.connect() as conn:
                    user = conn.execute(text("SELECT * FROM users WHERE email=:e"), {"e": e}).fetchone()
                    if user and verify_password(p, user.password_hash):
                        st.session_state['logged_in_user'] = dict(user._mapping)
                        cookies["logged_in_user_id"] = str(user.user_id)
                        cookies.save()
                        st.rerun()
    with t2:
        with st.form("reg"):
            n, em, pw = st.text_input("Name"), st.text_input("E-Mail"), st.text_input("Passwort", type="password")
            r = st.selectbox("Rolle", ["Spieler", "Trainer", "Elternteil", "Organisator"])
            te = st.multiselect("Teams", TEAM_LISTE)
            if st.form_submit_button("Registrieren"):
                s, m = register_new_user(n, em, pw, r, te)
                if s: st.success(m)
                else: st.error(m)
else:
    user = st.session_state['logged_in_user']
    if st.button("Ausloggen"):
        if "logged_in_user_id" in cookies: del cookies["logged_in_user_id"]; cookies.save()
        st.session_state['logged_in_user'] = None; st.rerun()

    # Tabs für Hauptbereich
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Aufgaben", "📅 Mein Kalender", "👨‍👩‍👧 Meine Familie", "👥 Admin"])
    
    with tab1: # Aufgaben
        if user['rolle'] in ['Admin', 'Organisator']:
            with st.expander("➕ Neue Aufgabe"):
                with st.form("task"):
                    kat = st.text_input("Kategorie")
                    desc = st.text_area("Beschreibung")
                    max_h = st.number_input("Max. Helfer", min_value=1, value=1)
                    teams = st.multiselect("Teams", TEAM_LISTE)
                    s_d, s_t = st.date_input("Startdatum"), st.time_input("Startzeit")
                    e_d, e_t = st.date_input("Enddatum"), st.time_input("Endzeit")
                    if st.form_submit_button("Speichern"):
                        with engine.begin() as conn:
                            conn.execute(text("INSERT INTO tasks (kategorie, beschreibung, max_helfer, betroffene_teams, start_zeit, ende_zeit, erstellt_von) VALUES (:k, :b, :m, :t, :s, :e, :u)"),
                                         {"k": kat, "b": desc, "m": max_h, "t": ", ".join(teams), "s": f"{s_d} {s_t}", "e": f"{e_d} {e_t}", "u": user['user_id']})
                        st.rerun()

        # Liste Aufgaben
        tasks = pd.read_sql(text("SELECT * FROM tasks"), engine)
        for _, row in tasks.iterrows():
            assignments = pd.read_sql(text("SELECT u.name FROM task_assignments ta JOIN users u ON ta.user_id = u.user_id WHERE ta.task_id = :tid"), engine, params={"tid": row['task_id']})
            st.write(f"**{row['kategorie']}** - {row['start_zeit']}")
            st.write(f"Helfer: {len(assignments)} / {row['max_helfer']}")
            if len(assignments) < row['max_helfer'] and user['user_id'] not in assignments['name'].values:
                if st.button("Übernehmen", key=f"acc_{row['task_id']}"):
                    with engine.begin() as conn:
                        conn.execute(text("INSERT INTO task_assignments (task_id, user_id) VALUES (:tid, :uid)"), {"tid": row['task_id'], "uid": user['user_id']})
                    st.rerun()
            if user['rolle'] == 'Admin' or user['user_id'] == row['erstellt_von']:
                if st.button("🗑️ Löschen", key=f"del_{row['task_id']}"):
                    with engine.begin() as conn:
                        conn.execute(text("DELETE FROM tasks WHERE task_id=:tid"), {"tid": row['task_id']})
                    st.rerun()
            st.divider()

    with tab2: # Kalender
        st.subheader("Mein Team-Kalender")
        # Hier Filter-Logik für Teams... (wie oben besprochen)
        st.write("Zeige hier Aufgaben für Teams des Users.")

    with tab3: # Familie
        st.subheader("Familienmitglieder")
        # Logik für Kind hinzufügen / verknüpfen...

    with tab4: # Admin
        if user['rolle'] == 'Admin':
            st.subheader("Benutzerverwaltung")
            users = pd.read_sql(text("SELECT * FROM users"), engine)
            st.dataframe(users)
            # Lösch-Logik...
