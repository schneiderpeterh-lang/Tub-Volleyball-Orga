import streamlit as st
import pandas as pd
from supabase import create_client, Client
from streamlit_calendar import calendar
from datetime import datetime

# -----------------------------------------------------------------------------
# 1. SEITENKONFIGURATION & DESIGN
# -----------------------------------------------------------------------------
st.set_page_config(page_title="TuB Bocholt - Orga", page_icon="🏐", layout="wide")

def apply_custom_css():
    st.markdown("""
        <style>
        /* Verstecke das Streamlit Branding */
        #MainMenu {visibility: hidden;}
        header {visibility: hidden;}
        footer {visibility: hidden;}
        
        /* Moderne Buttons */
        .stButton>button {
            border-radius: 8px;
            border: none;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            transition: all 0.3s ease;
        }
        .stButton>button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 10px rgba(0, 0, 0, 0.15);
        }
        </style>
    """, unsafe_allow_html=True)

apply_custom_css()

# -----------------------------------------------------------------------------
# 2. DATENBANK-VERBINDUNG & CACHING
# -----------------------------------------------------------------------------
@st.cache_resource
def init_connection() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = init_connection()

@st.cache_data(ttl=300)
def load_all_events():
    try:
        response = supabase.table("events").select("*").execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"Fehler beim Laden der Events: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_all_users():
    try:
        response = supabase.table("users").select("*").execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_attendance():
    try:
        response = supabase.table("event_attendance").select("*").execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_tasks():
    try:
        response = supabase.table("tasks").select("*").execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        return pd.DataFrame()

# -----------------------------------------------------------------------------
# 3. SEITENLEISTE (IMPRESSUM & DATENSCHUTZ)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🏐 TuB Bocholt")
    st.markdown("Willkommen im digitalen Vereinsheim!")
    st.markdown("---")
    
    # Mock-Login (Ersetze dies durch deine echte Auth-Logik)
    if "user" not in st.session_state:
        st.session_state.user = {"name": "Admin Test", "rolle": "Admin", "team": "U12, U13", "id": "123"}
    
    user = st.session_state.user
    st.success(f"Eingeloggt als: {user['name']}\n\nRolle: {user['rolle']}")
    
    st.markdown("---")
    with st.expander("⚖️ Impressum & Datenschutz"):
        st.markdown("""
        **Impressum**
        TuB Bocholt – Abteilung Volleyball
        Lowicker Str. 19c
        46395 Bocholt
        Vertreten durch: Abteilungsleitung
        
        **Datenschutz**
        Wir speichern deinen Namen, deine E-Mail-Adresse und deine Teamzugehörigkeit ausschließlich zur internen Organisation von Spieltagen und Helferaufgaben. 
        Die Daten werden sicher und verschlüsselt auf europäischen Servern (Supabase) gespeichert. 
        Du hast jederzeit das Recht auf Auskunft, Berichtigung und Löschung deiner Daten.
        """)

# -----------------------------------------------------------------------------
# 4. RECHTE & TEAM-FILTER LOGIK
# -----------------------------------------------------------------------------
my_teams = set()
if user.get('team') and user['team'] != "Kein Team": 
    my_teams.update([t.strip() for t in user['team'].split(',')])

def is_relevant(teams_str):
    if user['rolle'] in ['Admin', 'Organisator']: 
        return True
    if pd.isna(teams_str) or not str(teams_str).strip(): 
        return True 
    return any(t.strip() in my_teams for t in str(teams_str).split(','))

# Daten laden
events_df = load_all_events()
users_df = load_all_users()
attendance_df = load_attendance()
tasks_df = load_tasks()

# -----------------------------------------------------------------------------
# 5. DYNAMISCHE TABS AUFBAUEN
# -----------------------------------------------------------------------------
tab_titles = ["🏠 Übersicht", "📅 Spieltage & Events", "🧩 Freie Aufgaben"]
if user['rolle'] != 'Elternteil':
    tab_titles.append("📆 Kalender-Ansicht")
tab_titles.extend(["👨‍👩‍👧 Familie", "⚙️ Admin"])

tabs = st.tabs(tab_titles)

# -----------------------------------------------------------------------------
# TAB 1: ÜBERSICHT (DASHBOARD)
# -----------------------------------------------------------------------------
with tabs[0]:
    st.header("🏠 Deine Übersicht")
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🚨 Hilfe gesucht")
        if not tasks_df.empty:
            open_tasks = tasks_df[tasks_df['status'] == 'offen']
            found_open = False
            for _, task in open_tasks.iterrows():
                if is_relevant(task.get('team', '')):
                    found_open = True
                    st.warning(f"**{task.get('title', 'Aufgabe')}** ({task.get('team', 'Allgemein')})\n\n{task.get('date', '')} - {task.get('description', '')}")
                    if st.button("Übernehmen", key=f"take_{task.get('id', '')}"):
                        st.info("Aufgabe übernommen! (Datenbank-Update hier einfügen)")
            if not found_open:
                st.success("Aktuell gibt es keine offenen Aufgaben für deine Teams!")
        else:
            st.success("Aktuell gibt es keine offenen Aufgaben für deine Teams!")
            
    with col2:
        st.subheader("✅ Deine übernommenen Aufgaben")
        if not tasks_df.empty:
            my_tasks = tasks_df[tasks_df['assigned_to'] == user['id']]
            if not my_tasks.empty:
                for _, task in my_tasks.iterrows():
                    st.success(f"**{task.get('title', '')}** am {task.get('date', '')}")
            else:
                st.info("Du hast aktuell keine Aufgaben übernommen.")
        else:
            st.info("Du hast aktuell keine Aufgaben übernommen.")

# -----------------------------------------------------------------------------
# TAB 2: SPIELTAGE & EVENTS
# -----------------------------------------------------------------------------
with tabs[1]:
    st.header("📅 Spieltage & Events")
    
    if not events_df.empty:
        for _, event in events_df.iterrows():
            if is_relevant(event.get('team', '')):
                event_id = event.get('id')
                with st.expander(f"🏐 {event.get('date', '')} - {event.get('title', 'Event')} ({event.get('team', 'Allgemein')})"):
                    st.write(f"**Ort:** {event.get('location', 'Unbekannt')}")
                    st.write(event.get('description', ''))
                    
                    st.markdown("**Teilnehmer:**")
                    if not attendance_df.empty and event_id:
                        event_attendees = attendance_df[attendance_df['event_id'] == event_id]
                        if not event_attendees.empty:
                            for _, att in event_attendees.iterrows():
                                st.markdown(f"- {att.get('user_name', 'Unbekannt')} ({att.get('status', '')})")
                        else:
                            st.write("Noch keine Zu- oder Absagen.")
                    
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button("👍 Bin dabei", key=f"yes_{event_id}"):
                            st.success("Erfolgreich zugesagt!")
                    with col_b:
                        if st.button("👎 Kann nicht", key=f"no_{event_id}"):
                            st.warning("Erfolgreich abgesagt!")
    else:
        st.write("Aktuell stehen keine Termine an.")

# -----------------------------------------------------------------------------
# TAB 3: FREIE AUFGABEN
# -----------------------------------------------------------------------------
with tabs[2]:
    st.header("🧩 Freie Aufgaben")
    st.write("Allgemeine Vereinsaufgaben, die nicht an einen spezifischen Spieltag gebunden sind.")
    if not tasks_df.empty:
        free_tasks = tasks_df[tasks_df['type'] == 'frei']
        if not free_tasks.empty:
            st.dataframe(free_tasks[['title', 'description', 'status']])
        else:
            st.write("Keine freien Aufgaben verfügbar.")

# -----------------------------------------------------------------------------
# TAB 4: KALENDER (Wird für Elternteile übersprungen)
# -----------------------------------------------------------------------------
current_tab_index = 3

if user['rolle'] != 'Elternteil':
    with tabs[current_tab_index]:
        st.header("📆 Kalender-Ansicht")
        
        calendar_options = {
            "headerToolbar": {
                "left": "today prev,next",
                "center": "title",
                "right": "dayGridMonth,timeGridWeek,listWeek"
            },
            "initialView": "dayGridMonth",
            "height": 600,
            "locale": "de",
        }
        
        custom_css_calendar = """
        .fc-toolbar-title { font-size: 1.2rem !important; }
        @media (max-width: 768px) {
            .fc-toolbar { flex-direction: column; gap: 10px; }
            .fc-toolbar-chunk { display: flex; justify-content: center; width: 100%; }
        }
        """
        
        # Events dynamisch aus dem DataFrame für den Kalender aufbereiten
        calendar_events = []
        if not events_df.empty:
            for _, ev in events_df.iterrows():
                if is_relevant(ev.get('team', '')):
                    calendar_events.append({
                        "title": ev.get('title', 'Event'),
                        "start": str(ev.get('date', datetime.today().date())),
                        "backgroundColor": "#0ea5e9"
                    })
        
        calendar(events=calendar_events, options=calendar_options, custom_css=custom_css_calendar, key="vereinskalender")
    current_tab_index += 1

# -----------------------------------------------------------------------------
# TAB 5: FAMILIE
# -----------------------------------------------------------------------------
with tabs[current_tab_index]:
    st.header("👨‍👩‍👧 Familie")
    st.write("Verwalte hier die Profile deiner Familie und verknüpfe sie mit den entsprechenden Mannschaften.")
current_tab_index += 1

# -----------------------------------------------------------------------------
# TAB 6: ADMIN
# -----------------------------------------------------------------------------
with tabs[current_tab_index]:
    st.header("⚙️ Admin-Bereich")
    
    if user['rolle'] in ['Admin', 'Organisator']:
        st.subheader("Neuen Nutzer anlegen")
        
        with st.form("new_user_form"):
            new_name = st.text_input("Name")
            new_email = st.text_input("E-Mail")
            new_password = st.text_input("Passwort", type="password")
            new_role = st.selectbox("Rolle", ["Spieler", "Elternteil", "Trainer", "Organisator", "Admin"])
            new_team = st.text_input("Team (optional, z.B. U12, U13)")
            
            dsgvo_akzeptiert = st.checkbox("Die Datenschutzerklärung wurde gelesen und der Datenverarbeitung wird zugestimmt. *")
            
            submit_user = st.form_submit_button("Nutzer anlegen")
            
            if submit_user:
                if not dsgvo_akzeptiert:
                    st.error("🚨 Fehler: Dem Datenschutz muss zwingend zugestimmt werden, um einen Account anzulegen.")
                elif not new_email or not new_password:
                    st.warning("Bitte E-Mail und Passwort eingeben.")
                else:
                    try:
                        # Supabase Auth Logik hier einbinden
                        # res = supabase.auth.admin.create_user({"email": new_email, "password": new_password, "user_metadata": {"name": new_name, "rolle": new_role}})
                        st.success(f"Nutzer {new_name} ({new_email}) wurde erfolgreich angelegt!")
                    except Exception as e:
                        st.error(f"Fehler beim Anlegen: {e}")
                        
        st.markdown("---")
        st.subheader("Bestehende Nutzer (Nur für Admins sichtbar)")
        if not users_df.empty:
            st.dataframe(users_df)
    else:
        st.error("Du hast keine Berechtigung, diesen Bereich zu sehen.")
