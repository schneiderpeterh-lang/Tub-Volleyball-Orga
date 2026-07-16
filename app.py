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
        
        # Spalten für Familienverknüpfung und Teams nachträglich hinzufügen (falls Tabelle schon existiert)
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES users(user_id);"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS team TEXT;"))
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
        
        # NEU: Start- und Endzeit für Tasks hinzufügen (falls nicht existent)
        try:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS start_zeit TEXT;"))
            conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS ende_zeit TEXT;"))
            conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS betroffene_teams TEXT;"))
        except Exception:
            pass
            
        # NEU: Tabelle für Mehrfach-Eltern-Zuweisung
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS parent_child (
                parent_id INTEGER REFERENCES users(user_id),
                child_id INTEGER REFERENCES users(user_id),
                PRIMARY KEY (parent_id, child_id)
            );
        """))
        try:
            # Daten aus alter Struktur in neue überführen (falls existent)
            conn.execute(text("""
                INSERT INTO parent_child (parent_id, child_id)
                SELECT parent_id, user_id FROM users 
                WHERE parent_id IS NOT NULL
                ON CONFLICT DO NOTHING;
            """))
        except Exception:
            pass

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
                    INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, team)
                    VALUES (:name, :email, :hash, 'Admin', 1, 'Kein Team')
                """),
                {"name": name, "email": email, "hash": hashed}
            )
        return True
    except Exception as e:
        st.error(f"Fehler beim Erstellen des Admins: {e}")
        return False

def register_new_user(name, email, password, rolle, team_list):
    """Registriert einen neuen Benutzer sicher in der PostgreSQL-Datenbank."""
    hashed = hash_password(password)
    team_str = ", ".join(team_list) if team_list else "Kein Team"
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, team)
                    VALUES (:name, :email, :hash, :rolle, 1, :team)
                """),
                {"name": name, "email": email, "hash": hashed, "rolle": rolle, "team": team_str}
            )
        return True, "Erfolgreich registriert! Du kannst dich nun im linken Tab einloggen."
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            return False, "Diese E-Mail-Adresse ist bereits registriert!"
        return False, f"Fehler bei der Registrierung: {e}"

def add_child(parent_id, child_name, child_team_list):
    """Fügt ein Kind hinzu, das mit dem Account des Elternteils verknüpft ist."""
    dummy_email = f"kind_{uuid.uuid4().hex[:8]}@tub.lokal"
    dummy_pass = hash_password(secrets.token_hex(16)) 
    team_str = ", ".join(child_team_list) if child_team_list else "Kein Team"
    
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text("""
                    INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, parent_id, team)
                    VALUES (:name, :email, :hash, 'Kind', 1, :parent_id, :team)
                    RETURNING user_id
                """),
                {"name": child_name, "email": dummy_email, "hash": dummy_pass, "parent_id": parent_id, "team": team_str}
            )
            new_child_id = result.scalar()
            
            # Direkt in die neue Mapping-Tabelle eintragen
            conn.execute(
                text("INSERT INTO parent_child (parent_id, child_id) VALUES (:p, :c) ON CONFLICT DO NOTHING"),
                {"p": parent_id, "c": new_child_id}
            )
            
        return True, f"{child_name} wurde erfolgreich als Familienmitglied hinzugefügt!"
    except Exception as e:
        return False, f"Fehler beim Hinzufügen: {e}"

def link_existing_child(parent_id, child_id):
    """Verknüpft ein bereits existierendes Kind mit einem weiteren Elternteil."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO parent_child (parent_id, child_id) VALUES (:p, :c) ON CONFLICT DO NOTHING"),
                {"p": parent_id, "c": child_id}
            )
        return True, "Kind erfolgreich verknüpft!"
    except Exception as e:
        return False, f"Fehler bei der Verknüpfung: {e}"

def get_children(parent_id):
    """Lädt alle Kinder eines Benutzers (über beide Tabellenwege)."""
    try:
        with engine.connect() as conn:
            return pd.read_sql(
                text("""
                    SELECT DISTINCT u.user_id, u.name, u.team 
                    FROM users u 
                    LEFT JOIN parent_child pc ON u.user_id = pc.child_id
                    WHERE u.parent_id = :parent_id OR pc.parent_id = :parent_id
                """), 
                conn, 
                params={"parent_id": parent_id}
            )
    except Exception:
        return pd.DataFrame()

def get_all_children_in_db():
    """Lädt alle Kinder, die im System existieren, um sie verknüpfen zu können."""
    try:
        with engine.connect() as conn:
            return pd.read_sql(text("SELECT user_id, name, team FROM users WHERE rolle = 'Kind' ORDER BY name"), conn)
    except Exception:
        return pd.DataFrame()

def delete_user(user_id):
    """Löscht einen Benutzer/ein Kind und bereinigt alle zugehörigen Daten."""
    try:
        with engine.begin() as conn:
            # 1. Verknüpfungen in parent_child entfernen
            conn.execute(text("DELETE FROM parent_child WHERE parent_id = :id OR child_id = :id"), {"id": user_id})
            
            # 2. Alte parent_id Struktur bereinigen
            conn.execute(text("UPDATE users SET parent_id = NULL WHERE parent_id = :id"), {"id": user_id})
            
            # 3. Aufgaben freigeben (nicht löschen, nur Zuweisung entfernen)
            conn.execute(text("UPDATE tasks SET zugewiesen_an = NULL WHERE zugewiesen_an = :id"), {"id": user_id})
            
            # 4. Endgültig den User löschen
            conn.execute(text("DELETE FROM users WHERE user_id = :id"), {"id": user_id})
            
        return True, "Der Account wurde erfolgreich und sicher gelöscht."
    except Exception as e:
        return False, f"Fehler beim Löschen: {e}"

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
            SELECT t.task_id, t.kategorie, t.beschreibung, t.punkte_wert, t.zugewiesen_an, t.start_zeit, t.ende_zeit, t.betroffene_teams, u.name as assignee_name
            FROM tasks t
            LEFT JOIN users u ON t.zugewiesen_an = u.user_id
            ORDER BY t.task_id DESC
        """)
        with engine.connect() as conn:
            return pd.read_sql(query, conn)
    except Exception:
        return pd.DataFrame()

def create_task(kategorie, beschreibung, punkte_wert, start_zeit=None, ende_zeit=None, betroffene_teams=None):
    """Erstellt eine neue Aufgabe in der Datenbank."""
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO tasks (kategorie, beschreibung, punkte_wert, start_zeit, ende_zeit, betroffene_teams)
                    VALUES (:kat, :besch, :pkt, :start, :ende, :teams)
                """),
                {
                    "kat": kategorie, 
                    "besch": beschreibung, 
                    "pkt": punkte_wert,
                    "start": start_zeit,
                    "ende": ende_zeit,
                    "teams": betroffene_teams
                }
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

# Globale Liste der Teams zur Wiederverwendung
TEAM_LISTE = ["U12", "U13", "U14", "U16", "U18", "U20", "Herren 1", "Herren 2", "Herren 3", "Herren 4"]

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
            
            col1, col2 = st.columns(2)
            with col1:
                # Neue Rolle 'Organisator' hinzugefügt
                new_rolle = st.selectbox("Ich bin im Verein...", ["Spieler", "Trainer", "Elternteil", "Organisator"])
            with col2:
                # Team-Zuweisung bei Registrierung (Mehrfachauswahl)
                new_team = st.multiselect("Mein(e) Team(s) / Mannschaft(en)", TEAM_LISTE)
                
            dsgvo = st.checkbox("Ich stimme der Verarbeitung meiner Daten für die Vereinsorganisation zu (DSGVO).")
            
            if st.form_submit_button("Kostenlos Registrieren"):
                if not dsgvo:
                    st.error("Du musst dem Datenschutz zustimmen, um die App nutzen zu können.")
                elif not new_name or not new_email or not new_password:
                    st.error("Bitte fülle alle Felder aus.")
                else:
                    success, msg = register_new_user(new_name, new_email, new_password, new_rolle, new_team)
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)

# FALL C: Benutzer ist erfolgreich eingeloggt -> Dashboard & Adminbereich anzeigen
else:
    user = st.session_state['logged_in_user']
    user_team_display = f" ({user['team']})" if user.get('team') and user.get('team') != "Kein Team" else ""
    st.write(f"Willkommen zurück, **{user['name']}** - {user['rolle']}{user_team_display}!")
    
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
        st.write("Hier kannst du Familienmitglieder anlegen oder bestehende Kinder mit deinem Account verknüpfen. Du kannst später stellvertretend für sie Vereinsaufgaben übernehmen.")
        if not children_df.empty:
            st.table(children_df[['name', 'team']].rename(columns={'name': 'Name des Kindes', 'team': 'Mannschaft'}))
            
        tab_new, tab_exist = st.tabs(["➕ Neues Kind anlegen", "🔗 Bestehendes Kind verknüpfen"])
        
        with tab_new:
            # Neues Kind hinzufügen
            with st.form("add_child_form"):
                col1, col2 = st.columns(2)
                with col1:
                    child_name = st.text_input("Vor- und Nachname des Kindes")
                with col2:
                    child_team = st.multiselect("Mannschaft(en) des Kindes", TEAM_LISTE)
                    
                if st.form_submit_button("Neues Familienmitglied speichern"):
                    if child_name:
                        success, msg = add_child(user['user_id'], child_name, child_team)
                        if success:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
                    else:
                        st.warning("Bitte gib einen Namen ein.")
                        
        with tab_exist:
            all_kids_df = get_all_children_in_db()
            if not all_kids_df.empty:
                with st.form("link_child_form"):
                    kid_options = {row['user_id']: f"{row['name']} ({row['team']})" for _, row in all_kids_df.iterrows()}
                    selected_kid_id = st.selectbox("Wähle ein Kind aus der Datenbank", options=list(kid_options.keys()), format_func=lambda x: kid_options[x])
                    
                    if st.form_submit_button("Kind mit meinem Account verknüpfen"):
                        success, msg = link_existing_child(user['user_id'], selected_kid_id)
                        if success:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
            else:
                st.info("Es sind noch keine Kinder im System angelegt worden.")

    # --- ZENTRALER DATENABRUF ---
    try:
        tasks_df = get_all_tasks_with_assignees()
    except Exception:
        tasks_df = pd.DataFrame()

    # --- 📅 Mein Team-Kalender ---
    st.markdown("---")
    st.subheader("📅 Mein Team-Kalender")
    st.write("Hier siehst du übersichtlich alle anstehenden Termine, die für deine Mannschaften (und die deiner Kinder) relevant sind.")
    
    if not tasks_df.empty:
        # Sammle alle Teams des Users und seiner Kinder in einem Set (vermeidet Duplikate)
        my_teams = set()
        if user.get('team') and user['team'] != "Kein Team":
            my_teams.update([t.strip() for t in user['team'].split(',')])
            
        if not children_df.empty:
            for _, child in children_df.iterrows():
                if child.get('team') and child['team'] != "Kein Team":
                    my_teams.update([t.strip() for t in child['team'].split(',')])
                    
        # Hilfsfunktion zum Filtern der Termine
        def is_my_team(task_teams_str):
            if pd.isna(task_teams_str) or not task_teams_str:
                return False
            task_teams = [t.strip() for t in task_teams_str.split(',')]
            return any(team in my_teams for team in task_teams)
            
        # Filtern der Tabelle
        cal_df = tasks_df[tasks_df['betroffene_teams'].apply(is_my_team)].copy()
        
        if not cal_df.empty:
            # Versuch einer chronologischen Sortierung anhand des Datumsstrings
            try:
                cal_df['sort_date'] = pd.to_datetime(cal_df['start_zeit'].str.replace(' Uhr', ''), format='%d.%m.%Y %H:%M', errors='coerce')
                cal_df = cal_df.sort_values(by='sort_date')
            except:
                pass # Falls das Parsen fehlschlägt, behalte die Ursprungssortierung
                
            # Tabelle anzeigen (Index ausblenden für sauberen Look)
            st.dataframe(
                cal_df[['start_zeit', 'ende_zeit', 'kategorie', 'beschreibung', 'betroffene_teams']].rename(
                    columns={
                        'start_zeit': 'Start', 
                        'ende_zeit': 'Ende', 
                        'kategorie': 'Kategorie', 
                        'beschreibung': 'Beschreibung', 
                        'betroffene_teams': 'Teams'
                    }
                ), 
                use_container_width=True,
                hide_index=True
            )
        else:
            if my_teams:
                st.info(f"Für deine zugewiesenen Teams ({', '.join(my_teams)}) stehen aktuell keine spezifischen Termine an.")
            else:
                st.info("Dir sind aktuell keine Teams zugewiesen. Bearbeite dein Profil oder lege Kinder an, um hier Termine zu sehen.")
    else:
        st.info("Es sind noch keine Aufgaben oder Termine im System angelegt.")

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
                
                # Datum- und Zeit-Auswahl
                col1, col2 = st.columns(2)
                with col1:
                    start_date = st.date_input("Startdatum", value=datetime.date.today())
                    start_time = st.time_input("Startzeit", value=datetime.time(10, 0))
                with col2:
                    end_date = st.date_input("Enddatum", value=datetime.date.today())
                    end_time = st.time_input("Endzeit", value=datetime.time(12, 0))
                
                # Neues Feld für betroffene Teams
                task_teams = st.multiselect("Betroffene Teams (optional)", TEAM_LISTE)
                
                if st.form_submit_button("Aufgabe speichern"):
                    if kategorie_input and beschreibung_input:
                        # Datum und Zeit schön als String formatieren
                        start_dt_str = f"{start_date.strftime('%d.%m.%Y')} {start_time.strftime('%H:%M')} Uhr"
                        end_dt_str = f"{end_date.strftime('%d.%m.%Y')} {end_time.strftime('%H:%M')} Uhr"
                        teams_str = ", ".join(task_teams) if task_teams else None
                        
                        success, msg = create_task(
                            kategorie=kategorie_input, 
                            beschreibung=beschreibung_input, 
                            punkte_wert=punkte_input,
                            start_zeit=start_dt_str,
                            ende_zeit=end_dt_str,
                            betroffene_teams=teams_str
                        )
                        if success:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
                    else:
                        st.error("Bitte Kategorie und Beschreibung ausfüllen.")
                        
    st.write("") # Etwas Abstand
    
    # 2. Aufgaben auflisten & annehmen (Für alle)
    if not tasks_df.empty:
        for _, row in tasks_df.iterrows():
            with st.container():
                col1, col2, col3 = st.columns([4, 1, 3])
                
                with col1:
                    st.write(f"**{row['kategorie']}**")
                    # Wenn Zeiten vorhanden sind, zeige sie mit einem Icon an
                    if pd.notna(row.get('start_zeit')) and pd.notna(row.get('ende_zeit')):
                        st.write(f"🗓️ **{row['start_zeit']}** bis **{row['ende_zeit']}**")
                    # Wenn Teams zugewiesen sind
                    if pd.notna(row.get('betroffene_teams')) and row['betroffene_teams']:
                        st.write(f"👕 **Teams:** {row['betroffene_teams']}")
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

    # --- Admin-Bereich (Nur für Admins sichtbar) ---
    if user['rolle'] == 'Admin':
        st.markdown("---")
        st.subheader("👥 Admin-Bereich: Benutzerverwaltung")
        try:
            with engine.connect() as conn:
                # Hole alle User inkl. dem neuen 'team' Feld
                df_users = pd.read_sql("SELECT user_id, name, email, rolle, team, dsgvo_akzeptiert, parent_id FROM users", conn)
            
            # Neue Typisierung: Verlässt sich primär auf die Rolle, da parent_id jetzt primär im parent_child table steht
            df_users['Typ'] = df_users['rolle'].apply(lambda x: 'Kind / Sub-Account' if x == 'Kind' else 'Haupt-Account')
            st.dataframe(df_users[['user_id', 'name', 'email', 'rolle', 'team', 'Typ', 'dsgvo_akzeptiert']], use_container_width=True)
            
            # NEU: Formular zum Löschen von Benutzern oder doppelten Kindern
            with st.expander("🗑️ Account oder doppeltes Kind löschen"):
                with st.form("delete_user_form"):
                    st.write("Wähle hier einen Account aus, der vollständig gelöscht werden soll (Aufgaben werden wieder freigegeben).")
                    
                    # Dictionary zum sauberen Anzeigen in der Selectbox
                    user_options = {
                        row['user_id']: f"{row['name']} ({row['Typ']}, Team: {row['team']})" 
                        for _, row in df_users.iterrows()
                    }
                    
                    selected_del_id = st.selectbox(
                        "Zu löschender Account:", 
                        options=list(user_options.keys()), 
                        format_func=lambda x: user_options[x]
                    )
                    
                    if st.form_submit_button("Account unwiderruflich löschen"):
                        if selected_del_id == user['user_id']:
                            st.error("Sicherheitsblockade: Du kannst dich nicht selbst als Admin löschen!")
                        else:
                            success, msg = delete_user(selected_del_id)
                            if success:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                                
        except Exception as e:
            st.error(f"Fehler beim Laden der Benutzerliste: {e}")
