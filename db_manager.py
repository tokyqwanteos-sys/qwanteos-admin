import sqlite3
import json
import os
import pandas as pd
from datetime import datetime

DB_PATH = "qwanteos.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Activer le mode WAL pour améliorer la concurrence en multi-utilisateurs
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            full_name TEXT,
            role TEXT NOT NULL DEFAULT 'operateur',
            created_at TEXT,
            last_login TEXT,
            login_attempts INTEGER DEFAULT 0,
            locked_until TEXT
        );
        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT NOT NULL,
            poste TEXT,
            actif INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS planning (
            date TEXT NOT NULL,
            agent_id INTEGER NOT NULL,
            statut TEXT NOT NULL,
            FOREIGN KEY (agent_id) REFERENCES agents(id),
            PRIMARY KEY (date, agent_id)
        );
        CREATE TABLE IF NOT EXISTS heures (
            date TEXT NOT NULL,
            agent_id INTEGER NOT NULL,
            total REAL DEFAULT 0,
            nuit REAL DEFAULT 0,
            FOREIGN KEY (agent_id) REFERENCES agents(id),
            PRIMARY KEY (date, agent_id)
        );
        CREATE TABLE IF NOT EXISTS taches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id INTEGER NOT NULL,
            tache TEXT NOT NULL,
            match_info TEXT,
            wf TEXT,
            ligue TEXT,
            remarques TEXT,
            statut TEXT NOT NULL,
            date_debut TEXT,
            date_fin TEXT,
            temps_total_secondes INTEGER DEFAULT 0,
            temps_formate TEXT,
            evenements TEXT,
            FOREIGN KEY (agent_id) REFERENCES agents(id)
        );
        CREATE TABLE IF NOT EXISTS cloud_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            source_feuille TEXT,
            type_travail TEXT,
            statut TEXT,
            duree_total TEXT,
            duree_num REAL,
            remarques TEXT,
            date_parsed TEXT,
            jour TEXT,
            semaine TEXT,
            mois TEXT
        );
        CREATE TABLE IF NOT EXISTS connection_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            username TEXT,
            success INTEGER,
            ip TEXT
        );
        CREATE TABLE IF NOT EXISTS pointages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            agent_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (agent_id) REFERENCES agents(id)
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            full_name TEXT,
            message TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            is_read INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()

# ---------- AGENTS ----------
def get_all_agents():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, nom, poste, actif FROM agents ORDER BY nom")
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def add_agent(nom, poste):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO agents (nom, poste, actif) VALUES (?, ?, 1)", (nom, poste))
    conn.commit()
    conn.close()

def delete_agent(agent_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    conn.commit()
    conn.close()

# ---------- PLANNING ----------
def get_planning_for_date(date):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT agent_id, statut FROM planning WHERE date = ?", (date,))
    rows = c.fetchall()
    conn.close()
    return {row["agent_id"]: row["statut"] for row in rows}

def set_planning(date, agent_id, statut):
    conn = get_db()
    c = conn.cursor()
    c.execute("REPLACE INTO planning (date, agent_id, statut) VALUES (?, ?, ?)", (date, agent_id, statut))
    conn.commit()
    conn.close()

# ---------- HEURES (addition) ----------
def get_heures_for_date(date):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT agent_id, total, nuit FROM heures WHERE date = ?", (date,))
    rows = c.fetchall()
    conn.close()
    return {row["agent_id"]: {"total": row["total"], "nuit": row["nuit"]} for row in rows}

def set_heures(date, agent_id, total, nuit=0):
    """Ajoute les heures (total et nuit) à la date existante."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO heures (date, agent_id, total, nuit)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(date, agent_id) DO UPDATE SET
            total = total + excluded.total,
            nuit = nuit + excluded.nuit
    """, (date, agent_id, total, nuit))
    conn.commit()
    conn.close()

# ---------- TÂCHES ----------
def add_task(agent_id, tache, match_info, wf, ligue, remarques, statut, date_debut, evenements):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO taches (agent_id, tache, match_info, wf, ligue, remarques, statut, date_debut, evenements)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (agent_id, tache, match_info, wf, ligue, remarques, statut, date_debut, json.dumps(evenements)))
    conn.commit()
    conn.close()
    return c.lastrowid

def update_task(task_id, **kwargs):
    conn = get_db()
    c = conn.cursor()
    fields = []
    values = []
    for key, val in kwargs.items():
        if key == "evenements":
            val = json.dumps(val)
        fields.append(f"{key} = ?")
        values.append(val)
    values.append(task_id)
    c.execute(f"UPDATE taches SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    conn.close()

def get_tasks_by_agent(agent_id, statut=None):
    conn = get_db()
    c = conn.cursor()
    if statut:
        c.execute("SELECT * FROM taches WHERE agent_id = ? AND statut = ?", (agent_id, statut))
    else:
        c.execute("SELECT * FROM taches WHERE agent_id = ?", (agent_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ---------- CLOUD DATA ----------
def add_cloud_data(row):
    def safe_str(val):
        if pd.isna(val):
            return None
        if isinstance(val, pd.Timestamp):
            return val.isoformat()
        if val is None:
            return None
        return str(val)

    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO cloud_data (date, source_feuille, type_travail, statut, duree_total, duree_num, remarques, date_parsed, jour, semaine, mois)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        safe_str(row.get("Date")),
        safe_str(row.get("Source_Feuille")),
        safe_str(row.get("Type_Travail")),
        safe_str(row.get("Statut")),
        safe_str(row.get("Duree_Total")),
        row.get("Duree_Num"),
        safe_str(row.get("Remarques")),
        safe_str(row.get("Date_Parsed")),
        safe_str(row.get("Jour")),
        safe_str(row.get("Semaine")),
        safe_str(row.get("Mois"))
    ))
    conn.commit()
    conn.close()

def get_all_cloud_data():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM cloud_data")
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def clear_cloud_data():
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM cloud_data")
    conn.commit()
    conn.close()

# ---------- POINTAGES ----------
def add_pointage(date, agent_id, type_pointage, timestamp):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO pointages (date, agent_id, type, timestamp)
        VALUES (?, ?, ?, ?)
    """, (date, agent_id, type_pointage, timestamp))
    conn.commit()
    conn.close()

def get_pointages_by_date_agent(date, agent_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT type, timestamp FROM pointages WHERE date = ? AND agent_id = ? ORDER BY timestamp", (date, agent_id))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_pointages_by_date(date):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT agent_id, type, timestamp FROM pointages WHERE date = ? ORDER BY agent_id, timestamp", (date,))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def clear_pointages(date=None, agent_id=None):
    conn = get_db()
    c = conn.cursor()
    if date and agent_id:
        c.execute("DELETE FROM pointages WHERE date = ? AND agent_id = ?", (date, agent_id))
    elif date:
        c.execute("DELETE FROM pointages WHERE date = ?", (date,))
    else:
        c.execute("DELETE FROM pointages")
    conn.commit()
    conn.close()

# ---------- MESSAGES ----------
def add_message(username, full_name, message):
    conn = get_db()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("""
        INSERT INTO messages (username, full_name, message, timestamp, is_read)
        VALUES (?, ?, ?, ?, 0)
    """, (username, full_name, message, now))
    conn.commit()
    conn.close()

def get_messages(limit=50):
    """Récupère les derniers messages (limite) du plus récent au plus ancien."""
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT username, full_name, message, timestamp, is_read
        FROM messages
        ORDER BY timestamp DESC
        LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def count_unread_messages(username=None):
    """Compte les messages non lus. Si username est fourni, exclut ses propres messages."""
    conn = get_db()
    c = conn.cursor()
    if username:
        c.execute("SELECT COUNT(*) FROM messages WHERE is_read = 0 AND username != ?", (username,))
    else:
        c.execute("SELECT COUNT(*) FROM messages WHERE is_read = 0")
    count = c.fetchone()[0]
    conn.close()
    return count

def mark_messages_as_read(username):
    """Marque comme lus tous les messages (sauf ceux de l'utilisateur)."""
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE messages SET is_read = 1 WHERE username != ? AND is_read = 0", (username,))
    conn.commit()
    conn.close()
