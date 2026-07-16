import streamlit as st
import pandas as pd
import datetime
import hashlib
import secrets
import traceback
import uuid
from sqlalchemy import create_engine, text

# Versuch, den Cookie-Manager zu importieren (mit hilfreicher Fehlermeldung bei Fehlen)
try:
    from streamlit_cookies_manager import EncryptedCookieManager
except ImportError:
    st.error("📦 **Fehlendes Paket!** Bitte füge `streamlit-cookies-manager` zu deiner `requirements.txt` auf GitHub hinzu.")
    st.stop()

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
# 1.b COOKIE-MANAGER INITIALISIEREN
# ==========================================
# Wir nutzen das Datenbank-Passwort als sicheren Schlüssel zum Verschlüsseln der Cookies
cookies = EncryptedCookieManager(
    prefix="tub_orga",
    password=DB_URL  
)

# Wichtig: Warten, bis der Browser die Cookies an den Server geschickt hat
if not cookies.ready():
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
        
        # Spalte für Familienverknüpfung nachträglich hinzufügen (falls Tabelle schon existiert)
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES users(user_id);"))
        except Exception:
            pass 
            
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
    dummy_email = f"kind_{uuid.uuid4().hex[:8]}@tub.lokal"
    dummy_pass = hash_password(secrets.token_hex(16)) 
    
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
        query = text("SELECT * FROM users WHERE email = :email AND rolle != 'Kind'") 
        result = conn.execute(query, {"email": email}).fetchone()
        if result and verify_password(password, result.password_hash):
            return dict(result._mapping)
    return None

def get_user_by_id(user_id):
    """Lädt einen User anhand der ID (für den Auto-Login via Cookie)."""
    try:
        with engine.connect() as conn:
            query = text("SELECT * FROM users WHERE user_id = :id AND rolle != 'Kind'")
            result = conn.execute(query, {"id": user_id}).fetchone()
            if result:
                return dict(result._mapping)
    except Exception:
        pass
    return None

def get_all_tasks_with_assignees():
    """Lädt alle Aufgaben und verknüpft sie mit dem Namen der zugewiesenen Person."""
    try:
        query = text("""
            SELECT t.task_id, t.kategorie, t.beschreibung, t.punkte_wert, t.zugewiesen_an, u.name as assignee_name
            FROM tasks t
            LEFT JOIN users u ON t.zugewiesen_an = u.user_id
            ORDER BY t.task_id DESC
        """)
        with engine.connect() as conn:
            return pd.read_sql(query, conn)
    except Exception:
        return pd.DataFrame()

def create_task(kategorie, beschreibung, punkte_wert):
    """Erstellt eine neue Aufgabe in der Datenbank."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO tasks (kategorie, beschreibung, punkte_wert)
                    VALUES (:kat, :besch, :pkt)
                """),
                {"kat": kategorie, "besch": beschreibung, "pkt": punkte_wert}
            )
        return True, "Aufgabe erfolgreich angelegt!"
    except Exception as e:
        return False, f"Fehler beim Erstellen der Aufgabe: {e}"

def accept_task(task_id, user_id):
    """Weist eine Aufgabe einem Benutzer (oder Kind) zu."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE tasks SET zugewiesen_an = :user_id WHERE task_id = :task_id"),
                {"user_id": user_id, "task_id": task_id}
            )
        return True, "Aufgabe erfolgreich übernommen!"
    except Exception as e:
        return False, f"Fehler bei der Übernahme: {e}"


# ==========================================
# 5. BENUTZEROBERFLÄCHE (MAIN UI)
# ==========================================
st.title("🏐 TuB Helfer-Orga")

# Session-Status für Login initialisieren ODER Cookie auslesen
if 'logged_in_user' not in st.session_state:
    
    # 1. Zuerst prüfen: Haben wir einen gültigen Cookie aus einer alten Sitzung?
    saved_user_id = cookies.get("logged_in_user_id")
    
    if saved_user_id:
        # User aus Datenbank abrufen
        auto_user = get_user_by_id(int(saved_user_id))
        st.session_state['logged_in_user'] = auto_user
    else:
        # Kein Cookie vorhanden -> Nicht eingeloggt
        st.session_state['logged_in_user'] = None

user_count = get_user_count()

# FALL A: Datenbank ist komplett leer -> Erstmaligen Admin einrichten
if user_count == 0:
    st.warning("⚠️ Keine Benutzer in der Datenbank gefunden. Bitte richte den ersten Admin-Account ein:")
    with st.form("setup_admin_form"):
        admin_name = st.text_input("Dein Name (z.B. Max Mustermann)")
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
                    # 1. Im Session-State merken
                    st.session_state['logged_in_user'] = user
                    
                    # 2. Dauerhaft im verschlüsselten Cookie speichern!
                    cookies["logged_in_user_id"] = str(user['user_id'])
                    cookies.save()
                    
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
            
            # Neue Rolle 'Organisator' hinzugefügt
            new_rolle = st.selectbox("Ich bin im Verein...", ["Spieler", "Trainer", "Elternteil", "Organisator"])
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
        # Ausloggen bedeutet: Cookie löschen UND Session leeren
        if "logged_in_user_id" in cookies:
            del cookies["logged_in_user_id"]
            cookies.save()
            
        st.session_state['logged_in_user'] = None
        st.rerun()
        
    # --- Familien- und Kinderverwaltung ---
    st.markdown("---")
    st.subheader("👨‍👩‍👧 Meine Familie / Kinder")
    
    # Bestehende Kinder abrufen
    children_df = get_children(user['user_id'])
    
    with st.expander("Verwaltung öffnen"):
        st.write("Hier kannst du Familienmitglieder (z. B. Kinder ohne eigene Mailadresse) anlegen. Du kannst später stellvertretend für sie Vereinsaufgaben übernehmen.")
        if not children_df.empty:
            st.table(children_df[['name']].rename(columns={'name': 'Name des Kindes'}))
        
        # Neues Kind hinzufügen
        with st.form("add_child_form"):
            child_name = st.text_input("Vor- und Nachname des Kindes")
            if st.form_submit_button("Familienmitglied speichern"):
                if child_name:
                    success, msg = add_child(user['user_id'], child_name)
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.warning("Bitte gib einen Namen ein.")

    # --- Haupt-Dashboard: AUFGABEN ---
    st.markdown("---")
    st.subheader("📋 Aktuelle Aufgaben & Schichten")
    
    # 1. Aufgaben erstellen (Nur für Admins & Organisatoren)
    if user['rolle'] in ['Admin', 'Organisator']:
        with st.expander("➕ Neue Aufgabe anlegen"):
            with st.form("new_task_form"):
                kategorie_input = st.text_input("Kategorie (z.B. Hallenaufbau, Catering, Schiedsgericht)")
                beschreibung_input = st.text_area("Beschreibung / Details")
                punkte_input = st.number_input("Punkte-Wert", min_value=1, value=1)
                
                if st.form_submit_button("Aufgabe speichern"):
                    if kategorie_input and beschreibung_input:
                        success, msg = create_task(kategorie_input, beschreibung_input, punkte_input)
                        if success:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
                    else:
                        st.error("Bitte Kategorie und Beschreibung ausfüllen.")
                        
    st.write("") # Etwas Abstand
    
    # 2. Aufgaben auflisten & annehmen (Für alle)
    try:
        tasks_df = get_all_tasks_with_assignees()
        
        if not tasks_df.empty:
            for _, row in tasks_df.iterrows():
                with st.container():
                    col1, col2, col3 = st.columns([4, 1, 3])
                    
                    with col1:
                        st.write(f"**{row['kategorie']}**")
                        st.caption(row['beschreibung'])
                    
                    with col2:
                        st.write(f"Punkte: **{row['punkte_wert']}**")
                    
                    with col3:
                        if pd.isna(row['zugewiesen_an']):
                            # Aufgabe ist noch frei
                            # Dropdown zur Auswahl: Ich selbst oder eines meiner Kinder
                            options = {user['user_id']: "Ich selbst"}
                            if not children_df.empty:
                                for _, child in children_df.iterrows():
                                    options[child['user_id']] = f"Kind: {child['name']}"
                                    
                            selected_user_id = st.selectbox(
                                "Wer übernimmt?", 
                                options=list(options.keys()), 
                                format_func=lambda x: options[x],
                                key=f"sel_{row['task_id']}",
                                label_visibility="collapsed"
                            )
                            
                            if st.button("Übernehmen", key=f"btn_{row['task_id']}", use_container_width=True):
                                success, msg = accept_task(row['task_id'], selected_user_id)
                                if success:
                                    st.success(msg)
                                    st.rerun()
                                else:
                                    st.error(msg)
                        else:
                            # Aufgabe ist vergeben
                            st.success(f"✅ Angenommen von:\n**{row['assignee_name']}**")
                            
                    st.divider() # Trennlinie zwischen den Aufgaben
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
                df_users = pd.read_sql("SELECT user_id, name, email, rolle, dsgvo_akzeptiert, parent_id FROM users", conn)
            
            df_users['Typ'] = df_users['parent_id'].apply(lambda x: 'Kind / Sub-Account' if pd.notnull(x) else 'Haupt-Account')
            st.dataframe(df_users[['user_id', 'name', 'email', 'rolle', 'Typ', 'dsgvo_akzeptiert']], use_container_width=True)
        except Exception as e:
            st.error(f"Fehler beim Laden der Benutzerliste: {e}")
