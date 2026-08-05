import sqlite3
import json
import os
from datetime import datetime

DB_PATH = "qwanteos.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

# ---------- Lecture du fichier ----------
SAUVEGARDE_FILE = "sauvegardes/sauvegarde_last.json"

if not os.path.exists(SAUVEGARDE_FILE):
    print(f"❌ Fichier {SAUVEGARDE_FILE} introuvable.")
    exit(1)

with open(SAUVEGARDE_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

print("✅ Fichier chargé.")

# ---------- Connexion à la base ----------
conn = get_db()
c = conn.cursor()

# ---------- Sauvegarde de la base actuelle (facultatif mais prudent) ----------
conn.execute("BEGIN TRANSACTION")
# On peut vider les tables avant restauration (attention : perte des données récentes)
# Demander confirmation
reponse = input("⚠️  Voulez-vous vider les tables existantes et restaurer depuis la sauvegarde ? (o/N) : ")
if reponse.lower() != "o":
    print("❌ Opération annulée.")
    conn.close()
    exit(0)

# Vider les tables
tables = ["agents", "planning", "heures", "taches", "pointages", "messages", "cloud_data", "shared_tasks"]
for table in tables:
    c.execute(f"DELETE FROM {table}")
print("🗑️ Tables vidées.")

# ---------- 1. Restaurer les agents ----------
agents_data = data.get("agents", [])
for agent in agents_data:
    # Le fichier a des clés "Nom", "Poste", "id" ; on les transforme
    nom = agent["Nom"]
    poste = agent["Poste"]
    # On insère sans l'id pour que SQLite génère un nouvel id
    c.execute("INSERT INTO agents (nom, poste, actif) VALUES (?, ?, 1)", (nom, poste))
print(f"👤 {len(agents_data)} agents restaurés.")

# Récupérer les IDs des agents (pour les relations)
c.execute("SELECT id, nom FROM agents")
rows = c.fetchall()
nom_to_id = {row["nom"]: row["id"] for row in rows}

# ---------- 2. Restaurer le planning ----------
planning_data = data.get("planning", {})
compteur_planning = 0
for date_str, plan in planning_data.items():
    for nom, statut in plan.items():
        agent_id = nom_to_id.get(nom)
        if agent_id:
            c.execute("INSERT OR REPLACE INTO planning (date, agent_id, statut) VALUES (?, ?, ?)",
                      (date_str, agent_id, statut))
            compteur_planning += 1
print(f"📅 {compteur_planning} entrées de planning restaurées.")

# ---------- 3. Restaurer les heures ----------
heures_data = data.get("heures", {})
compteur_heures = 0
for date_str, dict_agents in heures_data.items():
    for nom, values in dict_agents.items():
        agent_id = nom_to_id.get(nom)
        if agent_id:
            if isinstance(values, dict):
                total = values.get("total", 0.0)
                nuit = values.get("nuit", 0.0)
            else:
                total = float(values)
                nuit = 0.0
            # On fait un INSERT OR REPLACE pour éviter les conflits
            c.execute("INSERT OR REPLACE INTO heures (date, agent_id, total, nuit) VALUES (?, ?, ?, ?)",
                      (date_str, agent_id, total, nuit))
            compteur_heures += 1
print(f"⏱️ {compteur_heures} enregistrements d'heures restaurés.")

# ---------- 4. Restaurer les données cloud ----------
cloud_data = data.get("donnees_cloud_centralisees", [])
compteur_cloud = 0
for row in cloud_data:
    # Les colonnes attendues dans la table cloud_data
    # On s'assure que les clés existent
    c.execute("""
        INSERT INTO cloud_data (
            date, source_feuille, type_travail, statut, duree_total, duree_num,
            remarques, date_parsed, jour, semaine, mois
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        row.get("date"),
        row.get("source_feuille"),
        row.get("type_travail"),
        row.get("statut"),
        row.get("duree_total"),
        row.get("duree_num", 0.0),
        row.get("remarques"),
        row.get("date_parsed"),
        row.get("jour"),
        row.get("semaine"),
        row.get("mois")
    ))
    compteur_cloud += 1
print(f"☁️ {compteur_cloud} enregistrements cloud restaurés.")

# ---------- 5. Restaurer les tâches ----------
# 5a. Tâches terminées (depuis taches_operateur)
taches_operateur = data.get("taches_operateur", {})
compteur_taches = 0
for tache, entries in taches_operateur.items():
    for entry in entries:
        # Récupérer l'agent via l'utilisateur de la sauvegarde (ici "Toky")
        # Mais on peut aussi stocker le nom de l'agent dans la sauvegarde ? Non. On va utiliser l'utilisateur "Toky" comme agent pour ces tâches.
        # Pour simplifier, on va attribuer ces tâches à l'agent correspondant au nom "Toky" (qui est dans nom_to_id)
        agent_id = nom_to_id.get("Toky")
        if not agent_id:
            # Si "Toky" n'existe pas, on prend le premier agent (mais normalement il existe)
            agent_id = list(nom_to_id.values())[0] if nom_to_id else None
        if not agent_id:
            print("⚠️ Aucun agent trouvé pour les tâches, saut.")
            break

        # Extraire les champs
        evenements = entry.get("evenements", [])
        date_debut = entry.get("date_debut", "")
        date_fin = entry.get("date_fin", "")
        temps_secondes = entry.get("temps_secondes", 0)
        temps_formate = entry.get("temps_formate", "00:00:00")
        match_info = entry.get("match", "")
        wf = entry.get("wf", "")
        ligue = entry.get("ligue", "")
        remarques = entry.get("remarques", "")
        statut = "termine"  # puisque c'est terminé

        # Insérer
        c.execute("""
            INSERT INTO taches (
                agent_id, tache, match_info, wf, ligue, remarques,
                statut, date_debut, date_fin, temps_total_secondes, temps_formate, evenements
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            agent_id, tache, match_info, wf, ligue, remarques,
            statut, date_debut, date_fin, int(temps_secondes), temps_formate,
            json.dumps(evenements)
        ))
        compteur_taches += 1
print(f"📋 {compteur_taches} tâches terminées restaurées.")

# 5b. Tâches en cours (depuis taches_en_cours)
taches_en_cours = data.get("taches_en_cours", [])
compteur_cours = 0
for task in taches_en_cours:
    agent_id = nom_to_id.get("Toky")  # même logique
    if not agent_id:
        agent_id = list(nom_to_id.values())[0] if nom_to_id else None
    if not agent_id:
        break

    # Extraire
    tache = task.get("tache")
    match_info = task.get("match", "")
    wf = task.get("wf", "")
    ligue = task.get("ligue", "")
    remarques = task.get("remarques", "")
    statut = task.get("statut", "en_cours")  # peut être "en_cours" ou "pause"
    date_debut = task.get("date_debut", "")
    date_fin = task.get("date_fin", "")
    temps_total_secondes = task.get("temps_total_secondes", 0)
    temps_formate = task.get("temps_formate", "00:00:00")
    evenements = task.get("evenements", [])

    c.execute("""
        INSERT INTO taches (
            agent_id, tache, match_info, wf, ligue, remarques,
            statut, date_debut, date_fin, temps_total_secondes, temps_formate, evenements
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        agent_id, tache, match_info, wf, ligue, remarques,
        statut, date_debut, date_fin, int(temps_total_secondes), temps_formate,
        json.dumps(evenements)
    ))
    compteur_cours += 1
print(f"⏳ {compteur_cours} tâches en cours restaurées.")

# ---------- Validation ----------
conn.commit()
conn.close()

print("✅ Restauration terminée avec succès !")
print(f"Résumé : {len(agents_data)} agents, {compteur_planning} planning, {compteur_heures} heures, {compteur_cloud} cloud, {compteur_taches} tâches terminées, {compteur_cours} en cours.")
