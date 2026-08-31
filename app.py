import streamlit as st
import pandas as pd
import datetime
import hashlib
import secrets
import traceback
import uuid
import io
from sqlalchemy import create_engine, text

try:
    import icalendar
except ImportError:
    st.error("📦 **Fehlendes Paket!** Bitte füge `icalendar` zu deiner `requirements.txt` auf GitHub hinzu, um den Kalender-Import zu nutzen.")
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
    st.error(f"Datenbankfehler beim Verbindungsaufbau: {e}")
    st.stop()

# ==========================================
# 2. DATENBANK-TABELLEN INITIALISIEREN
# ==========================================
def update_db_schema(engine):
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
        """))
        
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES users(user_id);"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS team TEXT;"))
        except Exception: pass 
            
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
        
        # Updates für Tasks
        try:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS start_zeit TEXT;"))
            conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS ende_zeit TEXT;"))
            conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS betroffene_teams TEXT;"))
            conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS max_helfer INTEGER DEFAULT 1;"))
            conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS erstellt_von INTEGER REFERENCES users(user_id);"))
        except Exception: pass

        # Updates für Events (um ICS Daten sauber zu speichern)
        try:
            conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS titel TEXT;"))
            conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS start_zeit TEXT;"))
            conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS ende_zeit TEXT;"))
            conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS betroffene_teams TEXT;"))
        except Exception: pass
            
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS parent_child (
                parent_id INTEGER REFERENCES users(user_id),
                child_id INTEGER REFERENCES users(user_id),
                PRIMARY KEY (parent_id, child_id)
            );
        """))
        
        # Task Assignments (Mehrere Helfer pro Aufgabe)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS task_assignments (
                assignment_id SERIAL PRIMARY KEY,
                task_id INTEGER REFERENCES tasks(task_id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE
            );
        """))

try:
    update_db_schema(engine)
except Exception as e:
    st.error(f"Fehler bei der Tabellen-Initialisierung: {e}")
    st.stop()

# ==========================================
# 3. KRYPTOGRAFIE & USER-VERWALTUNG
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

def get_user_count():
    try:
        with engine.connect() as conn: return conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
    except: return 0

def create_initial_admin(name, email, password):
    hashed = hash_password(password)
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, team) VALUES (:n, :e, :h, 'Admin', 1, 'Kein Team')"),
                {"n": name, "e": email, "h": hashed})
        return True
    except: return False

def register_new_user(name, email, password, rolle, team_list):
    hashed = hash_password(password)
    team_str = ", ".join(team_list) if team_list else "Kein Team"
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, team) VALUES (:n, :e, :h, :r, 1, :t)"),
                {"n": name, "e": email, "h": hashed, "r": rolle, "t": team_str})
        return True, "Erfolgreich registriert!"
    except Exception as e:
        if "unique" in str(e).lower(): return False, "E-Mail bereits registriert!"
        return False, str(e)

def authenticate(email, password):
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM users WHERE email = :email AND rolle != 'Kind'"), {"email": email}).fetchone()
        if result and verify_password(password, result.password_hash): return dict(result._mapping)
    return None

def get_user_by_id(user_id):
    try:
        with engine.connect() as conn:
            res = conn.execute(text("SELECT * FROM users WHERE user_id = :id AND rolle != 'Kind'"), {"id": user_id}).fetchone()
            if res: return dict(res._mapping)
    except: pass
    return None

def add_child(parent_id, child_name, child_team_list):
    dummy_email = f"kind_{uuid.uuid4().hex[:8]}@tub.lokal"
    dummy_pass = hash_password(secrets.token_hex(16)) 
    team_str = ", ".join(child_team_list) if child_team_list else "Kein Team"
    try:
        with engine.begin() as conn:
            res = conn.execute(text("INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, parent_id, team) VALUES (:n, :e, :h, 'Kind', 1, :p, :t) RETURNING user_id"),
                {"n": child_name, "e": dummy_email, "h": dummy_pass, "p": parent_id, "t": team_str})
            conn.execute(text("INSERT INTO parent_child (parent_id, child_id) VALUES (:p, :c) ON CONFLICT DO NOTHING"), {"p": parent_id, "c": res.scalar()})
        return True, f"{child_name} erfolgreich hinzugefügt!"
    except Exception as e: return False, str(e)

def link_existing_child(parent_id, child_id):
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO parent_child (parent_id, child_id) VALUES (:p, :c) ON CONFLICT DO NOTHING"), {"p": parent_id, "c": child_id})
        return True, "Verknüpft!"
    except: return False, "Fehler!"

def get_children(parent_id):
    try:
        with engine.connect() as conn:
            return pd.read_sql(text("SELECT DISTINCT u.user_id, u.name, u.team FROM users u LEFT JOIN parent_child pc ON u.user_id = pc.child_id WHERE u.parent_id = :p OR pc.parent_id = :p"), conn, params={"p": parent_id})
    except: return pd.DataFrame()

def get_all_children_in_db():
    try:
        with engine.connect() as conn: return pd.read_sql(text("SELECT user_id, name, team FROM users WHERE rolle = 'Kind' ORDER BY name"), conn)
    except: return pd.DataFrame()

def delete_user(user_id):
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM parent_child WHERE parent_id = :id OR child_id = :id"), {"id": user_id})
            conn.execute(text("UPDATE users SET parent_id = NULL WHERE parent_id = :id"), {"id": user_id})
            conn.execute(text("DELETE FROM task_assignments WHERE user_id = :id"), {"id": user_id})
            conn.execute(text("DELETE FROM users WHERE user_id = :id"), {"id": user_id})
        return True, "Account gelöscht."
    except Exception as e: return False, str(e)

# ==========================================
# 4. EVENTS & AUFGABEN SQL
# ==========================================
def parse_and_import_ics(file_bytes, team_str):
    """Liest eine ICS Datei und speichert VEVENTs in der Datenbank"""
    try:
        cal = icalendar.Calendar.from_ical(file_bytes)
        events_added = 0
        with engine.begin() as conn:
            for component in cal.walk():
                if component.name == "VEVENT":
                    titel = str(component.get('summary', 'Unbekanntes Event'))
                    ort = str(component.get('location', ''))
                    
                    # Startzeit
                    dtstart = component.get('dtstart')
                    start_str = ""
                    if dtstart:
                        start_dt = dtstart.dt
                        if isinstance(start_dt, datetime.datetime): start_str = start_dt.strftime('%d.%m.%Y %H:%M')
                        else: start_str = start_dt.strftime('%d.%m.%Y')
                        
                    # Endzeit
                    dtend = component.get('dtend')
                    ende_str = ""
                    if dtend:
                        ende_dt = dtend.dt
                        if isinstance(ende_dt, datetime.datetime): ende_str = ende_dt.strftime('%d.%m.%Y %H:%M')
                        else: ende_str = ende_dt.strftime('%d.%m.%Y')

                    conn.execute(text("""
                        INSERT INTO events (titel, start_zeit, ende_zeit, ort, betroffene_teams)
                        VALUES (:titel, :start, :ende, :ort, :teams)
                    """), {"titel": titel, "start": start_str, "ende": ende_str, "ort": ort, "teams": team_str})
                    events_added += 1
        return True, f"{events_added} Termine erfolgreich für {team_str} importiert!"
    except Exception as e:
        return False, f"Fehler beim ICS Import: {e}"

def get_all_events():
    try:
        with engine.connect() as conn:
            return pd.read_sql(text("SELECT * FROM events ORDER BY event_id DESC"), conn)
    except: return pd.DataFrame()

def get_all_tasks():
    try:
        with engine.connect() as conn: return pd.read_sql(text("SELECT * FROM tasks ORDER BY task_id DESC"), conn)
    except: return pd.DataFrame()

def get_task_assignments():
    try:
        with engine.connect() as conn:
            return pd.read_sql(text("SELECT ta.task_id, ta.user_id, u.name as assignee_name FROM task_assignments ta JOIN users u ON ta.user_id = u.user_id"), conn)
    except: return pd.DataFrame()

def create_task(kategorie, beschreibung, max_helfer, user_id, start=None, ende=None, teams=None, event_id=None):
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO tasks (kategorie, beschreibung, max_helfer, erstellt_von, start_zeit, ende_zeit, betroffene_teams, event_id)
                VALUES (:kat, :besch, :max, :erst, :st, :en, :teams, :ev)
            """), {"kat": kategorie, "besch": beschreibung, "max": max_helfer, "erst": user_id, "st": start, "en": ende, "teams": teams, "ev": event_id})
        return True, "Aufgabe erstellt!"
    except Exception as e: return False, str(e)

def delete_task(task_id):
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM tasks WHERE task_id = :t"), {"t": task_id})
        return True, "Aufgabe gelöscht!"
    except: return False, "Fehler beim Löschen."

def delete_event(event_id):
    try:
        with engine.begin() as conn:
            # Lösche erst alle Tasks, die an dieses Event gekoppelt sind
            conn.execute(text("DELETE FROM tasks WHERE event_id = :e"), {"e": event_id})
            conn.execute(text("DELETE FROM events WHERE event_id = :e"), {"e": event_id})
        return True, "Spieltag inkl. Aufgaben gelöscht!"
    except Exception as e: return False, str(e)

def accept_task(task_id, user_id):
    try:
        with engine.begin() as conn:
            existing = conn.execute(text("SELECT 1 FROM task_assignments WHERE task_id = :t AND user_id = :u"), {"t": task_id, "u": user_id}).scalar()
            if existing: return False, "Bereits eingetragen!"
            conn.execute(text("INSERT INTO task_assignments (task_id, user_id) VALUES (:t, :u)"), {"t": task_id, "u": user_id})
        return True, "Übernommen!"
    except Exception as e: return False, str(e)


# ==========================================
# 5. UI COMPONENTS
# ==========================================
st.title("🏐 TuB Helfer-Orga")
TEAM_LISTE = ["U12", "U13", "U14", "U16", "U18", "U20", "Herren 1", "Herren 2", "Herren 3", "Herren 4"]

if 'logged_in_user' not in st.session_state:
    st.session_state['logged_in_user'] = None

if get_user_count() == 0:
    st.warning("⚠️ Keine Benutzer in der Datenbank gefunden. Richte den Admin ein:")
    with st.form("setup"):
        if st.form_submit_button("Admin erstellen") and create_initial_admin(st.text_input("Name"), st.text_input("E-Mail"), st.text_input("Passwort", type="password")):
            st.success("Erstellt! Lade die Seite neu.")
            st.rerun()

elif st.session_state['logged_in_user'] is None:
    t_login, t_reg = st.tabs(["🔑 Einloggen", "📝 Neu Registrieren"])
    with t_login:
        with st.form("login"):
            user = authenticate(st.text_input("E-Mail"), st.text_input("Passwort", type="password"))
            if st.form_submit_button("Einloggen"):
                if user:
                    st.session_state['logged_in_user'] = user
                    st.rerun()
                else: st.error("Zugangsdaten ungültig.")
    with t_reg:
        with st.form("reg"):
            n, e, p = st.text_input("Name"), st.text_input("E-Mail"), st.text_input("Passwort", type="password")
            r, t = st.selectbox("Rolle", ["Spieler", "Trainer", "Elternteil", "Organisator"]), st.multiselect("Team", TEAM_LISTE)
            dsgvo = st.checkbox("DSGVO zustimmen")
            if st.form_submit_button("Registrieren") and dsgvo and n and e and p:
                succ, msg = register_new_user(n, e, p, r, t)
                if succ: st.success(msg)
                else: st.error(msg)

else:
    user = st.session_state['logged_in_user']
    st.write(f"Willkommen zurück, **{user['name']}** - {user['rolle']}!")
    if st.button("🚪 Ausloggen"):
        st.session_state['logged_in_user'] = None
        st.rerun()

    # DATEN LADEN
    children_df = get_children(user['user_id'])
    tasks_df = get_all_tasks()
    assign_df = get_task_assignments()
    events_df = get_all_events()

    # TEAM LOGIK FÜR FILTER
    my_teams = set()
    if user.get('team') and user['team'] != "Kein Team": my_teams.update([t.strip() for t in user['team'].split(',')])
    if not children_df.empty:
        for _, c in children_df.iterrows():
            if c.get('team') and c['team'] != "Kein Team": my_teams.update([t.strip() for t in c['team'].split(',')])
    
    def is_relevant(teams_str):
        if pd.isna(teams_str) or not str(teams_str).strip(): return True # Allgemeine Termine
        return any(t.strip() in my_teams for t in str(teams_str).split(','))

    # TABS AUFBAUEN
    tab_titles = ["🏆 Spieltage & Events", "📋 Freie Aufgaben", "📅 Kalender-Ansicht", "👨‍👩‍👧 Familie"]
    if user['rolle'] == 'Admin': tab_titles.append("👥 Admin")
    tabs = st.tabs(tab_titles)

    # Session State für die Team-Navigation initialisieren
    if 'selected_event_team' not in st.session_state:
        st.session_state['selected_event_team'] = None

    # ----------------------------------------------------
    # TAB 1: SPIELTAGE & EVENTS (NEU)
    # ----------------------------------------------------
    with tabs[0]:
        st.write("Hier findest du organisierte Spieltage. Wähle eine Altersklasse/ein Team, um die Termine zu sehen.")
        
        rel_events = events_df[events_df['betroffene_teams'].apply(is_relevant)] if not events_df.empty else pd.DataFrame()
        
        # Helfer-Funktion zum Zeichnen der Events, damit wir Code nicht doppeln
        def render_event_list(events_to_show):
            for _, ev in events_to_show.iterrows():
                ev_id = ev['event_id']
                with st.expander(f"🏐 {ev['titel']} ({ev['start_zeit']})", expanded=False):
                    st.write(f"📍 **Ort:** {ev['ort']} | 👕 **Teams:** {ev['betroffene_teams']}")
                    
                    # Tasks für dieses Event laden
                    ev_tasks = tasks_df[tasks_df['event_id'] == ev_id] if not tasks_df.empty else pd.DataFrame()
                    
                    st.markdown("#### Organisation & Aufgaben:")
                    if not ev_tasks.empty:
                        for _, tsk in ev_tasks.iterrows():
                            t_id = tsk['task_id']
                            t_assigns = assign_df[assign_df['task_id'] == t_id] if not assign_df.empty else pd.DataFrame()
                            cur_h = len(t_assigns)
                            max_h = int(tsk.get('max_helfer', 1))
                            
                            tc1, tc2 = st.columns([3, 2])
                            with tc1:
                                st.write(f"**{tsk['kategorie']}** ({cur_h}/{max_h} belegt)")
                                st.caption(tsk['beschreibung'])
                                if cur_h > 0: st.write("👥 " + ", ".join(t_assigns['assignee_name'].tolist()))
                            with tc2:
                                options = {user['user_id']: "Ich selbst"}
                                if not children_df.empty:
                                    for _, child in children_df.iterrows(): options[child['user_id']] = f"Kind: {child['name']}"
                                if not t_assigns.empty:
                                    options = {k: v for k, v in options.items() if k not in t_assigns['user_id'].tolist()}
                                
                                if cur_h < max_h:
                                    if options:
                                        sel_u = st.selectbox("Wer?", list(options.keys()), format_func=lambda x: options[x], key=f"sel_ev_{t_id}", label_visibility="collapsed")
                                        if st.button("Eintragen", key=f"btn_ev_{t_id}"):
                                            success, msg = accept_task(t_id, sel_u)
                                            if success: st.success(msg); st.rerun()
                                    else: st.success("✅ Du bist eingetragen.")
                                else: st.success("✅ Voll belegt.")
                                
                                if user['rolle'] in ['Admin', 'Organisator'] or tsk.get('erstellt_von') == user['user_id']:
                                    if st.button("🗑️ Löschen", key=f"del_ev_{t_id}"): 
                                        delete_task(t_id); st.rerun()
                            st.divider()
                    else:
                        st.info("Noch keine Aufgaben für dieses Event hinterlegt.")
                        
                    # Neue Aufgabe ZU DIESEM EVENT hinzufügen
                    if user['rolle'] in ['Admin', 'Organisator']:
                        st.markdown("➕ **Neuen Orga-Punkt für dieses Event erstellen**")
                        with st.form(f"form_ev_{ev_id}"):
                            nk = st.text_input("Was wird gebraucht? (z.B. Kuchen, Fahrer, Spielerzusage)")
                            nb = st.text_area("Details")
                            nm = st.number_input("Anzahl Personen", min_value=1, value=1)
                            if st.form_submit_button("Zum Event hinzufügen"):
                                if nk:
                                    create_task(nk, nb, nm, user['user_id'], ev['start_zeit'], ev['ende_zeit'], ev['betroffene_teams'], event_id=ev_id)
                                    st.rerun()
                                    
                    # Event löschen
                    if user['rolle'] == 'Admin':
                        if st.button("🚨 Komplettes Event löschen", key=f"del_event_{ev_id}"):
                            delete_event(ev_id); st.rerun()

        if not rel_events.empty:
            if st.session_state['selected_event_team'] is None:
                # --- KACHEL-ANSICHT ---
                available_teams = set()
                for _, ev in rel_events.iterrows():
                    if pd.notna(ev['betroffene_teams']):
                        available_teams.update([t.strip() for t in str(ev['betroffene_teams']).split(',')])
                
                valid_teams = sorted(list(available_teams))
                
                if valid_teams:
                    st.markdown("### Wähle eine Altersklasse / ein Team:")
                    # Kacheln als Buttons in 3er Spalten
                    cols = st.columns(3)
                    for i, t_name in enumerate(valid_teams):
                        with cols[i % 3]:
                            if st.button(f"🏐 {t_name}", key=f"tile_{t_name}", use_container_width=True):
                                st.session_state['selected_event_team'] = t_name
                                st.rerun()
                else:
                    st.info("Keine spezifischen Teams in den Spieltagen hinterlegt.")
            else:
                # --- DETAIL-ANSICHT EINES TEAMS ---
                sel_team = st.session_state['selected_event_team']
                
                col_back, col_title = st.columns([1, 4])
                with col_back:
                    if st.button("🔙 Zurück", use_container_width=True):
                        st.session_state['selected_event_team'] = None
                        st.rerun()
                with col_title:
                    st.markdown(f"### Termine für: **{sel_team}**")
                
                # Nur Events filtern, die dieses Team enthalten
                def is_selected_team(teams_str):
                    if pd.isna(teams_str): return False
                    return sel_team in [t.strip() for t in str(teams_str).split(',')]
                    
                team_events = rel_events[rel_events['betroffene_teams'].apply(is_selected_team)].copy()
                
                if not team_events.empty:
                    # Datum parsen, um zwischen "Nächstes" und "Kommende" zu unterscheiden
                    team_events['sort_date'] = pd.to_datetime(
                        team_events['start_zeit'].astype(str).str.replace(' Uhr', ''), 
                        dayfirst=True, 
                        errors='coerce'
                    )
                    
                    now = pd.Timestamp(datetime.datetime.now())
                    
                    # Aufteilen in Zukunft, Vergangenheit, etc.
                    future_events = team_events[team_events['sort_date'] >= now].sort_values('sort_date')
                    past_events = team_events[team_events['sort_date'] < now].sort_values('sort_date', ascending=False)
                    unparsed_events = team_events[team_events['sort_date'].isna()]
                    
                    if not future_events.empty:
                        # Findet als nächstes statt (am ersten verfügbaren Datum)
                        next_date = future_events.iloc[0]['sort_date'].date()
                        next_events = future_events[future_events['sort_date'].dt.date == next_date]
                        upcoming_events = future_events[future_events['sort_date'].dt.date > next_date]
                        
                        st.markdown("#### 🚨 Findet als nächstes statt")
                        render_event_list(next_events)
                        
                        if not upcoming_events.empty:
                            st.markdown("#### 📅 Kommende Termine")
                            render_event_list(upcoming_events)
                    else:
                        st.success("Keine anstehenden Termine in der Zukunft!")
                        
                    if not past_events.empty or not unparsed_events.empty:
                        with st.expander("🕰️ Vergangene / Unbestimmte Termine"):
                            if not past_events.empty:
                                render_event_list(past_events)
                            if not unparsed_events.empty:
                                render_event_list(unparsed_events)
                else:
                    st.info("Für dieses Team wurden noch keine Spieltage angelegt.")
        else:
            st.info("Keine Spieltage für deine Teams gefunden.")

    # ----------------------------------------------------
    # TAB 2: FREIE AUFGABEN (STANDALONE)
    # ----------------------------------------------------
    with tabs[1]:
        if user['rolle'] in ['Admin', 'Organisator']:
            with st.expander("➕ Allgemeine Aufgabe anlegen (Ohne Event-Bezug)"):
                with st.form("new_task_form"):
                    k = st.text_input("Kategorie")
                    b = st.text_area("Details")
                    m = st.number_input("Helfer", min_value=1, value=1)
                    t = st.multiselect("Teams", TEAM_LISTE)
                    c1, c2 = st.columns(2)
                    with c1: sd, stt = st.date_input("Start"), st.time_input("Zeit")
                    if st.form_submit_button("Speichern"):
                        dt_str = f"{sd.strftime('%d.%m.%Y')} {stt.strftime('%H:%M')} Uhr"
                        create_task(k, b, m, user['user_id'], dt_str, None, ", ".join(t) if t else None)
                        st.rerun()
                        
        st.write("")
        # Zeige nur Tasks, die NICHT an ein Event gekoppelt sind
        free_tasks = tasks_df[tasks_df['event_id'].isna()] if not tasks_df.empty else pd.DataFrame()
        
        if not free_tasks.empty:
            for _, row in free_tasks.iterrows():
                t_id = row['task_id']
                t_assigns = assign_df[assign_df['task_id'] == t_id] if not assign_df.empty else pd.DataFrame()
                cur_h, max_h = len(t_assigns), int(row.get('max_helfer', 1))
                
                with st.container():
                    col1, col2 = st.columns([3, 2])
                    with col1:
                        st.write(f"**{row['kategorie']}**")
                        if pd.notna(row.get('start_zeit')): st.write(f"🗓️ {row['start_zeit']}")
                        if pd.notna(row.get('betroffene_teams')) and row['betroffene_teams']: st.write(f"👕 Teams: {row['betroffene_teams']}")
                        st.caption(row['beschreibung'])
                        st.write(f"👥 {cur_h}/{max_h} belegt. " + ", ".join(t_assigns['assignee_name'].tolist()))
                    with col2:
                        options = {user['user_id']: "Ich selbst"}
                        if not children_df.empty:
                            for _, child in children_df.iterrows(): options[child['user_id']] = f"Kind: {child['name']}"
                        if not t_assigns.empty: options = {k: v for k, v in options.items() if k not in t_assigns['user_id'].tolist()}
                        
                        if cur_h < max_h:
                            if options:
                                sel_u = st.selectbox("Wer?", list(options.keys()), key=f"sel_f_{t_id}", label_visibility="collapsed")
                                if st.button("Übernehmen", key=f"btn_f_{t_id}"):
                                    accept_task(t_id, sel_u); st.rerun()
                            else: st.success("✅ Eingetragen.")
                        else: st.success("✅ Voll!")
                        
                        if user['rolle'] == 'Admin' or row.get('erstellt_von') == user['user_id']:
                            if st.button("🗑️ Löschen", key=f"del_f_{t_id}"): delete_task(t_id); st.rerun()
                st.divider()
        else: st.info("Aktuell keine allgemeinen Aufgaben.")

    # ----------------------------------------------------
    # TAB 3: KALENDER
    # ----------------------------------------------------
    with tabs[2]:
        st.write("Chronologische Übersicht der Termine (Events & Aufgaben).")
        
        # NEU: Dropdown für den Team-Filter im Kalender
        filter_optionen = ["Alle meine Teams"] + TEAM_LISTE
        selected_cal_team = st.selectbox("Kalender filtern nach Team:", filter_optionen)
        
        # Eigene Filter-Logik für den Kalender
        def cal_is_relevant(teams_str):
            # Wenn "Alle" ausgewählt ist, greift die normale Logik (zeigt eigene Teams + allgemeine Termine)
            if selected_cal_team == "Alle meine Teams":
                return is_relevant(teams_str)
            # Wenn ein festes Team ausgewählt wurde, blende allgemeine Termine aus und suche exakt nach dem Team
            else:
                if pd.isna(teams_str) or not str(teams_str).strip():
                    return False
                return selected_cal_team in [t.strip() for t in str(teams_str).split(',')]

        cal_data = []
        
        # Events in Kalender packen
        if not events_df.empty:
            for _, ev in events_df[events_df['betroffene_teams'].apply(cal_is_relevant)].iterrows():
                cal_data.append({"Datum": ev['start_zeit'], "Typ": "🏆 Spieltag", "Titel": ev['titel'], "Teams": ev['betroffene_teams']})
        
        # Allgemeine Tasks in Kalender packen
        if not tasks_df.empty:
            for _, tk in tasks_df[tasks_df['event_id'].isna() & tasks_df['betroffene_teams'].apply(cal_is_relevant)].iterrows():
                if pd.notna(tk.get('start_zeit')):
                    cal_data.append({"Datum": tk['start_zeit'], "Typ": "📋 Aufgabe", "Titel": tk['kategorie'], "Teams": tk['betroffene_teams']})
                    
        if cal_data:
            cal_df = pd.DataFrame(cal_data)
            try:
                cal_df['sort_date'] = pd.to_datetime(cal_df['Datum'].str.replace(' Uhr', ''), format='%d.%m.%Y %H:%M', errors='coerce')
                cal_df = cal_df.sort_values(by='sort_date').drop(columns=['sort_date'])
            except: pass
            st.dataframe(cal_df, use_container_width=True, hide_index=True)
        else: st.info("Keine Einträge im Kalender.")

    # ----------------------------------------------------
    # TAB 4: FAMILIE
    # ----------------------------------------------------
    with tabs[3]:
        with st.form("add_c"):
            c1, c2 = st.columns(2)
            with c1: cn = st.text_input("Name Kind")
            with c2: ct = st.multiselect("Teams", TEAM_LISTE)
            if st.form_submit_button("Kind anlegen") and cn:
                add_child(user['user_id'], cn, ct); st.rerun()
                
        with st.form("link_c"):
            all_k = get_all_children_in_db()
            if not all_k.empty:
                opts = {r['user_id']: f"{r['name']} ({r['team']})" for _, r in all_k.iterrows()}
                sk = st.selectbox("Bestehendes Kind verknüpfen", list(opts.keys()), format_func=lambda x: opts[x])
                if st.form_submit_button("Verknüpfen"): link_existing_child(user['user_id'], sk); st.rerun()

    # ----------------------------------------------------
    # TAB 5: ADMIN
    # ----------------------------------------------------
    if user['rolle'] == 'Admin':
        with tabs[4]:
            st.subheader("📅 ICS Kalender-Import")
            st.write("Lade hier den Spielplan (ICS-Datei aus SAMS/Web) eines Teams hoch. Daraus werden automatisch 'Events' erstellt.")
            with st.form("ics_import"):
                ics_file = st.file_uploader("ICS-Datei auswählen", type=["ics"])
                target_team = st.multiselect("Für welches Team gilt dieser Spielplan?", TEAM_LISTE)
                if st.form_submit_button("Spielplan importieren"):
                    if ics_file and target_team:
                        succ, msg = parse_and_import_ics(ics_file.read(), ", ".join(target_team))
                        if succ: st.success(msg)
                        else: st.error(msg)
                    else: st.warning("Bitte Datei und Team wählen.")
                    
            st.divider()
            st.subheader("👥 User-Verwaltung")
            with engine.connect() as conn:
                df_u = pd.read_sql("SELECT user_id, name, email, rolle, team FROM users", conn)
            st.dataframe(df_u, use_container_width=True)
            with st.form("del_u"):
                opts = {r['user_id']: f"{r['name']} ({r['rolle']})" for _, r in df_u.iterrows()}
                d_id = st.selectbox("Löschen:", list(opts.keys()), format_func=lambda x: opts[x])
                if st.form_submit_button("User Löschen") and d_id != user['user_id']:
                    delete_user(d_id); st.rerun()
