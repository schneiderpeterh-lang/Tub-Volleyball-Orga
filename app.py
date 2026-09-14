import streamlit as st
import pandas as pd
import datetime
import hashlib
import secrets
import uuid
from sqlalchemy import create_engine, text

try:
    import icalendar
except ImportError:
    st.error("📦 **Fehlendes Paket!** Bitte füge `icalendar` zu deiner `requirements.txt` auf GitHub hinzu, um den Kalender-Import zu nutzen.")
    st.stop()

try:
    from streamlit_calendar import calendar
except ImportError:
    st.error("📦 **Fehlendes Paket!** Bitte füge `streamlit-calendar` zu deiner `requirements.txt` auf GitHub hinzu, um die Kalender-Ansicht zu nutzen.")
    st.stop()

# ==========================================
# 1. KONFIGURATION & DATENBANK-VERBINDUNG
# ==========================================
st.set_page_config(page_title="TuB Orga", page_icon="🏐", layout="wide", initial_sidebar_state="expanded")

with st.sidebar:
    st.title("🏐 TuB Bocholt")
    st.markdown("### Helfer-Organisation")
    st.markdown("Hier organisieren wir unsere Spieltage, Turniere und Aufgaben im Verein.")
    st.divider()
    st.markdown("#### Rechtliches")
    
    with st.expander("⚖️ Impressum", expanded=False):
        st.markdown("""
        **TuB Bocholt 1907 e.V.**
        Abteilung Volleyball
        Lowicker Str. 19c
        46395 Bocholt
        """)
        
    with st.expander("🛡️ Datenschutz", expanded=False):
        st.markdown("""
        **Zweck der Datenspeicherung:**
        Wir speichern deinen Namen, deine E-Mail-Adresse und deine Teamzugehörigkeit ausschließlich zur internen Organisation.
        """)
        
    st.divider()
    st.caption("App-Version 1.6 (Inkl. Punkte & Bugfixes) | Status: Online 🟢")

def inject_custom_css():
    st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stButton > button {
        border-radius: 8px !important;
        transition: all 0.3s ease !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1) !important;
        font-weight: 500 !important;
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 10px rgba(0,0,0,0.15) !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        padding-bottom: 5px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 6px 6px 0px 0px;
        padding: 10px 16px;
        transition: background-color 0.3s ease;
    }
    .stTabs [aria-selected="true"] {
        background-color: rgba(28, 131, 225, 0.1); 
        border-bottom: 3px solid #1c83e1;
    }
    div[data-testid="stContainer"] {
        border-radius: 12px;
        transition: all 0.3s ease;
    }
    div[data-testid="stContainer"]:hover {
        border-color: #1c83e1;
    }
    </style>
    """, unsafe_allow_html=True)

inject_custom_css()

@st.cache_resource
def get_database_engine():
    try:
        db_url = st.secrets["DB_URL"].replace("6543", "5432")
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://")
        return create_engine(
            db_url, 
            connect_args={"sslmode": "require", "connect_timeout": 15},
            pool_pre_ping=True
        )
    except Exception as e:
        st.error(f"Datenbankfehler: {e}")
        st.stop()

engine = get_database_engine()

# ==========================================
# 2. DATENBANK-TABELLEN INITIALISIEREN
# ==========================================
@st.cache_resource
def update_db_schema(_engine):
    with _engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                user_id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                rolle TEXT NOT NULL,
                dsgvo_akzeptiert INTEGER DEFAULT 0,
                parent_id INTEGER REFERENCES users(user_id),
                team TEXT
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS teams (
                team_id SERIAL PRIMARY KEY,
                team_name TEXT NOT NULL
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS events (
                event_id SERIAL PRIMARY KEY,
                team_id INTEGER REFERENCES teams(team_id),
                titel TEXT,
                start_zeit TEXT,
                ende_zeit TEXT,
                ort TEXT,
                betroffene_teams TEXT,
                event_typ TEXT
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id SERIAL PRIMARY KEY,
                event_id INTEGER REFERENCES events(event_id) ON DELETE CASCADE,
                kategorie TEXT,
                beschreibung TEXT,
                max_helfer INTEGER DEFAULT 1,
                erstellt_von INTEGER REFERENCES users(user_id),
                start_zeit TEXT,
                ende_zeit TEXT,
                betroffene_teams TEXT,
                zugewiesen_an INTEGER REFERENCES users(user_id),
                tausch_angefragt INTEGER DEFAULT 0
            );
        """))
        
        try:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS punkte INTEGER DEFAULT 1;"))
        except Exception:
            pass

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS parent_child (
                parent_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
                child_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
                PRIMARY KEY (parent_id, child_id)
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS task_assignments (
                assignment_id SERIAL PRIMARY KEY,
                task_id INTEGER REFERENCES tasks(task_id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
                kommentar TEXT
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS event_attendance (
                event_id INTEGER REFERENCES events(event_id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
                status TEXT NOT NULL,
                PRIMARY KEY (event_id, user_id)
            );
        """))
    return True

try:
    update_db_schema(engine)
except Exception as e:
    st.error(f"Fehler bei Schema-Update: {e}")
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

def clear_caches():
    st.cache_data.clear()

@st.cache_data(ttl=60)
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
        clear_caches()
        return True
    except: return False

def authenticate(email, password):
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM users WHERE email = :email AND rolle != 'Kind'"), {"email": email}).fetchone()
        if result and verify_password(password, result.password_hash): return dict(result._mapping)
    return None

def register_new_user(name, email, password, rolle, team_list):
    hashed = hash_password(password)
    team_str = ", ".join(team_list) if team_list else "Kein Team"
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, team) VALUES (:n, :e, :h, :r, 1, :t)"),
                {"n": name, "e": email, "h": hashed, "r": rolle, "t": team_str})
        clear_caches()
        return True, "Erfolgreich registriert!"
    except Exception as e:
        return False, str(e)

@st.cache_data(ttl=60)
def get_children(parent_id):
    try:
        with engine.connect() as conn:
            return pd.read_sql(text("SELECT DISTINCT u.user_id, u.name, u.team FROM users u LEFT JOIN parent_child pc ON u.user_id = pc.child_id WHERE u.parent_id = :p OR pc.parent_id = :p"), conn, params={"p": parent_id})
    except: return pd.DataFrame()

@st.cache_data(ttl=60)
def get_all_users():
    try:
        with engine.connect() as conn:
            return pd.read_sql(text("SELECT user_id, name, email, rolle, team FROM users ORDER BY name"), conn)
    except: return pd.DataFrame()

# ==========================================
# 4. EVENTS, AUFGABEN & PUNKTE SQL
# ==========================================
@st.cache_data(ttl=60)
def get_user_points_df():
    try:
        with engine.connect() as conn:
            query = text("""
                SELECT 
                    u.user_id,
                    u.name,
                    u.rolle,
                    u.team,
                    COALESCE(SUM(t.punkte), 0) AS gesamt_punkte
                FROM users u
                LEFT JOIN task_assignments ta ON u.user_id = ta.user_id
                LEFT JOIN tasks t ON ta.task_id = t.task_id
                GROUP BY u.user_id, u.name, u.rolle, u.team
            """)
            return pd.read_sql(query, conn)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=60)
def get_all_events():
    try:
        with engine.connect() as conn:
            return pd.read_sql(text("SELECT * FROM events ORDER BY event_id DESC"), conn)
    except: return pd.DataFrame()

@st.cache_data(ttl=60)
def get_all_tasks():
    try:
        with engine.connect() as conn: 
            return pd.read_sql(text("SELECT task_id, event_id, kategorie, beschreibung, max_helfer, punkte, erstellt_von, start_zeit, ende_zeit, betroffene_teams FROM tasks ORDER BY task_id DESC"), conn)
    except: return pd.DataFrame()

@st.cache_data(ttl=60)
def get_task_assignments():
    try:
        with engine.connect() as conn:
            return pd.read_sql(text("SELECT ta.task_id, ta.user_id, ta.kommentar, u.name as assignee_name FROM task_assignments ta JOIN users u ON ta.user_id = u.user_id"), conn)
    except: return pd.DataFrame()

@st.cache_data(ttl=60)
def get_all_attendance():
    try:
        with engine.connect() as conn:
            return pd.read_sql(text("""
                SELECT ea.event_id, ea.user_id, ea.status, u.name 
                FROM event_attendance ea
                JOIN users u ON ea.user_id = u.user_id
            """), conn)
    except: return pd.DataFrame()

def accept_task(task_id, user_id, kommentar=None):
    try:
        with engine.begin() as conn:
            existing = conn.execute(text("SELECT 1 FROM task_assignments WHERE task_id = :t AND user_id = :u"), {"t": task_id, "u": user_id}).scalar()
            if existing: return False, "Bereits eingetragen!"
            conn.execute(text("INSERT INTO task_assignments (task_id, user_id, kommentar) VALUES (:t, :u, :k)"), {"t": task_id, "u": user_id, "k": kommentar})
        clear_caches()
        return True, "Übernommen!"
    except Exception as e: return False, str(e)

def cancel_task(task_id, user_id):
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM task_assignments WHERE task_id = :t AND user_id = :u"), {"t": task_id, "u": user_id})
        clear_caches()
        return True, "Aufgabe erfolgreich freigegeben!"
    except Exception as e:
        return False, str(e)

def create_task(kategorie, beschreibung, max_helfer, punkte, user_id, start=None, ende=None, teams=None, event_id=None):
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO tasks (kategorie, beschreibung, max_helfer, punkte, erstellt_von, start_zeit, ende_zeit, betroffene_teams, event_id)
                VALUES (:kat, :besch, :max, :pkt, :erst, :st, :en, :teams, :ev)
            """), {"kat": kategorie, "besch": beschreibung, "max": max_helfer, "pkt": punkte, "erst": user_id, "st": start, "en": ende, "teams": teams, "ev": event_id})
        clear_caches()
        return True, "Aufgabe erstellt!"
    except Exception as e: return False, str(e)

def delete_task(task_id):
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM task_assignments WHERE task_id = :t"), {"t": task_id})
            conn.execute(text("DELETE FROM tasks WHERE task_id = :t"), {"t": task_id})
        clear_caches()
        return True, "Aufgabe gelöscht!"
    except Exception as e: return False, str(e)

def delete_event(event_id):
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM tasks WHERE event_id = :e"), {"e": event_id})
            conn.execute(text("DELETE FROM event_attendance WHERE event_id = :e"), {"e": event_id})
            conn.execute(text("DELETE FROM events WHERE event_id = :e"), {"e": event_id})
        clear_caches()
        return True, "Spieltag gelöscht!"
    except Exception as e: return False, str(e)

def set_event_attendance(event_id, user_id, status):
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO event_attendance (event_id, user_id, status)
                VALUES (:e, :u, :s)
                ON CONFLICT (event_id, user_id) 
                DO UPDATE SET status = EXCLUDED.status
            """), {"e": event_id, "u": user_id, "s": status})
        clear_caches()
        return True
    except Exception as e: return False

def update_event_location(event_id, neuer_ort):
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE events SET ort = :ort WHERE event_id = :id"), {"ort": neuer_ort, "id": event_id})
        clear_caches()
        return True
    except Exception:
        return False

# ==========================================
# 5. UI COMPONENTS
# ==========================================
st.title("🏐 TuB Helfer-Orga")
TEAM_LISTE = ["U12", "U13", "U14", "U16", "U18", "U20", "Herren 1", "Herren 2", "Herren 3", "Herren 4", "Damen 1"]
KATEGORIE_OPTIONEN = ["Fahrdienst", "Catering", "Schiedsgericht", "Sonstiges (Freitext)"]

if 'logged_in_user' not in st.session_state:
    st.session_state['logged_in_user'] = None

if get_user_count() == 0:
    st.warning("⚠️ Keine Benutzer gefunden. Richte den Admin ein:")
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
                else: 
                    st.error("Zugangsdaten ungültig.")
    with t_reg:
        with st.form("reg"):
            n, e, p = st.text_input("Name"), st.text_input("E-Mail"), st.text_input("Passwort", type="password")
            r, t = st.selectbox("Rolle", ["Spieler", "Trainer", "Elternteil", "Organisator"]), st.multiselect("Team", TEAM_LISTE)
            dsgvo = st.checkbox("DSGVO zustimmen")
            if st.form_submit_button("Registrieren"):
                if dsgvo and n and e and p:
                    succ, msg = register_new_user(n, e, p, r, t)
                    if succ: st.success(msg)
                    else: st.error(msg)
                else:
                    st.warning("Bitte fülle alle Pflichtfelder aus und stimme der DSGVO zu.")

else:
    user = st.session_state['logged_in_user']
    col_w, col_logout = st.columns([5, 1])
    with col_w:
        st.write(f"Willkommen zurück, **{user['name']}** - {user['rolle']}!")
    with col_logout:
        if st.button("🚪 Ausloggen", use_container_width=True):
            st.session_state['logged_in_user'] = None
            st.rerun()

    children_df = get_children(user['user_id'])
    tasks_df = get_all_tasks()
    assign_df = get_task_assignments()
    events_df = get_all_events()
    points_df = get_user_points_df()
    all_attendance_df = get_all_attendance()
    all_users_df = get_all_users()

    if not assign_df.empty:
        assign_df['display_name'] = assign_df.apply(
            lambda r: f"{r['assignee_name']} ({r['kommentar']})" if pd.notna(r.get('kommentar')) and str(r.get('kommentar')).strip() else r['assignee_name'], 
            axis=1
        )

    my_teams = set()
    if user.get('team') and user['team'] != "Kein Team": my_teams.update([t.strip() for t in user['team'].split(',')])
    if not children_df.empty:
        for _, c in children_df.iterrows():
            if c.get('team') and c['team'] != "Kein Team": my_teams.update([t.strip() for t in c['team'].split(',')])
    
    def is_relevant(teams_str):
        if user['rolle'] in ['Admin', 'Organisator']: return True
        if pd.isna(teams_str) or not str(teams_str).strip(): return True
        return any(t.strip() in my_teams for t in str(teams_str).split(','))

    tab_titles = ["🏠 Übersicht", "🏆 Spieltage & Events", "📋 Freie Aufgaben"]
    if user['rolle'] != 'Elternteil': tab_titles.append("📅 Kalender-Ansicht")
    tab_titles.append("👨‍👩‍👧 Familie")
    if user['rolle'] == 'Admin': tab_titles.append("👥 Admin")
        
    tabs = st.tabs(tab_titles)
    
    tab_idx = 0
    tab_overview = tabs[tab_idx]; tab_idx += 1
    tab_events = tabs[tab_idx]; tab_idx += 1
    tab_tasks = tabs[tab_idx]; tab_idx += 1
    
    if user['rolle'] != 'Elternteil':
        tab_calendar = tabs[tab_idx]; tab_idx += 1
    else:
        tab_calendar = None
        
    tab_family = tabs[tab_idx]; tab_idx += 1
    
    if user['rolle'] == 'Admin':
        tab_admin = tabs[tab_idx]; tab_idx += 1
    else:
        tab_admin = None
    
    if 'selected_event_team' not in st.session_state:
        st.session_state['selected_event_team'] = None

    @st.dialog("⚠️ Aufgabe wirklich abgeben?")
    def confirm_cancel(t_id, u_id, t_name, u_name):
        st.warning(f"Möchtest du die Aufgabe **{t_name}** für **{u_name}** wirklich wieder freigeben?")
        st.write("Sie rutscht dadurch zurück in die Liste der offenen Aufgaben und kann von anderen übernommen werden.")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("❌ Ja, abgeben", use_container_width=True):
                succ, msg = cancel_task(t_id, u_id)
                if succ: st.rerun()
        with c2:
            if st.button("Behalten", type="primary", use_container_width=True):
                st.rerun()

    # ----------------------------------------------------
    # TAB 0: ÜBERSICHT (INKLUSIVE PUNKTE)
    # ----------------------------------------------------
    with tab_overview:
        
        user_points = 0
        if not points_df.empty and user['user_id'] in points_df['user_id'].values:
            user_points = int(points_df[points_df['user_id'] == user['user_id']]['gesamt_punkte'].iloc[0])

        st.metric(label="🌟 Deine gesammelten Helferpunkte", value=f"{user_points} Pkt.")
        
        if user['rolle'] in ['Admin', 'Organisator', 'Trainer']:
            with st.expander("📊 Punkte-Übersicht der Elternteile"):
                if not points_df.empty:
                    eltern_points = points_df[points_df['rolle'] == 'Elternteil'].copy()
                    
                    if user['rolle'] == 'Trainer' and user.get('team'):
                        trainer_teams = [t.strip() for t in user['team'].split(',')]
                        eltern_points = eltern_points[eltern_points['team'].apply(
                            lambda t: any(team in str(t) for team in trainer_teams) if pd.notna(t) else False
                        )]
                    
                    st.dataframe(
                        eltern_points[['name', 'team', 'gesamt_punkte']].rename(
                            columns={'name': 'Elternteil', 'team': 'Team', 'gesamt_punkte': 'Punkte'}
                        ).sort_values(by='Punkte', ascending=False),
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info("Noch keine Punkte erfasst.")
                    
        st.divider()
        st.write("Dein schneller Überblick: Wo wird aktuell Hilfe gebraucht und wofür bist du schon eingetragen?")
        
        my_family_uids = [user['user_id']]
        if not children_df.empty: my_family_uids.extend(children_df['user_id'].tolist())
        
        my_assigned_tids = assign_df[assign_df['user_id'].isin(my_family_uids)]['task_id'].unique().tolist() if not assign_df.empty else []
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### 🚨 Hilfe dringend gesucht")
            found_open = False
            if not tasks_df.empty:
                for _, tsk in tasks_df.iterrows():
                    if is_relevant(tsk.get('betroffene_teams')):
                        t_id = tsk['task_id']
                        t_assigns = assign_df[assign_df['task_id'] == t_id] if not assign_df.empty else pd.DataFrame()
                        cur_h = len(t_assigns)
                        max_h = int(tsk.get('max_helfer', 1))
                        
                        if cur_h < max_h:
                            found_open = True
                            context = "📋 Freie Aufgabe"
                            date_str = tsk.get('start_zeit', 'Kein Datum')
                            if pd.notna(tsk.get('event_id')):
                                ev_row = events_df[events_df['event_id'] == tsk['event_id']]
                                if not ev_row.empty:
                                    context = f"🏆 {ev_row.iloc[0]['titel']}"
                                    date_str = ev_row.iloc[0]['start_zeit']
                                    
                            with st.container(border=True):
                                st.write(f"**{tsk['kategorie']}** ({tsk.get('punkte', 1)} Pkt.)")
                                st.caption(f"{context} | 🗓️ {date_str}")
                                st.write(f"👥 Belegt: {cur_h} / {max_h}")
                                
                                options = {user['user_id']: "Ich selbst"}
                                if not children_df.empty:
                                    for _, child in children_df.iterrows(): options[child['user_id']] = f"Kind: {child['name']}"
                                if not t_assigns.empty:
                                    options = {k: v for k, v in options.items() if k not in t_assigns['user_id'].tolist()}
                                
                                if options:
                                    kat_lower = str(tsk['kategorie']).lower() 
                                    if "catering" in kat_lower or "fahr" in kat_lower or "auto" in kat_lower:
                                        with st.form(key=f"form_dash_{t_id}"):
                                            sel_u = st.selectbox("Wer?", list(options.keys()), format_func=lambda x: options[x], label_visibility="collapsed")
                                            if "catering" in kat_lower:
                                                kommentar = st.text_input("Was bringst du mit?", placeholder="z.B. Kuchen, Salat")
                                            else:
                                                kommentar = st.text_input("Freie Sitzplätze / Info:", placeholder="z.B. 3 freie Plätze")
                                                
                                            if st.form_submit_button("Übernehmen", use_container_width=True):
                                                if not kommentar.strip():
                                                    st.warning("Bitte fülle das Feld aus.")
                                                else:
                                                    success, msg = accept_task(t_id, sel_u, kommentar)
                                                    if success: st.rerun()
                                    else:
                                        c_sel, c_btn = st.columns([2, 1])
                                        with c_sel:
                                            sel_u = st.selectbox("Wer?", list(options.keys()), format_func=lambda x: options[x], key=f"dash_sel_{t_id}", label_visibility="collapsed")
                                        with c_btn:
                                            if st.button("Übernehmen", key=f"dash_btn_{t_id}", use_container_width=True):
                                                success, msg = accept_task(t_id, sel_u)
                                                if success: st.rerun()
            if not found_open:
                st.success("Aktuell sind alle Aufgaben für deine Teams belegt. Super!")

        with col2:
            st.markdown("#### ✅ Deine übernommenen Aufgaben")
            if my_assigned_tids:
                for t_id in my_assigned_tids:
                    tsk_row = tasks_df[tasks_df['task_id'] == t_id]
                    if not tsk_row.empty:
                        tsk = tsk_row.iloc[0]
                        fam_assigns = assign_df[(assign_df['task_id'] == t_id) & (assign_df['user_id'].isin(my_family_uids))]
                        
                        context = "📋 Freie Aufgabe"
                        date_str = tsk.get('start_zeit', 'Kein Datum')
                        if pd.notna(tsk.get('event_id')):
                            ev_row = events_df[events_df['event_id'] == tsk['event_id']]
                            if not ev_row.empty:
                                context = f"🏆 {ev_row.iloc[0]['titel']}"
                                date_str = ev_row.iloc[0]['start_zeit']
                                
                        with st.container(border=True):
                            st.write(f"**{tsk['kategorie']}**")
                            st.caption(f"{context} | 🗓️ {date_str}")
                            
                            for _, assign_row in fam_assigns.iterrows():
                                c1, c2 = st.columns([3, 1])
                                with c1:
                                    st.write(f"👷‍♂️ {assign_row['display_name']}")
                                with c2:
                                    if st.button("Abgeben", key=f"dash_cancel_{t_id}_{assign_row['user_id']}", use_container_width=True):
                                        confirm_cancel(t_id, assign_row['user_id'], tsk['kategorie'], assign_row['assignee_name'])
            else:
                st.info("Du bist aktuell für keine anstehenden Aufgaben eingetragen.")

    # ----------------------------------------------------
    # TAB 1: SPIELTAGE & EVENTS
    # ----------------------------------------------------
    with tab_events:
        st.write("Wähle eine Altersklasse/ein Team, um die Termine zu sehen.")
        
        rel_events = events_df[events_df['betroffene_teams'].apply(is_relevant)] if not events_df.empty else pd.DataFrame()
        
        admin_options = {}
        if user['rolle'] in ['Admin', 'Organisator'] and not all_users_df.empty:
            admin_options = {row['user_id']: f"Admin-Zuweisung: {row['name']}" for _, row in all_users_df.iterrows()}
            
        def render_event_list(events_to_show):
            for _, ev in events_to_show.iterrows():
                ev_id = ev['event_id']
                with st.expander(f"🏐 {ev['titel']} ({ev['start_zeit']})", expanded=False):
                    
                    ort_text = ev.get('ort')
                    if pd.isna(ort_text) or not str(ort_text).strip():
                        ort_text = "⚠️ Noch nicht festgelegt"
                        
                    st.write(f"📍 **Ort:** {ort_text} | 👕 **Teams:** {ev['betroffene_teams']}")
                    
                    if "⚠️" in ort_text and user['rolle'] in ['Admin', 'Organisator', 'Trainer']:
                        with st.form(f"form_ort_{ev_id}"):
                            c1, c2 = st.columns([3, 1])
                            with c1:
                                neuer_ort = st.text_input("Austragungsort nachtragen:", label_visibility="collapsed", placeholder="z.B. Sporthalle Lowick")
                            with c2:
                                if st.form_submit_button("Speichern", use_container_width=True) and neuer_ort:
                                    update_event_location(ev_id, neuer_ort)
                                    st.rerun()

                    st.markdown("#### 🏃‍♂️ Spieler-Teilnahme")
                    attendance_df = all_attendance_df[all_attendance_df['event_id'] == ev_id] if not all_attendance_df.empty else pd.DataFrame()
                    
                    if not attendance_df.empty:
                        dabei = attendance_df[attendance_df['status'] == 'dabei']['name'].tolist()
                        abgesagt = attendance_df[attendance_df['status'] == 'abgesagt']['name'].tolist()
                        
                        if dabei:
                            st.success(f"✅ **Dabei ({len(dabei)}):**\n" + "\n".join([f"- {name}" for name in dabei]))
                        if abgesagt:
                            st.error(f"❌ **Abgesagt ({len(abgesagt)}):**\n" + "\n".join([f"- {name}" for name in abgesagt]))
                    else:
                        st.info("Noch keine Rückmeldungen für diesen Spieltag.")
                    
                    att_options = {user['user_id']: "Ich selbst"}
                    if not children_df.empty:
                        for _, child in children_df.iterrows(): att_options[child['user_id']] = f"Kind: {child['name']}"
                    
                    if user['rolle'] in ['Admin', 'Organisator']:
                        for uid, uname in admin_options.items():
                            if uid not in att_options: att_options[uid] = uname
                                
                    c1, c2, c3 = st.columns([2, 1, 1])
                    with c1:
                        sel_att_u = st.selectbox("Wer?", list(att_options.keys()), format_func=lambda x: att_options[x], key=f"att_u_{ev_id}", label_visibility="collapsed")
                    with c2:
                        if st.button("✅ Bin dabei", key=f"btn_yes_{ev_id}", use_container_width=True):
                            set_event_attendance(ev_id, sel_att_u, 'dabei')
                            st.rerun()
                    with c3:
                        if st.button("❌ Absagen", key=f"btn_no_{ev_id}", use_container_width=True):
                            set_event_attendance(ev_id, sel_att_u, 'abgesagt')
                            st.rerun()
                            
                    st.divider()
                    
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
                                st.write(f"**{tsk['kategorie']}** ({tsk.get('punkte', 1)} Pkt.)")
                                st.caption(tsk['beschreibung'])
                                
                                belegt_text = "Niemand" if t_assigns.empty else ", ".join(t_assigns['display_name'].tolist())
                                st.write(f"👥 Belegt: {cur_h} / {max_h}. {belegt_text}")
                                
                                fam_in_task = t_assigns[t_assigns['user_id'].isin(my_family_uids)] if not t_assigns.empty else pd.DataFrame()
                                if not fam_in_task.empty:
                                    for _, fam_row in fam_in_task.iterrows():
                                        f_col1, f_col2 = st.columns([2, 1])
                                        with f_col2:
                                            if st.button("Abgeben", key=f"ev_cancel_{t_id}_{fam_row['user_id']}", use_container_width=True):
                                                confirm_cancel(t_id, fam_row['user_id'], tsk['kategorie'], fam_row['assignee_name'])
                                                
                            with tc2:
                                options = {user['user_id']: "Ich selbst"}
                                if not children_df.empty:
                                    for _, child in children_df.iterrows(): options[child['user_id']] = f"Kind: {child['name']}"
                                if not t_assigns.empty:
                                    options = {k: v for k, v in options.items() if k not in t_assigns['user_id'].tolist()}
                                
                                if cur_h < max_h:
                                    if options:
                                        kat_lower = str(tsk['kategorie']).lower() 
                                        if "catering" in kat_lower or "fahr" in kat_lower or "auto" in kat_lower:
                                            with st.form(key=f"form_ev_{t_id}"):
                                                sel_u = st.selectbox("Wer?", list(options.keys()), format_func=lambda x: options[x], label_visibility="collapsed")
                                                if "catering" in kat_lower:
                                                    kommentar = st.text_input("Was bringst du mit?", placeholder="z.B. Kuchen, Salat")
                                                else:
                                                    kommentar = st.text_input("Freie Sitzplätze / Info:", placeholder="z.B. 3 freie Plätze")
                                                    
                                                if st.form_submit_button("Übernehmen", use_container_width=True):
                                                    if not kommentar.strip():
                                                        st.warning("Bitte fülle das Feld aus.")
                                                    else:
                                                        success, msg = accept_task(t_id, sel_u, kommentar)
                                                        if success: st.rerun()
                                        else:
                                            c_sel, c_btn = st.columns([2, 1])
                                            with c_sel:
                                                sel_u = st.selectbox("Wer?", list(options.keys()), format_func=lambda x: options[x], key=f"ev_sel_{t_id}", label_visibility="collapsed")
                                            with c_btn:
                                                if st.button("Übernehmen", key=f"ev_btn_{t_id}", use_container_width=True):
                                                    success, msg = accept_task(t_id, sel_u)
                                                    if success: st.rerun()
                                    else: st.success("✅ Familie komplett eingetragen.")
                                else: st.success("✅ Voll belegt.")
                                
                                if user['rolle'] in ['Admin', 'Organisator'] or tsk.get('erstellt_von') == user['user_id']:
                                    if st.button("🗑️ Löschen", key=f"del_ev_{t_id}"): 
                                        delete_task(t_id); st.rerun()
                            st.divider()
                    else:
                        st.info("Noch keine Aufgaben für dieses Event hinterlegt.")
                        
                    if user['rolle'] in ['Admin', 'Organisator', 'Trainer']:
                        st.markdown("➕ **Neuen Orga-Punkt erstellen**")
                        with st.form(f"form_create_ev_{ev_id}"):
                            nk_sel = st.selectbox("Kategorie / Was wird gebraucht?", KATEGORIE_OPTIONEN)
                            nk_free = st.text_input("Eigene Eingabe (falls Sonstiges gewählt wurde):")
                            nb = st.text_area("Details")
                            
                            c_h, c_p = st.columns(2)
                            with c_h: nm = st.number_input("Anzahl Personen", min_value=1, value=1)
                            with c_p: pkt = st.number_input("Punkte", min_value=1, value=1)
                            
                            if st.form_submit_button("Hinzufügen"):
                                final_nk = nk_free if nk_sel == "Sonstiges (Freitext)" else nk_sel
                                if final_nk:
                                    create_task(final_nk, nb, nm, pkt, user['user_id'], ev['start_zeit'], ev['ende_zeit'], ev['betroffene_teams'], event_id=ev_id)
                                    st.rerun()
                                    
                    if user['rolle'] == 'Admin':
                        if st.button("🚨 Komplettes Event löschen", key=f"del_event_{ev_id}"):
                            delete_event(ev_id); st.rerun()

        if not rel_events.empty:
            if st.session_state['selected_event_team'] is None:
                available_teams = set()
                for _, ev in rel_events.iterrows():
                    if pd.notna(ev['betroffene_teams']): available_teams.update([t.strip() for t in str(ev['betroffene_teams']).split(',')])
                valid_teams = sorted(list(available_teams))
                
                if valid_teams:
                    cols = st.columns(3)
                    for i, t_name in enumerate(valid_teams):
                        with cols[i % 3]:
                            if st.button(f"🏐 {t_name}", key=f"tile_{t_name}", use_container_width=True):
                                st.session_state['selected_event_team'] = t_name
                                st.rerun()
                else: st.info("Keine spezifischen Teams in den Spieltagen hinterlegt.")
            else:
                sel_team = st.session_state['selected_event_team']
                col_back, col_title = st.columns([1, 4])
                with col_back:
                    if st.button("🔙 Zurück", use_container_width=True):
                        st.session_state['selected_event_team'] = None
                        st.rerun()
                with col_title: st.markdown(f"### Termine für: **{sel_team}**")
                
                def is_selected_team(teams_str):
                    if pd.isna(teams_str): return False
                    return sel_team in [t.strip() for t in str(teams_str).split(',')]
                    
                team_events = rel_events[rel_events['betroffene_teams'].apply(is_selected_team)].copy()
                
                if not team_events.empty:
                    team_events['sort_date'] = pd.to_datetime(team_events['start_zeit'].astype(str).str.replace(' Uhr', ''), dayfirst=True, errors='coerce')
                    now = pd.Timestamp(datetime.datetime.now())
                    future_events = team_events[team_events['sort_date'] >= now].sort_values('sort_date')
                    past_events = team_events[team_events['sort_date'] < now].sort_values('sort_date', ascending=False)
                    unparsed_events = team_events[team_events['sort_date'].isna()]
                    
                    if not future_events.empty:
                        next_date = future_events.iloc[0]['sort_date'].date()
                        next_events = future_events[future_events['sort_date'].dt.date == next_date]
                        upcoming_events = future_events[future_events['sort_date'].dt.date > next_date]
                        
                        st.markdown("#### 🚨 Findet als nächstes statt")
                        render_event_list(next_events)
                        if not upcoming_events.empty:
                            st.markdown("#### 📅 Kommende Termine")
                            render_event_list(upcoming_events)
                    else: st.success("Keine anstehenden Termine in der Zukunft!")
                        
                    if not past_events.empty or not unparsed_events.empty:
                        with st.expander("🕰️ Vergangene / Unbestimmte Termine"):
                            if not past_events.empty: render_event_list(past_events)
                            if not unparsed_events.empty: render_event_list(unparsed_events)
                else: st.info("Für dieses Team wurden noch keine Spieltage angelegt.")
        else: st.info("Keine Spieltage für deine Teams gefunden.")

    # ----------------------------------------------------
    # TAB 2: FREIE AUFGABEN
    # ----------------------------------------------------
    with tab_tasks:
        if user['rolle'] in ['Admin', 'Organisator', 'Trainer']:
            with st.expander("➕ Allgemeine Aufgabe anlegen (Ohne Event-Bezug)"):
                with st.form("new_task_form"):
                    k_sel = st.selectbox("Kategorie", KATEGORIE_OPTIONEN)
                    k_free = st.text_input("Eigene Eingabe:")
                    b = st.text_area("Details")
                    
                    c_h, c_p = st.columns(2)
                    with c_h: m = st.number_input("Helfer", min_value=1, value=1)
                    with c_p: pkt = st.number_input("Punkte", min_value=1, value=1)
                    
                    t = st.multiselect("Teams", TEAM_LISTE)
                    c1, c2 = st.columns(2)
                    with c1: sd, stt = st.date_input("Start"), st.time_input("Zeit")
                    if st.form_submit_button("Speichern"):
                        final_k = k_free if k_sel == "Sonstiges (Freitext)" else k_sel
                        if final_k:
                            dt_str = f"{sd.strftime('%d.%m.%Y')} {stt.strftime('%H:%M')} Uhr"
                            create_task(final_k, b, m, pkt, user['user_id'], dt_str, None, ", ".join(t) if t else None)
                            st.rerun()
                        
        st.write("")
        free_tasks = tasks_df[tasks_df['event_id'].isna()] if not tasks_df.empty else pd.DataFrame()
        
        if not free_tasks.empty:
            for _, row in free_tasks.iterrows():
                if not is_relevant(row.get('betroffene_teams')): continue
                
                t_id = row['task_id']
                t_assigns = assign_df[assign_df['task_id'] == t_id] if not assign_df.empty else pd.DataFrame()
                cur_h, max_h = len(t_assigns), int(row.get('max_helfer', 1))
                
                with st.container():
                    col1, col2 = st.columns([3, 2])
                    with col1:
                        st.write(f"**{row['kategorie']}** ({row.get('punkte', 1)} Pkt.)")
                        if pd.notna(row.get('start_zeit')): st.write(f"🗓️ {row['start_zeit']}")
                        if pd.notna(row.get('betroffene_teams')) and row['betroffene_teams']: st.write(f"👕 Teams: {row['betroffene_teams']}")
                        st.caption(row['beschreibung'])
                        
                        belegt_text = "Niemand" if t_assigns.empty else ", ".join(t_assigns['display_name'].tolist())
                        st.write(f"👥 Belegt: {cur_h}/{max_h}. {belegt_text}")
                        
                        fam_in_task = t_assigns[t_assigns['user_id'].isin(my_family_uids)] if not t_assigns.empty else pd.DataFrame()
                        if not fam_in_task.empty:
                            for _, fam_row in fam_in_task.iterrows():
                                f_col1, f_col2 = st.columns([2, 1])
                                with f_col2:
                                    if st.button("Abgeben", key=f"free_cancel_{t_id}_{fam_row['user_id']}", use_container_width=True):
                                        confirm_cancel(t_id, fam_row['user_id'], row['kategorie'], fam_row['assignee_name'])
                                        
                    with col2:
                        options = {user['user_id']: "Ich selbst"}
                        if not children_df.empty:
                            for _, child in children_df.iterrows(): options[child['user_id']] = f"Kind: {child['name']}"
                        if not t_assigns.empty: options = {k: v for k, v in options.items() if k not in t_assigns['user_id'].tolist()}
                        
                        if cur_h < max_h:
                            if options:
                                kat_lower = str(row['kategorie']).lower() 
                                if "catering" in kat_lower or "fahr" in kat_lower or "auto" in kat_lower:
                                    with st.form(key=f"form_free_{t_id}"):
                                        sel_u = st.selectbox("Wer?", list(options.keys()), format_func=lambda x: options[x], label_visibility="collapsed")
                                        if "catering" in kat_lower:
                                            kommentar = st.text_input("Was bringst du mit?", placeholder="z.B. Kuchen, Salat")
                                        else:
                                            kommentar = st.text_input("Freie Sitzplätze / Info:", placeholder="z.B. 3 freie Plätze")
                                            
                                        if st.form_submit_button("Übernehmen", use_container_width=True):
                                            if not kommentar.strip():
                                                st.warning("Bitte fülle das Feld aus.")
                                            else:
                                                success, msg = accept_task(t_id, sel_u, kommentar)
                                                if success: st.rerun()
                                else:
                                    c_sel, c_btn = st.columns([2, 1])
                                    with c_sel:
                                        sel_u = st.selectbox("Wer?", list(options.keys()), format_func=lambda x: options[x], key=f"free_sel_{t_id}", label_visibility="collapsed")
                                    with c_btn:
                                        if st.button("Übernehmen", key=f"free_btn_{t_id}", use_container_width=True):
                                            success, msg = accept_task(t_id, sel_u)
                                            if success: st.rerun()
                            else: st.success("✅ Eingetragen.")
                        else: st.success("✅ Voll!")
                        
                        if user['rolle'] == 'Admin' or row.get('erstellt_von') == user['user_id']:
                            if st.button("🗑️ Löschen", key=f"del_f_{t_id}"): delete_task(t_id); st.rerun()
                st.divider()
        else: st.info("Aktuell keine allgemeinen Aufgaben.")

    # ----------------------------------------------------
    # TAB 3: KALENDER (Nicht für Elternteile)
    # ----------------------------------------------------
    if tab_calendar is not None:
        with tab_calendar:
            st.write("Chronologische Übersicht aller relevanten Termine in einem interaktiven Kalender.")
            
            filter_optionen = ["Alle meine Teams"] + TEAM_LISTE
            selected_cal_team = st.selectbox("Kalender filtern nach Team:", filter_optionen)
            
            def cal_is_relevant(teams_str):
                if selected_cal_team == "Alle meine Teams": return is_relevant(teams_str)
                else:
                    if pd.isna(teams_str) or not str(teams_str).strip(): return False
                    return selected_cal_team in [t.strip() for t in str(teams_str).split(',')]

            def parse_to_iso(date_str):
                if pd.isna(date_str) or not str(date_str).strip(): return None
                try:
                    clean_str = str(date_str).replace(' Uhr', '').strip()
                    dt = pd.to_datetime(clean_str, dayfirst=True, errors='coerce')
                    if pd.isna(dt): return None
                    return dt.isoformat()
                except: return None

            calendar_events = []
            
            if not events_df.empty:
                for _, ev in events_df[events_df['betroffene_teams'].apply(cal_is_relevant)].iterrows():
                    start_iso = parse_to_iso(ev['start_zeit'])
                    end_iso = parse_to_iso(ev.get('ende_zeit'))
                    if start_iso:
                        calendar_events.append({
                            "title": f"🏆 {ev['titel']} ({ev['betroffene_teams']})",
                            "start": start_iso,
                            "end": end_iso if end_iso else start_iso,
                            "backgroundColor": "#1c83e1",
                            "borderColor": "#1c83e1"
                        })
                        
            if not tasks_df.empty:
                for _, tk in tasks_df[tasks_df['event_id'].isna() & tasks_df['betroffene_teams'].apply(cal_is_relevant)].iterrows():
                    start_iso = parse_to_iso(tk.get('start_zeit'))
                    if start_iso:
                        calendar_events.append({
                            "title": f"📋 {tk['kategorie']} ({tk.get('betroffene_teams', 'Alle')})",
                            "start": start_iso,
                            "end": start_iso,
                            "backgroundColor": "#f9ab00",
                            "borderColor": "#f9ab00",
                            "textColor": "#000000"
                        })
                        
            if calendar_events:
                calendar_options = {
                    "headerToolbar": {
                        "left": "today prev,next",
                        "center": "title",
                        "right": "dayGridMonth,timeGridWeek,listMonth",
                    },
                    "initialView": "dayGridMonth",
                    "height": 600,
                    "navLinks": True,
                    "locale": "de",
                    "firstDay": 1,
                    "buttonText": {
                        "today": "Heute",
                        "month": "Monat",
                        "week": "Woche",
                        "list": "Liste"
                    }
                }
                
                custom_css = """
                    .fc-event-title { font-weight: 600; font-size: 0.85em; white-space: normal; }
                    .fc-toolbar-title { font-size: 1.2rem !important; }
                    .fc-button { border-radius: 6px !important; }
                    .fc-theme-standard .fc-scrollgrid { border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden; }
                    @media (max-width: 768px) {
                        .fc-toolbar { flex-direction: column; gap: 10px; }
                        .fc-toolbar-chunk { display: flex; justify-content: center; width: 100%; }
                    }
                """
                
                calendar(events=calendar_events, options=calendar_options, custom_css=custom_css, key=f"cal_{selected_cal_team}")
            else: 
                st.info("Keine Einträge im Kalender für diesen Filter.")

    # ----------------------------------------------------
    # TAB 4: FAMILIE
    # ----------------------------------------------------
    with tab_family:
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
    if tab_admin is not None:
        with tab_admin:
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
            st.dataframe(all_users_df, use_container_width=True)
            
            st.divider()
            st.subheader("🔑 Passwort zurücksetzen")
            st.write("Vergib hier ein neues Passwort für Nutzer, die ihres vergessen haben.")
            with st.form("reset_pw_form"):
                opts = {r['user_id']: f"{r['name']} ({r['email']})" for _, r in all_users_df.iterrows()}
                reset_id = st.selectbox("Benutzer auswählen:", list(opts.keys()), format_func=lambda x: opts[x])
                new_pw = st.text_input("Neues Passwort", type="password")
                
                if st.form_submit_button("Passwort überschreiben"):
                    if new_pw.strip() == "":
                        st.warning("Bitte ein gültiges Passwort eingeben.")
                    else:
                        succ, msg = reset_password(reset_id, new_pw)
                        if succ: 
                            st.success(f"{msg} Der Nutzer kann sich nun mit dem neuen Passwort einloggen.")
                        else: 
                            st.error(msg)

            with st.form("del_u"):
                opts = {r['user_id']: f"{r['name']} ({r['rolle']})" for _, r in all_users_df.iterrows()}
                d_id = st.selectbox("Löschen:", list(opts.keys()), format_func=lambda x: opts[x])
                if st.form_submit_button("User Löschen") and d_id != user['user_id']:
                    delete_user(d_id); st.rerun()
