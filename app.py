# ... existing code ...
    # --- ZENTRALER DATENABRUF ---
    try:
        tasks_df = get_all_tasks_with_assignees()
    except Exception:
        tasks_df = pd.DataFrame()

    # --- 📅 Mein Team-Kalender ---
    st.markdown("---")
    st.subheader("📅 Mein Kalender (Teams & Allgemein)")
    st.write("Hier siehst du übersichtlich alle anstehenden Termine, die für deine Mannschaften (und die deiner Kinder) relevant sind, sowie allgemeine Vereins-Termine.")
    
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
        def is_relevant_event(task_teams_str):
            # Wenn kein Team angegeben ist (allgemeiner Termin), für alle anzeigen
            if pd.isna(task_teams_str) or not str(task_teams_str).strip() or task_teams_str == "None":
                return True
            
            # Ansonsten prüfen, ob eines der betroffenen Teams in meinen Teams ist
            task_teams_list = [t.strip() for t in task_teams_str.split(',')]
            return any(team in my_teams for team in task_teams_list)
            
        # Filtern der Tabelle
        cal_df = tasks_df[tasks_df['betroffene_teams'].apply(is_relevant_event)].copy()
        
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
            st.info("Es stehen aktuell keine Termine an.")
    else:
        st.info("Es sind noch keine Aufgaben oder Termine im System angelegt.")

    # --- Haupt-Dashboard: AUFGABEN ---
    st.markdown("---")
# ... existing code ...
