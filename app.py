def parse_and_import_csv(file_bytes, team_str):
    try:
        content = file_bytes.decode('utf-8', errors='replace')
        df = pd.read_csv(io.StringIO(content), sep=';')
        if len(df.columns) < 2:
            df = pd.read_csv(io.StringIO(content), sep=',')
        
        events_added = 0
        tasks_added = 0
        
        with engine.begin() as conn:
            for _, row in df.iterrows():
                m1 = str(row.get('Mannschaft 1', 'Unbekannt'))
                m2 = str(row.get('Mannschaft 2', 'Unbekannt'))
                schiri = str(row.get('Schiedsgericht', ''))
                
                # Überspringe das Spiel, wenn TuB Bocholt weder spielt noch pfeift
                if 'bocholt' not in m1.lower() and 'bocholt' not in m2.lower() and 'bocholt' not in schiri.lower():
                    continue
                
                ort = str(row.get('Austragungsort', ''))
                
                date_col = [c for c in df.columns if 'Datum' in c]
                dt_str = str(row[date_col[0]]) if date_col else ""
                start_str = dt_str.replace(',', '').strip() if dt_str else ""
                titel = f"{m1} vs. {m2}"
                
                res = conn.execute(text("""
                    INSERT INTO events (titel, start_zeit, ende_zeit, ort, betroffene_teams)
                    VALUES (:titel, :start, :ende, :ort, :teams)
                    RETURNING event_id
                """), {"titel": titel, "start": start_str, "ende": "", "ort": ort, "teams": team_str})
                
                event_id = res.scalar()
                events_added += 1
                
                if 'bocholt' in schiri.lower():
                    conn.execute(text("""
                        INSERT INTO tasks (kategorie, beschreibung, max_helfer, start_zeit, betroffene_teams, event_id, punkte)
                        VALUES ('Schiedsgericht', 'Wir stellen das Schiedsgericht für dieses Spiel.', 2, :st, :teams, :ev, 2)
                    """), {"st": start_str, "teams": team_str, "ev": event_id})
                    tasks_added += 1
        
        clear_caches()
        return True, f"Erfolg! {events_added} relevante Spiele und {tasks_added} Schiedsgericht-Aufgaben für {team_str} importiert."
    except Exception as e:
        return False, f"Fehler beim CSV Import: {e}"
