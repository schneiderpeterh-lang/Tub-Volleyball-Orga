import streamlit as st
import pandas as pd
import datetime
import hashlib
import secrets
import traceback
import socket
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
    
    # Erzwinge IPv4 Verbindung durch explizites Setzen der Adresse, falls der Resolver IPv6 liefert
    # Wir nutzen hier den 'connect_args' Parameter um dem Adapter zu helfen
    engine = create_engine(
        DB_URL, 
        connect_args={
            "sslmode": "require",
            "connect_timeout": 5,
            "options": "-c inet6=false" # Versuch, IPv6 auf Treiberebene zu unterbinden
        }
    )
    
    # Test-Connection
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        
    # Erst jetzt schema initialisieren
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
# BENUTZER-PRÜFUNG
# ==========================================

def get_user_count():
    """Gibt die Anzahl der registrierten Benutzer zurück."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
            return result
    except Exception:
        return 0

def create_initial_admin(name, email, password):
    """Erstellt den allerersten Administrator in der Datenbank."""
    hashed = hash_password(password)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert)
                    VALUES (:name, :email, :hash, 'Admin', 1)
                """),
                {"name": name, "email": email, "hash": hashed}
            )
        return True
    except Exception as e:
        st.error(f"Fehler beim Erstellen des Admins: {e}")
        return False

# ==========================================
# MAIN UI
# ==========================================

st.title("🏐 TuB Helfer-Orga")

# Session State initialisieren
if 'logged_in_user' not in st.session_state:
    st.session_state['logged_in_user'] = None

user_count = get_user_count()

# FALL A: Noch keine Benutzer in der Datenbank -> Setup-Modus
if user_count == 0:
    st.warning("⚠️ Keine Benutzer in der Datenbank gefunden. Bitte richte den ersten Admin-Account ein:")
    
    with st.form("setup_admin_form"):
        admin_name = st.text_input("Dein Name (z.B. Peter Schneider)")
        admin_email = st.text_input("E-Mail-Adresse")
        admin_pass = st.text_input("Sicheres Passwort", type="password")
        submit_setup = st.form_submit_button("Initialen Admin-Account erstellen")
        
        if submit_setup:
            if admin_name and admin_email and admin_pass:
                success = create_initial_admin(admin_name, admin_email, admin_pass)
                if success:
                    st.success("Admin-Account erfolgreich erstellt! Die Seite lädt neu...")
                    st.rerun()
            else:
                st.error("Bitte fülle alle Felder aus.")

# FALL B: Benutzer vorhanden, aber nicht eingeloggt -> Login-Modus
elif st.session_state['logged_in_user'] is None:
    with st.form("login_form"):
        st.subheader("Login")
        email = st.text_input("E-Mail")
        password = st.text_input("Passwort", type="password")
        
        if st.form_submit_button("Einloggen"):
            user = authenticate(email, password)
            if user:
                st.session_state['logged_in_user'] = user
                st.rerun()
            else:
                st.error("Zugangsdaten ungültig.")

# FALL C: Benutzer ist eingeloggt -> Dashboard anzeigen
else:
    user = st.session_state['logged_in_user']
    st.write(f"Willkommen zurück, **{user['name']}** ({user['rolle']})!")
    
    if st.button("Ausloggen"):
        st.session_state['logged_in_user'] = None
        st.rerun()

    # Admin-Bereich anzeigen, wenn die Rolle stimmt
    if user['rolle'] == 'Admin':
        st.markdown("---")
        st.subheader("👥 Admin-Bereich: Benutzerverwaltung")
        try:
            with engine.connect() as conn:
                df_users = pd.read_sql("SELECT user_id, name, email, rolle, dsgvo_akzeptiert FROM users", conn)
            st.dataframe(df_users, use_container_width=True)
        except Exception as e:
            st.error(f"Fehler beim Laden der Benutzerliste: {e}")
