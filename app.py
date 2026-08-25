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
    
    # Sicherheits-Fix: SQLAlchemy 1.4+ erfordert 'postgresql://' statt 'postgres://'
    if DB_URL.startswith("postgres://"):
        DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)
        
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
    """Initialisiert alle notwendigen Tabellen und Spalten in PostgreSQL, falls sie fehlen."""
    with engine.begin() as conn:
        # User Tabelle
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                user_id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                rolle TEXT NOT NULL,
                dsgvo_akzeptiert INTEGER DEFAULT 0,
                parent_id INTEGER,
                team TEXT
            );
        """))
        
        # Parent-Child Verknüpfung
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS parent_child (
                parent_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
                child_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
                PRIMARY KEY (parent_id, child_id)
            );
        """))

        # Tasks Tabelle (Aufgaben)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id SERIAL PRIMARY KEY,
                kategorie TEXT,
                beschreibung TEXT,
                start_zeit TEXT,
                ende_zeit TEXT,
                betroffene_teams TEXT,
                erstellt_von INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
                max_helfer INTEGER DEFAULT 1
            );
        """))

        # Task Assignments (Wer hat die Aufgabe übernommen?)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS task_assignments (
                assignment_id SERIAL PRIMARY KEY,
                task_id INTEGER REFERENCES tasks(task_id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE
            );
        """))
        
        # Sicherheits-Updates: Fehlende Spalten hinzufügen (falls alte Tabelle existiert)
        try: conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS parent_id INTEGER;"))
        except: pass 
        try: conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS team TEXT;"))
        except: pass 
        try: conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS start_zeit TEXT;"))
        except: pass
        try: conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS ende_zeit TEXT;"))
        except: pass
        try: conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS betroffene_teams TEXT;"))
        except: pass
        try: conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS erstellt_von INTEGER REFERENCES users(user_id) ON DELETE SET NULL;"))
        except: pass
        try: conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS max_helfer INTEGER DEFAULT 1;"))
        except: pass

        # Daten-Migration alter Parent-Struktur
        try:
            conn.execute(text("""
                INSERT INTO parent_child (parent_id, child_id)
                SELECT parent_id, user_id FROM users WHERE parent_id IS NOT NULL
                ON CONFLICT DO NOTHING;
            """))
        except: pass

# Schema beim Start prüfen/anlegen
try:
    update_db_schema(engine)
except Exception as e:
    st.error(f"Fehler bei der Tabellen-Initialisierung: {e}")


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
    try:
        with engine.connect() as conn:
            return conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
    except: return 0

def create_initial_admin(name, email, password):
    hashed = hash_password(password)
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, team)
                VALUES (:name, :email, :hash, 'Admin', 1, 'Kein Team')
            """), {"name": name, "email": email, "hash": hashed})
        return True
    except Exception as e:
        st.error(f"Fehler beim Erstellen des Admins: {e}")
        return False

def register_new_user(name, email, password, rolle, team_list):
    hashed = hash_password(password)
    team_str = ", ".join(team_list) if team_list else "Kein Team"
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, team)
                VALUES (:name, :email, :hash, :rolle, 1, :team)
            """), {"name": name, "email": email, "hash": hashed, "rolle": rolle, "team": team_str})
        return True, "Erfolgreich registriert! Du kannst dich nun im linken Tab einloggen."
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            return False, "Diese E-Mail-Adresse ist bereits registriert!"
        return False, f"Fehler bei der Registrierung: {e}"

def add_child(parent_id, child_name, child_team_list):
    dummy_email = f"kind_{uuid.uuid4().hex[:8]}@tub.lokal"
    dummy_pass = hash_password(secrets.token_hex(16)) 
    team_str = ", ".join(child_team_list) if child_team_list else "Kein Team"
    try:
        with engine.begin() as conn:
            result = conn.execute(text("""
                INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, parent_id, team)
                VALUES (:name, :email, :hash, 'Kind', 1, :parent_id, :team) RETURNING user_id
            """), {"name": child_name, "email": dummy_email, "hash": dummy_pass, "parent_id": parent_id, "team": team_str})
            new_child_id = result.scalar()
            conn.execute(text("INSERT INTO parent_child (parent_id, child_id) VALUES (:p, :c) ON CONFLICT DO NOTHING"),
                         {"p": parent_id, "c": new_child_id})
        return True, f"{child_name} erfolgreich hinzugefügt!"
    except Exception as e:
        return False, f"Fehler beim Hinzufügen: {e}"

def link_existing_child(parent_id, child_id):
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO parent_child (parent_id, child_id) VALUES (:p, :c) ON CONFLICT DO NOTHING"),
                         {"p": parent_id, "c": child_id})
        return True, "Kind erfolgreich verknüpft!"
    except Exception as e:
        return False, f"Fehler bei der Verknüpfung: {e}"

def get_children(parent_id):
    try:
        with engine.connect() as conn:
            return pd.read_sql(text("""
                SELECT DISTINCT u.user_id, u.name, u.team 
                FROM users u 
                LEFT JOIN parent_child pc ON u.user_id = pc.child_id
                WHERE u.parent_id = :parent_id OR pc.parent_id = :parent_id
            """), conn, params={"parent_id": parent_id})
    except: return pd.DataFrame()

def get_all_children_in_db():
    try:
        with engine.connect() as conn:
            return pd.read_sql(text("SELECT user_id, name, team FROM users WHERE rolle = 'Kind' ORDER BY name"), conn)
    except: return pd.DataFrame()

def delete_user(user_id):
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM parent_child WHERE parent_id = :id OR child_id = :id"), {"id": user_id})
            conn.execute(text("UPDATE users SET parent_id = NULL WHERE parent_id = :id"), {"id": user_id})
            conn.execute(text("DELETE FROM task_assignments WHERE user_id = :id"), {"id": user_id})
            conn.execute(text("DELETE FROM users WHERE user_id = :id"), {"id": user_id})
        return True, "Account erfolgreich gelöscht."
    except Exception as e:
        return False, f"Fehler beim Löschen: {e}"

def authenticate(email, password):
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM users WHERE email = :email AND rolle != 'Kind'"), {"email": email}).fetchone()
        if result and verify_password(password, result.password_hash):
            return dict(result._mapping)
    return None

def get_tasks_and_assignments():
    try:
        with engine.connect() as conn:
            tasks_df = pd.read_sql(text("SELECT * FROM tasks ORDER BY task_id DESC"), conn)
            assigns_df = pd.read_sql(text("""
                SELECT ta.task_id, ta.user_id, u.name as assignee_name 
                FROM task_assignments ta 
                JOIN users u ON ta.user_id = u.user_id
            """), conn)
            return tasks_df, assigns_df
    except:
        return pd.DataFrame(), pd.DataFrame()

def create_task(kategorie, beschreibung, max_helfer, erstellt_von, start_zeit=None, ende_zeit=None, betroffene_teams=None):
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO tasks (kategorie, beschreibung, max_helfer, erstellt_von, start_zeit, ende_zeit, betroffene_teams)
                VALUES (:kat, :besch, :max_h, :erst, :start, :ende, :teams)
            """), {
                "kat": kategorie, "besch": beschreibung, "max_h": max_helfer, "erst": erstellt_von,
                "start": start_zeit, "ende": ende_zeit, "teams": betroffene_teams
            })
        return True, "Aufgabe erfolgreich angelegt!"
    except Exception as e:
        return False, f"Fehler beim Erstellen der Aufgabe: {e}"

def accept_task(task_id, user_id):
    try:
        with engine.begin() as conn:
            # Prüfen ob der Nutzer schon eingetragen ist
            existing = conn.execute(text("SELECT 1 FROM task_assignments WHERE task_id = :t AND user_id = :u"), 
                                    {"t": task_id, "u": user_id}).scalar()
            if existing:
                return False, "Diese Person ist bereits für die Aufgabe eingetragen!"
            
            conn.execute(text("INSERT INTO task_assignments (task_id, user_id) VALUES (:t, :u)"), 
                         {"t": task_id, "u": user_id})
        return True, "Aufgabe erfolgreich übernommen!"
    except Exception as e:
        return False, f"Fehler bei der Übernahme: {e}"

def delete_task(task_id):
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM tasks WHERE task_id = :t"), {"t": task_id})
        return True, "Aufgabe gelöscht."
    except Exception as e:
        return False, f"Fehler beim Löschen der Aufgabe: {e}"


# ==========================================
# 5. BENUTZEROBERFLÄCHE (MAIN UI)
# ==========================================
st.title("🏐 TuB Helfer-Orga")

TEAM_LISTE = ["U12", "U13", "U14", "U16", "U18", "U20", "Herren 1", "Herren 2", "Herren 3", "Herren 4"]

# Sicheres Session-Management (Ohne Cookies!)
if 'logged_in_user' not in st.session_state:
    st.session_state['logged_in_user'] = None

user_count = get_user_count()

# FALL A: Erste Einrichtung
if user_count == 0:
    st.warning("⚠️ Keine Benutzer in der Datenbank gefunden. Bitte richte den ersten Admin-Account ein:")
    with st.form("setup_admin_form"):
        admin_name = st.text_input("Dein Name (z.B. Max Mustermann)")
        admin_email = st.text_input("E-Mail-Adresse")
        admin_pass = st.text_input("Sicheres Passwort", type="password")
        if st.form_submit_button("Initialen Admin-Account erstellen"):
            if admin_name and admin_email and admin_pass:
                if create_initial_admin(admin_name, admin_email, admin_pass):
                    st.success("Admin-Account erfolgreich erstellt! Bitte lade die Seite neu.")
                    st.rerun()
            else:
                st.error("Bitte fülle alle Felder aus.")

# FALL B: Login & Registrierung
elif st.session_state['logged_in_user'] is None:
    tab_login, tab_register = st.tabs(["🔑 Einloggen", "📝 Neu Registrieren"])
    
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
                    st.error("Zugangsdaten ungültig.")
                    
    with tab_register:
        with st.form("register_form"):
            st.subheader("Werde Teil der TuB Helfer-Crew!")
            new_name = st.text_input("Vor- und Nachname")
            new_email = st.text_input("E-Mail-Adresse")
            new_password = st.text_input("Passwort", type="password")
            col1, col2 = st.columns(2)
            with col1:
                new_rolle = st.selectbox("Ich bin im Verein...", ["Spieler", "Trainer", "Elternteil", "Organisator"])
            with col2:
                new_team = st.multiselect("Mein(e) Team(s) / Mannschaft(en)", TEAM_LISTE)
            dsgvo = st.checkbox("Ich stimme der Verarbeitung meiner Daten für die Vereinsorganisation zu (DSGVO).")
            
            if st.form_submit_button("Kostenlos Registrieren"):
                if not dsgvo: st.error("Bitte dem Datenschutz zustimmen.")
                elif not new_name or not new_email or not new_password: st.error("Bitte alle Felder ausfüllen.")
                else:
                    success, msg = register_new_user(new_name, new_email, new_password, new_rolle, new_team)
                    if success: st.success(msg)
                    else: st.error(msg)

# FALL C: Eingeloggt (Das Haupt-Dashboard)
else:
    user = st.session_state['logged_in_user']
    user_team_display = f" ({user['team']})" if user.get('team') and user.get('team') != "Kein Team" else ""
    
    col1, col2 = st.columns([4, 1])
    with col1:
        st.write(f"Willkommen zurück, **{user['name']}** - {user['rolle']}{user_team_display}!")
    with col2:
        if st.button("🚪 Ausloggen"):
            st.session_state['logged_in_user'] = None
            st.rerun()
            
    # Lade Aufgaben, Zuweisungen und Kinder nur 1x pro Refresh
    tasks_df, assigns_df = get_tasks_and_assignments()
    children_df = get_children(user['user_id'])
    
    # Aufbau der Reiter (Tabs)
    tab_list = ["📋 Aufgaben & Schichten", "📅 Mein Kalender", "👨‍👩‍👧 Meine Familie"]
    if user['rolle'] == 'Admin':
        tab_list.append("👥 Admin-Bereich")
        
    tabs = st.tabs(tab_list)
    
    # ----------------------------------------------------
    # TAB 1: AUFGABEN & SCHICHTEN
    # ----------------------------------------------------
    with tabs[0]:
        if user['rolle'] in ['Admin', 'Organisator']:
            with st.expander("➕ Neue Aufgabe anlegen"):
                with st.form("new_task_form"):
                    kategorie_input = st.text_input("Kategorie (z.B. Hallenaufbau, Catering)")
                    beschreibung_input = st.text_area("Beschreibung / Details")
                    
                    c1, c2, c3 = st.columns(3)
                    with c1: max_helfer_input = st.number_input("Benötigte Helfer", min_value=1, value=1)
                    with c2: start_date = st.date_input("Startdatum", value=datetime.date.today())
                    with c3: start_time = st.time_input("Startzeit", value=datetime.time(10, 0))
                    
                    c4, c5, c6 = st.columns(3)
                    with c5: end_date = st.date_input("Enddatum", value=datetime.date.today())
                    with c6: end_time = st.time_input("Endzeit", value=datetime.time(12, 0))
                    
                    task_teams = st.multiselect("Betroffene Teams (optional)", TEAM_LISTE)
                    
                    if st.form_submit_button("Aufgabe speichern"):
                        if kategorie_input and beschreibung_input:
                            start_dt_str = f"{start_date.strftime('%d.%m.%Y')} {start_time.strftime('%H:%M')} Uhr"
                            end_dt_str = f"{end_date.strftime('%d.%m.%Y')} {end_time.strftime('%H:%M')} Uhr"
                            teams_str = ", ".join(task_teams) if task_teams else None
                            
                            success, msg = create_task(kategorie_input, beschreibung_input, max_helfer_input, 
                                                       user['user_id'], start_dt_str, end_dt_str, teams_str)
                            if success:
                                st.success(msg)
                                st.rerun()
                            else: st.error(msg)
                        else: st.error("Bitte Kategorie und Beschreibung ausfüllen.")
                        
        st.write("") 
        
        if not tasks_df.empty:
            for _, row in tasks_df.iterrows():
                task_id = row['task_id']
                # Helfer für diese Aufgabe ermitteln
                task_assigns = assigns_df[assigns_df['task_id'] == task_id] if not assigns_df.empty else pd.DataFrame()
                current_helfer = len(task_assigns)
                max_h = int(row['max_helfer']) if pd.notna(row['max_helfer']) else 1
                
                with st.container():
                    col1, col2, col3 = st.columns([4, 2, 2])
                    with col1:
                        st.write(f"**{row['kategorie']}**")
                        if pd.notna(row.get('start_zeit')) and pd.notna(row.get('ende_zeit')):
                            st.write(f"🗓️ **{row['start_zeit']}** bis **{row['ende_zeit']}**")
                        if pd.notna(row.get('betroffene_teams')) and row['betroffene_teams']:
                            st.write(f"👕 **Teams:** {row['betroffene_teams']}")
                        st.caption(row['beschreibung'])
                    
                    with col2:
                        st.write(f"**Helfer:** {current_helfer} / {max_h}")
                        if current_helfer > 0:
                            st.write("👥 Dabei sind: " + ", ".join(task_assigns['assignee_name'].tolist()))
                        else:
                            st.write("👥 Noch keine Helfer")
                    
                    with col3:
                        # Optionen für Übernahme aufbauen (User selbst + Kinder)
                        options = {user['user_id']: "Ich selbst"}
                        if not children_df.empty:
                            for _, child in children_df.iterrows():
                                options[child['user_id']] = f"Kind: {child['name']}"
                                
                        # Bereits zugewiesene herausfiltern, damit man sich nicht doppelt einträgt
                        if not task_assigns.empty:
                            assigned_ids = task_assigns['user_id'].tolist()
                            options = {k: v for k, v in options.items() if k not in assigned_ids}
                            
                        if current_helfer < max_h:
                            if options:
                                selected_user_id = st.selectbox("Wer übernimmt?", options=list(options.keys()), 
                                                                format_func=lambda x: options[x], key=f"sel_{task_id}", label_visibility="collapsed")
                                if st.button("Übernehmen", key=f"btn_{task_id}", use_container_width=True):
                                    success, msg = accept_task(task_id, selected_user_id)
                                    if success:
                                        st.success(msg)
                                        st.rerun()
                                    else: st.error(msg)
                            else:
                                st.success("✅ Du (und deine Familie) bist bereits eingetragen.")
                        else:
                            st.success("✅ Schicht ist voll belegt!")
                            
                        # Löschen Button für Admins & Ersteller
                        if user['rolle'] == 'Admin' or row['erstellt_von'] == user['user_id']:
                            if st.button("🗑️ Löschen", key=f"del_{task_id}", type="secondary", use_container_width=True):
                                success, msg = delete_task(task_id)
                                if success:
                                    st.success(msg)
                                    st.rerun()
                                else: st.error(msg)
                                
                st.divider()
        else:
            st.info("Es sind aktuell keine Aufgaben eingetragen.")

    # ----------------------------------------------------
    # TAB 2: KALENDER
    # ----------------------------------------------------
    with tabs[1]:
        st.write("Hier siehst du alle Termine deiner Mannschaften sowie allgemeine Vereinstermine.")
        if not tasks_df.empty:
            my_teams = set()
            if user.get('team') and user['team'] != "Kein Team":
                my_teams.update([t.strip() for t in user['team'].split(',')])
            if not children_df.empty:
                for _, child in children_df.iterrows():
                    if child.get('team') and child['team'] != "Kein Team":
                        my_teams.update([t.strip() for t in child['team'].split(',')])
                        
            def is_relevant_event(task_teams_str):
                if pd.isna(task_teams_str) or not str(task_teams_str).strip():
                    return True # Allgemeiner Termin
                task_teams = [t.strip() for t in str(task_teams_str).split(',')]
                return any(team in my_teams for team in task_teams)
                
            cal_df = tasks_df[tasks_df['betroffene_teams'].apply(is_relevant_event)].copy()
            if not cal_df.empty:
                try:
                    cal_df['sort_date'] = pd.to_datetime(cal_df['start_zeit'].str.replace(' Uhr', ''), format='%d.%m.%Y %H:%M', errors='coerce')
                    cal_df = cal_df.sort_values(by='sort_date')
                except: pass
                st.dataframe(cal_df[['start_zeit', 'ende_zeit', 'kategorie', 'beschreibung', 'betroffene_teams']].rename(
                    columns={'start_zeit': 'Start', 'ende_zeit': 'Ende', 'kategorie': 'Kategorie', 
                             'beschreibung': 'Beschreibung', 'betroffene_teams': 'Teams'}
                ), use_container_width=True, hide_index=True)
            else:
                st.info("Aktuell stehen keine Termine an.")
        else:
            st.info("Es sind noch keine Aufgaben oder Termine im System angelegt.")

    # ----------------------------------------------------
    # TAB 3: FAMILIE
    # ----------------------------------------------------
    with tabs[2]:
        st.write("Verwalte hier Familienmitglieder. Du kannst stellvertretend für sie Aufgaben übernehmen.")
        if not children_df.empty:
            st.table(children_df[['name', 'team']].rename(columns={'name': 'Name des Kindes', 'team': 'Mannschaft'}))
            
        t_new, t_exist = st.tabs(["➕ Neues Kind anlegen", "🔗 Bestehendes Kind verknüpfen"])
        with t_new:
            with st.form("add_child_form"):
                col1, col2 = st.columns(2)
                with col1: child_name = st.text_input("Vor- und Nachname des Kindes")
                with col2: child_team = st.multiselect("Mannschaft(en) des Kindes", TEAM_LISTE)
                if st.form_submit_button("Neues Familienmitglied speichern"):
                    if child_name:
                        success, msg = add_child(user['user_id'], child_name, child_team)
                        if success: st.success(msg); st.rerun()
                        else: st.error(msg)
                    else: st.warning("Bitte Namen eingeben.")
        with t_exist:
            all_kids_df = get_all_children_in_db()
            if not all_kids_df.empty:
                with st.form("link_child_form"):
                    kid_options = {row['user_id']: f"{row['name']} ({row['team']})" for _, row in all_kids_df.iterrows()}
                    selected_kid_id = st.selectbox("Wähle ein Kind aus der Datenbank", options=list(kid_options.keys()), format_func=lambda x: kid_options[x])
                    if st.form_submit_button("Kind mit meinem Account verknüpfen"):
                        success, msg = link_existing_child(user['user_id'], selected_kid_id)
                        if success: st.success(msg); st.rerun()
                        else: st.error(msg)
            else:
                st.info("Keine Kinder im System.")

    # ----------------------------------------------------
    # TAB 4: ADMIN BEREICH
    # ----------------------------------------------------
    if user['rolle'] == 'Admin':
        with tabs[3]:
            try:
                with engine.connect() as conn:
                    df_users = pd.read_sql("SELECT user_id, name, email, rolle, team, dsgvo_akzeptiert FROM users", conn)
                df_users['Typ'] = df_users['rolle'].apply(lambda x: 'Kind / Sub-Account' if x == 'Kind' else 'Haupt-Account')
                st.dataframe(df_users[['user_id', 'name', 'email', 'rolle', 'team', 'Typ', 'dsgvo_akzeptiert']], use_container_width=True)
                
                with st.expander("🗑️ Account oder doppeltes Kind löschen"):
                    with st.form("delete_user_form"):
                        st.write("Wähle einen Account aus, der vollständig gelöscht werden soll.")
                        user_options = {row['user_id']: f"{row['name']} ({row['Typ']}, Team: {row['team']})" for _, row in df_users.iterrows()}
                        selected_del_id = st.selectbox("Zu löschender Account:", options=list(user_options.keys()), format_func=lambda x: user_options[x])
                        if st.form_submit_button("Account unwiderruflich löschen"):
                            if selected_del_id == user['user_id']:
                                st.error("Du kannst dich nicht selbst löschen!")
                            else:
                                success, msg = delete_user(selected_del_id)
                                if success: st.success(msg); st.rerun()
                                else: st.error(msg)
            except Exception as e:
                st.error(f"Fehler beim Laden der Benutzerliste: {e}")
