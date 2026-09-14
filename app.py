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
    st.caption("App-Version 1.4 (Inkl. Punktesystem) | Status: Online 🟢")

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
        
        # Sicherstellen, dass die Punktespalte existiert
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
    
    tab_overview = tabs[0]
    tab_events = tabs[1]
    tab_tasks = tabs[2]
    
    @st.dialog("⚠️ Aufgabe wirklich abgeben?")
    def confirm_cancel(t_id, u_id, t_name, u_name):
        st.warning(f"Möchtest du die Aufgabe **{t_name}** für **{u_name}** wirklich wieder freigeben?")
        st.write("Sie rutscht dadurch zurück in die Liste der offenen Aufgaben und kann von anderen übernommen werden.")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("❌ Ja, abgeben", use_container_width=True):
                succ, msg = cancel_task(t_id, u_id)
                if succ:
                    st.rerun()
        with c2:
            if st.button("Behalten", type="primary", use_container_width=True):
                st.rerun()

    # ----------------------------------------------------
    # TAB 0: ÜBERSICHT (INKLUSIVE PUNKTE)
    # ----------------------------------------------------
    with tab_overview:
        
        # Punkte des aktuell eingeloggten Users ermitteln
        user_points = 0
        if not points_df.empty and user['user_id'] in points_df['user_id'].values:
            user_points = int(points_df[points_df['user_id'] == user['user_id']]['gesamt_punkte'].iloc[0])

        st.metric(label="🌟 Deine gesammelten Helferpunkte", value=f"{user_points} Pkt.")
        
        # Punkte-Übersicht für Trainer, Orga und Admins
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
        
        # Behebung des Key-Fehlers durch .unique()
        my_assigned_tids = assign_df[assign_df['user_id'].isin(my_family_uids)]['task_id'].unique().tolist() if not assign_df.empty else []
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### 🚨 Hilfe dringend gesucht")
            if not tasks_df.empty:
                for _, tsk in tasks_df.iterrows():
                    if is_relevant(tsk.get('betroffene_teams')):
                        t_id = tsk['task_id']
                        t_assigns = assign_df[assign_df['task_id'] == t_id] if not assign_df.empty else pd.DataFrame()
                        cur_h = len(t_assigns)
                        max_h = int(tsk.get('max_helfer', 1))
                        
                        if cur_h < max_h:
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
    # TAB 1 & 2: WEITERE REITER
    # ----------------------------------------------------
    with tab_events:
        st.info("Hier findest du zukünftig die gefilterten Events. Die Aufgabenverwaltung (Übernehmen & Abgeben) funktioniert hier analog zur Dashboard-Logik.")
    
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
