import streamlit as st
import pandas as pd
import datetime
import hashlib
import secrets
import traceback
import uuid
from sqlalchemy import create_engine, text

# ==========================================
# 1. KONFIGURATION & DATENBANK-VERBINDUNG
# ==========================================
st.set_page_config(page_title="TuB Orga", page_icon="🏐", layout="wide")

# Verbindung aufbauen (Daten kommen sicher aus den Streamlit Secrets)
try:
    DB_URL = st.secrets["DB_URL"]
    engine = create_engine(
        DB_URL, 
        connect_args={
            "sslmode": "require",
            "connect_timeout": 15
        },
        pool_pre_ping=True
    )
except Exception as e:
    st.error(f"Datenbankfehler beim Verbindungsaufbau: {e}")
    st.stop()


# ==========================================
# 2. DATENBANK-TABELLEN INITIALISIEREN
# ==========================================
def update_db_schema(engine):
    """Initialisiert alle notwendigen Tabellen in PostgreSQL, falls sie fehlen."""
    with engine.begin() as conn:
        # User Tabelle anlegen
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                user_id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                rolle TEXT NOT NULL,
                dsgvo_akzeptiert INTEGER DEFAULT 0
            );
        """))
        
        # NEU: Spalte für Familienverknüpfung nachträglich hinzufügen (falls Tabelle schon existiert)
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES users(user_id);"))
        except Exception:
            pass # Ignorieren, falls es in älteren Postgres-Versionen zu Fehlern führt
            
        conn.execute(text("""
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

# Schema beim Start einmal prüfen/anlegen
try:
    update_db_schema(engine)
except Exception as e:
    st.error(f"Fehler bei der Tabellen-Initialisierung: {e}")
    st.stop()


# ==========================================
# 3. KRYPTOGRAFIE & PASSWORT-SCHUTZ
# ==========================================
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return f"{salt}${hash_obj.hex()}"

def verify_password(password: str, hashed_password: str) -> bool:
    if "$" not in hashed_password: 
        return password == hashed_password
    salt, hash_hex = hashed_password.split('$')
    hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000)
    return hash_obj.hex() == hash_hex


# ==========================================
# 4. USER-VERWALTUNG & SQL-AKTIONEN
# ==========================================
def get_user_count():
    """Prüft, ob bereits Benutzer in der Datenbank existieren."""
    try:
        with engine.connect() as conn:
            return conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
    except Exception:
        return 0

def create_initial_admin(name, email, password):
    """Erstellt den allerersten Administrator beim allerersten Start."""
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

def register_new_user(name, email, password, rolle):
    """Registriert einen neuen Benutzer sicher in der PostgreSQL-Datenbank."""
    hashed = hash_password(password)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert)
                    VALUES (:name, :email, :hash, :rolle, 1)
                """),
                {"name": name, "email": email, "hash": hashed, "rolle": rolle}
            )
        return True, "Erfolgreich registriert! Du kannst dich nun im linken Tab einloggen."
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            return False, "Diese E-Mail-Adresse ist bereits registriert!"
        return False, f"Fehler bei der Registrierung: {e}"

def add_child(parent_id, child_name):
    """Fügt ein Kind hinzu, das mit dem Account des Elternteils verknüpft ist."""
    # Generiere eine eindeutige "Dummy"-E-Mail-Adresse für die Datenbank
    dummy_email = f"kind_{uuid.uuid4().hex[:8]}@tub.lokal"
    dummy_pass = hash_password(secrets.token_hex(16)) # Zufälliges Passwort, da sich Kinder nicht einloggen
    
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, parent_id)
                    VALUES (:name, :email, :hash, 'Kind', 1, :parent_id)
                """),
                {"name": child_name, "email": dummy_email, "hash": dummy_pass, "parent_id": parent_id}
            )
        return True, f"{child_name} wurde erfolgreich als Familienmitglied hinzugefügt!"
    except Exception as e:
        return False, f"Fehler beim Hinzufügen: {e}"

def get_children(parent_id):
    """Lädt alle Kinder eines Benutzers."""
    try:
        with engine.connect() as conn:
            return pd.read_sql(
                text("SELECT user_id, name FROM users WHERE parent_id = :parent_id"), 
                conn, 
                params={"parent_id": parent_id}
            )
    except Exception:
        return pd.DataFrame()

def authenticate(email, password):
    """Prüft E-Mail und Passwort beim Login."""
    with engine.connect() as conn:
        query = text("SELECT * FROM users WHERE email = :email AND rolle != 'Kind'") # Kinder loggen sich nicht selbst ein
        result = conn.execute(query, {"email": email}).fetchone()
        if result and verify_password(password, result.password_hash):
            return dict(result._mapping)
    return None

def get_all_tasks():
    """Lädt alle Aufgaben für das Haupt-Dashboard."""
    try:
        return pd.read_sql("SELECT * FROM tasks", engine)
    except Exception:
        return pd.DataFrame()


# ==========================================
# 5. BENUTZEROBERFLÄCHE (MAIN UI)
# ==========================================
st.title("🏐 TuB Helfer-Orga")

# Session-Status für Login initialisieren
if 'logged_in_user' not in st.session_state:
    st.session_state['logged_in_user'] = None

user_count = get_user_count()

# FALL A: Datenbank ist komplett leer -> Erstmaligen Admin einrichten
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
                    st.success("Admin-Account erfolgreich erstellt! Bitte lade die Seite neu.")
                    st.rerun()
            else:
                st.error("Bitte fülle alle Felder aus.")

# FALL B: User sind vorhanden, aber niemand ist eingeloggt
elif st.session_state['logged_in_user'] is None:
    
    # Trennung der Ansicht in zwei Reiter
    tab_login, tab_register = st.tabs(["🔑 Einloggen", "📝 Neu Registrieren"])
    
    # ------------------- REITER 1: LOGIN -------------------
    with tab_login:
        with st.form("login_form"):
            st.subheader("Willkommen zurück!")
            email = st.text_input("E-Mail")
            password = st.text_input("Passwort", type="password")
            
            if st.form_submit_button("Einloggen"):
                user = authenticate(email, password)
                if user:
                    st.session_state['logged_in_user'] = user
                    st.rerun()
                else:
                    st.error("Zugangsdaten ungültig oder Account existiert nicht.")
                    
    # ------------------- REITER 2: REGISTRIERUNG -------------------
    with tab_register:
        with st.form("register_form"):
            st.subheader("Werde Teil der TuB Helfer-Crew!")
            new_name = st.text_input("Vor- und Nachname")
            new_email = st.text_input("E-Mail-Adresse")
            new_password = st.text_input("Passwort", type="password")
            
            new_rolle = st.selectbox("Ich bin im Verein...", ["Spieler", "Trainer", "Elternteil"])
            dsgvo = st.checkbox("Ich stimme der Verarbeitung meiner Daten für die Vereinsorganisation zu (DSGVO).")
            
            if st.form_submit_button("Kostenlos Registrieren"):
                if not dsgvo:
                    st.error("Du musst dem Datenschutz zustimmen, um die App nutzen zu können.")
                elif not new_name or not new_email or not new_password:
                    st.error("Bitte fülle alle Felder aus.")
                else:
                    success, msg = register_new_user(new_name, new_email, new_password, new_rolle)
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)

# FALL C: Benutzer ist erfolgreich eingeloggt -> Dashboard & Adminbereich anzeigen
else:
    user = st.session_state['logged_in_user']
    st.write(f"Willkommen zurück, **{user['name']}** ({user['rolle']})!")
    
    if st.button("Ausloggen"):
        st.session_state['logged_in_user'] = None
        st.rerun()
        
    # --- Familien- und Kinderverwaltung ---
    st.markdown("---")
    st.subheader("👨‍👩‍👧 Meine Familie / Kinder")
    st.write("Hier kannst du Familienmitglieder (z. B. Kinder ohne eigene Mailadresse) anlegen. Du kannst später stellvertretend für sie Vereinsaufgaben übernehmen.")
    
    # Bestehende Kinder anzeigen
    children_df = get_children(user['user_id'])
    if not children_df.empty:
        st.table(children_df[['name']].rename(columns={'name': 'Name des Kindes'}))
    
    # Neues Kind hinzufügen
    with st.expander("➕ Kind / Familienmitglied hinzufügen"):
        with st.form("add_child_form"):
            child_name = st.text_input("Vor- und Nachname des Kindes")
            if st.form_submit_button("Speichern"):
                if child_name:
                    success, msg = add_child(user['user_id'], child_name)
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.warning("Bitte gib einen Namen ein.")

    # --- Haupt-Dashboard (Für jeden eingeloggten User sichtbar) ---
    st.markdown("---")
    st.subheader("📋 Aktuelle Aufgaben & Schichten")
    try:
        tasks = get_all_tasks()
        if not tasks.empty:
            st.dataframe(tasks, use_container_width=True)
        else:
            st.info("Es sind aktuell keine Aufgaben eingetragen.")
    except Exception as e:
        st.error(f"Fehler beim Laden der Aufgaben: {e}")

    # --- Admin-Bereich (Nur für Admins sichtbar) ---
    if user['rolle'] == 'Admin':
        st.markdown("---")
        st.subheader("👥 Admin-Bereich: Benutzerverwaltung")
        try:
            with engine.connect() as conn:
                # Wir laden hier alle User und zeigen auch die parent_id an, um Kinder zu erkennen
                df_users = pd.read_sql("SELECT user_id, name, email, rolle, dsgvo_akzeptiert, parent_id FROM users", conn)
            
            # Formatierung für eine schönere Ansicht im Admin-Bereich
            df_users['Typ'] = df_users['parent_id'].apply(lambda x: 'Kind / Sub-Account' if pd.notnull(x) else 'Haupt-Account')
            st.dataframe(df_users[['user_id', 'name', 'email', 'rolle', 'Typ', 'dsgvo_akzeptiert']], use_container_width=True)
        except Exception as e:
            st.error(f"Fehler beim Laden der Benutzerliste: {e}")
