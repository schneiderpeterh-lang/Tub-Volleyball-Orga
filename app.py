import streamlit as st
import pandas as pd
import datetime
import hashlib
import hmac
import secrets
import uuid
import io
import re
import os
import html
import streamlit.components.v1 as components
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
# 0. SICHERHEITS-KONSTANTEN
# ==========================================
PW_ITERATIONS = 600_000
ALLOWED_SELF_ROLES = ["Spieler", "Elternteil"]  # diese Rollen darf man bei der Registrierung selbst wählen
VERGEBBARE_ROLLEN = ["Spieler", "Elternteil", "Trainer", "Organisator", "Admin"]  # nur durch einen Admin vergebbar
MIN_PW_LENGTH = 8

# ==========================================
# 1. KONFIGURATION & DATENBANK-VERBINDUNG
# ==========================================
st.set_page_config(page_title="TuB Helfer-Orga", page_icon="🏐", layout="wide", initial_sidebar_state="auto")

APP_VERSION = "4.6 (Kacheln Übersicht)"
BRAND = "#82368c"        # Vereinslila (aus tub-bocholt.de)
BRAND_DARK = "#5e2766"
SCHIRI_COLOR = "#c2410c"  # Orange für Schiedsgericht-Termine
LOGO_PATH = "logo.png"   # optional: Vereinslogo als logo.png ins Repo legen

def inject_custom_css():
    st.markdown(f"""
    <style>
    #MainMenu {{visibility: hidden;}}
    footer {{visibility: hidden;}}
    .block-container {{padding-top: 2rem; max-width: 1200px;}}

    /* ---------- Kopfbereich im Vereinsstil ---------- */
    .tub-header {{
        background: linear-gradient(135deg, {BRAND} 0%, {BRAND_DARK} 100%);
        color: #fff; padding: 20px 26px; border-radius: 16px; margin-bottom: 22px;
        box-shadow: 0 6px 18px rgba(94, 39, 102, 0.25);
    }}
    .tub-header .eyebrow {{font-size: .78rem; letter-spacing: .1em; text-transform: uppercase; opacity: .85;}}
    .tub-header .title {{font-size: 1.75rem; font-weight: 700; line-height: 1.2; margin-top: 2px;}}
    .tub-header .sub {{font-size: .95rem; opacity: .9; margin-top: 4px;}}
    @media (max-width: 640px) {{
        .tub-header {{padding: 14px 16px; border-radius: 12px;}}
        .tub-header .title {{font-size: 1.35rem;}}
    }}

    /* ---------- Abschnittstitel ---------- */
    .tub-section {{font-size: 1.1rem; font-weight: 700; margin: 6px 0 10px 0; display: flex; align-items: center; gap: 8px;}}
    .tub-section::before {{content: ""; width: 4px; height: 1.1em; background: {BRAND}; border-radius: 2px; display: inline-block;}}

    /* ---------- Kennzahl-Kacheln (Übersicht) ---------- */
    .kpi-grid {{display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px;}}
    @media (max-width: 640px) {{ .kpi-grid {{grid-template-columns: 1fr;}} }}
    .kpi {{background: #fff; border: 1px solid #eee5ef; border-radius: 14px; padding: 14px 18px;
           box-shadow: 0 1px 3px rgba(43, 34, 48, 0.06);}}
    .kpi .label {{font-size: .85rem; color: #555;}}
    .kpi .value {{font-size: 2rem; font-weight: 700; line-height: 1.15; margin: 4px 0 2px 0;}}
    .kpi .when {{font-size: .95rem; font-weight: 600; color: {BRAND};}}
    .kpi .sub {{font-size: .82rem; color: #777; margin-top: 4px; overflow-wrap: anywhere;}}

    /* ---------- Badges ---------- */
    .tub-badge {{
        display: inline-block; background: rgba(130, 54, 140, 0.12); color: {BRAND};
        border-radius: 999px; padding: 1px 10px; font-size: .78rem; font-weight: 600; vertical-align: middle;
    }}
    .tub-badge.grey {{background: #ececec; color: #555;}}
    .tub-badge.sr {{background: rgba(194, 65, 12, .12); color: {SCHIRI_COLOR};}}

    /* ---------- Karten (Container mit Rahmen) ---------- */
    div[data-testid="stVerticalBlockBorderWrapper"],
    div[data-testid="stContainer"] {{
        border-radius: 14px; background: #ffffff;
        box-shadow: 0 1px 3px rgba(43, 34, 48, 0.06);
        transition: box-shadow .2s ease, border-color .2s ease;
    }}
    div[data-testid="stVerticalBlockBorderWrapper"]:hover,
    div[data-testid="stContainer"]:hover {{
        box-shadow: 0 6px 16px rgba(43, 34, 48, 0.10);
    }}

    /* ---------- Buttons ---------- */
    .stButton > button, .stFormSubmitButton > button {{
        border-radius: 10px !important; font-weight: 600 !important;
        transition: all .2s ease !important;
    }}
    .stButton > button:hover, .stFormSubmitButton > button:hover {{transform: translateY(-1px);}}

    /* ---------- Tabs (Login) ---------- */
    .stTabs [data-baseweb="tab-list"] {{gap: 8px;}}
    .stTabs [data-baseweb="tab"] {{border-radius: 8px 8px 0 0; padding: 10px 16px;}}
    .stTabs [aria-selected="true"] {{background-color: rgba(130, 54, 140, 0.10);}}

    /* ---------- Sidebar ---------- */
    section[data-testid="stSidebar"] {{border-right: 1px solid rgba(130, 54, 140, 0.12);}}
    .tub-user {{background: #fff; border-radius: 12px; padding: 12px 14px; border: 1px solid rgba(130,54,140,.15);}}
    .tub-user .name {{font-weight: 700;}}
    .tub-user .role {{font-size: .82rem; color: {BRAND}; font-weight: 600;}}
    </style>
    """, unsafe_allow_html=True)

inject_custom_css()

def render_header(subtitle="Spieltage, Helferaufgaben und Fahrten an einem Ort"):
    st.markdown(f"""
    <div class="tub-header">
        <div class="eyebrow">TuB Bocholt 1907 e.V. · Volleyball</div>
        <div class="title">Helfer-Orga</div>
        <div class="sub">{subtitle}</div>
    </div>
    """, unsafe_allow_html=True)

def section_title(text_):
    st.markdown(f'<div class="tub-section">{html.escape(str(text_))}</div>', unsafe_allow_html=True)

def points_badge(points):
    try: p = int(points)
    except Exception: p = 1
    return f'<span class="tub-badge">★ {p} Pkt.</span>'

def render_capacity(cur, mx, names=None):
    mx = max(int(mx or 1), 1)
    st.progress(min(cur / mx, 1.0), text=f"{cur} von {mx} Plätzen belegt")
    if names:
        st.caption("Eingetragen: " + ", ".join(names))

def render_footer():
    st.write("")
    st.divider()
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        with st.expander("Impressum"):
            st.markdown("""
            **TuB Bocholt 1907 e.V.**
            Abteilung Volleyball
            Lowicker Str. 19c
            46395 Bocholt

            **Vertreten durch:**
            Abteilungsleitung Volleyball

            **Kontakt:**
            E-Mail: info@tub-bocholt-volleyball.de
            Web: www.tub-bocholt-volleyball.de
            """)
    with c2:
        with st.expander("Datenschutz"):
            st.markdown("""
            **Zweck der Datenspeicherung:**
            Wir speichern deinen Namen, deine E-Mail-Adresse und deine Teamzugehörigkeit ausschließlich zur internen Organisation von Spieltagen und Helferaufgaben.

            **Sicherheit:**
            Die Daten werden sicher und verschlüsselt gespeichert. Du hast jederzeit das Recht auf Auskunft, Berichtigung und Löschung deiner Daten.
            """)
    with c3:
        st.caption(f"App-Version {APP_VERSION}")

if os.path.exists(LOGO_PATH):
    st.logo(LOGO_PATH)

@st.cache_resource
def get_database_engine():
    try:
        # Nur den Port austauschen (nicht jedes Vorkommen von "6543", z. B. im Passwort)
        db_url = st.secrets["DB_URL"].replace(":6543/", ":5432/")
        
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+psycopg2://"):
            db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
            
        return create_engine(
            db_url, 
            connect_args={"sslmode": "require", "connect_timeout": 15},
            pool_pre_ping=True
        )
    except Exception as e:
        st.error(f"Datenbankfehler beim Verbindungsaufbau: {e}")
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
                dsgvo_akzeptiert INTEGER DEFAULT 0
            );
        """))
        
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES users(user_id);"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS team TEXT;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS dsgvo_zeitpunkt TIMESTAMPTZ;"))
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
                zugewiesen_an INTEGER REFERENCES users(user_id),
                tausch_angefragt INTEGER DEFAULT 0
            );
        """))
        
        try:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS start_zeit TEXT;"))
            conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS ende_zeit TEXT;"))
            conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS betroffene_teams TEXT;"))
            conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS max_helfer INTEGER DEFAULT 1;"))
            conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS erstellt_von INTEGER REFERENCES users(user_id);"))
            conn.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS punkte INTEGER DEFAULT 1;"))
        except Exception: pass

        try:
            conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS titel TEXT;"))
            conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS start_zeit TEXT;"))
            conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS ende_zeit TEXT;"))
            conn.execute(text("ALTER TABLE events ADD COLUMN IF NOT EXISTS betroffene_teams TEXT;"))
        except Exception: pass
            
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
                user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE
            );
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS login_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                expires_at TIMESTAMPTZ NOT NULL
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
        
        try:
            conn.execute(text("ALTER TABLE task_assignments ADD COLUMN IF NOT EXISTS kommentar TEXT;"))
        except Exception: pass
        
    return True

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
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PW_ITERATIONS)
    return f"pbkdf2_sha256${PW_ITERATIONS}${salt}${h.hex()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        parts = str(stored).split("$")
        if len(parts) == 4 and parts[0] == "pbkdf2_sha256":   # neues Format
            _, iters, salt, hash_hex = parts
            iters = int(iters)
        elif len(parts) == 2:                                 # altes Format: salt$hash
            salt, hash_hex = parts
            iters = 100_000
        else:
            return False                                      # kein Klartext-Vergleich mehr
        h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iters)
        return hmac.compare_digest(h.hex(), hash_hex)
    except Exception:
        return False

def reset_password(user_id, new_password):
    hashed = hash_password(new_password)
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE users SET password_hash = :h WHERE user_id = :u"), {"h": hashed, "u": user_id})
        clear_caches()
        delete_user_sessions(user_id)  # nach Passwortwechsel überall abmelden
        return True, "Passwort erfolgreich geändert!"
    except Exception as e: 
        return False, str(e)

# ---- "Angemeldet bleiben": zufälliges Token im Browser-Cookie, nur dessen Hash in der Datenbank ----
SESSION_COOKIE = "tub_session"
SESSION_DAYS = 30

def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def create_login_session(user_id):
    token = secrets.token_urlsafe(32)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM login_sessions WHERE expires_at < NOW()"))
        conn.execute(text("""
            INSERT INTO login_sessions (token_hash, user_id, expires_at)
            VALUES (:h, :u, NOW() + make_interval(days => :d))
        """), {"h": _hash_token(token), "u": user_id, "d": SESSION_DAYS})
    return token

def user_from_session_token(token):
    if not token or len(token) > 200:
        return None
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT u.* FROM login_sessions s JOIN users u ON u.user_id = s.user_id
                WHERE s.token_hash = :h AND s.expires_at > NOW() AND u.rolle != 'Kind'
            """), {"h": _hash_token(token)}).fetchone()
    except Exception:
        return None
    if not row:
        return None
    user_data = dict(row._mapping)
    user_data.pop("password_hash", None)
    return user_data

def delete_login_session(token):
    if not token:
        return
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM login_sessions WHERE token_hash = :h"), {"h": _hash_token(token)})
    except Exception:
        pass

def delete_user_sessions(user_id):
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM login_sessions WHERE user_id = :u"), {"u": user_id})
    except Exception:
        pass

def _write_cookie(value, max_age):
    # Setzt das Cookie im Browser (Streamlit kann Cookies nur lesen, nicht schreiben)
    components.html(f"""<script>
        const secure = window.parent.location.protocol === "https:" ? "; Secure" : "";
        window.parent.document.cookie = "{SESSION_COOKIE}={value}; Max-Age={max_age}; Path=/; SameSite=Lax" + secure;
    </script>""", height=0)

def read_session_cookie():
    try:
        return st.context.cookies.get(SESSION_COOKIE)
    except Exception:
        return None

def clear_caches():
    st.cache_data.clear()

@st.cache_data(ttl=60)
def get_user_count():
    # Absichtlich ohne try/except: Bei einem Datenbankfehler soll NICHT das Admin-Setup erscheinen.
    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM users")).scalar()

@st.cache_data(ttl=60)
def get_all_users():
    try:
        with engine.connect() as conn:
            return pd.read_sql(text("SELECT user_id, name, email, rolle, team FROM users ORDER BY name"), conn)
    except: return pd.DataFrame()

def create_initial_admin(name, email, password):
    hashed = hash_password(password)
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, dsgvo_zeitpunkt, team) VALUES (:n, :e, :h, 'Admin', 1, NOW(), 'Kein Team')"),
                {"n": name.strip(), "e": email.strip().lower(), "h": hashed})
        clear_caches()
        return True
    except: return False

def register_new_user(name, email, password, rolle, team_list):
    # Serverseitige Prüfung: höhere Rollen darf nur ein Admin vergeben
    if rolle not in ALLOWED_SELF_ROLES:
        return False, "Diese Rolle kann nicht selbst gewählt werden."
    if len(password) < MIN_PW_LENGTH:
        return False, f"Das Passwort muss mindestens {MIN_PW_LENGTH} Zeichen lang sein."
    hashed = hash_password(password)
    team_str = ", ".join(team_list) if team_list else "Kein Team"
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, dsgvo_zeitpunkt, team)
                VALUES (:n, :e, :h, :r, 1, NOW(), :t)
            """), {"n": name.strip(), "e": email.strip().lower(), "h": hashed, "r": rolle, "t": team_str})
        clear_caches()
        return True, "Erfolgreich registriert!"
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower(): return False, "E-Mail bereits registriert!"
        return False, str(e)

def authenticate(email, password):
    email = (email or "").strip()
    if not email or not password:
        return None
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT * FROM users WHERE LOWER(email) = LOWER(:email) AND rolle != 'Kind'"),
            {"email": email},
        ).fetchone()
    if result and verify_password(password, result.password_hash):
        user_data = dict(result._mapping)
        # Alte Hashes beim erfolgreichen Login automatisch auf das neue Format aktualisieren
        if not str(user_data.get("password_hash", "")).startswith("pbkdf2_sha256$"):
            try:
                with engine.begin() as conn:
                    conn.execute(text("UPDATE users SET password_hash = :h WHERE user_id = :u"),
                                 {"h": hash_password(password), "u": user_data["user_id"]})
            except Exception:
                pass
        user_data.pop("password_hash", None)  # Hash nicht in der Session speichern
        return user_data
    return None

def set_user_role(user_id, rolle):
    if rolle not in VERGEBBARE_ROLLEN:
        return False, "Ungültige Rolle."
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE users SET rolle = :r WHERE user_id = :u AND rolle != 'Kind'"),
                         {"r": rolle, "u": user_id})
        clear_caches()
        return True, "Rolle geändert. Sie gilt für den Nutzer ab dem nächsten Login."
    except Exception as e:
        return False, str(e)

def add_child(parent_id, child_name, child_team_list):
    dummy_email = f"kind_{uuid.uuid4().hex[:8]}@tub.lokal"
    dummy_pass = hash_password(secrets.token_hex(16)) 
    team_str = ", ".join(child_team_list) if child_team_list else "Kein Team"
    try:
        with engine.begin() as conn:
            res = conn.execute(text("INSERT INTO users (name, email, password_hash, rolle, dsgvo_akzeptiert, parent_id, team) VALUES (:n, :e, :h, 'Kind', 1, :p, :t) RETURNING user_id"),
                {"n": child_name, "e": dummy_email, "h": dummy_pass, "p": parent_id, "t": team_str})
            conn.execute(text("INSERT INTO parent_child (parent_id, child_id) VALUES (:p, :c) ON CONFLICT DO NOTHING"), {"p": parent_id, "c": res.scalar()})
        clear_caches()
        return True, f"{child_name} erfolgreich hinzugefügt!"
    except Exception as e: return False, str(e)

def link_existing_child(parent_id, child_id):
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO parent_child (parent_id, child_id) VALUES (:p, :c) ON CONFLICT DO NOTHING"), {"p": parent_id, "c": child_id})
        clear_caches()
        return True, "Verknüpft!"
    except: return False, "Fehler!"

@st.cache_data(ttl=60)
def get_children(parent_id):
    try:
        with engine.connect() as conn:
            return pd.read_sql(text("SELECT DISTINCT u.user_id, u.name, u.team FROM users u LEFT JOIN parent_child pc ON u.user_id = pc.child_id WHERE u.parent_id = :p OR pc.parent_id = :p"), conn, params={"p": parent_id})
    except: return pd.DataFrame()

@st.cache_data(ttl=60)
def get_all_children_in_db():
    try:
        with engine.connect() as conn: return pd.read_sql(text("SELECT user_id, name, team FROM users WHERE rolle = 'Kind' ORDER BY name"), conn)
    except: return pd.DataFrame()

def delete_user(user_id):
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM login_sessions WHERE user_id = :id"), {"id": user_id})
            conn.execute(text("DELETE FROM parent_child WHERE parent_id = :id OR child_id = :id"), {"id": user_id})
            conn.execute(text("UPDATE users SET parent_id = NULL WHERE parent_id = :id"), {"id": user_id})
            conn.execute(text("DELETE FROM task_assignments WHERE user_id = :id"), {"id": user_id})
            conn.execute(text("DELETE FROM event_attendance WHERE user_id = :id"), {"id": user_id})
            # Fremdschlüssel in tasks lösen, damit das Löschen nicht fehlschlägt
            conn.execute(text("UPDATE tasks SET erstellt_von = NULL WHERE erstellt_von = :id"), {"id": user_id})
            conn.execute(text("UPDATE tasks SET zugewiesen_an = NULL WHERE zugewiesen_an = :id"), {"id": user_id})
            conn.execute(text("DELETE FROM users WHERE user_id = :id"), {"id": user_id})
        clear_caches()
        return True, "Account gelöscht."
    except Exception as e: return False, str(e)

# ==========================================
# 4. EVENTS, AUFGABEN & CSV IMPORT SQL
# ==========================================
# ---- Datum robust lesen: "12.10.2026 14:00", "Sa, 12.10.2026 14:00", "12.10.26", "2026-10-12 14:00" ----
_DATUM_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})")
_ISO_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_ZEIT_RE = re.compile(r"(\d{1,2}):(\d{2})")

def parse_datum(value):
    """Gibt einen pd.Timestamp zurück oder None, wenn kein Datum erkennbar ist."""
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime.datetime)):
        return None if pd.isna(value) else pd.Timestamp(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    s_ = str(value)
    m = _DATUM_RE.search(s_)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
    else:
        m = _ISO_RE.search(s_)
        if not m:
            return None
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    t = _ZEIT_RE.search(s_[m.end():])
    hh, mm = (int(t.group(1)), int(t.group(2))) if t else (0, 0)
    try:
        return pd.Timestamp(year=y, month=mo, day=d, hour=hh, minute=mm)
    except ValueError:
        return None

def parse_datum_series(series):
    return pd.to_datetime(series.apply(parse_datum), errors="coerce")

# Erkennt TuB-Bocholt-Mannschaften ("TuB Bocholt", "TuB Bocholt 2", "TuB 1907 Bocholt" ...),
# aber NICHT andere Bocholter Vereine. Bei Bedarf hier anpassen.
TUB_MUSTER = re.compile(r"\btub\b.*\bbocholt\b|\bbocholt\b.*\btub\b", re.IGNORECASE)

def ist_tub(name):
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return False
    return bool(TUB_MUSTER.search(" ".join(str(name).split())))

def _find_col(columns, *needles):
    for c in columns:
        lc = str(c).strip().lower()
        if all(n in lc for n in needles):
            return c
    return None

def _clean(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()

def read_sams_csv(file_bytes):
    """Liest die SAMS-CSV und gibt nur Spiele zurück, bei denen TuB Bocholt spielt oder das Schiedsgericht stellt."""
    try:
        try:
            content = file_bytes.decode('utf-8-sig')
        except UnicodeDecodeError:
            content = file_bytes.decode('iso-8859-1')
        df = pd.read_csv(io.StringIO(content), sep=';', dtype=str)
        if len(df.columns) < 2:
            df = pd.read_csv(io.StringIO(content), sep=',', dtype=str)
    except Exception as e:
        return None, f"Die Datei konnte nicht gelesen werden: {e}"

    c_m1 = _find_col(df.columns, "mannschaft 1")
    c_m2 = _find_col(df.columns, "mannschaft 2")
    c_sr = _find_col(df.columns, "schiedsgericht")
    c_datum = _find_col(df.columns, "datum")
    c_zeit = _find_col(df.columns, "uhrzeit")
    c_ort = _find_col(df.columns, "austragungsort")
    fehlend = [n for n, c in [("Mannschaft 1", c_m1), ("Mannschaft 2", c_m2), ("Datum", c_datum)] if c is None]
    if fehlend:
        return None, "In der CSV fehlen die Spalten: " + ", ".join(fehlend) + ". Ist das ein Spielplan-Export aus SAMS?"

    zeilen = []
    for _, row in df.iterrows():
        m1, m2 = _clean(row[c_m1]), _clean(row[c_m2])
        sr = _clean(row[c_sr]) if c_sr else ""
        spielt = ist_tub(m1) or ist_tub(m2)
        pfeift = ist_tub(sr)
        if not (spielt or pfeift):
            continue
        datum = _clean(row[c_datum]).replace(',', '')
        zeit = _clean(row[c_zeit]) if c_zeit else ""
        rolle = "Spiel + Schiedsgericht" if (spielt and pfeift) else ("Spiel" if spielt else "Schiedsgericht")
        zeilen.append({
            "Datum": datum, "Uhrzeit": zeit, "Spiel": f"{m1} vs. {m2}",
            "Rolle": rolle, "Ort": _clean(row[c_ort]) if c_ort else "",
            "_start": (parse_datum(f"{datum} {zeit}").strftime("%d.%m.%Y %H:%M")
                       if parse_datum(f"{datum} {zeit}") is not None else f"{datum} {zeit}".strip()),
            "_schiri": pfeift,
        })
    info = f"{len(zeilen)} von {len(df)} Spielen betreffen TuB Bocholt (als Mannschaft oder Schiedsgericht)."
    return pd.DataFrame(zeilen), info

def import_sams_rows(rows, team_str):
    """Legt die gefilterten Spiele an. Bereits vorhandene Spiele (gleicher Titel, Termin und Team) werden übersprungen."""
    events_added = tasks_added = skipped = 0
    try:
        with engine.begin() as conn:
            for _, r in rows.iterrows():
                vorhanden = conn.execute(text("""
                    SELECT 1 FROM events WHERE titel = :titel AND start_zeit = :start AND betroffene_teams = :teams LIMIT 1
                """), {"titel": r["Spiel"], "start": r["_start"], "teams": team_str}).fetchone()
                if vorhanden:
                    skipped += 1
                    continue
                event_id = conn.execute(text("""
                    INSERT INTO events (titel, start_zeit, ende_zeit, ort, betroffene_teams)
                    VALUES (:titel, :start, :ende, :ort, :teams)
                    RETURNING event_id
                """), {"titel": r["Spiel"], "start": r["_start"], "ende": "", "ort": r["Ort"], "teams": team_str}).scalar()
                events_added += 1
                if r["_schiri"]:
                    conn.execute(text("""
                        INSERT INTO tasks (kategorie, beschreibung, max_helfer, start_zeit, betroffene_teams, event_id, punkte)
                        VALUES ('Schiedsgericht', 'Wir stellen das Schiedsgericht für dieses Spiel.', 2, :st, :teams, :ev, 2)
                    """), {"st": r["_start"], "teams": team_str, "ev": event_id})
                    tasks_added += 1
        clear_caches()
        msg = f"{events_added} Spiele und {tasks_added} Schiedsgericht-Aufgaben für {team_str} importiert."
        if skipped:
            msg += f" {skipped} Spiel war schon vorhanden und wurde übersprungen." if skipped == 1 else f" {skipped} Spiele waren schon vorhanden und wurden übersprungen."
        return True, msg
    except Exception as e:
        return False, f"Fehler beim Import: {e}"

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
            return pd.read_sql(text("SELECT task_id, event_id, kategorie, beschreibung, max_helfer, erstellt_von, start_zeit, ende_zeit, betroffene_teams, COALESCE(punkte, 1) as punkte FROM tasks ORDER BY task_id DESC"), conn)
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
                    COALESCE(SUM(COALESCE(t.punkte, 1)), 0) AS gesamt_punkte
                FROM users u
                LEFT JOIN task_assignments ta ON u.user_id = ta.user_id
                LEFT JOIN tasks t ON ta.task_id = t.task_id
                GROUP BY u.user_id, u.name, u.rolle, u.team
            """)
            return pd.read_sql(query, conn)
    except:
        return pd.DataFrame()

def create_task(kategorie, beschreibung, max_helfer, user_id, start=None, ende=None, teams=None, event_id=None, punkte=1):
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO tasks (kategorie, beschreibung, max_helfer, erstellt_von, start_zeit, ende_zeit, betroffene_teams, event_id, punkte)
                VALUES (:kat, :besch, :max, :erst, :st, :en, :teams, :ev, :pts)
            """), {"kat": kategorie, "besch": beschreibung, "max": max_helfer, "erst": user_id, "st": start, "en": ende, "teams": teams, "ev": event_id, "pts": punkte})
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
        return True, "Spieltag inkl. Aufgaben gelöscht!"
    except Exception as e: return False, str(e)

def delete_all_events_for_team(team_name):
    try:
        with engine.connect() as conn:
            events = pd.read_sql(text("SELECT event_id, betroffene_teams FROM events"), conn)
            
        deleted_count = 0
        for _, ev in events.iterrows():
            teams_str = str(ev.get('betroffene_teams', ''))
            if team_name in [t.strip() for t in teams_str.split(',')]:
                delete_event(ev['event_id'])
                deleted_count += 1
                
        clear_caches()
        return True, f"Erfolgreich {deleted_count} Spieltage inkl. aller Aufgaben für '{team_name}' gelöscht!"
    except Exception as e:
        return False, f"Fehler beim Löschen der Spieltage: {e}"

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
    except Exception: return False

def update_event_location(event_id, neuer_ort):
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE events SET ort = :ort WHERE event_id = :id"), {"ort": neuer_ort, "id": event_id})
        clear_caches()
        return True
    except Exception:
        return False

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

def format_assignee_name(row):
    if pd.notna(row.get('kommentar')) and str(row.get('kommentar')).strip():
        return f"{row['assignee_name']} ({row['kommentar']})"
    return row['assignee_name']

def render_task_accept_ui(tsk_row, options, key_prefix):
    t_id = tsk_row['task_id']
    kat_lower = str(tsk_row['kategorie']).lower()
    
    if "fahr" in kat_lower or "auto" in kat_lower:
        with st.form(key=f"{key_prefix}_drive_{t_id}"):
            sel_u = st.selectbox("Wer?", list(options.keys()), format_func=lambda x: options[x], label_visibility="collapsed")
            seats = st.number_input("Freie Plätze (ohne Fahrer)", min_value=1, max_value=8, value=3)
            if st.form_submit_button("🚀 Eintragen", use_container_width=True):
                success, msg = accept_task(t_id, sel_u, f"{seats} freie Plätze")
                if success: st.rerun()
                else: st.error(msg)
    elif "catering" in kat_lower or "kuchen" in kat_lower or "buffet" in kat_lower or "theke" in kat_lower:
        with st.form(key=f"{key_prefix}_cat_{t_id}"):
            sel_u = st.selectbox("Wer?", list(options.keys()), format_func=lambda x: options[x], label_visibility="collapsed")
            beitrag = st.text_input("Was bringst du mit?", placeholder="z.B. Kuchen, Salat, Muffins")
            if st.form_submit_button("🍰 Eintragen", use_container_width=True):
                if not beitrag.strip():
                    st.warning("Bitte gib kurz an, was du mitbringst.")
                else:
                    success, msg = accept_task(t_id, sel_u, beitrag.strip())
                    if success: st.rerun()
                    else: st.error(msg)
    else:
        c_sel, c_btn = st.columns([2, 1])
        with c_sel:
            sel_u = st.selectbox("Wer?", list(options.keys()), format_func=lambda x: options[x], key=f"{key_prefix}_sel_{t_id}", label_visibility="collapsed")
        with c_btn:
            if st.button("Übernehmen", key=f"{key_prefix}_btn_{t_id}", use_container_width=True):
                success, msg = accept_task(t_id, sel_u)
                if success: st.rerun()
                else: st.error(msg)

# ==========================================
# 5. UI COMPONENTS
# ==========================================
render_header()
TEAM_LISTE = ["U12", "U13", "U14", "U16", "U18", "U20", "Herren 1", "Herren 2", "Herren 3", "Herren 4", "Damen 1"]
KATEGORIE_OPTIONEN = ["Catering", "Fahrdienst", "Aufbau/Abbau", "Schiedsgericht", "Sonstiges (Freitext)"]

if 'logged_in_user' not in st.session_state:
    st.session_state['logged_in_user'] = None

# Nach einem Reload: Anmeldung aus dem Cookie wiederherstellen (nicht direkt nach dem Ausloggen)
if st.session_state['logged_in_user'] is None and not st.session_state.get('logged_out'):
    _token = read_session_cookie()
    if _token:
        _restored = user_from_session_token(_token)
        if _restored:
            st.session_state['logged_in_user'] = _restored
            st.session_state['session_token'] = _token

# Cookie-Aktionen aus dem vorherigen Durchlauf (Login/Logout) im Browser ausführen
if st.session_state.get('pending_cookie'):
    _write_cookie(st.session_state.pop('pending_cookie'), SESSION_DAYS * 24 * 3600)
if st.session_state.pop('clear_cookie', False):
    _write_cookie("", 0)

# Datenbankfehler sichtbar machen, statt fälschlich das Admin-Setup anzuzeigen
try:
    user_count = get_user_count()
except Exception:
    st.error("Die Datenbank ist gerade nicht erreichbar. Bitte versuche es in ein paar Minuten erneut.")
    st.stop()

if user_count == 0:
    st.warning("⚠️ Keine Benutzer in der Datenbank gefunden. Richte den Admin ein:")
    with st.form("setup"):
        if st.form_submit_button("Admin erstellen") and create_initial_admin(st.text_input("Name"), st.text_input("E-Mail"), st.text_input("Passwort", type="password")):
            st.success("Erstellt! Lade die Seite neu.")
            st.rerun()

elif st.session_state['logged_in_user'] is None:
    t_login, t_reg = st.tabs(["🔑 Einloggen", "📝 Neu Registrieren"])
    
    with t_login:
        with st.form("login"):
            login_email = st.text_input("E-Mail")
            login_pw = st.text_input("Passwort", type="password")
            remember = st.checkbox(f"Angemeldet bleiben ({SESSION_DAYS} Tage)", value=True,
                                   help="Auf fremden oder gemeinsam genutzten Geräten bitte abwählen.")
            login_submitted = st.form_submit_button("Einloggen")
        if login_submitted:
            logged_user = authenticate(login_email, login_pw)
            if logged_user:
                st.session_state['logged_in_user'] = logged_user
                st.session_state['logged_out'] = False
                if remember:
                    try:
                        token = create_login_session(logged_user['user_id'])
                        st.session_state['session_token'] = token
                        st.session_state['pending_cookie'] = token
                    except Exception:
                        pass  # Login klappt trotzdem, nur ohne "angemeldet bleiben"
                st.rerun()
            else: 
                st.error("Zugangsdaten ungültig.")
                    
        if st.button("Passwort vergessen?", use_container_width=True):
            st.info("💡 **Passwort vergessen?** Bitte sprich einen Trainer oder Administrator an. Diese können dir in Sekunden ein neues Passwort vergeben.")
                    
    with t_reg:
        with st.form("reg"):
            n = st.text_input("Name")
            e = st.text_input("E-Mail")
            p = st.text_input(f"Passwort (mind. {MIN_PW_LENGTH} Zeichen)", type="password")
            r = st.selectbox("Ich bin", ALLOWED_SELF_ROLES)
            t = st.multiselect("Team", TEAM_LISTE)
            code = st.text_input("Vereinscode (bekommst du vom Trainer oder der Orga)", type="password")
            
            st.markdown("---")
            with st.expander("🛡️ Datenschutzhinweise anzeigen"):
                st.markdown("""
                **Zweck der Datenspeicherung:**
                Wir speichern deinen Namen, deine E-Mail-Adresse und deine Teamzugehörigkeit ausschließlich zur internen Organisation von Spieltagen und Helferaufgaben.
                
                **Sicherheit:**
                Die Daten werden sicher und verschlüsselt gespeichert. Du hast jederzeit das Recht auf Auskunft, Berichtigung und Löschung deiner Daten.
                """)
            
            dsgvo = st.checkbox("Ich habe die Datenschutzhinweise gelesen und stimme der Verarbeitung meiner Daten zu.")
            st.markdown("---")
            
            if st.form_submit_button("Registrieren"):
                expected_code = str(st.secrets.get("VEREINSCODE", ""))
                if not expected_code or not hmac.compare_digest(code.encode("utf-8"), expected_code.encode("utf-8")):
                    st.error("Der Vereinscode ist ungültig.")
                elif not dsgvo:
                    st.warning("⚠️ Bitte stimme den Datenschutzrichtlinien zu, um dich zu registrieren.")
                elif not (n and e and p):
                    st.warning("⚠️ Bitte fülle alle Pflichtfelder (Name, E-Mail, Passwort) aus.")
                else:
                    succ, msg = register_new_user(n, e, p, r, t)
                    if succ: 
                        st.success(msg)
                    else: 
                        st.error(msg)

else:
    user = st.session_state['logged_in_user']

    children_df = get_children(user['user_id'])
    tasks_df = get_all_tasks()
    assign_df = get_task_assignments()
    events_df = get_all_events()
    all_attendance_df = get_all_attendance()
    all_users_df = get_all_users()
    points_df = get_user_points_df()

    my_teams = set()
    if user.get('team') and user['team'] != "Kein Team": my_teams.update([t.strip() for t in user['team'].split(',')])
    if not children_df.empty:
        for _, c in children_df.iterrows():
            if c.get('team') and c['team'] != "Kein Team": my_teams.update([t.strip() for t in c['team'].split(',')])
    
    def is_relevant(teams_str):
        if user['rolle'] in ['Admin', 'Organisator']: 
            return True
        if pd.isna(teams_str) or not str(teams_str).strip(): 
            return True 
        return any(t.strip() in my_teams for t in str(teams_str).split(','))


    # ----------------------------------------------------
    # TAB 0: ÜBERSICHT (DASHBOARD)
    # ----------------------------------------------------
    def page_overview():
        my_family_uids = [user['user_id']]
        if not children_df.empty:
            my_family_uids.extend(children_df['user_id'].tolist())
            
        my_points = 0
        if not points_df.empty:
            my_points = int(points_df[points_df['user_id'].isin(my_family_uids)]['gesamt_punkte'].sum())
            

        # AUFGABEN VORBEREITEN & SORTIEREN
        def parse_to_datetime(date_str):
            ts = parse_datum(date_str)
            return ts if ts is not None else pd.Timestamp.max

        sorted_tasks = []
        if not tasks_df.empty:
            for _, tsk in tasks_df.iterrows():
                tsk_dict = tsk.to_dict()
                date_str = tsk_dict.get('start_zeit', 'Kein Datum')
                context = "📋 Freie Aufgabe"
                ort = ""
                
                if pd.notna(tsk_dict.get('event_id')):
                    ev_row = events_df[events_df['event_id'] == tsk_dict['event_id']]
                    if not ev_row.empty:
                        ev = ev_row.iloc[0]
                        context = f"🏆 {ev['titel']}"
                        date_str = ev['start_zeit']
                        ort = str(ev.get('ort', '')).lower()
                        tsk_dict['event_titel'] = ev['titel']
                        tsk_dict['event_ort'] = ev['ort']
                        
                tsk_dict['display_date'] = date_str
                tsk_dict['context'] = context
                tsk_dict['ort'] = ort
                tsk_dict['sort_date'] = parse_to_datetime(date_str)
                sorted_tasks.append(tsk_dict)
                
            sorted_tasks.sort(key=lambda x: x['sort_date'])

        my_assigned_tids = assign_df[assign_df['user_id'].isin(my_family_uids)]['task_id'].unique().tolist() if not assign_df.empty else []

        # --- KENNZAHLEN ---
        open_count = 0
        for _tsk in sorted_tasks:
            if not is_relevant(_tsk.get('betroffene_teams')): continue
            _n = int((assign_df['task_id'] == _tsk['task_id']).sum()) if not assign_df.empty else 0
            if _n < int(_tsk.get('max_helfer', 1) or 1): open_count += 1

        WT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
        next_date, next_when, next_title, next_badge = "–", "", "Kein Termin geplant", ""
        if not events_df.empty:
            _rel = events_df[events_df['betroffene_teams'].apply(is_relevant)].copy()
            if not _rel.empty:
                _rel['dt'] = parse_datum_series(_rel['start_zeit'])
                _fut = _rel[_rel['dt'] >= pd.Timestamp.now()].sort_values('dt')
                if not _fut.empty:
                    _ev = _fut.iloc[0]
                    _dt = _ev['dt']
                    next_date = f"{WT[_dt.weekday()]}, {_dt.strftime('%d.%m.')}"
                    _zeit = "" if _dt.strftime('%H:%M') == "00:00" else _dt.strftime('%H:%M') + " Uhr"
                    _ort = str(_ev.get('ort') or "").strip()
                    next_when = " · ".join([x for x in [_zeit, _ort] if x])
                    next_title = str(_ev['titel'])
                    _sr = (not tasks_df.empty) and bool(((tasks_df['event_id'] == _ev['event_id']) &
                            tasks_df['kategorie'].astype(str).str.lower().str.contains('schiedsgericht')).any())
                    if _sr and 'bocholt' not in next_title.lower():
                        next_badge = '<span class="tub-badge sr">Schiedsgericht</span>'

        kacheln = (
            '<div class="kpi-grid">'
            f'<div class="kpi"><div class="label">Deine Helferpunkte</div><div class="value">{my_points}</div>'
            '<div class="sub">inkl. deiner Kinder</div></div>'
            f'<div class="kpi"><div class="label">Offene Aufgaben</div><div class="value">{open_count}</div>'
            '<div class="sub">in deinen Teams</div></div>'
            f'<div class="kpi"><div class="label">Nächster Spieltag {next_badge}</div>'
            f'<div class="value">{html.escape(next_date)}</div>'
            f'<div class="when">{html.escape(next_when)}</div>'
            f'<div class="sub">{html.escape(next_title)}</div></div>'
            '</div>'
        )
        st.markdown(kacheln, unsafe_allow_html=True)
        
        # --- HIGHLIGHT: FAHRER ---
        section_title("🚗 Fahrer für Auswärtsspiele gesucht")
        found_driver_task = False
        for tsk in sorted_tasks:
            if not is_relevant(tsk.get('betroffene_teams')): continue
            kategorie = str(tsk.get('kategorie', '')).lower()
            
            if 'fahr' in kategorie or 'auto' in kategorie:
                t_id = tsk['task_id']
                t_assigns = assign_df[assign_df['task_id'] == t_id] if not assign_df.empty else pd.DataFrame()
                cur_h = len(t_assigns)
                max_h = int(tsk.get('max_helfer', 1))
                
                if cur_h < max_h and pd.notna(tsk.get('event_id')):
                    ort = tsk.get('ort', '')
                    if 'bocholt' not in ort and ort.strip() != '':
                        found_driver_task = True
                        with st.container(border=True):
                            c_info, c_action = st.columns([3, 2])
                            with c_info:
                                st.markdown(f"**{html.escape(str(tsk.get('event_titel', 'Event')))}** &nbsp;<span class=\"tub-badge\">Auswärts</span>", unsafe_allow_html=True)
                                st.write(f"📍 **Ziel:** {tsk.get('event_ort', ort)} | 🗓️ {tsk['display_date']}")
                                render_capacity(cur_h, max_h)
                            with c_action:
                                options = {user['user_id']: "Ich fahre selbst"}
                                if not children_df.empty:
                                    for _, child in children_df.iterrows(): options[child['user_id']] = f"Fahre für Kind: {child['name']}"
                                if not t_assigns.empty:
                                    options = {k: v for k, v in options.items() if k not in t_assigns['user_id'].tolist()}
                                
                                if options:
                                    with st.form(key=f"drive_form_{t_id}"):
                                        sel_u = st.selectbox("Wer fährt?", list(options.keys()), format_func=lambda x: options[x], label_visibility="collapsed")
                                        seats = st.number_input("Freie Plätze (ohne Fahrer)", min_value=1, max_value=8, value=3)
                                        if st.form_submit_button("🚀 Übernehmen", use_container_width=True):
                                            kommentar_text = f"({seats} freie Plätze)"
                                            success, msg = accept_task(t_id, sel_u, kommentar_text)
                                            if success: st.rerun()
                                else:
                                    st.success("✅ Aus deiner Familie ist bereits jemand eingetragen.")

        if not found_driver_task:
            st.info("Aktuell sind alle Auswärtsfahrten deiner Teams abgedeckt oder es stehen keine an.")
            
        st.divider()
        
        @st.dialog("⚠️ Aufgabe wirklich abgeben?")
        def confirm_cancel(t_id, u_id, t_name, u_name):
            st.warning(f"Möchtest du die Aufgabe **{t_name}** für **{u_name}** wirklich wieder freigeben?")
            st.write("Sie rutscht dadurch zurück in die Liste der offenen Aufgaben.")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("❌ Ja, abgeben", use_container_width=True):
                    succ, msg = cancel_task(t_id, u_id)
                    if succ: st.rerun()
            with c2:
                if st.button("Behalten", type="primary", use_container_width=True):
                    st.rerun()

        # --- UNTERKATEGORIEN (TABS) FÜR MANNSCHAFTEN ---
        overview_teams = TEAM_LISTE if user['rolle'] in ['Admin', 'Organisator'] else sorted(list(my_teams))
        if not overview_teams:
            overview_teams = []
            
        st.write("")
        section_title("Aufgaben nach Team")
        idx = 0
        tab_name = st.pills("Team", ["Alle"] + overview_teams, default="Alle", key="ov_team", label_visibility="collapsed") or "Alle"
        col1, col2 = st.columns(2)
        
        with col1:
            section_title("🚨 Hilfe gesucht")
            found_open = False
            
            for tsk in sorted_tasks:
                kategorie = str(tsk.get('kategorie', '')).lower()
                if 'fahr' in kategorie or 'auto' in kategorie:
                    if pd.notna(tsk.get('event_id')) and 'bocholt' not in tsk.get('ort', ''):
                        continue
                        
                teams_str = str(tsk.get('betroffene_teams', ''))
                
                if tab_name != "Alle":
                    if pd.isna(teams_str) or not teams_str.strip() or tab_name not in [t.strip() for t in teams_str.split(',')]:
                        continue
                else:
                    if not is_relevant(teams_str): continue
                    
                t_id = tsk['task_id']
                t_assigns = assign_df[assign_df['task_id'] == t_id] if not assign_df.empty else pd.DataFrame()
                cur_h = len(t_assigns)
                max_h = int(tsk.get('max_helfer', 1))
                
                if cur_h < max_h:
                    found_open = True
                    with st.container(border=True):
                        st.markdown(f"**{html.escape(str(tsk['kategorie']))}** &nbsp;{points_badge(tsk.get('punkte', 1))}", unsafe_allow_html=True)
                        st.caption(f"{tsk['context']} | 🗓️ {tsk['display_date']}")
                        render_capacity(cur_h, max_h)
                        
                        options = {user['user_id']: "Ich selbst"}
                        if not children_df.empty:
                            for _, child in children_df.iterrows(): options[child['user_id']] = f"Kind: {child['name']}"
                        if not t_assigns.empty:
                            options = {k: v for k, v in options.items() if k not in t_assigns['user_id'].tolist()}
                        
                        if options:
                            render_task_accept_ui(tsk, options, key_prefix=f"dash_ov_{idx}")
                        else:
                            st.success("✅ Familie bereits eingetragen.")
                            
            if not found_open:
                st.success("In diesem Bereich sind aktuell alle Aufgaben belegt. Super!")

        with col2:
            section_title("✅ Deine Aufgaben")
            found_mine = False
            
            if my_assigned_tids:
                for t_id in my_assigned_tids:
                    tsk = next((item for item in sorted_tasks if item["task_id"] == t_id), None)
                    if not tsk: continue
                    
                    teams_str = str(tsk.get('betroffene_teams', ''))
                    if tab_name != "Alle":
                        if pd.isna(teams_str) or not teams_str.strip() or tab_name not in [t.strip() for t in teams_str.split(',')]:
                            continue
                    else:
                        if not is_relevant(teams_str): continue
                        
                    found_mine = True
                    fam_assigns = assign_df[(assign_df['task_id'] == t_id) & (assign_df['user_id'].isin(my_family_uids))]
                    
                    with st.container(border=True):
                        st.markdown(f"**{html.escape(str(tsk['kategorie']))}** &nbsp;{points_badge(tsk.get('punkte', 1))}", unsafe_allow_html=True)
                        st.caption(f"{tsk['context']} | 🗓️ {tsk['display_date']}")
                        
                        for _, assign_row in fam_assigns.iterrows():
                            c1_sub, c2_sub = st.columns([3, 1])
                            with c1_sub:
                                st.write(f"👷‍♂️ {format_assignee_name(assign_row)}")
                            with c2_sub:
                                if st.button("Abgeben", key=f"cancel_{t_id}_{assign_row['user_id']}_tab_{idx}", use_container_width=True):
                                    confirm_cancel(t_id, assign_row['user_id'], tsk['kategorie'], assign_row['assignee_name'])
            
            if not found_mine:
                st.info("Du bist in dieser Ansicht aktuell für keine anstehenden Aufgaben eingetragen.")

    # ----------------------------------------------------
    # TAB 1: SPIELTAGE & EVENTS
    # ----------------------------------------------------
    def page_events():
        st.caption("Wähle ein Team, um seine Termine, Rückmeldungen und Aufgaben zu sehen.")
        
        rel_events = events_df[events_df['betroffene_teams'].apply(is_relevant)] if not events_df.empty else pd.DataFrame()
        
        admin_options = {}
        if user['rolle'] in ['Admin', 'Organisator'] and not all_users_df.empty:
            admin_options = {row['user_id']: f"Admin-Zuweisung: {row['name']}" for _, row in all_users_df.iterrows()}
            
        def render_event_list(events_to_show):
            for _, ev in events_to_show.iterrows():
                ev_id = ev['event_id']
                with st.expander(f"🏐 {ev['titel']} ({ev['start_zeit']})", expanded=False):
                    st.write(f"📍 **Ort:** {ev['ort']} | 👕 **Teams:** {ev['betroffene_teams']}")
                    
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
                                st.markdown(f"**{html.escape(str(tsk['kategorie']))}** &nbsp;{points_badge(tsk.get('punkte', 1))}", unsafe_allow_html=True)
                                st.caption(tsk['beschreibung'])
                                formatted_names = [format_assignee_name(row) for _, row in t_assigns.iterrows()]
                                render_capacity(cur_h, max_h, formatted_names)
                                
                            with tc2:
                                options = {user['user_id']: "Ich selbst"}
                                if not children_df.empty:
                                    for _, child in children_df.iterrows(): options[child['user_id']] = f"Kind: {child['name']}"
                                if not t_assigns.empty:
                                    options = {k: v for k, v in options.items() if k not in t_assigns['user_id'].tolist()}
                                
                                if cur_h < max_h:
                                    if options:
                                        render_task_accept_ui(tsk, options, key_prefix=f"ev_{ev_id}")
                                    else: st.success("✅ Familie komplett eingetragen.")
                                else: st.success("✅ Voll belegt.")
                                
                                if user['rolle'] in ['Admin', 'Organisator', 'Trainer'] or tsk.get('erstellt_von') == user['user_id']:
                                    if st.button("🗑️ Löschen", key=f"del_ev_{t_id}"): 
                                        delete_task(t_id); st.rerun()
                            st.divider()
                    else:
                        st.info("Noch keine Aufgaben für dieses Event hinterlegt.")
                        
                    if user['rolle'] in ['Admin', 'Organisator', 'Trainer']:
                        st.markdown("➕ **Neuen Orga-Punkt erstellen**")
                        with st.form(f"form_ev_{ev_id}"):
                            nk_sel = st.selectbox("Kategorie / Was wird gebraucht?", KATEGORIE_OPTIONEN)
                            nk_free = st.text_input("Eigene Eingabe (falls Sonstiges gewählt):")
                            nb = st.text_area("Details")
                            nm = st.number_input("Anzahl Personen", min_value=1, value=1)
                            n_pts = st.number_input("Punkte für diese Aufgabe", min_value=1, max_value=10, value=1)
                            if st.form_submit_button("Hinzufügen"):
                                final_nk = nk_free if nk_sel == "Sonstiges (Freitext)" else nk_sel
                                if final_nk:
                                    create_task(final_nk, nb, nm, user['user_id'], ev['start_zeit'], ev['ende_zeit'], ev['betroffene_teams'], event_id=ev_id, punkte=n_pts)
                                    st.rerun()
                                    
                    if user['rolle'] == 'Admin':
                        if st.button("🚨 Komplettes Event löschen", key=f"del_event_{ev_id}"):
                            delete_event(ev_id); st.rerun()

        if not rel_events.empty:
            available_teams = set()
            for _, ev in rel_events.iterrows():
                if pd.notna(ev['betroffene_teams']):
                    available_teams.update([t.strip() for t in str(ev['betroffene_teams']).split(',') if t.strip()])
            valid_teams = sorted(list(available_teams))

            if not valid_teams:
                st.info("Keine spezifischen Teams in den Spieltagen hinterlegt.")
            else:
                default_team = next((t for t in valid_teams if t in my_teams), None)
                sel_team = st.pills("Team", valid_teams, default=default_team, key="ev_team", label_visibility="collapsed")
                if not sel_team:
                    st.info("Wähle oben ein Team aus.")
                else:
                    section_title(f"Termine für {sel_team}")
                    def is_selected_team(teams_str):
                        if pd.isna(teams_str): return False
                        return sel_team in [t.strip() for t in str(teams_str).split(',')]
                    
                    team_events = rel_events[rel_events['betroffene_teams'].apply(is_selected_team)].copy()
                
                    if not team_events.empty:
                        team_events['sort_date'] = parse_datum_series(team_events['start_zeit'])
                        now = pd.Timestamp(datetime.datetime.now())
                        future_events = team_events[team_events['sort_date'] >= now].sort_values('sort_date')
                        past_events = team_events[team_events['sort_date'] < now].sort_values('sort_date', ascending=False)
                        unparsed_events = team_events[team_events['sort_date'].isna()]
                    
                        if not future_events.empty:
                            next_date = future_events.iloc[0]['sort_date'].date()
                            next_events = future_events[future_events['sort_date'].dt.date == next_date]
                            upcoming_events = future_events[future_events['sort_date'].dt.date > next_date]
                        
                            section_title("Als Nächstes")
                            render_event_list(next_events)
                            if not upcoming_events.empty:
                                section_title("Kommende Termine")
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
    def page_tasks():
        if user['rolle'] in ['Admin', 'Organisator', 'Trainer']:
            with st.expander("➕ Allgemeine Aufgabe anlegen (Ohne Event-Bezug)"):
                with st.form("new_task_form"):
                    k_sel = st.selectbox("Kategorie", KATEGORIE_OPTIONEN)
                    k_free = st.text_input("Eigene Eingabe (falls Sonstiges gewählt):")
                    b = st.text_area("Details")
                    m = st.number_input("Helfer", min_value=1, value=1)
                    n_pts = st.number_input("Punkte für diese Aufgabe", min_value=1, max_value=10, value=1)
                    t = st.multiselect("Teams", TEAM_LISTE)
                    c1, c2 = st.columns(2)
                    with c1: sd, stt = st.date_input("Start"), st.time_input("Zeit")
                    if st.form_submit_button("Speichern"):
                        final_k = k_free if k_sel == "Sonstiges (Freitext)" else k_sel
                        if final_k:
                            dt_str = f"{sd.strftime('%d.%m.%Y')} {stt.strftime('%H:%M')} Uhr"
                            create_task(final_k, b, m, user['user_id'], dt_str, None, ", ".join(t) if t else None, punkte=n_pts)
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
                        st.markdown(f"**{html.escape(str(row['kategorie']))}** &nbsp;{points_badge(row.get('punkte', 1))}", unsafe_allow_html=True)
                        if pd.notna(row.get('start_zeit')): st.write(f"🗓️ {row['start_zeit']}")
                        if pd.notna(row.get('betroffene_teams')) and row['betroffene_teams']: st.write(f"👕 Teams: {row['betroffene_teams']}")
                        st.caption(row['beschreibung'])
                        
                        formatted_names = [format_assignee_name(r) for _, r in t_assigns.iterrows()]
                        render_capacity(cur_h, max_h, formatted_names)
                        
                    with col2:
                        options = {user['user_id']: "Ich selbst"}
                        if not children_df.empty:
                            for _, child in children_df.iterrows(): options[child['user_id']] = f"Kind: {child['name']}"
                        if not t_assigns.empty: options = {k: v for k, v in options.items() if k not in t_assigns['user_id'].tolist()}
                        
                        if cur_h < max_h:
                            if options:
                                render_task_accept_ui(row, options, key_prefix="free")
                            else: st.success("✅ Eingetragen.")
                        else: st.success("✅ Voll!")
                        
                        if user['rolle'] in ['Admin', 'Organisator', 'Trainer'] or row.get('erstellt_von') == user['user_id']:
                            if st.button("🗑️ Löschen", key=f"del_f_{t_id}"): delete_task(t_id); st.rerun()
                st.divider()
        else: st.info("Aktuell keine allgemeinen Aufgaben.")

    # ----------------------------------------------------
    # TAB 3: KALENDER (Nicht für Elternteile)
    # ----------------------------------------------------
    def page_calendar():
        st.caption("Alle Termine deiner Teams. Auf dem Handy ist die Liste am übersichtlichsten.")

        team_filter = st.pills("Team", ["Meine Teams"] + TEAM_LISTE, default="Meine Teams",
                               key="cal_team", label_visibility="collapsed") or "Meine Teams"
        c_art, c_view = st.columns([3, 2])
        with c_art:
            art_filter = st.segmented_control("Art", ["Alle", "Spiele", "Schiedsgericht", "Aufgaben"], default="Alle",
                                              key="cal_art", label_visibility="collapsed") or "Alle"
        with c_view:
            view = st.segmented_control("Ansicht", ["Liste", "Monat"], default="Liste",
                                        key="cal_view", label_visibility="collapsed") or "Liste"
        st.markdown(
            f'<div style="font-size:.8rem;color:#666;margin:-4px 0 6px 0">'
            f'<span style="color:{BRAND}">●</span> Spiel &nbsp; '
            f'<span style="color:{SCHIRI_COLOR}">●</span> Schiedsgericht &nbsp; '
            f'<span style="color:#5f5f5f">●</span> Aufgabe</div>', unsafe_allow_html=True)

        def cal_is_relevant(teams_str):
            if team_filter == "Meine Teams":
                return is_relevant(teams_str)
            if pd.isna(teams_str) or not str(teams_str).strip():
                return False
            return team_filter in [t.strip() for t in str(teams_str).split(',')]

        to_ts = parse_datum
        ohne_datum = []

        # ---- Einträge sammeln (Spieltage + freie Aufgaben) ----
        entries = []
        if not events_df.empty:
            for _, ev in events_df[events_df['betroffene_teams'].apply(cal_is_relevant)].iterrows():
                ts = to_ts(ev['start_zeit'])
                if ts is None:
                    ohne_datum.append(f"{ev['titel']} ({ev['start_zeit']})")
                    continue
                # Gehört zu diesem Spiel eine Schiedsgericht-Aufgabe (z. B. aus dem SAMS-Import)?
                schiri = tasks_df[(tasks_df['event_id'] == ev['event_id']) &
                                  tasks_df['kategorie'].astype(str).str.lower().str.contains('schiedsgericht')] if not tasks_df.empty else pd.DataFrame()
                spielt_selbst = 'bocholt' in str(ev['titel']).lower()
                eintrag = {
                    "id": f"ev{ev['event_id']}", "ts": ts, "end": to_ts(ev.get('ende_zeit')),
                    "art": "Spieltag", "titel": str(ev['titel']),
                    "teams": str(ev['betroffene_teams'] or ""), "ort": str(ev.get('ort') or ""),
                    "farbe": BRAND, "schiri": False,
                }
                if not schiri.empty:
                    eintrag["schiri"] = True
                    sr_ids = schiri['task_id'].tolist()
                    eintrag["belegt"] = int(assign_df['task_id'].isin(sr_ids).sum()) if not assign_df.empty else 0
                    eintrag["max"] = int(pd.to_numeric(schiri['max_helfer'], errors='coerce').fillna(1).sum())
                    if not spielt_selbst:
                        eintrag["art"] = "Schiedsgericht"
                        eintrag["farbe"] = SCHIRI_COLOR
                entries.append(eintrag)
        if not tasks_df.empty:
            for _, tk in tasks_df[tasks_df['event_id'].isna() & tasks_df['betroffene_teams'].apply(cal_is_relevant)].iterrows():
                ts = to_ts(tk.get('start_zeit'))
                if ts is None:
                    ohne_datum.append(f"{tk['kategorie']} ({tk.get('start_zeit')})")
                    continue
                belegt = int((assign_df['task_id'] == tk['task_id']).sum()) if not assign_df.empty else 0
                maximal = int(tk.get('max_helfer', 1) or 1)
                ist_sr = 'schiedsgericht' in str(tk['kategorie']).lower()
                entries.append({
                    "id": f"tk{tk['task_id']}", "ts": ts, "end": None,
                    "art": "Schiedsgericht" if ist_sr else "Aufgabe", "titel": str(tk['kategorie']),
                    "teams": str(tk.get('betroffene_teams') or "Alle"), "ort": "",
                    "farbe": SCHIRI_COLOR if ist_sr else "#5f5f5f", "belegt": belegt, "max": maximal,
                    "schiri": ist_sr,
                })
        if art_filter == "Spiele":
            entries = [e for e in entries if e["art"] == "Spieltag"]
        elif art_filter == "Schiedsgericht":
            entries = [e for e in entries if e.get("schiri")]
        elif art_filter == "Aufgaben":
            entries = [e for e in entries if e["art"] == "Aufgabe"]
        entries.sort(key=lambda e: e["ts"])

        if ohne_datum:
            st.warning(f"{len(ohne_datum)} Termin(e) können nicht angezeigt werden, weil das Datum nicht lesbar ist, "
                       f"z. B.: {ohne_datum[0]}")

        if not entries:
            st.info("Keine Termine für diese Auswahl.")
            return

        WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
        MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
                  "August", "September", "Oktober", "November", "Dezember"]
        esc = lambda v: html.escape(str(v))

        def entry_card(e):
            zeit = e["ts"].strftime("%H:%M")
            zeit_txt = "" if zeit == "00:00" else f"{zeit} Uhr"
            details = " · ".join([x for x in [zeit_txt, esc(e["ort"])] if x])
            status = ""
            if e["art"] == "Spieltag" and e.get("schiri"):
                status += '<span class="tub-badge sr">+ Schiedsgericht</span> '
            if "max" in e:
                frei = max(e["max"] - e["belegt"], 0)
                status += f'<span class="tub-badge">{frei} frei</span>' if frei else '<span class="tub-badge grey">besetzt</span>' 
            return f"""
            <div class="cal-item" style="border-left-color:{e['farbe']}">
                <div class="cal-date">
                    <div class="cal-wd">{WOCHENTAGE[e['ts'].weekday()]}</div>
                    <div class="cal-day">{e['ts'].day}</div>
                </div>
                <div class="cal-body">
                    <div class="cal-kind">{esc(e['art'])} · {esc(e['teams'])}</div>
                    <div class="cal-title">{esc(e['titel'])} {status}</div>
                    <div class="cal-meta">{details}</div>
                </div>
            </div>"""

        CARD_CSS = f"""
        <style>
        .cal-month {{font-weight:700; color:{BRAND}; margin:18px 0 8px 0; font-size:.95rem; text-transform:uppercase; letter-spacing:.06em;}}
        .cal-item {{display:flex; gap:14px; align-items:flex-start; background:#fff; border:1px solid #eee5ef;
                   border-left:5px solid {BRAND}; border-radius:12px; padding:10px 14px; margin-bottom:8px;}}
        .cal-date {{min-width:42px; text-align:center;}}
        .cal-wd {{font-size:.75rem; color:#777; text-transform:uppercase;}}
        .cal-day {{font-size:1.45rem; font-weight:700; line-height:1.1;}}
        .cal-body {{flex:1; min-width:0;}}
        .cal-kind {{font-size:.75rem; color:#777;}}
        .cal-title {{font-weight:600; overflow-wrap:anywhere;}}
        .cal-meta {{font-size:.85rem; color:#555; overflow-wrap:anywhere;}}
        .tub-badge.sr {{background: rgba(194, 65, 12, .12); color: {SCHIRI_COLOR};}}
        </style>"""

        def render_list(items):
            out, last_month = [CARD_CSS], None
            for e in items:
                m = (e["ts"].year, e["ts"].month)
                if m != last_month:
                    out.append(f'<div class="cal-month">{MONATE[m[1]-1]} {m[0]}</div>')
                    last_month = m
                out.append(entry_card(e))
            # Zeilen ohne Einrückung zusammenfügen, damit Markdown das HTML nicht als Codeblock liest
            html_block = "".join(line.strip() for line in "".join(out).splitlines())
            st.markdown(html_block, unsafe_allow_html=True)

        # ---------------- LISTE (Standard, handyfreundlich) ----------------
        if view == "Liste":
            heute = pd.Timestamp.now().normalize()
            kommend = [e for e in entries if e["ts"] >= heute]
            vergangen = [e for e in entries if e["ts"] < heute][::-1]
            if kommend:
                render_list(kommend)
            else:
                st.success("Keine anstehenden Termine.")
            if vergangen:
                with st.expander(f"Vergangene Termine ({len(vergangen)})"):
                    render_list(vergangen)
            return

        # ---------------- MONAT (eher für den PC) ----------------
        cal_events = []
        for e in entries:
            if e["art"] == "Spieltag":
                kurz = e["teams"]
            elif e["art"] == "Schiedsgericht":
                kurz = f"SR {e['teams']}"
            else:
                kurz = e["titel"]
            cal_events.append({
                "id": e["id"], "title": kurz,
                "start": e["ts"].isoformat(),
                "end": (e["end"] or e["ts"]).isoformat(),
                "backgroundColor": e["farbe"], "borderColor": e["farbe"], "textColor": "#ffffff",
            })
        calendar_options = {
            "initialView": "dayGridMonth",
            "headerToolbar": {"left": "prev,next", "center": "title", "right": "today"},
            "buttonText": {"today": "Heute"},
            "locale": "de",
            "firstDay": 1,
            "height": "auto",
            "dayMaxEvents": 2,
            "moreLinkText": "mehr",
            "eventDisplay": "block",
            "displayEventTime": False,
            "fixedWeekCount": False,
        }
        custom_css = """
            .fc .fc-toolbar { flex-wrap: wrap; gap: 6px; }
            .fc .fc-toolbar-title { font-size: 1.05rem !important; }
            .fc .fc-button { padding: .3em .6em !important; font-size: .85rem !important; border-radius: 8px !important; }
            .fc .fc-daygrid-day-number { font-size: .8rem; }
            .fc .fc-col-header-cell-cushion { font-size: .75rem; }
            .fc .fc-event-title { font-size: .72rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
            .fc-theme-standard .fc-scrollgrid { border-radius: 10px; overflow: hidden; }
        """
        state = calendar(events=cal_events, options=calendar_options, custom_css=custom_css,
                         key=f"cal_{team_filter}")
        st.caption("Tippe auf einen Termin, um die Details zu sehen.")

        clicked = None
        if isinstance(state, dict) and state.get("callback") == "eventClick":
            clicked = (state.get("eventClick") or {}).get("event", {}).get("id")
        if clicked:
            treffer = [e for e in entries if e["id"] == clicked]
            if treffer:
                render_list(treffer)

    # ----------------------------------------------------
    # TAB 4: FAMILIE
    # ----------------------------------------------------
    def page_family():
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
    # TAB 5: PUNKTE & AUSWERTUNG (Trainer, Organisatoren, Admin)
    # ----------------------------------------------------
    def page_stats():
        st.subheader("📊 Helferpunkte der Elternteile")
        st.write("Hier siehst du, wie viele Punkte die jeweiligen Elternteile durch übernommene Aufgaben gesammelt haben.")
            
        if not points_df.empty:
            eltern_df = points_df[points_df['rolle'] == 'Elternteil'].copy()
                
            if user['rolle'] == 'Trainer' and user.get('team') and user['team'] != "Kein Team":
                trainer_teams = [t.strip() for t in user['team'].split(',')]
                st.caption(f"Dein Trainer-Team-Filter: **{', '.join(trainer_teams)}**")
                eltern_df = eltern_df[eltern_df['team'].apply(lambda t: any(team in str(t) for team in trainer_teams))]
                
            if not eltern_df.empty:
                display_df = eltern_df[['name', 'team', 'gesamt_punkte']].rename(
                    columns={'name': 'Elternteil', 'team': 'Zugeordnete Teams', 'gesamt_punkte': 'Gesammelte Punkte'}
                ).sort_values(by='Gesammelte Punkte', ascending=False)
                    
                st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("Keine Elternteile für diese Auswahl gefunden.")
        else:
            st.info("Noch keine Punkteeinträge vorhanden.")

    # ----------------------------------------------------
    # TAB 6: ADMIN
    # ----------------------------------------------------
    def page_admin():
        st.subheader("🚨 Spielplan zurücksetzen (Massen-Löschen)")
        st.write("Lösche alle Termine eines Teams, bevor du einen aktualisierten Spielplan hochlädst, um doppelte Einträge zu vermeiden.")
        with st.form("delete_team_events"):
            del_team = st.selectbox("Welches Team soll zurückgesetzt werden?", TEAM_LISTE)
            confirm_del = st.checkbox("Ja, ich möchte alle Termine, Aufgaben und Rückmeldungen dieses Teams unwiderruflich löschen.")
            if st.form_submit_button("Spielplan löschen"):
                if confirm_del:
                    succ, msg = delete_all_events_for_team(del_team)
                    if succ: 
                        st.success(msg)
                        st.rerun()
                    else: 
                        st.error(msg)
                else:
                    st.warning("Bitte bestätige den Löschvorgang mit dem Häkchen.")
            
        st.divider()
            
        st.subheader("📅 Spielplan-Import (SAMS CSV)")
        st.write("Lade den Spielplan als **CSV-Datei** aus SAMS hoch. Übernommen werden **nur Spiele, bei denen TuB Bocholt spielt oder das Schiedsgericht stellt**. Für Schiedsgericht-Einsätze wird automatisch eine Aufgabe angelegt.")
        csv_file = st.file_uploader("SAMS CSV-Datei auswählen", type=["csv"], key="sams_csv")
        if csv_file is not None:
            sams_rows, sams_info = read_sams_csv(csv_file.getvalue())
            if sams_rows is None:
                st.error(sams_info)
            elif sams_rows.empty:
                st.warning(sams_info + " Es gibt nichts zu importieren.")
            else:
                st.caption(sams_info + " Vorschau:")
                st.dataframe(sams_rows[["Datum", "Uhrzeit", "Spiel", "Rolle", "Ort"]], hide_index=True, use_container_width=True)
                with st.form("csv_import"):
                    target_team = st.multiselect("Für welches Team gilt dieser Spielplan?", TEAM_LISTE)
                    if st.form_submit_button(f"Diese {len(sams_rows)} Spiele importieren"):
                        if target_team:
                            succ, msg = import_sams_rows(sams_rows, ", ".join(target_team))
                            if succ: st.success(msg)
                            else: st.error(msg)
                        else:
                            st.warning("Bitte ein Team wählen.")
                    
        st.divider()
        st.subheader("👥 User-Verwaltung")
        st.dataframe(all_users_df, use_container_width=True)
            
        st.divider()
        st.subheader("🎭 Rollen vergeben")
        st.write("Trainer, Organisatoren und weitere Admins können sich nicht selbst registrieren. Hier vergibst du diese Rollen.")
        if not all_users_df.empty:
            with st.form("role_form"):
                erwachsene = all_users_df[all_users_df['rolle'] != 'Kind']
                opts_r = {r['user_id']: f"{r['name']} ({r['rolle']})" for _, r in erwachsene.iterrows()}
                role_uid = st.selectbox("Benutzer", list(opts_r.keys()), format_func=lambda x: opts_r[x])
                new_role = st.selectbox("Neue Rolle", VERGEBBARE_ROLLEN)
                if st.form_submit_button("Rolle speichern"):
                    if role_uid == user['user_id'] and new_role != 'Admin':
                        st.warning("Du kannst dir nicht selbst die Admin-Rolle entziehen.")
                    else:
                        ok, msg = set_user_role(role_uid, new_role)
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)
            
        st.divider()
        st.subheader("🔑 Passwort zurücksetzen")
        st.write("Vergib hier ein neues Passwort für Nutzer, die ihres vergessen haben.")
        with st.form("reset_pw_form"):
            opts = {r['user_id']: f"{r['name']} ({r['email']})" for _, r in all_users_df.iterrows()}
            reset_id = st.selectbox("Benutzer auswählen:", list(opts.keys()), format_func=lambda x: opts[x])
            new_pw = st.text_input("Neues Passwort", type="password")
                
            if st.form_submit_button("Passwort überschreiben"):
                if len(new_pw.strip()) < MIN_PW_LENGTH:
                    st.warning(f"Bitte ein Passwort mit mindestens {MIN_PW_LENGTH} Zeichen eingeben.")
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

    # ----------------------------------------------------
    # NAVIGATION (Seitenleiste) – nur erlaubte Seiten werden angeboten
    # ----------------------------------------------------
    pages = [
        st.Page(page_overview, title="Übersicht", icon=":material/home:", url_path="uebersicht", default=True),
        st.Page(page_events, title="Spieltage", icon=":material/sports_volleyball:", url_path="spieltage"),
        st.Page(page_tasks, title="Freie Aufgaben", icon=":material/task_alt:", url_path="aufgaben"),
    ]
    if user['rolle'] != 'Elternteil':
        pages.append(st.Page(page_calendar, title="Kalender", icon=":material/calendar_month:", url_path="kalender"))
    pages.append(st.Page(page_family, title="Familie", icon=":material/family_restroom:", url_path="familie"))
    if user['rolle'] in ['Admin', 'Organisator', 'Trainer']:
        pages.append(st.Page(page_stats, title="Punkte & Auswertung", icon=":material/leaderboard:", url_path="punkte"))
    if user['rolle'] == 'Admin':
        pages.append(st.Page(page_admin, title="Admin", icon=":material/admin_panel_settings:", url_path="admin"))

    nav = st.navigation(pages, position="sidebar")

    with st.sidebar:
        st.markdown(f"""
        <div class="tub-user">
            <div class="name">{html.escape(str(user['name']))}</div>
            <div class="role">{html.escape(str(user['rolle']))}</div>
        </div>
        """, unsafe_allow_html=True)
        st.write("")
        if st.button("Ausloggen", icon=":material/logout:", use_container_width=True):
            delete_login_session(st.session_state.pop('session_token', None) or read_session_cookie())
            st.session_state['logged_in_user'] = None
            st.session_state['logged_out'] = True
            st.session_state['clear_cookie'] = True
            st.rerun()

    nav.run()

render_footer()
