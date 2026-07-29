import streamlit as st
import pandas as pd
import calendar
import time
import json
import os
import glob
import requests
import io
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta, time as datetime_time
from collections import defaultdict
import re
import hashlib
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import base64
from PIL import Image
from zoneinfo import ZoneInfo

import db_manager  # ← Nouvel import

# --- Nouvel import pour la sauvegarde manuelle ---
from sauvegarde_manager import gestionnaire_sauvegarde

# --- FUSEAU HORAIRE MADAGASCAR (UTC+3) ---
MADA_TZ = ZoneInfo("Indian/Antananarivo")

# --- LISTE GLOBALE DES TÂCHES DISPONIBLES (utilisée dans plusieurs pages) ---
TACHES_DISPONIBLES = [
    "INTEGRATION", "OTHER CAM", "PREMIUM", "CORRECTION",
    "SUBSTITUTIONS", "FEP", "MATCH SETUP", "ATTENTE VIDEOS",
    "CHECK", "PREPARATION", "FICHIER", "SCOUTING"
]

# --- INITIALISATION DE LA BASE DE DONNÉES ---
db_manager.init_db()

# --- CRÉATION DE LA TABLE shared_tasks SI ELLE N'EXISTE PAS ---
def init_shared_tasks_table():
    conn = db_manager.get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS shared_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tache TEXT NOT NULL,
            match_info TEXT,
            wf TEXT,
            ligue TEXT,
            remarques TEXT,
            date_creation TEXT,
            assigne_a TEXT,
            statut TEXT DEFAULT 'disponible'
        )
    """)
    conn.commit()
    conn.close()

init_shared_tasks_table()

# --- FONCTIONS POUR LES TÂCHES PARTAGÉES ---
def add_shared_task(tache, match_info="", wf="", ligue="", remarques="", assigne_a=None, statut="disponible"):
    conn = db_manager.get_db()
    c = conn.cursor()
    date_creation = datetime.now(MADA_TZ).isoformat()
    c.execute(
        "INSERT INTO shared_tasks (tache, match_info, wf, ligue, remarques, date_creation, assigne_a, statut) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (tache, match_info, wf, ligue, remarques, date_creation, assigne_a, statut)
    )
    conn.commit()
    conn.close()

def get_all_shared_tasks():
    conn = db_manager.get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM shared_tasks ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    tasks = []
    for row in rows:
        tasks.append({
            "id": row[0],
            "tache": row[1],
            "match_info": row[2] or "",
            "wf": row[3] or "",
            "ligue": row[4] or "",
            "remarques": row[5] or "",
            "date_creation": row[6],
            "assigne_a": row[7] or None,
            "statut": row[8]
        })
    return tasks

def update_shared_task(task_id, **kwargs):
    conn = db_manager.get_db()
    c = conn.cursor()
    fields = []
    values = []
    for key, val in kwargs.items():
        fields.append(f"{key} = ?")
        values.append(val)
    values.append(task_id)
    if fields:
        query = f"UPDATE shared_tasks SET {', '.join(fields)} WHERE id = ?"
        c.execute(query, values)
    conn.commit()
    conn.close()

def delete_shared_task(task_id):
    conn = db_manager.get_db()
    c = conn.cursor()
    c.execute("DELETE FROM shared_tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()

def get_tasks_for_agent(agent_name):
    conn = db_manager.get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM shared_tasks WHERE assigne_a = ? AND statut != 'termine'", (agent_name,))
    rows = c.fetchall()
    conn.close()
    tasks = []
    for row in rows:
        tasks.append({
            "id": row[0],
            "tache": row[1],
            "match_info": row[2] or "",
            "wf": row[3] or "",
            "ligue": row[4] or "",
            "remarques": row[5] or "",
            "date_creation": row[6],
            "assigne_a": row[7] or None,
            "statut": row[8]
        })
    return tasks

# --- MIGRATION DES DONNÉES EXISTANTES (une seule fois) ---
def migrer_donnees():
    """Importe les données depuis les fichiers JSON vers SQLite."""
    if not os.path.exists("sauvegardes/sauvegarde_last.json"):
        return
    # Vérifier si la table agents est vide
    conn = db_manager.get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM agents")
    if c.fetchone()[0] > 0:
        conn.close()
        return  # déjà migré
    conn.close()
    
    with open("sauvegardes/sauvegarde_last.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Agents
    for agent in data.get("agents", []):
        # Vérifier s'il existe déjà
        conn = db_manager.get_db()
        c = conn.cursor()
        c.execute("SELECT id FROM agents WHERE nom = ?", (agent["Nom"],))
        if not c.fetchone():
            db_manager.add_agent(agent["Nom"], agent["Poste"])
        conn.close()
    
    # Récupérer les IDs des agents
    agents_db = db_manager.get_all_agents()
    nom_to_id = {a["nom"]: a["id"] for a in agents_db}
    
    # Planning
    for date, plan in data.get("planning", {}).items():
        for nom, statut in plan.items():
            agent_id = nom_to_id.get(nom)
            if agent_id:
                db_manager.set_planning(date, agent_id, statut)
    
    # Heures
    for date, heures_dict in data.get("heures", {}).items():
        for nom, heures in heures_dict.items():
            agent_id = nom_to_id.get(nom)
            if agent_id:
                if isinstance(heures, dict):
                    total = heures.get("total", 0)
                    nuit = heures.get("nuit", 0)
                else:
                    total = float(heures)
                    nuit = 0
                db_manager.set_heures(date, agent_id, total, nuit)
    
    # Cloud data
    for row in data.get("donnees_cloud_centralisees", []):
        db_manager.add_cloud_data(row)
    
    # Tâches (on les ignore pour la migration, elles seront re-créées)
    # On peut aussi les migrer mais ce n'est pas critique.
    print("Migration terminée.")

# Exécuter la migration
# migrer_donnees()   # <--- SUPPRIMÉ : on ne l'appelle plus automatiquement

# --- NOUVELLE FONCTION DE FORMATAGE DES DATES ISO (avec fuseau Madagascar) ---
def formater_datetime_iso(iso_str):
    """Convertit une chaîne ISO en date/heure locale Madagascar (format DD/MM/YYYY HH:MM:SS)"""
    if not iso_str:
        return ""
    try:
        # Parser en naive puis attribuer le fuseau MADA
        dt = datetime.fromisoformat(iso_str)
        # Si la chaîne n'a pas de fuseau, on la considère comme locale MADA
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=MADA_TZ)
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    except:
        return iso_str

# --- FONCTION DE FORMATAGE DES DURÉES EN HH:MM:SS ---
def format_duration_hms(seconds):
    """Convertit un nombre de secondes en chaîne HH:MM:SS (avec gestion des négatifs)"""
    if seconds is None or pd.isna(seconds):
        return "00:00:00"
    signe = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{signe}{h:02d}:{m:02d}:{s:02d}"

# --- GESTION DES COMPTES UTILISATEURS ---
def hash_password(password):
    """Hache un mot de passe avec SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def validate_password(password):
    """Valide la complexité du mot de passe"""
    if len(password) < 8:
        return False, "Le mot de passe doit contenir au moins 8 caractères"
    if not re.search(r"[A-Z]", password):
        return False, "Le mot de passe doit contenir au moins une majuscule"
    if not re.search(r"[a-z]", password):
        return False, "Le mot de passe doit contenir au moins une minuscule"
    if not re.search(r"[0-9]", password):
        return False, "Le mot de passe doit contenir au moins un chiffre"
    return True, "Mot de passe valide"

def load_users():
    """Charge les utilisateurs depuis le fichier (pour compatibilité)"""
    users_file = "sauvegardes/users.json"
    if os.path.exists(users_file):
        try:
            with open(users_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_users(users):
    """Sauvegarde les utilisateurs dans le fichier (pour compatibilité)"""
    try:
        if not os.path.exists("sauvegardes"):
            os.makedirs("sauvegardes")
        with open("sauvegardes/users.json", "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=4)
        return True
    except:
        return False

def log_connection_attempt(username, success, ip="127.0.0.1"):
    """Journalise les tentatives de connexion"""
    log_file = "sauvegardes/connection_log.json"
    log_entry = {
        "timestamp": datetime.now(MADA_TZ).isoformat(),
        "username": username,
        "success": success,
        "ip": ip
    }
    
    try:
        if not os.path.exists("sauvegardes"):
            os.makedirs("sauvegardes")
        
        logs = []
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8") as f:
                logs = json.load(f)
        
        logs.append(log_entry)
        
        # Garder tous les logs sans limite
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(logs, f, ensure_ascii=False, indent=4)
    except:
        pass

def register_user(username, password, full_name="", role="operateur", access_code=""):
    """Enregistre un nouvel utilisateur avec gestion des rôles"""
    users = load_users()
    
    if username in users:
        return False, "Ce nom d'utilisateur existe déjà"
    
    # Vérification du code d'accès pour le rôle admin
    if role == "admin":
        if access_code != "2104":
            return False, "❌ Code d'accès Admin incorrect."
    # Pour operateur, pas de code requis
    
    valid, message = validate_password(password)
    if not valid:
        return False, message
    
    users[username] = {
        "password": hash_password(password),
        "full_name": full_name,
        "role": role,
        "created_at": datetime.now(MADA_TZ).isoformat(),
        "last_login": None,
        "login_attempts": 0,
        "locked_until": None
    }
    
    if save_users(users):
        return True, f"✅ Compte créé avec succès en tant que {role.capitalize()}"
    return False, "Erreur lors de la création du compte"

def authenticate_user(username, password):
    """Authentifie un utilisateur avec gestion des tentatives"""
    users = load_users()
    
    if username not in users:
        log_connection_attempt(username, False)
        return False, "Identifiant ou mot de passe incorrect"
    
    user = users[username]
    
    # Vérifier si le compte est bloqué
    if user.get("locked_until"):
        lock_time = datetime.fromisoformat(user["locked_until"])
        # Attribuer le fuseau MADA (si nécessaire)
        if lock_time.tzinfo is None:
            lock_time = lock_time.replace(tzinfo=MADA_TZ)
        if datetime.now(MADA_TZ) < lock_time:
            remaining = (lock_time - datetime.now(MADA_TZ)).seconds // 60
            return False, f"Compte bloqué pour {remaining} minutes"
    
    # Vérifier le mot de passe
    if user["password"] == hash_password(password):
        # Réinitialiser les tentatives
        user["login_attempts"] = 0
        user["locked_until"] = None
        user["last_login"] = datetime.now(MADA_TZ).isoformat()
        save_users(users)
        log_connection_attempt(username, True)
        
        # Stocker le rôle dans la session
        st.session_state.user_role = user.get("role", "operateur")
        return True, "Connexion réussie"
    else:
        # Incrémenter les tentatives
        user["login_attempts"] = user.get("login_attempts", 0) + 1
        
        # Bloquer après 5 tentatives
        if user["login_attempts"] >= 5:
            user["locked_until"] = (datetime.now(MADA_TZ) + timedelta(minutes=15)).isoformat()
            log_connection_attempt(username, False)
            save_users(users)
            return False, "Compte bloqué pour 15 minutes (trop de tentatives)"
        
        save_users(users)
        log_connection_attempt(username, False)
        remaining = 5 - user["login_attempts"]
        return False, f"Identifiant ou mot de passe incorrect. Tentatives restantes : {remaining}"

def get_user_role(username):
    """Récupère le rôle d'un utilisateur"""
    users = load_users()
    if username in users:
        return users[username].get("role", "operateur")
    return "operateur"

# --- FONCTION DE TIMEOUT D'INACTIVITÉ (DÉSACTIVÉE) ---
def check_inactivity():
    # Fonction désactivée - plus de timeout
    pass

# --- FONCTIONS POUR L'EXPORT GOOGLE SHEETS (VERSION INCRÉMENTIELLE) ---
def get_google_sheet_client():
    """Initialise le client Google Sheets via compte de service."""
    try:
        creds_dict = {
            "type": st.secrets["gcp"]["type"],
            "project_id": st.secrets["gcp"]["project_id"],
            "private_key_id": st.secrets["gcp"]["private_key_id"],
            "private_key": st.secrets["gcp"]["private_key"],
            "client_email": st.secrets["gcp"]["client_email"],
            "client_id": st.secrets["gcp"]["client_id"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": st.secrets["gcp"]["client_x509_cert_url"]
        }
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Erreur d'initialisation Google Sheets : {str(e)}")
        return None

def exporter_vers_google_sheets(utilisateur, df_export, spreadsheet_id):
    """
    Export incrémentiel : ajoute uniquement les lignes qui ne sont pas déjà présentes.
    Utilise la combinaison START, TACHES, DATE comme clé unique.
    """
    try:
        client = get_google_sheet_client()
        if client is None:
            return False, "Impossible d'initialiser le client Google Sheets."
        
        sheet = client.open_by_key(spreadsheet_id)
        
        # Vérifier si la feuille existe déjà
        try:
            worksheet = sheet.worksheet(utilisateur)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sheet.add_worksheet(title=utilisateur, rows="100", cols="20")
            # Nouvelle feuille : on écrit l'en-tête et toutes les données
            if not df_export.empty:
                headers = df_export.columns.tolist()
                worksheet.append_row(headers)
                for _, row in df_export.iterrows():
                    worksheet.append_row(row.tolist())
            return True, f"✅ Export initial vers la feuille '{utilisateur}' (créée)"
        
        # Feuille existante : lire les données actuelles
        existing_records = worksheet.get_all_values()
        if not existing_records:
            # Feuille vide : on écrit l'en-tête et toutes les lignes
            if not df_export.empty:
                headers = df_export.columns.tolist()
                worksheet.append_row(headers)
                for _, row in df_export.iterrows():
                    worksheet.append_row(row.tolist())
            return True, f"✅ Export réussi vers la feuille '{utilisateur}' (feuille vide)"
        
        # Extraire les en-têtes (première ligne)
        existing_headers = existing_records[0]
        # Les lignes de données (à partir de la deuxième ligne)
        existing_rows = existing_records[1:]
        
        # Construire un ensemble de clés uniques à partir des données existantes
        # On utilise les colonnes START, TACHES, DATE (ou une combinaison)
        # Pour la flexibilité, on utilise la colonne DATE, TACHES, START (ou MATCH / WF)
        # On va utiliser la clé composée de (START, TACHES, DATE) car c'est probablement unique
        # Note: les colonnes peuvent être dans un ordre différent, on les identifie par leur nom
        # On va créer un dictionnaire colonne -> index à partir des en-têtes
        col_index = {col: idx for idx, col in enumerate(existing_headers)}
        
        # Définir les colonnes clés : START, TACHES, DATE
        key_cols = ["START", "TACHES", "DATE"]
        # Vérifier si ces colonnes existent dans les en-têtes
        for k in key_cols:
            if k not in col_index:
                # Si une colonne clé manque, on ne peut pas dédupliquer proprement
                # On efface tout et on réécrit (comportement ancien)
                worksheet.clear()
                if not df_export.empty:
                    headers = df_export.columns.tolist()
                    worksheet.append_row(headers)
                    for _, row in df_export.iterrows():
                        worksheet.append_row(row.tolist())
                return True, f"✅ Export complet (déduplication impossible, réécriture) vers '{utilisateur}'"
        
        # Ensemble des clés existantes
        existing_keys = set()
        for row in existing_rows:
            # S'assurer que la ligne a assez de colonnes
            if len(row) <= max(col_index.values()):
                continue
            key = tuple(row[col_index[k]] for k in key_cols)
            existing_keys.add(key)
        
        # Parcourir les nouvelles lignes et ajouter celles qui n'existent pas
        added_count = 0
        for _, new_row in df_export.iterrows():
            key = tuple(str(new_row.get(k, "")) for k in key_cols)
            if key not in existing_keys:
                worksheet.append_row(new_row.tolist())
                added_count += 1
                # Ajouter la clé pour éviter les doublons dans le même lot
                existing_keys.add(key)
        
        return True, f"✅ Export incrémentiel réussi : {added_count} nouvelle(s) ligne(s) ajoutée(s) dans '{utilisateur}'"
    except Exception as e:
        return False, f"❌ Erreur : {str(e)}"

# --- CONFIGURATION DE L'APPLICATION ---
st.set_page_config(page_title="Qwanteos-Setup Admin", layout="wide", page_icon="⚙️")

# --- STYLE DARK TECH AVEC PARTICULES ANIMÉES (polices réduites) ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    * {
        font-family: 'Inter', 'Segoe UI', sans-serif;
    }
    
    /* Fond sombre avec dégradé et animation */
    .stApp {
        background: #0a0e1a;
        position: relative;
        overflow: hidden;
        min-height: 100vh;
    }
    
    /* Conteneur des particules */
    .particles-container {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        pointer-events: none;
        z-index: 0;
        overflow: hidden;
    }
    
    .particle {
        position: absolute;
        border-radius: 50%;
        background: rgba(100, 180, 255, 0.15);
        box-shadow: 0 0 20px rgba(100, 180, 255, 0.05);
        animation: floatParticle 20s infinite alternate ease-in-out;
    }
    
    .particle:nth-child(1) { width: 4px; height: 4px; top: 10%; left: 5%; animation-duration: 22s; animation-delay: 0s; }
    .particle:nth-child(2) { width: 6px; height: 6px; top: 30%; left: 80%; animation-duration: 25s; animation-delay: 2s; }
    .particle:nth-child(3) { width: 3px; height: 3px; top: 60%; left: 20%; animation-duration: 18s; animation-delay: 4s; }
    .particle:nth-child(4) { width: 5px; height: 5px; top: 80%; left: 70%; animation-duration: 28s; animation-delay: 1s; }
    .particle:nth-child(5) { width: 7px; height: 7px; top: 40%; left: 50%; animation-duration: 20s; animation-delay: 3s; }
    .particle:nth-child(6) { width: 4px; height: 4px; top: 15%; left: 40%; animation-duration: 24s; animation-delay: 5s; }
    .particle:nth-child(7) { width: 6px; height: 6px; top: 70%; left: 10%; animation-duration: 26s; animation-delay: 2s; }
    .particle:nth-child(8) { width: 3px; height: 3px; top: 90%; left: 90%; animation-duration: 19s; animation-delay: 6s; }
    .particle:nth-child(9) { width: 5px; height: 5px; top: 50%; left: 30%; animation-duration: 30s; animation-delay: 0s; }
    .particle:nth-child(10) { width: 4px; height: 4px; top: 20%; left: 60%; animation-duration: 21s; animation-delay: 4s; }
    
    @keyframes floatParticle {
        0% { transform: translate(0, 0) scale(1); opacity: 0.3; }
        25% { transform: translate(30px, -40px) scale(1.2); opacity: 0.8; }
        50% { transform: translate(-20px, 20px) scale(0.8); opacity: 0.5; }
        75% { transform: translate(15px, -15px) scale(1.1); opacity: 0.7; }
        100% { transform: translate(-10px, 10px) scale(1); opacity: 0.3; }
    }
    
    .grid-lines {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        pointer-events: none;
        z-index: 0;
        background-image: 
            linear-gradient(rgba(100, 180, 255, 0.03) 1px, transparent 1px),
            linear-gradient(90deg, rgba(100, 180, 255, 0.03) 1px, transparent 1px);
        background-size: 50px 50px;
        animation: gridMove 60s linear infinite;
    }
    
    @keyframes gridMove {
        0% { background-position: 0 0; }
        100% { background-position: 50px 50px; }
    }
    
    /* Conteneurs avec effet verre sombre */
    div[data-testid="stDataFrame"], .main .block-container, .stTabs [data-baseweb="tab-panel"] {
        background: rgba(12, 18, 34, 0.7) !important;
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border-radius: 20px;
        padding: 24px !important;
        border: 1px solid rgba(100, 180, 255, 0.08);
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
        transition: all 0.3s ease;
        animation: fadeSlideUp 0.6s ease-out;
        position: relative;
        z-index: 1;
    }
    
    @keyframes fadeSlideUp {
        from { opacity: 0; transform: translateY(20px); }
        to { opacity: 1; transform: translateY(0); }
    }
    
    /* Métriques sombres - tailles réduites */
    div[data-testid="stMetric"] {
        background: rgba(12, 18, 34, 0.6);
        backdrop-filter: blur(12px);
        border-radius: 16px;
        padding: 14px 18px;
        border: 1px solid rgba(100, 180, 255, 0.06);
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
        transition: all 0.25s ease;
        animation: fadeSlideUp 0.7s ease-out;
    }
    div[data-testid="stMetric"]:hover {
        transform: translateY(-4px) scale(1.01);
        box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
        border-color: rgba(100, 180, 255, 0.15);
    }
    div[data-testid="stMetricValue"] {
        color: #d0e4ff;
        font-weight: 600;
        font-size: 1.4rem;
        letter-spacing: -0.02em;
        text-shadow: 0 0 20px rgba(100, 180, 255, 0.1);
    }
    div[data-testid="stMetricLabel"] {
        color: #7a9bcb;
        font-weight: 400;
        font-size: 0.7rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    
    /* Boutons tech */
    .stButton button {
        background: rgba(20, 30, 50, 0.6);
        backdrop-filter: blur(8px);
        border: 1px solid rgba(100, 180, 255, 0.1);
        border-radius: 14px;
        padding: 6px 20px;
        font-weight: 500;
        font-size: 0.85rem;
        color: #b0ccee;
        transition: all 0.25s ease;
        box-shadow: 0 2px 12px rgba(0, 0, 0, 0.2);
    }
    .stButton button:hover {
        background: rgba(30, 50, 80, 0.8);
        border-color: rgba(100, 180, 255, 0.3);
        transform: scale(1.02);
        box-shadow: 0 6px 24px rgba(0, 0, 0, 0.4), 0 0 20px rgba(100, 180, 255, 0.05);
    }
    .stButton button[data-baseweb="button"][kind="primary"] {
        background: linear-gradient(135deg, #1a4a7a, #0d2b4a);
        border-color: transparent;
        color: white;
        box-shadow: 0 4px 20px rgba(26, 74, 122, 0.3);
    }
    .stButton button[data-baseweb="button"][kind="primary"]:hover {
        background: linear-gradient(135deg, #2a5a8a, #1a3a5a);
        box-shadow: 0 8px 30px rgba(26, 74, 122, 0.5);
    }
    
    /* Titres lumineux - tailles réduites */
    h1, h2, h3 {
        color: #d0e4ff;
        font-weight: 600;
        letter-spacing: -0.02em;
        text-shadow: 0 0 30px rgba(100, 180, 255, 0.05);
    }
    h1 {
        font-size: 1.8rem;
        font-weight: 700;
    }
    h1::after {
        content: '';
        display: block;
        width: 40px;
        height: 2px;
        background: linear-gradient(90deg, #4a8ecf, #1a4a7a);
        border-radius: 2px;
        margin-top: 4px;
        box-shadow: 0 0 20px rgba(74, 142, 207, 0.3);
    }
    h2 {
        font-size: 1.4rem;
    }
    h3 {
        font-size: 1.1rem;
    }
    
    /* Sidebar sombre */
    .css-1d391kg {
        background: rgba(8, 12, 24, 0.85) !important;
        backdrop-filter: blur(24px);
        border-right: 1px solid rgba(100, 180, 255, 0.06);
        box-shadow: 2px 0 30px rgba(0, 0, 0, 0.3);
    }
    
    /* Inputs */
    .stTextInput input, .stSelectbox select, .stTextArea textarea {
        background: rgba(12, 18, 34, 0.6);
        border: 1px solid rgba(100, 180, 255, 0.08);
        border-radius: 12px;
        padding: 8px 12px;
        font-size: 0.9rem;
        color: #d0e4ff;
        transition: all 0.25s ease;
        backdrop-filter: blur(8px);
    }
    .stTextInput input:focus, .stSelectbox select:focus, .stTextArea textarea:focus {
        border-color: #4a8ecf;
        box-shadow: 0 0 0 3px rgba(74, 142, 207, 0.15);
        background: rgba(12, 18, 34, 0.8);
    }
    
    /* Scrollbar */
    ::-webkit-scrollbar {
        width: 6px;
        height: 6px;
    }
    ::-webkit-scrollbar-track {
        background: rgba(0, 0, 0, 0.2);
        border-radius: 10px;
    }
    ::-webkit-scrollbar-thumb {
        background: #1a4a7a;
        border-radius: 10px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: #2a5a8a;
    }
    
    /* Alertes */
    .stAlert {
        border-radius: 14px;
        background: rgba(12, 18, 34, 0.7) !important;
        backdrop-filter: blur(8px);
        border-left: 4px solid #4a8ecf;
        animation: slideInRight 0.4s ease-out;
        color: #d0e4ff;
        font-size: 0.9rem;
    }
    @keyframes slideInRight {
        from { opacity: 0; transform: translateX(30px); }
        to { opacity: 1; transform: translateX(0); }
    }
    
    /* Badges */
    .status-badge {
        display: inline-block;
        padding: 4px 14px;
        border-radius: 20px;
        font-size: 0.7rem;
        font-weight: 500;
        background: rgba(74, 142, 207, 0.12);
        color: #8bb8ff;
        border: 1px solid rgba(74, 142, 207, 0.15);
    }
    .status-dot {
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        margin-right: 8px;
        background: #4ade80;
        box-shadow: 0 0 12px rgba(74, 222, 128, 0.2);
        animation: pulse-dot 2s infinite;
    }
    @keyframes pulse-dot {
        0%, 100% { opacity: 1; transform: scale(1); }
        50% { opacity: 0.5; transform: scale(0.9); }
    }
    
    /* Cartes de tâches */
    .task-card {
        background: rgba(12, 18, 34, 0.5);
        backdrop-filter: blur(8px);
        border-radius: 14px;
        padding: 12px 16px;
        margin-bottom: 10px;
        border-left: 3px solid #4a8ecf;
        transition: all 0.2s ease;
        box-shadow: 0 2px 12px rgba(0,0,0,0.2);
    }
    .task-card:hover {
        background: rgba(20, 30, 50, 0.7);
        transform: translateX(4px);
    }
    .task-card.paused {
        border-left-color: #f5b342;
    }
    .task-card.completed {
        border-left-color: #66bb6a;
        opacity: 0.7;
    }
    .task-timer {
        font-family: 'Inter', monospace;
        font-weight: 600;
        font-size: 1.3rem;
        color: #4a8ecf;
        letter-spacing: 0.04em;
        text-shadow: 0 0 20px rgba(74, 142, 207, 0.2);
    }
    .task-timer.paused {
        color: #f5b342;
    }
    .task-status {
        display: inline-block;
        padding: 2px 12px;
        border-radius: 12px;
        font-size: 0.65rem;
        font-weight: 500;
        text-transform: uppercase;
        background: rgba(74, 222, 128, 0.12);
        color: #4ade80;
    }
    .task-status.paused {
        background: rgba(245, 179, 66, 0.12);
        color: #f5b342;
    }
    .task-status.completed {
        background: rgba(74, 222, 128, 0.08);
        color: #4ade80;
    }
    
    /* Chat */
    .chat-message {
        background: rgba(12, 18, 34, 0.5);
        backdrop-filter: blur(8px);
        border-radius: 14px;
        padding: 12px 16px;
        margin-bottom: 12px;
        border-left: 3px solid #4a8ecf;
        animation: fadeSlideUp 0.4s ease-out;
    }
    .chat-message .sender {
        font-weight: 600;
        color: #8bb8ff;
        font-size: 0.9rem;
    }
    .chat-message .timestamp {
        font-size: 0.7rem;
        color: #5a7a9a;
        float: right;
    }
    .chat-message .content {
        margin-top: 6px;
        color: #d0e4ff;
        font-size: 0.9rem;
    }
    
    /* Bouton flottant chat */
    .floating-chat {
        position: fixed;
        bottom: 30px;
        right: 30px;
        z-index: 1000;
        background: linear-gradient(135deg, #1a4a7a, #0d2b4a);
        color: white;
        border-radius: 50%;
        width: 56px;
        height: 56px;
        display: flex;
        justify-content: center;
        align-items: center;
        font-size: 1.4rem;
        box-shadow: 0 8px 30px rgba(26, 74, 122, 0.4);
        transition: all 0.3s ease;
        border: 1px solid rgba(100, 180, 255, 0.15);
        text-decoration: none;
        cursor: pointer;
    }
    .floating-chat:hover {
        transform: scale(1.08);
        box-shadow: 0 12px 40px rgba(26, 74, 122, 0.6);
    }
    .floating-chat .badge {
        position: absolute;
        top: -4px;
        right: -4px;
        background: #ef4444;
        color: white;
        border-radius: 50%;
        padding: 0 6px;
        font-size: 0.65rem;
        font-weight: 600;
        min-width: 20px;
        text-align: center;
        line-height: 20px;
    }
    
    /* Page de connexion */
    .welcome-container {
        text-align: center;
        max-width: 600px;
        margin: 8vh auto;
        padding: 40px 32px;
        background: rgba(8, 12, 24, 0.7);
        backdrop-filter: blur(24px);
        border-radius: 30px;
        border: 1px solid rgba(100, 180, 255, 0.06);
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
        animation: fadeSlideUp 0.8s ease-out;
        position: relative;
        z-index: 1;
    }
    .welcome-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #d0e4ff;
        letter-spacing: -0.03em;
        text-shadow: 0 0 40px rgba(74, 142, 207, 0.1);
    }
    .welcome-subtitle {
        color: #7a9bcb;
        font-size: 1rem;
        margin-top: 4px;
    }
    .welcome-credit {
        color: #4a8ecf;
        font-size: 1rem;
        font-weight: 500;
        letter-spacing: 0.06em;
        margin-top: 20px;
        text-shadow: 0 0 20px rgba(74, 142, 207, 0.1);
    }
    .login-form {
        background: rgba(8, 12, 24, 0.5);
        backdrop-filter: blur(16px);
        border-radius: 24px;
        padding: 28px;
        border: 1px solid rgba(100, 180, 255, 0.06);
        box-shadow: 0 12px 40px rgba(0, 0, 0, 0.3);
    }
    
    /* Responsive */
    @media (max-width: 768px) {
        .welcome-title { font-size: 1.8rem; }
        .welcome-container { padding: 24px 16px; }
    }
    
    /* Couleur du texte général */
    p, div, span, label {
        color: #d0e4ff !important;
        font-size: 0.9rem;
    }
    .css-1d391kg p, .css-1d391kg div, .css-1d391kg span {
        color: #d0e4ff !important;
    }
    
    /* Positionnement du contenu */
    .main .block-container {
        position: relative;
        z-index: 1;
    }
    </style>
    
    <!-- Conteneur des particules -->
    <div class="particles-container">
        <div class="particle"></div>
        <div class="particle"></div>
        <div class="particle"></div>
        <div class="particle"></div>
        <div class="particle"></div>
        <div class="particle"></div>
        <div class="particle"></div>
        <div class="particle"></div>
        <div class="particle"></div>
        <div class="particle"></div>
    </div>
    
    <!-- Effet de grille -->
    <div class="grid-lines"></div>
""", unsafe_allow_html=True)

# --- LOGIQUE DE PERSISTANCE DE SESSION & SAUVEGARDE ---
# SUPPRESSION des fonctions sauvegarder_etat_connexion et charger_etat_connexion
# car elles stockaient l'état d'authentification dans un fichier partagé,
# ce qui causait des interférences entre les sessions utilisateurs.
# L'authentification est désormais gérée uniquement via st.session_state (propre à chaque navigateur).

# --- INITIALISATION DE SESSION ---
# On n'utilise plus charger_etat_connexion() car elle lit un fichier partagé.
# On initialise les variables de session avec des valeurs par défaut.
if "authentifie" not in st.session_state:
    st.session_state.authentifie = False
if "user_actif" not in st.session_state:
    st.session_state.user_actif = ""
if "user_role" not in st.session_state:
    st.session_state.user_role = "operateur"
if "user_changed" not in st.session_state:
    st.session_state.user_changed = False

# --- Variables pour le chat (message en cours) ---
if "chat_message_text" not in st.session_state:
    st.session_state.chat_message_text = ""

# --- Fonctions pour le chat (extension DB) ---
def send_chat_message(username, full_name, message, attachment_base64=None):
    """Envoie un message avec pièce jointe éventuelle (stockée en JSON)."""
    conn = db_manager.get_db()
    c = conn.cursor()
    # Créer le JSON
    data = {"text": message}
    if attachment_base64:
        data["attachment"] = attachment_base64
    data_str = json.dumps(data, ensure_ascii=False)
    c.execute(
        "INSERT INTO messages (username, full_name, message, timestamp) VALUES (?, ?, ?, ?)",
        (username, full_name, data_str, datetime.now(MADA_TZ).isoformat())
    )
    conn.commit()
    conn.close()

def get_chat_messages(limit=50):
    """Récupère les messages et parse le JSON."""
    conn = db_manager.get_db()
    c = conn.cursor()
    c.execute(
        "SELECT username, full_name, message, timestamp FROM messages ORDER BY timestamp DESC LIMIT ?",
        (limit,)
    )
    rows = c.fetchall()
    conn.close()
    messages = []
    for row in rows:
        username, full_name, msg_json, ts = row
        try:
            data = json.loads(msg_json)
            text = data.get("text", "")
            attachment = data.get("attachment", None)
        except:
            text = msg_json
            attachment = None
        # Formater la date en local MADA
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=MADA_TZ)
            ts_formatted = dt.strftime("%d/%m/%Y %H:%M:%S")
        except:
            ts_formatted = ts
        messages.append({
            "username": username,
            "full_name": full_name,
            "text": text,
            "attachment": attachment,
            "timestamp": ts_formatted,
            "raw_ts": ts
        })
    return messages

def clear_all_messages():
    """Supprime tous les messages."""
    conn = db_manager.get_db()
    c = conn.cursor()
    c.execute("DELETE FROM messages")
    conn.commit()
    conn.close()

# --- AGENTS PAR DÉFAUT ---
AGENTS_PAR_DEFAUT = [
    {"Nom": "Jean Doe", "Poste": "Setup Operator"},
    {"Nom": "Alice Smith", "Poste": "Team Leader"},
    {"Nom": "Isaïa", "Poste": "Setup Operator"},
    {"Nom": "Elizara", "Poste": "Setup Operator"}
]

# Initialisation des variables avec les valeurs par défaut si elles n'existent pas
if "agents" not in st.session_state: 
    st.session_state.agents = list(AGENTS_PAR_DEFAUT)
if "planning" not in st.session_state: 
    st.session_state.planning = {}
if "heures" not in st.session_state: 
    st.session_state.heures = {}
if "donnees_cloud_centralisees" not in st.session_state: 
    st.session_state.donnees_cloud_centralisees = []
if "couleurs" not in st.session_state:
    st.session_state.couleurs = {
        "Travail": "#2E7D32", "OFF": "#757575", "Congé": "#8D6E63", "Maladie": "#C62828", "Formation": "#1565C0"
    }
if "taches_operateur" not in st.session_state:
    st.session_state.taches_operateur = {}
if "taches_en_cours" not in st.session_state:
    st.session_state.taches_en_cours = []
if "task_id_counter" not in st.session_state:
    st.session_state.task_id_counter = 0
if "show_completed_tasks" not in st.session_state:
    st.session_state.show_completed_tasks = True

# --- CHARGEMENT AUTOMATIQUE DES DONNÉES AU DÉMARRAGE ---
# SUPPRIMÉ : on ne charge plus les données depuis un fichier JSON.
# Les données sont lues depuis SQLite via db_manager dans les pages.

# --- INTERFACE DE CONNEXION ---
if not st.session_state.authentifie:
    st.markdown("""
        <div class="welcome-container">
            <div class="welcome-title">⚙️ QWANTEOS-SETUP</div>
            <div class="welcome-subtitle">Gestion & Pointage professionnel</div>
            <hr style="border-color: rgba(100,180,255,0.08); width: 60%; margin: 20px auto;">
            <div class="welcome-credit">Created by Toky — Team Lead Setup</div>
            <div style="margin-top: 18px;">
                <span class="status-dot"></span>
                <span style="color: #7a9bcb; font-weight: 400;">Système opérationnel</span>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    st.write("")
    
    col_space, col_form, col_space2 = st.columns([4, 4, 4])
    with col_form:
        with st.container():
            st.markdown('<div class="login-form">', unsafe_allow_html=True)
            
            tab1, tab2 = st.tabs(["Connexion", "Inscription"])
            
            # --- ONGLET CONNEXION ---
            with tab1:
                with st.form("form_login"):
                    st.markdown("### Connexion")
                    identifiant = st.text_input("Nom d'utilisateur", value="")
                    mot_de_passe = st.text_input("Mot de passe", type="password")
                    btn_login = st.form_submit_button("Se connecter", use_container_width=True)
                    
                    if btn_login:
                        if identifiant and mot_de_passe:
                            success, message = authenticate_user(identifiant, mot_de_passe)
                            if success:
                                st.session_state.authentifie = True
                                st.session_state.user_actif = identifiant
                                st.session_state.user_role = get_user_role(identifiant)
                                st.session_state.user_changed = True
                                
                                # SUPPRESSION de l'appel à sauvegarder_etat_connexion()
                                # car elle stockait l'état d'authentification dans un fichier partagé.
                                # L'état est désormais uniquement dans st.session_state.
                                
                                # Sauvegarde automatique supprimée
                                # executer_sauvegarde_auto("login", identifiant)
                                
                                with st.spinner("Synchronisation des bases de données..."):
                                    time.sleep(1.2)
                                    
                                st.toast("✅ Connexion réussie ! Données chargées.", icon="✅")
                                st.rerun()
                            else:
                                st.error(f"❌ {message}")
                        else:
                            st.warning("⚠️ Veuillez remplir tous les champs")
            
            # --- ONGLET INSCRIPTION ---
            with tab2:
                with st.form("form_register"):
                    st.markdown("### Créer un compte")
                    st.info("🔒 Mot de passe : 8 caractères, 1 majuscule, 1 minuscule, 1 chiffre")
                    
                    new_username = st.text_input("Nom d'utilisateur")
                    new_fullname = st.text_input("Nom complet (optionnel)")
                    
                    # Sélection du rôle (plus que 2 rôles)
                    role_options = ["operateur", "admin"]
                    role_labels = {
                        "operateur": "Opérateur — Accès limité",
                        "admin": "Administrateur — Contrôle total"
                    }
                    selected_role = st.selectbox(
                        "Rôle du compte",
                        options=role_options,
                        format_func=lambda x: role_labels[x],
                        help="Sélectionnez le niveau d'accès"
                    )
                    
                    # Code d'accès pour admin uniquement
                    code_acces = ""
                    if selected_role == "admin":
                        code_acces = st.text_input(
                            "Code d'accès Admin", 
                            type="password",
                            placeholder="Entrez le code d'accès",
                            help="Code requis pour créer un compte Administrateur"
                        )
                        st.caption("📌 Code d'accès requis")
                    else:
                        st.caption("✅ Aucun code requis pour un compte Opérateur")
                    
                    new_password = st.text_input("Mot de passe", type="password")
                    confirm_password = st.text_input("Confirmer le mot de passe", type="password")
                    
                    btn_register = st.form_submit_button("S'inscrire", use_container_width=True)
                    
                    if btn_register:
                        if not new_username or not new_password or not confirm_password:
                            st.warning("⚠️ Veuillez remplir tous les champs obligatoires")
                        elif new_password != confirm_password:
                            st.error("❌ Les mots de passe ne correspondent pas")
                        else:
                            success, message = register_user(
                                new_username, 
                                new_password, 
                                new_fullname, 
                                selected_role,
                                code_acces
                            )
                            if success:
                                st.success(f"✅ {message}")
                                st.info("🔑 Vous pouvez maintenant vous connecter avec vos identifiants")
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.error(f"❌ {message}")
            
            st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# --- PAGE POUR OPÉRATEUR (DASHBOARD AVEC CHRONOMÈTRE PROFESSIONNEL) ---
def page_operateur_dashboard():
    # Titre plus discret
    st.title("⏱️ Suivi des Tâches")
    
    # En-tête utilisateur simplifié
    st.markdown(f"""
        <div style="
            background: rgba(8, 12, 24, 0.5);
            padding: 10px 18px;
            border-radius: 12px;
            border-left: 3px solid #4a8ecf;
            margin-bottom: 18px;
            backdrop-filter: blur(8px);
        ">
            <span style="color: #8bb8ff; font-weight: 500;">▸ {st.session_state.user_actif}</span>
            <span style="color: #5a7a9a; margin-left: 20px; font-size: 0.85em;">{datetime.now(MADA_TZ).strftime('%d/%m/%Y %H:%M')}</span>
        </div>
    """, unsafe_allow_html=True)

    # --- AFFICHAGE DES TÂCHES ASSIGNÉES À L'AGENT (depuis shared_tasks) ---
    with st.expander("📋 Mes tâches assignées", expanded=False):
        agent_name = st.session_state.user_actif
        mes_taches = get_tasks_for_agent(agent_name)
        if mes_taches:
            df_mes_taches = pd.DataFrame(mes_taches)
            df_mes_taches = df_mes_taches[["tache", "match_info", "wf", "ligue", "remarques", "date_creation"]]
            df_mes_taches.columns = ["Tâche", "Match", "WF", "Ligue", "Remarques", "Date création"]
            # Formater les dates de création
            df_mes_taches["Date création"] = df_mes_taches["Date création"].apply(formater_datetime_iso)
            st.dataframe(df_mes_taches, use_container_width=True, hide_index=True)
        else:
            st.info("Aucune tâche assignée pour le moment.")
    
    # --- SECTION NOUVELLE TÂCHE (plus compacte) ---
    st.markdown("### Nouvelle tâche")
    with st.container():
        col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 2, 2])
        with col1:
            tache_selectionnee = st.selectbox(
                "Type", options=TACHES_DISPONIBLES, key="new_task_select"
            )
        with col2:
            match_info = st.text_input("Match", placeholder="vs", key="match_new")
        with col3:
            wf_info = st.text_input("WF", placeholder="Workflow", key="wf_new")
        with col4:
            ligue_info = st.text_input("Ligue", placeholder="Ligue", key="ligue_new")
        with col5:
            remarques_info = st.text_area("Notes", placeholder="Remarques", key="remarques_new", height=60)
        
        col_btn1, col_btn2 = st.columns([1, 5])
        with col_btn1:
            if st.button("▶️ Démarrer", type="primary", use_container_width=True):
                agents_db = db_manager.get_all_agents()
                agent_id = None
                for ag in agents_db:
                    if ag["nom"].lower() == st.session_state.user_actif.lower():
                        agent_id = ag["id"]
                        break
                if agent_id is None:
                    st.error("❌ Compte non lié à un agent. Contactez l'admin.")
                    st.stop()
                
                task_id = st.session_state.task_id_counter + 1
                st.session_state.task_id_counter = task_id
                
                evenements = [{"type": "START", "time": datetime.now(MADA_TZ).isoformat()}]
                date_debut = datetime.now(MADA_TZ).strftime("%d/%m/%Y %H:%M:%S")
                
                db_id = db_manager.add_task(
                    agent_id=agent_id,
                    tache=tache_selectionnee,
                    match_info=match_info if match_info else "",
                    wf=wf_info if wf_info else "",
                    ligue=ligue_info if ligue_info else "",
                    remarques=remarques_info if remarques_info else "",
                    statut="en_cours",
                    date_debut=datetime.now(MADA_TZ).isoformat(),
                    evenements=evenements
                )
                
                new_task = {
                    "id": task_id,
                    "db_id": db_id,
                    "tache": tache_selectionnee,
                    "match": match_info or "",
                    "wf": wf_info or "",
                    "ligue": ligue_info or "",
                    "remarques": remarques_info or "",
                    "statut": "en_cours",
                    "start_time": datetime.now(MADA_TZ).isoformat(),
                    "elapsed_seconds": 0,
                    "last_start": time.time(),
                    "evenements": evenements,
                    "date_debut": date_debut,
                    "temps_total_secondes": 0,
                    "temps_formate": "00:00:00"
                }
                st.session_state.taches_en_cours.append(new_task)
                # Sauvegarde automatique supprimée
                # executer_sauvegarde_auto("task_start", st.session_state.user_actif)
                st.toast(f"✅ Tâche {tache_selectionnee} démarrée", icon="▶️")
                st.rerun()
    
    st.markdown("---")
    
    # --- TÂCHES EN COURS (affichage épuré) ---
    st.markdown("### 📋 Tâches en cours")
    if st.session_state.taches_en_cours:
        taches_actives = [t for t in st.session_state.taches_en_cours if t["statut"] != "termine"]
        taches_terminees = [t for t in st.session_state.taches_en_cours if t["statut"] == "termine"]
        
        # Métriques simplifiées
        col_met1, col_met2, col_met3 = st.columns(3)
        with col_met1:
            st.metric("Actives", len([t for t in taches_actives if t["statut"] == "en_cours"]))
        with col_met2:
            st.metric("En pause", len([t for t in taches_actives if t["statut"] == "pause"]))
        with col_met3:
            st.metric("Terminées", len(taches_terminees))
        
        if taches_actives:
            st.markdown("#### En cours")
            for task in taches_actives:
                if task["statut"] == "en_cours":
                    elapsed = task["elapsed_seconds"] + (time.time() - task["last_start"])
                else:
                    elapsed = task["elapsed_seconds"]
                
                # Format HH:MM:SS
                h = int(elapsed // 3600)
                m = int((elapsed % 3600) // 60)
                s = int(elapsed % 60)
                time_str = f"{h:02d}:{m:02d}:{s:02d}"
                
                if task["statut"] == "en_cours":
                    status_class = "running"
                    status_text = "En cours"
                    border_color = "#4a8ecf"
                else:
                    status_class = "paused"
                    status_text = "En pause"
                    border_color = "#f5b342"
                
                # Affichage plus compact
                with st.container():
                    cols = st.columns([2, 2, 3])
                    with cols[0]:
                        st.markdown(f"""
                            <div style="border-left: 3px solid {border_color}; padding-left: 10px;">
                                <div style="font-weight: 500;">{task['tache']}</div>
                                <div style="font-size: 0.8em; color: #7a9bcb;">
                                    {task['match']} | {task['wf']} | {task['ligue']}
                                </div>
                                <span class="task-status {status_class}">{status_text}</span>
                            </div>
                        """, unsafe_allow_html=True)
                    with cols[1]:
                        st.markdown(f"""
                            <div style="text-align: center; font-size: 1.3em; font-weight: 600; font-family: 'Inter', monospace; color: {border_color};">
                                {time_str}
                            </div>
                        """, unsafe_allow_html=True)
                    with cols[2]:
                        col_btn_pause, col_btn_resume, col_btn_stop = st.columns(3)
                        with col_btn_pause:
                            if task["statut"] == "en_cours":
                                if st.button("⏸️", key=f"pause_{task['id']}", help="Pause"):
                                    task["statut"] = "pause"
                                    task["elapsed_seconds"] += time.time() - task["last_start"]
                                    task["evenements"].append({"type": "PAUSE", "time": datetime.now(MADA_TZ).isoformat()})
                                    db_manager.update_task(task["db_id"], statut="pause", evenements=task["evenements"])
                                    # Sauvegarde automatique supprimée
                                    # executer_sauvegarde_auto("task_pause", st.session_state.user_actif)
                                    st.toast(f"⏸️ {task['tache']} en pause", icon="⏸️")
                                    st.rerun()
                        with col_btn_resume:
                            if task["statut"] == "pause":
                                if st.button("▶️", key=f"resume_{task['id']}", help="Reprendre"):
                                    task["statut"] = "en_cours"
                                    task["last_start"] = time.time()
                                    task["evenements"].append({"type": "REPRISE", "time": datetime.now(MADA_TZ).isoformat()})
                                    db_manager.update_task(task["db_id"], statut="en_cours", evenements=task["evenements"])
                                    # Sauvegarde automatique supprimée
                                    # executer_sauvegarde_auto("task_resume", st.session_state.user_actif)
                                    st.toast(f"▶️ {task['tache']} reprise", icon="▶️")
                                    st.rerun()
                        with col_btn_stop:
                            if st.button("⏹️", key=f"stop_{task['id']}", help="Terminer"):
                                if task["statut"] == "en_cours":
                                    task["elapsed_seconds"] += time.time() - task["last_start"]
                                task["evenements"].append({"type": "FIN", "time": datetime.now(MADA_TZ).isoformat()})
                                task["statut"] = "termine"
                                task["date_fin"] = datetime.now(MADA_TZ).strftime("%d/%m/%Y %H:%M:%S")
                                task["temps_total_secondes"] = task["elapsed_seconds"]
                                task["temps_formate"] = format_duration_hms(task["elapsed_seconds"])
                                
                                db_manager.update_task(
                                    task["db_id"],
                                    statut="termine",
                                    date_fin=datetime.now(MADA_TZ).isoformat(),
                                    temps_total_secondes=task["elapsed_seconds"],
                                    temps_formate=task["temps_formate"],
                                    evenements=task["evenements"]
                                )
                                
                                if task["tache"] not in st.session_state.taches_operateur:
                                    st.session_state.taches_operateur[task["tache"]] = []
                                st.session_state.taches_operateur[task["tache"]].append({
                                    "date_debut": task["date_debut"],
                                    "date_fin": task["date_fin"],
                                    "tache": task["tache"],
                                    "temps_secondes": task["elapsed_seconds"],
                                    "temps_formate": task["temps_formate"],
                                    "match": task["match"],
                                    "wf": task["wf"],
                                    "ligue": task["ligue"],
                                    "remarques": task["remarques"],
                                    "statut": "Terminé",
                                    "evenements": task["evenements"]
                                })
                                st.session_state.taches_en_cours = [t for t in st.session_state.taches_en_cours if t["id"] != task["id"]]
                                # Sauvegarde automatique supprimée
                                # executer_sauvegarde_auto("task_complete", st.session_state.user_actif)
                                st.toast(f"✅ {task['tache']} terminée ({task['temps_formate']})", icon="✅")
                                st.rerun()
                    st.markdown("---")
        else:
            st.info("Aucune tâche active.")
        
        # --- TÂCHES TERMINÉES (dans un expander) ---
        if taches_terminees:
            with st.expander("✅ Tâches terminées cette session", expanded=False):
                col_toggle, _ = st.columns([1, 3])
                with col_toggle:
                    show_tasks = st.checkbox("Afficher les détails", value=st.session_state.show_completed_tasks)
                    st.session_state.show_completed_tasks = show_tasks
                if st.session_state.show_completed_tasks:
                    for task in taches_terminees:
                        with st.expander(f"{task['tache']} - {task.get('temps_formate', '00:00:00')}"):
                            col_det1, col_det2 = st.columns(2)
                            with col_det1:
                                st.write(f"**Match:** {task.get('match', 'N/A')}")
                                st.write(f"**WF:** {task.get('wf', 'N/A')}")
                                st.write(f"**Ligue:** {task.get('ligue', 'N/A')}")
                            with col_det2:
                                st.write(f"**Début:** {task.get('date_debut', 'N/A')}")
                                st.write(f"**Fin:** {task.get('date_fin', 'N/A')}")
                                st.write(f"**Temps:** {task.get('temps_formate', '00:00:00')}")
                            if task.get('remarques'):
                                st.write(f"**Remarques:** {task['remarques']}")
                else:
                    st.caption("Détails masqués")
    else:
        st.info("Aucune tâche en cours. Démarrer une nouvelle tâche ci-dessus.")
    
    # --- HISTORIQUE COMPLET (dans un expander) ---
    with st.expander("📊 Historique complet des tâches", expanded=False):
        historique_data = []
        for tache, entries in st.session_state.taches_operateur.items():
            for entry in entries:
                historique_data.append({
                    "Date Début": entry.get("date_debut", "N/A"),
                    "Date Fin": entry.get("date_fin", "N/A"),
                    "Tâche": tache,
                    "Temps": entry.get("temps_formate", "00:00:00"),
                    "Temps (sec)": entry.get("temps_secondes", 0),
                    "MATCH": entry.get("match", "N/A"),
                    "WF": entry.get("wf", "N/A"),
                    "LIGUE": entry.get("ligue", "N/A"),
                    "REMARQUES": entry.get("remarques", "N/A"),
                    "Statut": entry.get("statut", "Terminé")
                })
        
        if historique_data:
            df_historique = pd.DataFrame(historique_data)
            col_met_a, col_met_b, col_met_c, col_met_d = st.columns(4)
            with col_met_a:
                st.metric("Total Tâches", len(historique_data))
            with col_met_b:
                total_temps = sum([entry.get("Temps (sec)", 0) for entry in historique_data])
                st.metric("Temps Total", format_duration_hms(total_temps))
            with col_met_c:
                if len(historique_data) > 0:
                    temps_moyen = total_temps / len(historique_data)
                    st.metric("Temps Moyen", format_duration_hms(temps_moyen))
            with col_met_d:
                types_counts = df_historique["Tâche"].value_counts()
                if not types_counts.empty:
                    st.metric("Types de tâches", len(types_counts))
            
            st.dataframe(
                df_historique[["Date Début", "Date Fin", "Tâche", "Temps", "MATCH", "WF", "LIGUE", "Statut"]],
                use_container_width=True,
                hide_index=True
            )
            
            col_exp1, col_exp2, col_exp3 = st.columns(3)
            with col_exp1:
                if st.button("Exporter CSV", use_container_width=True):
                    csv = df_historique.to_csv(index=False, encoding='utf-8-sig')
                    st.download_button(
                        label="📥 Télécharger",
                        data=csv,
                        file_name=f"historique_taches_{datetime.now(MADA_TZ).strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv"
                    )
            with col_exp2:
                if st.button("🗑️ Effacer l'historique", use_container_width=True, type="secondary"):
                    st.session_state.taches_operateur = {}
                    agents_db = db_manager.get_all_agents()
                    agent_id = None
                    for ag in agents_db:
                        if ag["nom"].lower() == st.session_state.user_actif.lower():
                            agent_id = ag["id"]
                            break
                    if agent_id:
                        conn = db_manager.get_db()
                        c = conn.cursor()
                        c.execute("DELETE FROM taches WHERE agent_id = ? AND statut = 'termine'", (agent_id,))
                        conn.commit()
                        conn.close()
                    # Sauvegarde automatique supprimée
                    # executer_sauvegarde_auto("clear_history", st.session_state.user_actif)
                    st.toast("🗑️ Historique effacé", icon="🗑️")
                    st.rerun()
            with col_exp3:
                if st.button("📊 Voir graphiques", use_container_width=True):
                    fig = px.pie(
                        df_historique,
                        names="Tâche",
                        title="Répartition des tâches",
                        color_discrete_sequence=px.colors.qualitative.Set3
                    )
                    fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color='#d0e4ff')
                    st.plotly_chart(fig, use_container_width=True)
                    
                    df_temps = df_historique.groupby("Tâche")["Temps (sec)"].sum().reset_index()
                    fig2 = px.bar(
                        df_temps,
                        x="Tâche",
                        y="Temps (sec)",
                        title="Temps total par type",
                        color="Tâche",
                        labels={"Temps (sec)": "Temps (secondes)"}
                    )
                    fig2.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color='#d0e4ff',
                                      xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
                                      yaxis=dict(gridcolor='rgba(255,255,255,0.05)'))
                    st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Aucune tâche dans l'historique.")
    
    # --- EXPORT GOOGLE SHEETS (dans un expander) ---
    with st.expander("Export vers Google Sheets", expanded=False):
        export_rows = []
        for tache, entries in st.session_state.taches_operateur.items():
            for entry in entries:
                evenements = entry.get("evenements", [])
                start_time = pause_time = reprise_time = fin_time = ""
                for evt in evenements:
                    if evt["type"] == "START":
                        start_time = evt["time"]
                    elif evt["type"] == "PAUSE":
                        pause_time = evt["time"]
                    elif evt["type"] == "REPRISE":
                        reprise_time = evt["time"]
                    elif evt["type"] == "FIN":
                        fin_time = evt["time"]
                export_rows.append({
                    "START": formater_datetime_iso(start_time),
                    "PAUSE": formater_datetime_iso(pause_time),
                    "REPRISE": formater_datetime_iso(reprise_time),
                    "FIN": formater_datetime_iso(fin_time),
                    "DATE": entry.get("date_debut", "").split(" ")[0] if entry.get("date_debut") else "",
                    "MATCH / WF": f"{entry.get('match', '')} / {entry.get('wf', '')}",
                    "LIGUE": entry.get("ligue", ""),
                    "TACHES": tache,
                    "STATUTS": entry.get("statut", "Terminé"),
                    "TOTAL": entry.get("temps_formate", ""),
                    "REMARQUES": entry.get("remarques", "")
                })
        
        if export_rows:
            df_export = pd.DataFrame(export_rows)
            st.dataframe(df_export, use_container_width=True, hide_index=True)
            if st.button("Exporter vers Google Sheets", type="primary", use_container_width=True):
                try:
                    SPREADSHEET_ID = st.secrets["google_sheets"]["spreadsheet_id"]
                except:
                    SPREADSHEET_ID = None
                    st.error("❌ SPREADSHEET_ID non configuré dans les secrets.")
                if SPREADSHEET_ID:
                    success, msg = exporter_vers_google_sheets(st.session_state.user_actif, df_export, SPREADSHEET_ID)
                    if success:
                        st.success(msg)
                        st.toast("Export effectué", icon="✅")
                    else:
                        st.error(msg)
        else:
            st.info("Aucune donnée à exporter.")

# --- PAGE RÉSUMÉ & PLANNING OPÉRATEUR ---
def page_operateur_resume():
    st.title("📊 Résumé & Planning")
    
    # Informations utilisateur
    st.markdown(f"""
        <div style="
            background: rgba(8, 12, 24, 0.5);
            padding: 15px 20px;
            border-radius: 12px;
            border-left: 3px solid #4a8ecf;
            margin-bottom: 20px;
            backdrop-filter: blur(8px);
        ">
            <span style="color: #8bb8ff; font-weight: 500;">▸ Connecté :</span>
            <span style="color: #d0e4ff;">{st.session_state.user_actif}</span>
            <span style="color: #5a7a9a; margin-left: 20px;">{datetime.now(MADA_TZ).strftime('%d/%m/%Y %H:%M')}</span>
        </div>
    """, unsafe_allow_html=True)
    
    # Charger les données depuis l'admin si disponibles
    user_login = st.session_state.user_actif
    agents_db = db_manager.get_all_agents()
    
    # Vérifier si l'utilisateur existe dans la liste des agents
    agent_trouve = False
    agent_info = None
    agent_id = None
    
    for agent in agents_db:
        if agent["nom"].lower() == user_login.lower():
            agent_trouve = True
            agent_info = agent
            agent_id = agent["id"]
            break
    
    if agent_trouve:
        st.success(f"✅ Bienvenue {agent_info['nom']} - {agent_info['poste']}")
        
        # --- SECTION PLANNING ---
        st.markdown("---")
        st.markdown("### 🗓️ Mon Planning")
        
        # Sélection de la semaine
        col_date1, col_date2 = st.columns(2)
        with col_date1:
            annee_sel = st.selectbox("Année", [2026, 2027], index=0, key="resume_yr")
        with col_date2:
            mois_options = {1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril", 5: "Mai", 6: "Juin", 7: "Juillet", 8: "Août", 9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre"}
            mois_sel = st.selectbox("Mois", list(mois_options.keys()), format_func=lambda x: mois_options[x], index=datetime.now(MADA_TZ).month - 1, key="resume_mo")
        
        cal = calendar.Calendar(firstweekday=0)
        semaines_du_mois = cal.monthdayscalendar(annee_sel, mois_sel)
        
        options_semaines = {}
        for idx, sem in enumerate(semaines_du_mois):
            jours_valides = [j for j in sem if j != 0]
            if jours_valides:
                options_semaines[idx] = f"Semaine {idx + 1} (Du {jours_valides[0]:02d} au {jours_valides[-1]:02d})"
        
        if options_semaines:
            semaine_idx = st.selectbox("Sélectionner la Semaine", list(options_semaines.keys()), format_func=lambda x: options_semaines[x], key="resume_wk")
            semaine_choisie = semaines_du_mois[semaine_idx]
            noms_jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
            
            # Afficher le planning de l'agent
            planning_agent = {}
            jours_planning = []
            
            for i, j in enumerate(semaine_choisie):
                if j != 0:
                    date_cle = f"{annee_sel}-{mois_sel:02d}-{j:02d}"
                    planning_date = db_manager.get_planning_for_date(date_cle)
                    statut = planning_date.get(agent_id, "Non défini")
                    planning_agent[noms_jours[i]] = statut
                    jours_planning.append({
                        "Jour": noms_jours[i],
                        "Date": f"{j:02d}/{mois_sel:02d}/{annee_sel}",
                        "Statut": statut
                    })
            
            if jours_planning:
                df_planning = pd.DataFrame(jours_planning)
                st.dataframe(df_planning, use_container_width=True, hide_index=True)
                
                # Afficher les métriques du planning
                col_stat1, col_stat2, col_stat3 = st.columns(3)
                with col_stat1:
                    nb_travail = len([p for p in planning_agent.values() if p == "Travail"])
                    st.metric("✅ Jours travaillés", nb_travail)
                with col_stat2:
                    nb_off = len([p for p in planning_agent.values() if p == "OFF"])
                    st.metric("⭕ Jours OFF", nb_off)
                with col_stat3:
                    nb_conge = len([p for p in planning_agent.values() if p == "Congé"])
                    st.metric("🏖️ Jours de congé", nb_conge)
        else:
            st.info("📋 Aucune semaine disponible pour ce mois.")
        
        # --- SECTION HEURES ---
        st.markdown("---")
        st.markdown("### ⏱️ Mes Heures")
        
        # Sélection du mois pour les heures
        col_mois_heures, col_btn_heures = st.columns([3, 1])
        with col_mois_heures:
            mois_heures = st.selectbox(
                "Sélectionner le mois",
                list(mois_options.keys()),
                format_func=lambda x: mois_options[x],
                index=datetime.now(MADA_TZ).month - 1,
                key="resume_heures_mo"
            )
        
        # Calculer les heures pour l'agent
        heures_agent = []
        total_heures_mois = 0.0
        total_heures_nuit_mois = 0.0
        jours_travailles = 0
        
        _, max_jours = calendar.monthrange(annee_sel, mois_heures)
        
        for jour in range(1, max_jours + 1):
            date_cle = f"{annee_sel}-{mois_heures:02d}-{jour:02d}"
            heures_date = db_manager.get_heures_for_date(date_cle)
            donnee = heures_date.get(agent_id)
            if donnee:
                heures = donnee.get("total", 0)
                heures_nuit = donnee.get("nuit", 0)
                if heures > 0:
                    dt_obj = datetime(annee_sel, mois_heures, jour)
                    heures_agent.append({
                        "Date": f"{jour:02d}/{mois_heures:02d}/{annee_sel}",
                        "Jour": noms_jours[dt_obj.weekday()],
                        "Heures": format_duration_hms(heures * 3600),
                        "Heures Nuit": format_duration_hms(heures_nuit * 3600),
                        "Heures (num)": heures
                    })
                    total_heures_mois += heures
                    total_heures_nuit_mois += heures_nuit
                    jours_travailles += 1
        
        if heures_agent:
            df_heures = pd.DataFrame(heures_agent)
            st.dataframe(
                df_heures[["Date", "Jour", "Heures", "Heures Nuit"]],
                use_container_width=True,
                hide_index=True
            )
            
            # Métriques des heures
            col_h1, col_h2, col_h3, col_h4 = st.columns(4)
            with col_h1:
                st.metric("📅 Jours travaillés", jours_travailles)
            with col_h2:
                st.metric("⏱️ Total Heures", format_duration_hms(total_heures_mois * 3600))
            with col_h3:
                st.metric("🌙 Heures de Nuit", format_duration_hms(total_heures_nuit_mois * 3600))
            with col_h4:
                if jours_travailles > 0:
                    moyenne = total_heures_mois / jours_travailles
                    st.metric("📊 Moyenne/Jour", format_duration_hms(moyenne * 3600))
        else:
            st.info("📋 Aucune heure enregistrée pour ce mois.")
        
        # --- SECTION RÉSUMÉ DES ACTIVITÉS ---
        st.markdown("---")
        st.markdown("### 📈 Résumé de mes activités")
        
        # Récupérer les tâches de l'opérateur depuis la session
        taches_agent = []
        for tache, entries in st.session_state.taches_operateur.items():
            for entry in entries:
                taches_agent.append({
                    "Date": entry.get("date_debut", "N/A"),
                    "Tâche": tache,
                    "Temps": entry.get("temps_formate", "00:00:00"),
                    "Temps (sec)": entry.get("temps_secondes", 0),
                    "MATCH": entry.get("match", "N/A"),
                    "WF": entry.get("wf", "N/A"),
                    "LIGUE": entry.get("ligue", "N/A")
                })
        
        if taches_agent:
            df_taches = pd.DataFrame(taches_agent)
            
            # Métriques
            col_m1, col_m2, col_m3 = st.columns(3)
            with col_m1:
                st.metric("📋 Total Tâches", len(taches_agent))
            with col_m2:
                total_tps = sum([t.get("Temps (sec)", 0) for t in taches_agent])
                st.metric("⏱️ Temps Total", format_duration_hms(total_tps))
            with col_m3:
                if len(taches_agent) > 0:
                    moy = total_tps / len(taches_agent)
                    st.metric("📊 Temps Moyen", format_duration_hms(moy))
            
            # Afficher les tâches
            st.dataframe(
                df_taches[["Date", "Tâche", "Temps", "MATCH", "WF", "LIGUE"]],
                use_container_width=True,
                hide_index=True
            )
            
            # Graphique de répartition
            fig = px.pie(
                df_taches,
                names="Tâche",
                title="Répartition de mes tâches",
                color_discrete_sequence=px.colors.qualitative.Set3
            )
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#d0e4ff'
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("📋 Aucune activité enregistrée pour le moment.")
        
    else:
        st.warning(f"""
            ⚠️ Aucun agent trouvé avec le nom '{user_login}'.
            
            Veuillez contacter l'administrateur pour que votre compte soit lié à un agent dans la base de données.
            
            **Agents disponibles :**
            {', '.join([a['nom'] for a in agents_db])}
        """)

# --- FONCTION DE CALCUL DU TEMPS DE NUIT (entre 22h et 5h) ---
def calculer_temps_nuit(dt_debut, dt_fin):
    """
    Calcule le nombre de secondes entre dt_debut et dt_fin qui tombent
    dans la plage nocturne [22h00, 05h00[ (heure locale Madagascar).
    Les dt doivent être des objets datetime avec fuseau (ou naive).
    """
    if dt_debut is None or dt_fin is None:
        return 0
    if dt_debut >= dt_fin:
        return 0
    # S'assurer que les dates ont un fuseau (si naive, on lui attribue MADA_TZ)
    if dt_debut.tzinfo is None:
        dt_debut = dt_debut.replace(tzinfo=MADA_TZ)
    if dt_fin.tzinfo is None:
        dt_fin = dt_fin.replace(tzinfo=MADA_TZ)
    
    total_nuit = 0
    # On va itérer minute par minute
    current = dt_debut.replace(second=0, microsecond=0)
    while current < dt_fin:
        # Prochaine minute
        next_min = current + timedelta(minutes=1)
        if next_min > dt_fin:
            next_min = dt_fin
        # Vérifier si l'heure actuelle est dans la plage nocturne
        heure = current.hour
        if heure >= 22 or heure < 5:
            # Ajouter la durée de cette minute (ou fraction)
            duree = (next_min - current).total_seconds()
            total_nuit += duree
        current = next_min
    return total_nuit

# --- NOUVELLE PAGE : STATISTIQUES & ANALYSES (OPÉRATEUR) avec analyse Nuit/Jour ---
def page_operateur_stats():
    st.title("📊 Statistiques & Analyses")
    
    # Informations utilisateur
    st.markdown(f"""
        <div style="
            background: rgba(8, 12, 24, 0.5);
            padding: 15px 20px;
            border-radius: 12px;
            border-left: 3px solid #4a8ecf;
            margin-bottom: 20px;
            backdrop-filter: blur(8px);
        ">
            <span style="color: #8bb8ff; font-weight: 500;">▸ Connecté :</span>
            <span style="color: #d0e4ff;">{st.session_state.user_actif}</span>
            <span style="color: #5a7a9a; margin-left: 20px;">{datetime.now(MADA_TZ).strftime('%d/%m/%Y %H:%M')}</span>
        </div>
    """, unsafe_allow_html=True)
    
    # Récupérer les données des tâches terminées
    taches_data = st.session_state.taches_operateur
    if not taches_data:
        st.info("📋 Aucune tâche terminée. Commencez à utiliser le chronomètre pour générer des statistiques.")
        return
    
    # Construire un DataFrame complet
    records = []
    for tache, entries in taches_data.items():
        for entry in entries:
            records.append({
                "tache": tache,
                "date_debut": entry.get("date_debut", ""),
                "date_fin": entry.get("date_fin", ""),
                "temps_secondes": entry.get("temps_secondes", 0),
                "temps_formate": entry.get("temps_formate", "00:00:00"),
                "match": entry.get("match", ""),
                "wf": entry.get("wf", ""),
                "ligue": entry.get("ligue", ""),
                "remarques": entry.get("remarques", ""),
                "evenements": entry.get("evenements", [])
            })
    
    df = pd.DataFrame(records)
    if df.empty:
        st.info("Aucune donnée à afficher.")
        return
    
    # Convertir les dates en datetime avec fuseau MADA
    def parse_date(date_str):
        if not date_str or date_str == "N/A":
            return None
        try:
            # Essayer de parser avec format "%d/%m/%Y %H:%M:%S"
            dt = datetime.strptime(date_str, "%d/%m/%Y %H:%M:%S")
            dt = dt.replace(tzinfo=MADA_TZ)
            return dt
        except:
            return None
    
    df["date_debut_dt"] = df["date_debut"].apply(parse_date)
    df["date_fin_dt"] = df["date_fin"].apply(parse_date)
    # Ne garder que les lignes avec des dates valides
    df = df.dropna(subset=["date_debut_dt", "date_fin_dt"])
    if df.empty:
        st.warning("Aucune tâche avec des dates valides.")
        return
    
    # Calcul du temps de nuit pour chaque tâche
    df["temps_nuit_sec"] = df.apply(
        lambda row: calculer_temps_nuit(row["date_debut_dt"], row["date_fin_dt"]),
        axis=1
    )
    # Temps de jour = total - nuit
    df["temps_jour_sec"] = df["temps_secondes"] - df["temps_nuit_sec"]
    df["temps_nuit_formate"] = df["temps_nuit_sec"].apply(format_duration_hms)
    df["temps_jour_formate"] = df["temps_jour_sec"].apply(format_duration_hms)
    
    # Filtrer par date (sidebar)
    st.sidebar.markdown("---")
    st.sidebar.subheader("📅 Filtres")
    date_min = df["date_debut_dt"].min().date()
    date_max = df["date_debut_dt"].max().date()
    col_filtre1, col_filtre2 = st.sidebar.columns(2)
    with col_filtre1:
        date_debut_filtre = st.date_input("Date début", value=date_min, min_value=date_min, max_value=date_max, key="stats_date_debut")
    with col_filtre2:
        date_fin_filtre = st.date_input("Date fin", value=date_max, min_value=date_min, max_value=date_max, key="stats_date_fin")
    
    # Appliquer les filtres
    mask = (df["date_debut_dt"].dt.date >= date_debut_filtre) & (df["date_debut_dt"].dt.date <= date_fin_filtre)
    df_filtre = df[mask]
    if df_filtre.empty:
        st.warning("Aucune donnée pour la période sélectionnée.")
        return
    
    # Métriques globales (HH:MM:SS)
    total_taches = len(df_filtre)
    total_temps_sec = df_filtre["temps_secondes"].sum()
    moyenne_sec = df_filtre["temps_secondes"].mean() if total_taches > 0 else 0
    mediane_sec = df_filtre["temps_secondes"].median() if total_taches > 0 else 0
    max_sec = df_filtre["temps_secondes"].max() if total_taches > 0 else 0
    min_sec = df_filtre["temps_secondes"].min() if total_taches > 0 else 0
    
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("📋 Tâches", total_taches)
    col2.metric("⏱️ Total", format_duration_hms(total_temps_sec))
    col3.metric("📊 Moyenne", format_duration_hms(moyenne_sec))
    col4.metric("📈 Médiane", format_duration_hms(mediane_sec))
    col5.metric("🔺 Max", format_duration_hms(max_sec))
    col6.metric("🔻 Min", format_duration_hms(min_sec))
    
    st.markdown("---")
    
    # --- NOUVELLE SECTION : ANALYSE NUIT / JOUR ---
    st.subheader("🌙 Analyse Nuit / Jour")
    
    total_nuit_sec = df_filtre["temps_nuit_sec"].sum()
    total_jour_sec = df_filtre["temps_jour_sec"].sum()
    total_sec = total_nuit_sec + total_jour_sec
    taux_nuit = (total_nuit_sec / total_sec * 100) if total_sec > 0 else 0
    
    col_n1, col_n2, col_n3 = st.columns(3)
    col_n1.metric("🌙 Total Nuit", format_duration_hms(total_nuit_sec))
    col_n2.metric("☀️ Total Jour", format_duration_hms(total_jour_sec))
    col_n3.metric("📊 Taux Nuit", f"{taux_nuit:.1f}%")
    
    # Graphique camembert Nuit/Jour
    if total_sec > 0:
        fig_nuit = px.pie(
            names=["Nuit", "Jour"],
            values=[total_nuit_sec, total_jour_sec],
            title="Répartition Nuit / Jour",
            color_discrete_sequence=["#1a4a7a", "#4a8ecf"]
        )
        fig_nuit.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color='#d0e4ff')
        st.plotly_chart(fig_nuit, use_container_width=True)
    else:
        st.info("Aucune donnée pour l'analyse Nuit/Jour.")
    
    st.markdown("---")
    
    # Graphiques existants
    col_g1, col_g2 = st.columns(2)
    
    with col_g1:
        # Répartition par type de tâche (camembert)
        fig_pie = px.pie(
            df_filtre,
            names="tache",
            title="Répartition des tâches par type",
            color_discrete_sequence=px.colors.qualitative.Set3
        )
        fig_pie.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color='#d0e4ff')
        st.plotly_chart(fig_pie, use_container_width=True)
    
    with col_g2:
        # Évolution des temps par jour (histogramme)
        df_jour = df_filtre.groupby(df_filtre["date_debut_dt"].dt.date)["temps_secondes"].sum().reset_index()
        df_jour["jour_str"] = df_jour["date_debut_dt"].astype(str)
        fig_bar = px.bar(
            df_jour,
            x="jour_str",
            y="temps_secondes",
            title="Temps total par jour",
            labels={"temps_secondes": "Temps (secondes)", "jour_str": "Date"},
            color_discrete_sequence=["#4a8ecf"]
        )
        fig_bar.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color='#d0e4ff',
                              xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
                              yaxis=dict(gridcolor='rgba(255,255,255,0.05)'))
        st.plotly_chart(fig_bar, use_container_width=True)
    
    st.markdown("---")
    
    # Tableau récapitulatif par type de tâche
    st.subheader("📋 Performances par type de tâche")
    df_type = df_filtre.groupby("tache").agg(
        nombre=("tache", "count"),
        temps_total=("temps_secondes", "sum"),
        temps_moyen=("temps_secondes", "mean"),
        temps_max=("temps_secondes", "max"),
        temps_min=("temps_secondes", "min"),
        nuit_total=("temps_nuit_sec", "sum"),
        jour_total=("temps_jour_sec", "sum")
    ).reset_index()
    df_type["temps_total_str"] = df_type["temps_total"].apply(format_duration_hms)
    df_type["temps_moyen_str"] = df_type["temps_moyen"].apply(format_duration_hms)
    df_type["temps_max_str"] = df_type["temps_max"].apply(format_duration_hms)
    df_type["temps_min_str"] = df_type["temps_min"].apply(format_duration_hms)
    df_type["nuit_total_str"] = df_type["nuit_total"].apply(format_duration_hms)
    df_type["jour_total_str"] = df_type["jour_total"].apply(format_duration_hms)
    
    st.dataframe(
        df_type[["tache", "nombre", "temps_total_str", "temps_moyen_str", "temps_max_str", "temps_min_str", "nuit_total_str", "jour_total_str"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "tache": "Type de tâche",
            "nombre": "Nombre",
            "temps_total_str": "Temps total",
            "temps_moyen_str": "Temps moyen",
            "temps_max_str": "Temps max",
            "temps_min_str": "Temps min",
            "nuit_total_str": "Total Nuit",
            "jour_total_str": "Total Jour"
        }
    )
    
    # Performance quotidienne
    st.markdown("---")
    st.subheader("📅 Performance quotidienne")
    df_perf_jour = df_filtre.groupby(df_filtre["date_debut_dt"].dt.date).agg(
        nb_taches=("tache", "count"),
        temps_total=("temps_secondes", "sum"),
        temps_moyen=("temps_secondes", "mean"),
        nuit_total=("temps_nuit_sec", "sum"),
        jour_total=("temps_jour_sec", "sum")
    ).reset_index()
    df_perf_jour["jour_str"] = df_perf_jour["date_debut_dt"].astype(str)
    df_perf_jour["temps_total_str"] = df_perf_jour["temps_total"].apply(format_duration_hms)
    df_perf_jour["temps_moyen_str"] = df_perf_jour["temps_moyen"].apply(format_duration_hms)
    df_perf_jour["nuit_total_str"] = df_perf_jour["nuit_total"].apply(format_duration_hms)
    df_perf_jour["jour_total_str"] = df_perf_jour["jour_total"].apply(format_duration_hms)
    
    st.dataframe(
        df_perf_jour[["jour_str", "nb_taches", "temps_total_str", "temps_moyen_str", "nuit_total_str", "jour_total_str"]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "jour_str": "Date",
            "nb_taches": "Tâches",
            "temps_total_str": "Temps total",
            "temps_moyen_str": "Temps moyen",
            "nuit_total_str": "Nuit",
            "jour_total_str": "Jour"
        }
    )
    
    # Graphique d'évolution du nombre de tâches par jour
    fig_line = px.line(
        df_perf_jour,
        x="jour_str",
        y="nb_taches",
        title="Évolution du nombre de tâches par jour",
        labels={"nb_taches": "Nombre de tâches", "jour_str": "Date"},
        markers=True
    )
    fig_line.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color='#d0e4ff',
                           xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
                           yaxis=dict(gridcolor='rgba(255,255,255,0.05)'))
    st.plotly_chart(fig_line, use_container_width=True)

# --- PAGE CHAT AMÉLIORÉE AVEC EMOJI, STICKERS, PHOTO ET EFFACER TOUT ---
def page_chat():
    st.title("💬 Chat Interne")
    
    # Informations utilisateur
    st.markdown(f"""
        <div style="
            background: rgba(8, 12, 24, 0.5);
            padding: 15px 20px;
            border-radius: 12px;
            border-left: 3px solid #4a8ecf;
            margin-bottom: 20px;
            backdrop-filter: blur(8px);
        ">
            <span style="color: #8bb8ff; font-weight: 500;">▸ Connecté :</span>
            <span style="color: #d0e4ff;">{st.session_state.user_actif}</span>
            <span style="color: #5a7a9a; margin-left: 20px;">{datetime.now(MADA_TZ).strftime('%d/%m/%Y %H:%M')}</span>
            <span style="color: #5a7a9a; margin-left: 20px;">💬 {len(get_chat_messages(limit=1000))} messages</span>
        </div>
    """, unsafe_allow_html=True)
    
    # --- BOUTON EFFACER TOUS LES MESSAGES ---
    col_clear, _ = st.columns([1, 3])
    with col_clear:
        if st.button("🗑️ Effacer tous les messages", type="secondary", use_container_width=True):
            if st.session_state.get("confirm_clear", False):
                clear_all_messages()
                st.session_state.confirm_clear = False
                st.toast("✅ Tous les messages ont été supprimés !", icon="🗑️")
                st.rerun()
            else:
                st.session_state.confirm_clear = True
                st.warning("⚠️ Cliquez à nouveau pour confirmer la suppression définitive.")
    
    # --- AFFICHAGE DES MESSAGES ---
    st.markdown("---")
    st.markdown("### 📜 Historique des messages")
    
    messages = get_chat_messages(limit=50)
    if not messages:
        st.info("Aucun message pour le moment. Soyez le premier à écrire !")
    else:
        for msg in reversed(messages):
            with st.container():
                col_left, col_right = st.columns([1, 5])
                with col_left:
                    st.markdown(f"**{msg['full_name'] or msg['username']}**")
                with col_right:
                    # Message texte
                    st.markdown(f"<div class='chat-message'><span class='sender'>{msg['full_name'] or msg['username']}</span> <span class='timestamp'>{msg['timestamp']}</span><div class='content'>{msg['text']}</div>", unsafe_allow_html=True)
                    # Pièce jointe (image)
                    if msg.get('attachment'):
                        try:
                            # L'attachment est stocké en base64
                            img_data = base64.b64decode(msg['attachment'])
                            st.image(img_data, use_container_width=True)
                        except:
                            st.write("📎 [Pièce jointe non affichable]")
                st.markdown("---")
    
    # --- ZONE DE SAISIE AVEC EMOJI, STICKERS ET PHOTO ---
    st.markdown("### ✉️ Écrire un message")
    
    # Espace emoji / stickers dans un expander
    with st.expander("😊 Emojis & Stickers", expanded=False):
        st.markdown("#### Emojis")
        emojis = ["😊", "👍", "❤️", "😂", "😍", "🔥", "👏", "🎉", "💪", "🙌", "🤝", "✨"]
        cols_emoji = st.columns(len(emojis))
        for i, emoji in enumerate(emojis):
            with cols_emoji[i]:
                if st.button(emoji, key=f"emoji_{i}", help="Insérer l'emoji"):
                    st.session_state.chat_message_text += emoji
                    st.rerun()
        
        st.markdown("#### Stickers")
        stickers = ["🌟", "🌈", "💯", "🚀", "🎯", "⭐", "🔥", "💎", "🎈", "🎁", "🏆", "📌"]
        cols_sticker = st.columns(len(stickers))
        for i, sticker in enumerate(stickers):
            with cols_sticker[i]:
                if st.button(sticker, key=f"sticker_{i}", help="Insérer le sticker"):
                    st.session_state.chat_message_text += sticker
                    st.rerun()
    
    # Formulaire d'envoi avec photo
    with st.form(key="chat_form", clear_on_submit=True):
        # Zone de saisie
        message_input = st.text_area(
            "Message",
            value=st.session_state.chat_message_text,
            placeholder="Tapez votre message ici...",
            height=100,
            key="chat_text_area"
        )
        # Mettre à jour la session quand l'utilisateur tape
        if message_input != st.session_state.chat_message_text:
            st.session_state.chat_message_text = message_input
        
        # Upload de photo
        uploaded_file = st.file_uploader("📎 Ajouter une photo", type=["jpg", "jpeg", "png", "gif"], accept_multiple_files=False)
        
        col_submit, col_clear_input = st.columns([1, 1])
        with col_submit:
            submitted = st.form_submit_button("📤 Envoyer", type="primary", use_container_width=True)
        with col_clear_input:
            clear_input = st.form_submit_button("🔄 Effacer le texte", use_container_width=True)
            if clear_input:
                st.session_state.chat_message_text = ""
                st.rerun()
        
        if submitted:
            # Récupérer le texte depuis la session (car clear_on_submit efface la zone)
            text_to_send = st.session_state.chat_message_text.strip()
            if text_to_send or uploaded_file:
                # Traiter la photo
                attachment_base64 = None
                if uploaded_file:
                    try:
                        # Lire et encoder en base64
                        img_bytes = uploaded_file.read()
                        attachment_base64 = base64.b64encode(img_bytes).decode('utf-8')
                    except Exception as e:
                        st.error(f"Erreur lors du traitement de l'image : {e}")
                
                # Envoyer
                users = load_users()
                full_name = users.get(st.session_state.user_actif, {}).get("full_name", st.session_state.user_actif)
                send_chat_message(st.session_state.user_actif, full_name, text_to_send, attachment_base64)
                st.session_state.chat_message_text = ""
                st.toast("✅ Message envoyé !", icon="✅")
                time.sleep(0.5)
                st.rerun()
            else:
                st.warning("⚠️ Veuillez écrire un message ou ajouter une photo.")

# --- NOUVELLE PAGE : RÉPARTITION DES TÂCHES (KANBAN) ---
def page_operateur_shared_tasks():
    st.title("Répartition des Tâches")
    
    # En-tête utilisateur simplifié
    st.markdown(f"""
        <div style="
            background: rgba(8, 12, 24, 0.5);
            padding: 10px 18px;
            border-radius: 12px;
            border-left: 3px solid #4a8ecf;
            margin-bottom: 18px;
            backdrop-filter: blur(8px);
        ">
            <span style="color: #8bb8ff; font-weight: 500;">▸ {st.session_state.user_actif}</span>
            <span style="color: #5a7a9a; margin-left: 20px; font-size: 0.85em;">{datetime.now(MADA_TZ).strftime('%d/%m/%Y %H:%M')}</span>
        </div>
    """, unsafe_allow_html=True)
    
    # Récupération des tâches partagées
    shared_tasks = get_all_shared_tasks()
    # Récupération de la liste des agents (utilisateurs avec rôle 'operateur')
    users = load_users()
    agent_names = [u for u, info in users.items() if info.get("role") == "operateur"]
    # Si aucun agent dans users, on prend ceux de la table agents
    if not agent_names:
        agents_db = db_manager.get_all_agents()
        agent_names = [a["nom"] for a in agents_db]
    
    # --- FORMULAIRE D'AJOUT DE TÂCHE ---
    with st.expander("➕ Ajouter une nouvelle tâche", expanded=False):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            # --- MODIFICATION ICI : remplacement du text_input par un selectbox ---
            new_tache = st.selectbox(
                "Tâche",
                options=TACHES_DISPONIBLES,
                key="new_tache_select"
            )
        with col2:
            new_match = st.text_input("Match", placeholder="vs")
        with col3:
            new_wf = st.text_input("WF", placeholder="Workflow")
        with col4:
            new_ligue = st.text_input("Ligue", placeholder="Ligue")
        new_remarques = st.text_area("Remarques", placeholder="Informations complémentaires", height=68)
        if st.button("📌 Ajouter la tâche", type="primary"):
            if new_tache.strip():
                add_shared_task(new_tache.strip(), new_match.strip(), new_wf.strip(), new_ligue.strip(), new_remarques.strip())
                st.toast("✅ Tâche ajoutée !", icon="✅")
                st.rerun()
            else:
                st.warning("⚠️ Veuillez sélectionner une tâche.")
    
    st.markdown("---")
    
    # --- AFFICHAGE EN DEUX COLONNES : TÂCHES DISPONIBLES ET TÂCHES ASSIGNÉES PAR AGENT ---
    col_left, col_right = st.columns(2)
    
    with col_left:
        st.markdown("### 📌 Tâches disponibles")
        tasks_disponibles = [t for t in shared_tasks if t["statut"] == "disponible" or t["assigne_a"] is None]
        if tasks_disponibles:
            for task in tasks_disponibles:
                with st.container():
                    st.markdown(f"""
                        <div style="background: rgba(8, 12, 24, 0.5); border-radius: 12px; padding: 12px; margin-bottom: 8px; border-left: 3px solid #4a8ecf; backdrop-filter: blur(8px);">
                            <div style="font-weight: 500;">{task['tache']}</div>
                            <div style="font-size: 0.8em; color: #7a9bcb;">
                                Match: {task['match_info']} | WF: {task['wf']} | Ligue: {task['ligue']}
                            </div>
                            <div style="font-size: 0.8em; color: #7a9bcb;">Remarques: {task['remarques']}</div>
                            <div style="font-size: 0.7em; color: #5a7a9a;">Créé le: {formater_datetime_iso(task['date_creation'])}</div>
                        </div>
                    """, unsafe_allow_html=True)
                    # Menu déroulant pour assigner à un agent
                    col_assign, col_del = st.columns([3, 1])
                    with col_assign:
                        selected_agent = st.selectbox(
                            "Assigner à",
                            options=[""] + agent_names,
                            key=f"assign_{task['id']}",
                            label_visibility="collapsed"
                        )
                        if selected_agent:
                            update_shared_task(task["id"], assigne_a=selected_agent, statut="assignee")
                            st.toast(f"✅ Tâche assignée à {selected_agent}", icon="✅")
                            st.rerun()
                    with col_del:
                        if st.button("🗑️", key=f"del_{task['id']}"):
                            delete_shared_task(task["id"])
                            st.toast("🗑️ Tâche supprimée", icon="🗑️")
                            st.rerun()
                    st.markdown("---")
        else:
            st.info("Aucune tâche disponible.")
    
    with col_right:
        st.markdown("### 👥 Tâches assignées par agent")
        if agent_names:
            # Pour chaque agent, on affiche ses tâches
            for agent in agent_names:
                tasks_agent = [t for t in shared_tasks if t["assigne_a"] == agent and t["statut"] != "termine"]
                with st.expander(f"▸ {agent} ({len(tasks_agent)})", expanded=False):
                    if tasks_agent:
                        for task in tasks_agent:
                            with st.container():
                                st.markdown(f"""
                                    <div style="background: rgba(8, 12, 24, 0.3); border-radius: 10px; padding: 10px; margin-bottom: 6px; border-left: 2px solid #f5b342; backdrop-filter: blur(4px);">
                                        <div style="font-weight: 500;">{task['tache']}</div>
                                        <div style="font-size: 0.8em; color: #7a9bcb;">
                                            Match: {task['match_info']} | WF: {task['wf']} | Ligue: {task['ligue']}
                                        </div>
                                        <div style="font-size: 0.7em; color: #5a7a9a;">Remarques: {task['remarques']}</div>
                                    </div>
                                """, unsafe_allow_html=True)
                                col_mark, col_unassign = st.columns([1, 1])
                                with col_mark:
                                    if st.button("✅ Terminée", key=f"done_{task['id']}"):
                                        update_shared_task(task["id"], statut="termine")
                                        st.toast("✅ Tâche marquée comme terminée", icon="✅")
                                        st.rerun()
                                with col_unassign:
                                    if st.button("↩️ Réassigner", key=f"unassign_{task['id']}"):
                                        update_shared_task(task["id"], assigne_a=None, statut="disponible")
                                        st.toast("↩️ Tâche réassignée (disponible)", icon="↩️")
                                        st.rerun()
                                st.markdown("---")
                    else:
                        st.caption("Aucune tâche assignée.")
        else:
            st.info("Aucun agent trouvé.")

# --- BARRE LATÉRALE GLOBALE AVEC AFFICHAGE DU RÔLE ---
with st.sidebar:
    # Afficher le rôle de l'utilisateur
    role_emoji = {
        "operateur": "▸",
        "admin": "▸"
    }
    role_label = {
        "operateur": "Opérateur",
        "admin": "Administrateur"
    }
    
    st.markdown(f"""
        <div style="margin-bottom: 20px;">
            <span class="status-dot"></span>
            <span style="color: #d0e4ff; font-weight: 500;">▸ Connecté :</span>
            <span style="color: #8bb8ff; font-weight: 600;">`{st.session_state.user_actif}`</span>
            <br>
            <span style="color: #5a7a9a; font-size: 12px;">{role_emoji.get(st.session_state.user_role, '▸')} {role_label.get(st.session_state.user_role, 'Opérateur')}</span>
        </div>
    """, unsafe_allow_html=True)
    
    # --- AFFICHAGE DES STATISTIQUES DE SÉCURITÉ ---
    users = load_users()
    if st.session_state.user_actif in users:
        user_data = users[st.session_state.user_actif]
        if user_data.get("last_login"):
            last_login = user_data["last_login"]
            try:
                dt = datetime.fromisoformat(last_login)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=MADA_TZ)
                last_login_str = dt.strftime("%d/%m/%Y %H:%M")
            except:
                last_login_str = last_login
            st.markdown(f"""
                <div style="font-size: 12px; color: #5a7a9a; margin-bottom: 10px;">
                    🕐 Dernière connexion: {last_login_str}
                </div>
            """, unsafe_allow_html=True)
    
    # --- SECTION SAUVEGARDE ---
    st.markdown("---")
    st.markdown("### 💾 Gestion des données")
    
    # Sauvegarde manuelle (nouvelle version)
    if st.button("💾 Sauvegarder maintenant (export JSON)", use_container_width=True, type="primary"):
        if st.session_state.authentifie and st.session_state.user_actif:
            # Construire les données à sauvegarder (les mêmes qu'avant)
            donnees = {
                "timestamp": datetime.now(MADA_TZ).isoformat(),
                "utilisateur": st.session_state.user_actif,
                "agents": db_manager.get_all_agents(),
                "planning": {},  # on peut récupérer tout le planning, mais on simplifie
                "heures": {},
                "donnees_cloud_centralisees": db_manager.get_all_cloud_data(),
                "taches_operateur": st.session_state.get("taches_operateur", {}),
                "taches_en_cours": st.session_state.get("taches_en_cours", []),
                "couleurs": st.session_state.get("couleurs", {}),
                "task_id_counter": st.session_state.get("task_id_counter", 0),
                "show_completed_tasks": st.session_state.get("show_completed_tasks", True)
            }
            success, msg = gestionnaire_sauvegarde.sauvegarder_donnees_manuelles(
                st.session_state.user_actif, donnees
            )
            if success:
                st.toast(f"✅ Sauvegarde manuelle effectuée : {msg}", icon="💾")
            else:
                st.toast(f"❌ Erreur : {msg}", icon="❌")
    
    # Restaurer la dernière sauvegarde (supprimé car plus utilisé)
    # On retire le bouton "Restaurer dernière sauvegarde"
    
    # Afficher le nombre de sauvegardes manuelles
    try:
        fichiers = glob.glob("sauvegardes/sauvegarde_manuelle_*.json")
        if fichiers:
            st.caption(f"📊 {len(fichiers)} sauvegardes manuelles disponibles")
    except:
        pass
    
    # --- ACTIONS SELON LE RÔLE ---
    # Zone critique - accessible à tous les admins
    if st.session_state.user_role == "admin":
        st.markdown("---")
        st.markdown("### ⚠️ Zone Critique")
        
        confirmer_reset = st.checkbox("Autoriser la remise à zéro")
        if st.button("🚨 Réinitialiser l'interface", type="primary", use_container_width=True, disabled=not confirmer_reset):
            # Effacer les tables (sauf utilisateurs)
            conn = db_manager.get_db()
            c = conn.cursor()
            c.execute("DELETE FROM agents")
            c.execute("DELETE FROM planning")
            c.execute("DELETE FROM heures")
            c.execute("DELETE FROM taches")
            c.execute("DELETE FROM cloud_data")
            c.execute("DELETE FROM pointages")
            c.execute("DELETE FROM messages")  # aussi effacer les messages
            c.execute("DELETE FROM shared_tasks")  # effacer les tâches partagées
            conn.commit()
            conn.close()
            # Réinitialiser les agents par défaut
            for agent in AGENTS_PAR_DEFAUT:
                db_manager.add_agent(agent["Nom"], agent["Poste"])
            
            st.session_state.agents = list(AGENTS_PAR_DEFAUT)
            st.session_state.planning = {}
            st.session_state.heures = {}
            st.session_state.donnees_cloud_centralisees = []
            st.session_state.taches_operateur = {}
            st.session_state.taches_en_cours = []
            st.session_state.task_id_counter = 0
            
            # Sauvegarde automatique supprimée
            # executer_sauvegarde_auto("reset", st.session_state.user_actif)
            st.toast("Grilles et compteur réinitialisés !", icon="💥")
            time.sleep(0.5)
            st.rerun()
    
    st.markdown("---")
    if st.button("🚪 Déconnexion", type="secondary", use_container_width=True):
        # Sauvegarde automatique supprimée
        # executer_sauvegarde_auto("logout", st.session_state.user_actif)
        
        # SUPPRESSION de l'appel à sauvegarder_etat_connexion()
        # car elle stockait l'état d'authentification dans un fichier partagé.
        # On réinitialise simplement les variables de session.
        st.session_state.authentifie = False
        st.session_state.user_actif = ""
        st.session_state.user_role = "operateur"
        st.session_state.user_changed = True
        
        st.rerun()
    st.markdown("---")

# --- FONCTIONS DE CALCUL (pour les heures de nuit - conservées mais utilisées ailleurs) ---
def calculer_heures_nuit(dt_e, dt_s, dt_dp=None, dt_fp=None):
    # Fonction existante, gardée pour compatibilité avec les imports de pointage
    # Elle utilise la plage 19h-5h, mais on garde la nouvelle fonction pour 22h-5h dans les stats
    total_nuit = 0.0
    courant = dt_e
    while courant < dt_s:
        prochain = courant + timedelta(minutes=15)
        if prochain > dt_s:
            prochain = dt_s
            
        milieu = courant + (prochain - courant) / 2
        h_milieu = milieu.time()
        
        if h_milieu >= datetime_time(19, 0) or h_milieu < datetime_time(5, 0):
            dans_pause = False
            if dt_dp and dt_fp and dt_dp <= milieu < dt_fp:
                dans_pause = True
                
            if not dans_pause:
                total_nuit += (prochain - courant).total_seconds() / 3600.0
                
        courant = prochain
    return round(total_nuit, 2)

# --- FORMATAGE (fonctions dépréciées remplacées par format_duration_hms) ---
# Les fonctions formater_en_duree et formater_en_ecart sont conservées pour compatibilité
# avec certaines parties du code (ex: suivi des heures) mais on les modifie pour utiliser le nouveau format
def formater_en_duree(val_float):
    """Convertit un nombre d'heures en HH:MM:SS (via secondes)"""
    try:
        val = float(val_float)
        seconds = val * 3600
        return format_duration_hms(seconds)
    except:
        return "00:00:00"

def formater_en_ecart(val_float):
    """Affiche l'écart en HH:MM:SS avec signe + ou -"""
    try:
        val = float(val_float)
        seconds = val * 3600
        if seconds == 0:
            return "00:00:00"
        signe = "+" if seconds > 0 else "-"
        return signe + format_duration_hms(abs(seconds))
    except:
        return "00:00:00"

# --- STYLES DES GRILLES (adaptés aux nouveaux formats) ---
def appliquer_couleur_jours_cloud(val_str):
    # val_str est au format HH:MM:SS (ou ancien XXhXX)
    try:
        # Convertir en secondes
        if "h" in val_str:
            # ancien format
            parts = val_str.lower().split('h')
            heures = int(parts[0])
            minutes = int(parts[1]) if len(parts) > 1 and parts[1].strip() else 0
            total_heures = heures + minutes/60
        elif ":" in val_str:
            parts = val_str.split(":")
            if len(parts) >= 2:
                heures = int(parts[0])
                minutes = int(parts[1])
                secondes = int(parts[2]) if len(parts) > 2 else 0
                total_heures = heures + minutes/60 + secondes/3600
            else:
                total_heures = float(val_str)
        else:
            total_heures = float(val_str)
        
        if total_heures >= 7.5:
            return "background-color: #2E7D32; color: white; font-weight: bold; text-align: center;"
        elif total_heures >= 7.0:
            return "background-color: #1565C0; color: white; font-weight: bold; text-align: center;"
        elif total_heures >= 6.5:
            return "background-color: #FBC02D; color: black; font-weight: bold; text-align: center;"
        elif total_heures > 0:
            return "background-color: #C62828; color: white; font-weight: bold; text-align: center;"
        else:
            return "text-align: center;"
    except:
        return "text-align: center;"

def appliquer_couleur_jours_suivi_brut(val_str):
    try:
        if "h" in val_str:
            parts = val_str.lower().split('h')
            heures = int(parts[0])
            minutes = int(parts[1]) if len(parts) > 1 and parts[1].strip() else 0
            total_heures = heures + minutes/60
        elif ":" in val_str:
            parts = val_str.split(":")
            heures = int(parts[0])
            minutes = int(parts[1])
            secondes = int(parts[2]) if len(parts) > 2 else 0
            total_heures = heures + minutes/60 + secondes/3600
        else:
            total_heures = float(val_str)
        
        if total_heures >= 8.0:
            return "background-color: #2E7D32; color: white; font-weight: bold; text-align: center;"
        elif total_heures > 0.0:
            return "background-color: #FBC02D; color: black; font-weight: bold; text-align: center;"
        else:
            return "background-color: #C62828; color: white; text-align: center;"
    except:
        return "text-align: center;"

def appliquer_couleur_totaux_ecart(val_str):
    # val_str est un écart avec signe
    if val_str.startswith("+"):
        return "background-color: #2E7D32; color: white; font-weight: bold; text-align: center;"
    elif val_str.startswith("-"):
        return "background-color: #C62828; color: white; font-weight: bold; text-align: center;"
    else:
        return "background-color: white; color: black; font-weight: bold; text-align: center;"

def appliquer_style_nuit(val_str):
    if val_str != "00:00:00" and val_str != "00h00":
        return "background-color: #0D47A1; color: white; font-weight: bold; text-align: center;"
    return "text-align: center;"

def convertir_temps_en_heures(val_str):
    # Convertit une chaîne HH:MM:SS ou XXhXX en heures décimales
    if pd.isna(val_str):
        return 0.0
    val_str = str(val_str).strip()
    if not val_str or val_str in ["0", "00:00:00", "00h00"]:
        return 0.0
    try:
        if ":" in val_str:
            parts = val_str.split(":")
            if len(parts) >= 3:
                h = int(parts[0])
                m = int(parts[1])
                s = int(parts[2])
                return h + (m / 60.0) + (s / 3600.0)
            elif len(parts) == 2:
                h = int(parts[0])
                m = int(parts[1])
                return h + (m / 60.0)
        elif "h" in val_str:
            val_str = val_str.lower().replace("h", ":").replace("m", "").replace("s", "")
            parts = val_str.split(":")
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 and parts[1].strip() else 0
            return h + (m / 60.0)
        return float(val_str)
    except Exception:
        return 0.0

# --- FONCTIONS POUR L'ANALYSE DES PERFORMANCES (CORRIGÉES) ---
def calculer_stats_agent(donnees_cloud, nom_agent, date_debut=None, date_fin=None):
    if not donnees_cloud:
        return None
    
    df = pd.DataFrame(donnees_cloud)
    # Utiliser les noms de colonnes en minuscules
    df_agent = df[df["source_feuille"] == nom_agent]
    
    if df_agent.empty:
        return None
    
    # Convertir date_parsed en datetime si elle existe
    if "date_parsed" in df_agent.columns:
        df_agent["date_parsed"] = pd.to_datetime(df_agent["date_parsed"], errors="coerce")
        # Filtrer si des dates sont fournies
        if date_debut is not None:
            df_agent = df_agent[df_agent["date_parsed"].dt.date >= date_debut]
        if date_fin is not None:
            df_agent = df_agent[df_agent["date_parsed"].dt.date <= date_fin]
    
    if df_agent.empty:
        return None
    
    stats = {
        "nom": nom_agent,
        "total_taches": len(df_agent),
        "total_heures": df_agent["duree_num"].sum(),
        "moyenne_heures": df_agent["duree_num"].mean(),
        "max_heures": df_agent["duree_num"].max(),
        "min_heures": df_agent["duree_num"].min(),
        "types_travail": df_agent["type_travail"].value_counts().to_dict(),
        "taches_par_jour": df_agent.groupby("jour").size().to_dict(),
        "heures_par_jour": df_agent.groupby("jour")["duree_num"].sum().to_dict(),
        "statuts": df_agent["statut"].value_counts().to_dict() if "statut" in df_agent.columns else {}
    }
    
    vitesse_par_type = {}
    for type_travail in df_agent["type_travail"].unique():
        df_type = df_agent[df_agent["type_travail"] == type_travail]
        if not df_type.empty:
            vitesse = len(df_type) / df_type["duree_num"].sum() if df_type["duree_num"].sum() > 0 else 0
            vitesse_par_type[type_travail] = round(vitesse, 2)
    
    stats["vitesse_par_type"] = vitesse_par_type
    
    if stats["total_heures"] > 0:
        stats["performance_globale"] = stats["total_taches"] / stats["total_heures"]
    else:
        stats["performance_globale"] = 0
    
    return stats

def calculer_stats_tous_agents(donnees_cloud, date_debut=None, date_fin=None):
    if not donnees_cloud:
        return {}
    
    df = pd.DataFrame(donnees_cloud)
    
    # Convertir date_parsed en datetime si elle existe
    if "date_parsed" in df.columns:
        df["date_parsed"] = pd.to_datetime(df["date_parsed"], errors="coerce")
        if date_debut is not None:
            df = df[df["date_parsed"].dt.date >= date_debut]
        if date_fin is not None:
            df = df[df["date_parsed"].dt.date <= date_fin]
    else:
        # Si la colonne n'existe pas, on ne peut pas filtrer
        pass
    
    if df.empty:
        return {}
    
    stats_tous = {}
    for agent in df["source_feuille"].unique():
        stats = calculer_stats_agent(donnees_cloud, agent, date_debut, date_fin)
        if stats:
            stats_tous[agent] = stats
    
    return stats_tous

# --- PAGE 1 : GESTION DES AGENTS ---
def page_gestion_agents():
    check_inactivity()
    st.title("👥 Gestion du Personnel")
    
    if st.session_state.user_role == "operateur":
        st.warning("🚫 Accès non autorisé.")
        return
    
    # Récupérer les agents depuis la DB
    agents_db = db_manager.get_all_agents()
    # Mettre à jour la session pour compatibilité avec le reste du code
    st.session_state.agents = [{"Nom": a["nom"], "Poste": a["poste"], "id": a["id"]} for a in agents_db]
    
    # Métriques principales
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Effectif Total", len(agents_db))
    col2.metric("Agents Actifs", len([a for a in agents_db if a.get("actif", 1) == 1]))
    
    # Utiliser les données cloud depuis la DB
    cloud_data = db_manager.get_all_cloud_data()
    if cloud_data:
        df_cloud = pd.DataFrame(cloud_data)
        total_taches = len(df_cloud)
        total_heures = df_cloud["duree_num"].sum() if "duree_num" in df_cloud.columns else 0
        col3.metric("Tâches Totales", total_taches)
        col4.metric("Heures Totales", format_duration_hms(total_heures * 3600))
    else:
        col3.metric("Tâches Totales", "0")
        col4.metric("Heures Totales", "00:00:00")
    
    st.markdown("---")
    
    # --- FILTRE DE DATE ---
    st.markdown("### 📅 Filtre de Période pour l'Analyse des Performances")
    col_date1, col_date2 = st.columns(2)
    with col_date1:
        date_debut_perf = st.date_input("Date de début", value=None, key="perf_date_debut")
    with col_date2:
        date_fin_perf = st.date_input("Date de fin", value=None, key="perf_date_fin")
    
    st.markdown("---")
    
    # --- RÉSUMÉ DES PERFORMANCES PAR AGENT ---
    st.markdown("### 📊 Résumé des Performances par Agent")
    
    if cloud_data:
        stats_tous = calculer_stats_tous_agents(cloud_data, date_debut_perf, date_fin_perf)
        if stats_tous:
            resume_data = []
            for agent, stats in stats_tous.items():
                types_str = ", ".join([f"{k}: {v}" for k, v in stats.get("types_travail", {}).items()])
                vitesse_str = ", ".join([f"{k}: {v:.2f}/h" for k, v in stats.get("vitesse_par_type", {}).items()])
                
                perf = stats.get("performance_globale", 0)
                if perf >= 1.5:
                    niveau = "⭐⭐⭐ Excellent"
                elif perf >= 1.0:
                    niveau = "⭐⭐ Bon"
                elif perf >= 0.5:
                    niveau = "⭐ Moyen"
                else:
                    niveau = "📉 À améliorer"
                
                resume_data.append({
                    "Agent": agent,
                    "Tâches": stats["total_taches"],
                    "Heures Total": format_duration_hms(stats["total_heures"] * 3600),
                    "Moyenne/H": format_duration_hms(stats["moyenne_heures"] * 3600),
                    "Performance": f"{perf:.2f} tâches/h",
                    "Niveau": niveau,
                    "Types de Travail": types_str[:50] + "..." if len(types_str) > 50 else types_str,
                    "Vitesse par Type": vitesse_str[:50] + "..." if len(vitesse_str) > 50 else vitesse_str
                })
            
            df_resume = pd.DataFrame(resume_data)
            st.dataframe(df_resume, use_container_width=True, hide_index=True)
        else:
            st.info("📋 Aucune donnée de performance disponible pour la période sélectionnée.")
    else:
        st.info("💡 Les statistiques de performance apparaîtront après la synchronisation cloud.")
    
    st.markdown("---")
    
    # --- GRAPHIQUE D'ACTIVITÉ ---
    st.markdown("### 📈 Graphique d'Activité des Agents")
    
    if cloud_data:
        df_cloud = pd.DataFrame(cloud_data)
        
        if date_debut_perf and "date_parsed" in df_cloud.columns:
            df_cloud["date_parsed"] = pd.to_datetime(df_cloud["date_parsed"], errors="coerce")
            df_cloud = df_cloud[df_cloud["date_parsed"].dt.date >= date_debut_perf]
        if date_fin_perf and "date_parsed" in df_cloud.columns:
            df_cloud["date_parsed"] = pd.to_datetime(df_cloud["date_parsed"], errors="coerce")
            df_cloud = df_cloud[df_cloud["date_parsed"].dt.date <= date_fin_perf]
        
        if not df_cloud.empty:
            fig1 = px.pie(
                df_cloud, 
                names="source_feuille", 
                title="Répartition des Tâches par Agent",
                color_discrete_sequence=px.colors.qualitative.Set3
            )
            fig1.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#d0e4ff',
                legend=dict(font=dict(color='#d0e4ff'))
            )
            st.plotly_chart(fig1, use_container_width=True)
            
            if "date_parsed" in df_cloud.columns:
                df_heures = df_cloud.groupby(["source_feuille", "jour"])["duree_num"].sum().reset_index()
                fig2 = px.line(
                    df_heures,
                    x="jour",
                    y="duree_num",
                    color="source_feuille",
                    title="Évolution des Heures Travaillées par Agent",
                    labels={"duree_num": "Heures", "jour": "Date"}
                )
                fig2.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font_color='#d0e4ff',
                    legend=dict(font=dict(color='#d0e4ff')),
                    xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.05)')
                )
                st.plotly_chart(fig2, use_container_width=True)
            
            df_types = df_cloud.groupby(["source_feuille", "type_travail"]).size().reset_index(name="Nombre")
            fig3 = px.bar(
                df_types,
                x="source_feuille",
                y="Nombre",
                color="type_travail",
                title="Types de Tâches par Agent",
                barmode="group"
            )
            fig3.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#d0e4ff',
                legend=dict(font=dict(color='#d0e4ff')),
                xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
                yaxis=dict(gridcolor='rgba(255,255,255,0.05)')
            )
            st.plotly_chart(fig3, use_container_width=True)
            
            if "duree_num" in df_cloud.columns and "source_feuille" in df_cloud.columns:
                df_perf = df_cloud.groupby("source_feuille").agg({
                    "duree_num": "sum",
                    "type_travail": "count"
                }).reset_index()
                df_perf.columns = ["Agent", "Heures_Total", "Nombre_Taches"]
                df_perf["Productivite"] = df_perf["Nombre_Taches"] / df_perf["Heures_Total"]
                df_perf["Productivite"] = df_perf["Productivite"].fillna(0)
                
                fig4 = px.scatter(
                    df_perf,
                    x="Heures_Total",
                    y="Nombre_Taches",
                    size="Productivite",
                    color="Agent",
                    hover_name="Agent",
                    title="Matrice de Performance (Taille = Productivité)",
                    labels={"Heures_Total": "Heures Totales", "Nombre_Taches": "Nombre de Tâches"}
                )
                fig4.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font_color='#d0e4ff',
                    legend=dict(font=dict(color='#d0e4ff')),
                    xaxis=dict(gridcolor='rgba(255,255,255,0.05)'),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.05)')
                )
                st.plotly_chart(fig4, use_container_width=True)
        else:
            st.info("📊 Aucune donnée à afficher pour la période sélectionnée.")
    else:
        st.info("💡 Les graphiques d'activité apparaîtront après la synchronisation cloud.")
    
    st.markdown("---")
    
    # --- SECTION GESTION DES AGENTS ---
    st.sidebar.header("📋 Actions RH")
    
    with st.sidebar.form("add_agent", clear_on_submit=True):
        st.markdown("### Ajouter un Agent")
        nom = st.text_input("Nom complet")
        poste = st.text_input("Poste")
        if st.form_submit_button("Ajouter l'agent") and nom.strip() and poste.strip():
            db_manager.add_agent(nom.strip(), poste.strip())
            # Sauvegarde automatique supprimée
            # executer_sauvegarde_auto("update_rh", st.session_state.user_actif)
            st.toast("✅ Agent ajouté ! Tous les admins verront ce changement.", icon="👤")
            st.rerun()

    if agents_db:
        df = pd.DataFrame(agents_db)
        st.dataframe(df[["nom", "poste"]], use_container_width=True, hide_index=True)
        
        st.sidebar.markdown("---")
        # Sélectionner l'agent par nom
        nom_suppr = st.sidebar.selectbox("Sélectionner l'agent", [a["nom"] for a in agents_db])
        if st.sidebar.button("Supprimer définitivement", type="primary"):
            # Récupérer l'id
            agent_id = next((a["id"] for a in agents_db if a["nom"] == nom_suppr), None)
            if agent_id:
                db_manager.delete_agent(agent_id)
            # Sauvegarde automatique supprimée
            # executer_sauvegarde_auto("update_rh", st.session_state.user_actif)
            st.toast("🗑️ Agent supprimé ! Tous les admins verront ce changement.", icon="🗑️")
            st.rerun()

# --- PAGE 2 : PLANNING ---
def page_planning():
    check_inactivity()
    st.title("🗓️ Planning Hebdomadaire")
    
    if st.session_state.user_role == "operateur":
        st.warning("🚫 Accès non autorisé.")
        return
    
    agents_db = db_manager.get_all_agents()
    if not agents_db:
        st.warning("Veuillez d'abord ajouter des agents dans la page 'Gestion du Personnel'.")
        return
    
    # Mettre à jour la session
    st.session_state.agents = [{"Nom": a["nom"], "Poste": a["poste"], "id": a["id"]} for a in agents_db]

    col1, col2, col3, _ = st.columns([2, 2, 3, 3])
    with col1:
        annee_sel = st.selectbox("Année", [2026, 2027], index=0, key="plan_yr")
    with col2:
        mois_options = {1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril", 5: "Mai", 6: "Juin", 7: "Juillet", 8: "Août", 9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre"}
        mois_sel = st.selectbox("Mois", list(mois_options.keys()), format_func=lambda x: mois_options[x], index=datetime.now(MADA_TZ).month - 1, key="plan_mo")

    cal = calendar.Calendar(firstweekday=0)
    semaines_du_mois = cal.monthdayscalendar(annee_sel, mois_sel)
    
    options_semaines = {}
    for idx, sem in enumerate(semaines_du_mois):
        jours_valides = [j for j in sem if j != 0]
        if jours_valides:
            options_semaines[idx] = f"Semaine {idx + 1} (Du {jours_valides[0]:02d} au {jours_valides[-1]:02d})"

    with col3:
        semaine_idx = st.selectbox("Sélectionner la Semaine", list(options_semaines.keys()), format_func=lambda x: options_semaines[x], key="plan_wk")

    with st.sidebar:
        st.header("🎨 Palette des Statuts")
        for statut in ["Travail", "OFF", "Congé", "Maladie", "Formation"]:
            st.session_state.couleurs[statut] = st.color_picker(f"Couleur : {statut}", st.session_state.couleurs[statut])

    st.markdown("---")
    semaine_choisie = semaines_du_mois[semaine_idx]
    noms_jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    colonnes_semaine, mapping_jours = [], {}
    
    for i, j in enumerate(semaine_choisie):
        if j != 0:
            nom_col = f"{noms_jours[i]} {j:02d}"
            colonnes_semaine.append(nom_col)
            mapping_jours[nom_col] = j

    rows = []
    for agent in agents_db:
        nom_agent = agent["nom"]
        agent_id = agent["id"]
        row = {"Agent": nom_agent, "Poste": agent["poste"]}
        for nom_col in colonnes_semaine:
            date_cle = f"{annee_sel}-{mois_sel:02d}-{mapping_jours[nom_col]:02d}"
            planning_date = db_manager.get_planning_for_date(date_cle)
            row[nom_col] = planning_date.get(agent_id, "Travail")
        rows.append(row)

    df_p = pd.DataFrame(rows)
    def style_brut_planning(val):
        color = st.session_state.couleurs.get(val, None)
        return f"background-color: {color}; color: white; font-weight: bold; text-align: center;" if color else "text-align: center;"

    st.dataframe(df_p.style.map(style_brut_planning, subset=colonnes_semaine), use_container_width=True, hide_index=True)

    # --- TABLEAU DE RÉCAPITULATIF GÉNÉRAL DES STATUTS PAR AGENT ---
    st.markdown("---")
    st.markdown("### 📊 Récapitulatif Général des Statuts par Agent")

    recap_data = []
    for agent in agents_db:
        nom_agent = agent["nom"]
        agent_id = agent["id"]
        stats_compteur = {"Travail": 0, "OFF": 0, "Congé": 0, "Maladie": 0, "Formation": 0}
        jours_total = 0
        
        for nom_col in colonnes_semaine:
            date_cle = f"{annee_sel}-{mois_sel:02d}-{mapping_jours[nom_col]:02d}"
            planning_date = db_manager.get_planning_for_date(date_cle)
            statut = planning_date.get(agent_id, "Travail")
            if statut in stats_compteur:
                stats_compteur[statut] += 1
            jours_total += 1
        
        recap_row = {
            "Agent": nom_agent,
            "Poste": agent["poste"],
            "Travail": stats_compteur["Travail"],
            "OFF": stats_compteur["OFF"],
            "Congé": stats_compteur["Congé"],
            "Maladie": stats_compteur["Maladie"],
            "Formation": stats_compteur["Formation"],
            "Total Jours": jours_total
        }
        recap_data.append(recap_row)

    df_recap = pd.DataFrame(recap_data)

    st.dataframe(
        df_recap.style.apply(
            lambda x: [
                f"background-color: {st.session_state.couleurs.get(col, 'transparent') if x[col] > 0 else 'transparent'}; "
                f"color: {'white' if x[col] > 0 else '#666'}; "
                f"font-weight: {'bold' if x[col] > 0 else 'normal'}; "
                f"text-align: center; "
                f"border-radius: 4px; "
                f"padding: 2px 6px;"
                for col in ["Travail", "OFF", "Congé", "Maladie", "Formation"]
            ],
            axis=1,
            subset=["Travail", "OFF", "Congé", "Maladie", "Formation"]
        ),
        use_container_width=True,
        hide_index=True
    )

    st.markdown("#### 📈 Synthèse des Statuts pour la Semaine")
    col_recap1, col_recap2, col_recap3, col_recap4, col_recap5 = st.columns(5)
    
    totaux_statuts = {
        "Travail": df_recap["Travail"].sum() if not df_recap.empty else 0,
        "OFF": df_recap["OFF"].sum() if not df_recap.empty else 0,
        "Congé": df_recap["Congé"].sum() if not df_recap.empty else 0,
        "Maladie": df_recap["Maladie"].sum() if not df_recap.empty else 0,
        "Formation": df_recap["Formation"].sum() if not df_recap.empty else 0
    }
    total_jours = df_recap["Total Jours"].sum() if not df_recap.empty else 0
    
    with col_recap1:
        st.metric(
            label="✅ Travail",
            value=f"{totaux_statuts['Travail']} jours",
            delta=f"{totaux_statuts['Travail']/total_jours*100:.0f}%" if total_jours > 0 else "0%"
        )
    with col_recap2:
        st.metric(
            label="⭕ OFF",
            value=f"{totaux_statuts['OFF']} jours",
            delta=f"{totaux_statuts['OFF']/total_jours*100:.0f}%" if total_jours > 0 else "0%"
        )
    with col_recap3:
        st.metric(
            label="🏖️ Congé",
            value=f"{totaux_statuts['Congé']} jours",
            delta=f"{totaux_statuts['Congé']/total_jours*100:.0f}%" if total_jours > 0 else "0%"
        )
    with col_recap4:
        st.metric(
            label="🤒 Maladie",
            value=f"{totaux_statuts['Maladie']} jours",
            delta=f"{totaux_statuts['Maladie']/total_jours*100:.0f}%" if total_jours > 0 else "0%"
        )
    with col_recap5:
        st.metric(
            label="📚 Formation",
            value=f"{totaux_statuts['Formation']} jours",
            delta=f"{totaux_statuts['Formation']/total_jours*100:.0f}%" if total_jours > 0 else "0%"
        )

    st.caption(f"👥 {len(agents_db)} agents concernés sur {len(colonnes_semaine)} jours ouvrés")

    st.markdown("---")
    st.markdown("### ⚡ Modifier un statut pour cette semaine")
    
    col_a, col_j, col_s, col_btn = st.columns([3, 2, 3, 2])
    with col_a:
        agent_choisi = st.selectbox("Agent", [a["nom"] for a in agents_db], key="mod_ag")
    with col_j:
        jour_choisi = st.selectbox("Jour", [mapping_jours[c] for c in colonnes_semaine], format_func=lambda x: f"{x:02d}", key="mod_jr")
    with col_s:
        statut_choisi = st.selectbox("Nouveau Statut", ["Travail", "OFF", "Congé", "Maladie", "Formation"], key="mod_st")
    with col_btn:
        st.write(""); st.write("")
        if st.button("Appliquer", type="primary", use_container_width=True, key="btn_apply_plan"):
            # Récupérer l'agent_id
            agent_id = next((a["id"] for a in agents_db if a["nom"] == agent_choisi), None)
            date_cle = f"{annee_sel}-{mois_sel:02d}-{jour_choisi:02d}"
            if agent_id:
                db_manager.set_planning(date_cle, agent_id, statut_choisi)
            # Sauvegarde automatique supprimée
            # executer_sauvegarde_auto("update_planning", st.session_state.user_actif)
            st.toast("✅ Statut mis à jour ! Tous les admins verront ce changement.", icon="📋")
            st.rerun()

# --- PAGE 3 : SUIVI DES HEURES (avec bouton de réinitialisation) ---
def page_suivi_heures():
    check_inactivity()
    st.title("⏱️ Suivi des Heures de Production")
    
    if st.session_state.user_role == "operateur":
        st.warning("🚫 Accès non autorisé.")
        return
    
    agents_db = db_manager.get_all_agents()
    if not agents_db:
        st.warning("Veuillez d'abord ajouter des agents dans la page 'Gestion du Personnel'.")
        return

    # Mettre à jour la session
    st.session_state.agents = [{"Nom": a["nom"], "Poste": a["poste"], "id": a["id"]} for a in agents_db]

    # --- Définir mois_options en dehors des onglets pour qu'il soit accessible partout ---
    mois_options = {1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril", 5: "Mai", 6: "Juin",
                    7: "Juillet", 8: "Août", 9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre"}

    # --- Sélection de l'année, du mois et de la semaine (commune à tous les onglets) ---
    col1, col2, col3, _ = st.columns([2, 2, 3, 3])
    with col1:
        annee_sel = st.selectbox("Année", [2026, 2027], index=0, key="hrs_yr")
    with col2:
        mois_sel = st.selectbox("Mois", list(mois_options.keys()), format_func=lambda x: mois_options[x],
                                index=datetime.now(MADA_TZ).month - 1, key="hrs_mo")

    cal = calendar.Calendar(firstweekday=0)
    semaines_du_mois = cal.monthdayscalendar(annee_sel, mois_sel)
    
    options_semaines = {}
    for idx, sem in enumerate(semaines_du_mois):
        jours_valides = [j for j in sem if j != 0]
        if jours_valides:
            options_semaines[idx] = f"Semaine {idx + 1} (Du {jours_valides[0]:02d} au {jours_valides[-1]:02d})"
            
    with col3:
        semaine_idx = st.selectbox("Sélectionner la Semaine", list(options_semaines.keys()),
                                   format_func=lambda x: options_semaines[x], key="hrs_wk")

    semaine_choisie = semaines_du_mois[semaine_idx]
    noms_jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    colonnes_semaine = [f"{noms_jours[i]} {j:02d}" for i, j in enumerate(semaine_choisie) if j != 0]
    
    # --- Création des onglets (4 onglets) ---
    tabs = st.tabs(["📊 Récapitulatif Heures", "✏️ Pointage Manuel", "📋 Présences", "📅 Présence Mensuelle"])

    # ---------- Onglet 1 : Récapitulatif Heures ----------
    with tabs[0]:
        st.markdown("---")
        
        # Import pointage
        st.sidebar.header("📥 Import Pointage")
        uploaded_file = st.sidebar.file_uploader("Importer le fichier pointeuse (.txt, .csv, .xlsx)", type=["txt", "csv", "xlsx"])
        
        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith('.txt'):
                    df_pointage = pd.read_csv(uploaded_file, header=None, names=["Agent", "Timestamp"], sep="\t", engine='python')
                elif uploaded_file.name.endswith('.csv'):
                    df_pointage = pd.read_csv(uploaded_file, header=None, names=["Agent", "Timestamp"], sep=None, engine='python')
                else:
                    df_pointage = pd.read_excel(uploaded_file, header=None, names=["Agent", "Timestamp"])
                    
                df_pointage["Agent"] = df_pointage["Agent"].astype(str).str.strip()
                df_pointage["Timestamp"] = df_pointage["Timestamp"].astype(str).str.strip()
                
                df_pointage["Timestamp"] = pd.to_datetime(df_pointage["Timestamp"], dayfirst=True, errors='coerce')
                df_pointage = df_pointage.dropna(subset=["Timestamp"])
                df_pointage["Date"] = df_pointage["Timestamp"].dt.strftime("%Y-%m-%d")
                
                if st.sidebar.button("Calculer et injecter le pointage", type="primary", use_container_width=True):
                    compteur_updates = 0
                    grouped = df_pointage.groupby(["Date", "Agent"])
                    
                    for (date_cle, agent_nom), group in grouped:
                        timestamps_tries = sorted(group["Timestamp"])
                        nb_pointages = len(timestamps_tries)
                        
                        heures_calculées = 0.0
                        heures_nuit_calculées = 0.0
                        
                        if nb_pointages >= 4:
                            p1, p2, p3, p4 = timestamps_tries[:4]
                            diff1 = (p2 - p1).total_seconds() / 3600.0
                            diff2 = (p4 - p3).total_seconds() / 3600.0
                            heures_calculées = round(max(0.0, diff1 + diff2), 2)
                            heures_nuit_calculées = calculer_heures_nuit(p1, p2) + calculer_heures_nuit(p3, p4)
                        elif nb_pointages >= 2:
                            p1, p2 = timestamps_tries[0], timestamps_tries[-1]
                            heures_calculées = round(max(0.0, (p2 - p1).total_seconds() / 3600.0), 2)
                            heures_nuit_calculées = calculer_heures_nuit(p1, p2)
                        
                        if nb_pointages >= 2:
                            agent_id = next((a["id"] for a in agents_db if a["nom"] == agent_nom), None)
                            if agent_id:
                                db_manager.set_heures(date_cle, agent_id, heures_calculées, heures_nuit_calculées)
                                # Enregistrer les pointages bruts dans la table pointages (optionnel)
                                for ts in timestamps_tries:
                                    db_manager.add_pointage(date_cle, agent_id, "pointage", ts.isoformat())
                                compteur_updates += 1
                                
                    # Sauvegarde automatique supprimée
                    # executer_sauvegarde_auto("import_pointeuse", st.session_state.user_actif)
                    st.sidebar.success(f"✔️ {compteur_updates} fiches journalières extraites !")
                    st.toast("📊 Pointage importé ! Tous les admins verront ces données.", icon="📊")
                    st.rerun()
                    
            except Exception as e:
                st.sidebar.error(f"Erreur d'analyse du fichier : {str(e)}")

        st.markdown(f"### 📊 Récapitulatif global d'Heures — {options_semaines[semaine_idx]}")
        
        rows_heures = []
        rows_dispatch_nuit = []
        rows_weekend = []
        
        for agent in agents_db:
            nom_agent = agent["nom"]
            agent_id = agent["id"]
            row = {"Agent": nom_agent, "Poste": agent["poste"]}
            row_nuit = {"Agent": nom_agent, "Poste": agent["poste"]}
            row_we = {"Agent": nom_agent, "Poste": agent["poste"]}
            
            total_semaine = 0.0
            nuit_semaine = 0.0
            ecart_semaine = 0.0
            samedi_semaine = 0.0
            dimanche_semaine = 0.0
            
            for i, j in enumerate(semaine_choisie):
                if j != 0:
                    nom_col = f"{noms_jours[i]} {j:02d}"
                    d_cle = f"{annee_sel}-{mois_sel:02d}-{j:02d}"
                    
                    heures_date = db_manager.get_heures_for_date(d_cle)
                    donnee = heures_date.get(agent_id, {})
                    hrs = donnee.get("total", 0.0)
                    hrs_nuit = donnee.get("nuit", 0.0)
                        
                    row[nom_col] = format_duration_hms(hrs * 3600)
                    row_nuit[nom_col] = format_duration_hms(hrs_nuit * 3600)
                    
                    total_semaine += hrs
                    nuit_semaine += hrs_nuit
                    if hrs > 0:
                        ecart_semaine += (hrs - 8.0)
                        
                    if noms_jours[i] == "Samedi":
                        samedi_semaine += hrs
                    elif noms_jours[i] == "Dimanche":
                        dimanche_semaine += hrs
            
            row["Total Semaine"] = format_duration_hms(total_semaine * 3600)
            row["Écart Semaine"] = formater_en_ecart(ecart_semaine)
            row_nuit["Total Nuit Semaine"] = format_duration_hms(nuit_semaine * 3600)
            
            row_we["Samedi (Semaine)"] = format_duration_hms(samedi_semaine * 3600)
            row_we["Dimanche (Semaine)"] = format_duration_hms(dimanche_semaine * 3600)
            row_we["Total WE Semaine"] = format_duration_hms((samedi_semaine + dimanche_semaine) * 3600)
            
            total_mois = 0.0
            nuit_mois = 0.0
            ecart_mois = 0.0
            samedi_mois = 0.0
            dimanche_mois = 0.0
            
            _, max_jours_mois = calendar.monthrange(annee_sel, mois_sel)
            for j_mois in range(1, max_jours_mois + 1):
                d_cle_mois = f"{annee_sel}-{mois_sel:02d}-{j_mois:02d}"
                heures_mois = db_manager.get_heures_for_date(d_cle_mois)
                donnee_mois = heures_mois.get(agent_id, {})
                hrs_m = donnee_mois.get("total", 0.0)
                hrs_n_m = donnee_mois.get("nuit", 0.0)
                    
                total_mois += hrs_m
                nuit_mois += hrs_n_m
                if hrs_m > 0:
                    ecart_mois += (hrs_m - 8.0)
                    
                dt_obj = datetime(annee_sel, mois_sel, j_mois)
                if dt_obj.weekday() == 5:
                    samedi_mois += hrs_m
                elif dt_obj.weekday() == 6:
                    dimanche_mois += hrs_m
                
            row["Total Mois"] = format_duration_hms(total_mois * 3600)
            row["Écart Mois"] = formater_en_ecart(ecart_mois)
            row_nuit["Total Nuit Mois"] = format_duration_hms(nuit_mois * 3600)
            
            row_we["Samedi (Mois)"] = format_duration_hms(samedi_mois * 3600)
            row_we["Dimanche (Mois)"] = format_duration_hms(dimanche_mois * 3600)
            row_we["Total WE Mois"] = format_duration_hms((samedi_mois + dimanche_mois) * 3600)
            
            rows_heures.append(row)
            rows_dispatch_nuit.append(row_nuit)
            rows_weekend.append(row_we)

        df_heures = pd.DataFrame(rows_heures)
        style_df = df_heures.style.map(appliquer_couleur_jours_suivi_brut, subset=colonnes_semaine)
        style_df = style_df.map(appliquer_couleur_totaux_ecart, subset=["Écart Semaine", "Écart Mois"])
        st.dataframe(style_df, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("### 🌙 Dispatching & Ventilation des Heures de Nuit (19:00:00 à 05:00:00)")
        df_nuit = pd.DataFrame(rows_dispatch_nuit)
        style_nuit = df_nuit.style.map(appliquer_style_nuit, subset=colonnes_semaine)
        st.dataframe(style_nuit, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("### 🏖️ Heures Week-end")
        df_weekend = pd.DataFrame(rows_weekend)
        
        def style_col_dimanche_uniquement(col):
            if "Dimanche" in col.name:
                return ["background-color: #1A237E; color: white; font-weight: bold; text-align: center;"] * len(col)
            return ["text-align: center;"] * len(col)
            
        style_we = df_weekend.style.apply(style_col_dimanche_uniquement, axis=0)
        st.dataframe(style_we, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("### 📅 Calendrier Officiel des Jours Fériés (Madagascar)")
        
        jours_feries_data = [
            {"Date": "01 Janvier", "Désignation": "Nouvel An"},
            {"Date": "29 Mars", "Désignation": "Commémoration des Événements de 1947"},
            {"Date": "06 Avril", "Désignation": "Lundi de Pâques"},
            {"Date": "01 Mai", "Désignation": "Fête du Travail"},
            {"Date": "14 Mai", "Désignation": "Ascension"},
            {"Date": "25 Mai", "Désignation": "Lundi de Pentecôte"},
            {"Date": "26 Juin", "Désignation": "Fête Nationale / Fête de l'Indépendance"},
            {"Date": "15 Août", "Désignation": "Assomption"},
            {"Date": "01 Novembre", "Désignation": "Toussaint"},
            {"Date": "25 Décembre", "Désignation": "Noël"}
        ]
        
        df_feries = pd.DataFrame(jours_feries_data)
        col_calendar, col_metric = st.columns([8, 4])
        
        with col_calendar:
            st.dataframe(df_feries, use_container_width=True, hide_index=True)
            
        with col_metric:
            st.metric(label="Total Jours Fériés Annuels", value=f"{len(jours_feries_data)} Jours")
            st.info("💡 Note : Les heures travaillées durant ces jours feront l'objet d'une majoration réglementaire sur les grilles de paie.")

        # --- Bouton de réinitialisation des données de suivi des heures ---
        st.markdown("---")
        st.warning("⚠️ La réinitialisation supprime toutes les données de suivi des heures (table `heures` et `pointages`). Cette action est irréversible.")
        if st.checkbox("Confirmer la réinitialisation des données de suivi des heures", key="reset_heures_confirm"):
            if st.button("🗑️ Réinitialiser les données de suivi des heures", type="primary", use_container_width=True):
                # Sauvegarde automatique supprimée
                # executer_sauvegarde_auto("reset_heures", st.session_state.user_actif)
                # Supprimer les données des tables heures et pointages
                conn = db_manager.get_db()
                c = conn.cursor()
                c.execute("DELETE FROM heures")
                c.execute("DELETE FROM pointages")
                conn.commit()
                conn.close()
                st.toast("✅ Données de suivi des heures réinitialisées avec succès !", icon="🗑️")
                time.sleep(0.5)
                st.rerun()

    # ---------- Onglet 2 : Pointage Manuel (multi-plages) ----------
    with tabs[1]:
        st.markdown("### ✏️ Saisie manuelle des pointages (multi‑plages)")
        st.info("Ajoutez une ou plusieurs plages horaires pour un agent et une date. Les heures s'ajouteront à celles déjà existantes.")
        
        col_agent_date = st.columns(2)
        with col_agent_date[0]:
            # Clé unique pour éviter les conflits
            agent_manuel = st.selectbox("Agent", [a["nom"] for a in agents_db], key="manuel_agent_select")
        with col_agent_date[1]:
            date_manuel = st.date_input("Date", value=datetime.now(MADA_TZ).date(), key="manuel_date")
        
        # Gestion des plages dynamiques
        if "plages_pointage" not in st.session_state:
            st.session_state.plages_pointage = [{"entree": "08:00", "debut_pause": "12:00", "fin_pause": "13:00", "sortie": "17:00"}]
        
        # Afficher les plages
        for i, plage in enumerate(st.session_state.plages_pointage):
            with st.container():
                col1, col2, col3, col4, col5 = st.columns([2,2,2,2,1])
                with col1:
                    plage["entree"] = st.text_input(f"Entrée {i+1}", value=plage["entree"], key=f"entree_{i}")
                with col2:
                    plage["debut_pause"] = st.text_input(f"Début pause {i+1}", value=plage["debut_pause"], key=f"deb_pause_{i}")
                with col3:
                    plage["fin_pause"] = st.text_input(f"Fin pause {i+1}", value=plage["fin_pause"], key=f"fin_pause_{i}")
                with col4:
                    plage["sortie"] = st.text_input(f"Sortie {i+1}", value=plage["sortie"], key=f"sortie_{i}")
                with col5:
                    if st.button("🗑️ Supprimer", key=f"del_plage_{i}"):
                        st.session_state.plages_pointage.pop(i)
                        st.rerun()
        
        if st.button("➕ Ajouter une plage"):
            st.session_state.plages_pointage.append({"entree": "08:00", "debut_pause": "12:00", "fin_pause": "13:00", "sortie": "17:00"})
            st.rerun()
        
        if st.button("💾 Enregistrer les pointages", type="primary", use_container_width=True):
            date_str = date_manuel.strftime("%Y-%m-%d")
            agent_id = next((a["id"] for a in agents_db if a["nom"] == agent_manuel), None)
            if agent_id is None:
                st.error("Agent non trouvé.")
            else:
                total_heures_jour = 0.0
                total_nuit_jour = 0.0
                for idx, plage in enumerate(st.session_state.plages_pointage):
                    try:
                        entree = datetime.strptime(plage["entree"], "%H:%M")
                        debut_pause = datetime.strptime(plage["debut_pause"], "%H:%M")
                        fin_pause = datetime.strptime(plage["fin_pause"], "%H:%M")
                        sortie = datetime.strptime(plage["sortie"], "%H:%M")
                    except:
                        st.error(f"Format d'heure invalide dans la plage {idx+1}. Utilisez HH:MM.")
                        st.stop()
                    dt_entree = datetime.combine(date_manuel, entree.time())
                    dt_debut_pause = datetime.combine(date_manuel, debut_pause.time())
                    dt_fin_pause = datetime.combine(date_manuel, fin_pause.time())
                    dt_sortie = datetime.combine(date_manuel, sortie.time())
                    # Insérer les événements
                    db_manager.add_pointage(date_str, agent_id, "entree", dt_entree.isoformat())
                    db_manager.add_pointage(date_str, agent_id, "debut_pause", dt_debut_pause.isoformat())
                    db_manager.add_pointage(date_str, agent_id, "fin_pause", dt_fin_pause.isoformat())
                    db_manager.add_pointage(date_str, agent_id, "sortie", dt_sortie.isoformat())
                    # Calcul des heures
                    travail1 = (dt_debut_pause - dt_entree).total_seconds() / 3600.0
                    travail2 = (dt_sortie - dt_fin_pause).total_seconds() / 3600.0
                    total_plage = max(0.0, travail1 + travail2)
                    total_heures_jour += total_plage
                    nuit_plage = calculer_heures_nuit(dt_entree, dt_sortie, dt_debut_pause, dt_fin_pause)
                    total_nuit_jour += nuit_plage
                # Enregistrer les totaux (addition)
                db_manager.set_heures(date_str, agent_id, total_heures_jour, total_nuit_jour)
                # Sauvegarde automatique supprimée
                # executer_sauvegarde_auto("pointage_manuel", st.session_state.user_actif)
                st.toast(f"✅ Pointage enregistré pour {agent_manuel} le {date_str} (Total: {format_duration_hms(total_heures_jour * 3600)})", icon="⏱️")
                st.rerun()

    # ---------- Onglet 3 : Présences ----------
    with tabs[2]:
        st.markdown("### 📋 Présences par Agent")
        col_date_presence = st.columns([2,1])
        with col_date_presence[0]:
            date_presence = st.date_input("Choisir une date", value=datetime.now(MADA_TZ).date(), key="presence_date")
        if st.button("Afficher les présences", use_container_width=True):
            date_str = date_presence.strftime("%Y-%m-%d")
            pointages = db_manager.get_pointages_by_date(date_str)
            if not pointages:
                st.info("📋 Aucun pointage pour cette date.")
            else:
                agent_ids = set(p["agent_id"] for p in pointages)
                for agent_id in agent_ids:
                    agent_nom = next((a["nom"] for a in agents_db if a["id"] == agent_id), "Inconnu")
                    events = [p for p in pointages if p["agent_id"] == agent_id]
                    events_sorted = sorted(events, key=lambda x: x["timestamp"])
                    data = []
                    for evt in events_sorted:
                        dt = datetime.fromisoformat(evt["timestamp"])
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=MADA_TZ)
                        data.append({"Type": evt["type"], "Heure": dt.strftime("%H:%M:%S")})
                    df_pres = pd.DataFrame(data)
                    st.subheader(f"👤 {agent_nom}")
                    st.dataframe(df_pres, use_container_width=True, hide_index=True)

    # ---------- Onglet 4 : Présence Mensuelle ----------
    with tabs[3]:
        st.markdown("### 📅 Présence Mensuelle par Agent")
        
        col_mois, col_agent = st.columns(2)
        with col_mois:
            annee_pres = st.selectbox("Année", [2026, 2027], index=0, key="pres_annee")
            mois_pres = st.selectbox("Mois", list(mois_options.keys()), format_func=lambda x: mois_options[x], 
                                     index=datetime.now(MADA_TZ).month - 1, key="pres_mois")
        with col_agent:
            agent_pres = st.selectbox("Agent", [a["nom"] for a in agents_db], key="pres_agent")
        
        agent_id_pres = next((a["id"] for a in agents_db if a["nom"] == agent_pres), None)
        if agent_id_pres is None:
            st.error("Agent introuvable.")
            st.stop()
            
        # Générer les jours du mois
        jours_mois = []
        noms_jours = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
        
        _, max_jours = calendar.monthrange(annee_pres, mois_pres)
        for j in range(1, max_jours + 1):
            date_cle = f"{annee_pres}-{mois_pres:02d}-{j:02d}"
            dt_obj = datetime(annee_pres, mois_pres, j)
            
            # 1. Récupérer les pointages pour trouver entrée / sortie
            pointages = db_manager.get_pointages_by_date(date_cle)
            events_agent = [p for p in pointages if p["agent_id"] == agent_id_pres]
            events_sorted = sorted(events_agent, key=lambda x: x["timestamp"])
            
            entree = ""
            sortie = ""
            if events_sorted:
                debut = datetime.fromisoformat(events_sorted[0]["timestamp"])
                fin = datetime.fromisoformat(events_sorted[-1]["timestamp"])
                if debut.tzinfo is None:
                    debut = debut.replace(tzinfo=MADA_TZ)
                if fin.tzinfo is None:
                    fin = fin.replace(tzinfo=MADA_TZ)
                entree = debut.strftime("%H:%M")
                sortie = fin.strftime("%H:%M")
            
            # 2. Récupérer le statut (Travail, OFF, Congé, etc.)
            planning_date = db_manager.get_planning_for_date(date_cle)
            statut = planning_date.get(agent_id_pres, "")
            
            # 3. Récupérer les heures calculées
            heures_date = db_manager.get_heures_for_date(date_cle)
            donnee_heures = heures_date.get(agent_id_pres, {})
            hrs_total = donnee_heures.get("total", 0.0)
            hrs_nuit = donnee_heures.get("nuit", 0.0)
            
            jours_mois.append({
                "Jour": noms_jours[dt_obj.weekday()],
                "Date": f"{j:02d}/{mois_pres:02d}/{annee_pres}",
                "HD": entree,
                "HF": sortie,
                "Statut": statut if statut else "Non défini",
                "HT Jour": format_duration_hms(hrs_total * 3600),
                "HT Nuit": format_duration_hms(hrs_nuit * 3600)
            })
            
        df_presence = pd.DataFrame(jours_mois)
        
        if df_presence.empty:
            st.info("Aucune donnée pour ce mois.")
        else:
            # Appliquer le style vert/bleu/rouge selon les heures travaillées
            def style_presence(row):
                styles = [""] * len(row)
                try:
                    val = convertir_temps_en_heures(row["HT Jour"])
                    if val >= 7.5:
                        styles[df_presence.columns.get_loc("HT Jour")] = "background-color: #2E7D32; color: white; font-weight: bold; text-align: center;"
                    elif val >= 7.0:
                        styles[df_presence.columns.get_loc("HT Jour")] = "background-color: #1565C0; color: white; font-weight: bold; text-align: center;"
                    elif val >= 6.5:
                        styles[df_presence.columns.get_loc("HT Jour")] = "background-color: #FBC02D; color: black; font-weight: bold; text-align: center;"
                    elif val > 0:
                        styles[df_presence.columns.get_loc("HT Jour")] = "background-color: #C62828; color: white; font-weight: bold; text-align: center;"
                except:
                    pass
                return styles

            st.dataframe(
                df_presence.style.apply(style_presence, axis=1),
                use_container_width=True,
                hide_index=True
            )
            
            # Métriques du mois
            total_heures_mois = sum([convertir_temps_en_heures(r["HT Jour"]) for _, r in df_presence.iterrows()])
            total_nuit_mois = sum([convertir_temps_en_heures(r["HT Nuit"]) for _, r in df_presence.iterrows()])
            jours_travail = sum([1 for _, r in df_presence.iterrows() if convertir_temps_en_heures(r["HT Jour"]) > 0])
            
            st.markdown("---")
            col_m1, col_m2, col_m3 = st.columns(3)
            col_m1.metric("📅 Jours Travaillés", jours_travail)
            col_m2.metric("⏱️ Total Heures Mois", format_duration_hms(total_heures_mois * 3600))
            col_m3.metric("🌙 Total Heures Nuit", format_duration_hms(total_nuit_mois * 3600))

# --- PAGE 4 : SYNCHRONISATION CLOUD ---
def page_synchronisation_cloud():
    check_inactivity()
    st.title("🌐 Analyse & Importation Multi-Feuilles Google Sheets")
    
    if st.session_state.user_role == "operateur":
        st.warning("🚫 Accès non autorisé.")
        return
    
    st.markdown("Cette interface extrait et centralise les données de production depuis vos 5 feuilles de suivi.")

    # --- DÉFINITION DES LIENS DES FEUILLES ---
    LIENS_FEUILLES = {
        "Toky": "https://docs.google.com/spreadsheets/d/e/2PACX-1vQU6MvzrX1xe2QrMg8uhBiUQ-sxz8X6F04f_3smdWifA7wXh4fKslIvPgfBJ4gQnWLvxv2iKRPP6Gyq/pub?gid=0&single=true&output=csv",
        "Ny Haingo": "https://docs.google.com/spreadsheets/d/e/2PACX-1vQU6MvzrX1xe2QrMg8uhBiUQ-sxz8X6F04f_3smdWifA7wXh4fKslIvPgfBJ4gQnWLvxv2iKRPP6Gyq/pub?gid=353808453&single=true&output=csv",
        "Zara": "https://docs.google.com/spreadsheets/d/e/2PACX-1vQU6MvzrX1xe2QrMg8uhBiUQ-sxz8X6F04f_3smdWifA7wXh4fKslIvPgfBJ4gQnWLvxv2iKRPP6Gyq/pub?gid=230349377&single=true&output=csv",
        "Isaia": "https://docs.google.com/spreadsheets/d/e/2PACX-1vQU6MvzrX1xe2QrMg8uhBiUQ-sxz8X6F04f_3smdWifA7wXh4fKslIvPgfBJ4gQnWLvxv2iKRPP6Gyq/pub?gid=1868581922&single=true&output=csv",
        "Vanja": "https://docs.google.com/spreadsheets/d/e/2PACX-1vQU6MvzrX1xe2QrMg8uhBiUQ-sxz8X6F04f_3smdWifA7wXh4fKslIvPgfBJ4gQnWLvxv2iKRPP6Gyq/pub?gid=1825784313&single=true&output=csv"
    }

    # --- FONCTION D'IMPORTATION AVEC GESTION DES DOUBLONS ---
    def importer_donnees_cloud(only_new=False):
        """Importe les données cloud avec option pour n'importer que les nouvelles données"""
        try:
            with st.spinner("Téléchargement instantané via CDN Google Web Publish (Sécurisé)..."):
                liste_dfs = []
                nouvelles_lignes = 0
                
                # Récupérer les données existantes pour détection des doublons
                donnees_existantes = []
                if only_new:
                    cloud_data_exist = db_manager.get_all_cloud_data()
                    if cloud_data_exist:
                        df_existant = pd.DataFrame(cloud_data_exist)
                        donnees_existantes = df_existant.apply(
                            lambda row: f"{row.get('date', '')}_{row.get('source_feuille', '')}_{row.get('type_travail', '')}_{row.get('statut', '')}_{row.get('duree_total', '')}", 
                            axis=1
                        ).tolist()
                
                for nom_feuille, export_url in LIENS_FEUILLES.items():
                    try:
                        reponse = requests.get(export_url, timeout=12)
                        if reponse.status_code != 200:
                            st.warning(f"Saut de l'onglet '{nom_feuille}' (Erreur d'accès Web Google {reponse.status_code})")
                            continue
                            
                        csv_data = io.StringIO(reponse.content.decode('utf-8'))
                        df_brut = pd.read_csv(csv_data, header=None)
                        
                        if df_brut.empty:
                            continue
                        
                        df_extrait = df_brut.iloc[1:, [4, 7, 8, 9, 10]].copy()
                        df_extrait.columns = ["Date", "Type_Travail", "Statut", "Duree_Total", "Remarques"]
                        
                        df_extrait = df_extrait.dropna(subset=["Date", "Type_Travail"])
                        df_extrait["Source_Feuille"] = nom_feuille
                        
                        if only_new and donnees_existantes:
                            df_extrait["_cle_unique"] = df_extrait.apply(
                                lambda row: f"{row['Date']}_{row['Source_Feuille']}_{row['Type_Travail']}_{row['Statut']}_{row['Duree_Total']}", 
                                axis=1
                            )
                            df_extrait = df_extrait[~df_extrait["_cle_unique"].isin(donnees_existantes)]
                            df_extrait = df_extrait.drop(columns=["_cle_unique"])
                            nouvelles_lignes += len(df_extrait)
                        else:
                            nouvelles_lignes += len(df_extrait)
                        
                        if not df_extrait.empty:
                            liste_dfs.append(df_extrait)
                    except Exception as ex_single:
                        st.warning(f"Saut de l'onglet '{nom_feuille}' suite à une erreur : {str(ex_single)}")
                        continue

                if not liste_dfs:
                    if only_new:
                        st.info("📋 Aucune nouvelle donnée à importer.")
                    else:
                        st.error("❌ Aucune feuille n'a pu être récupérée. Vérifiez l'état de la publication web.")
                    return False, 0

                df_global = pd.concat(liste_dfs, ignore_index=True)

                df_global["Date_Parsed"] = pd.to_datetime(df_global["Date"], errors="coerce")
                masque_na = df_global["Date_Parsed"].isna()
                if masque_na.any():
                    df_global.loc[masque_na, "Date_Parsed"] = pd.to_datetime(df_global.loc[masque_na, "Date"], dayfirst=True, errors="coerce")
                
                df_global = df_global.dropna(subset=["Date_Parsed"])
                
                df_global["Jour"] = df_global["Date_Parsed"].dt.strftime("%Y-%m-%d")
                df_global["Semaine"] = df_global["Date_Parsed"].dt.strftime("Semaine %U - %Y")
                df_global["Mois"] = df_global["Date_Parsed"].dt.strftime("%B %Y")
                
                df_global["Duree_Num"] = df_global["Duree_Total"].apply(convertir_temps_en_heures)

                # Insérer en DB
                for _, row in df_global.iterrows():
                    db_manager.add_cloud_data(row.to_dict())
                
                # Mettre à jour la session cache
                st.session_state["donnees_cloud_centralisees"] = db_manager.get_all_cloud_data()
                
                # Sauvegarde automatique supprimée
                # executer_sauvegarde_auto("import_multi_sheets", st.session_state.user_actif)
                return True, nouvelles_lignes

        except Exception as e:
            st.error(f"Une exception critique est survenue lors de l'intégration : {str(e)}")
            return False, 0

    # --- BOUTONS D'IMPORTATION ---
    st.sidebar.header("📅 Filtres de Dates Précis")
    date_debut = st.sidebar.date_input("Date de début", value=None)
    date_fin = st.sidebar.date_input("Date de fin", value=None)
    
    st.markdown("### Actions d'Importation")
    
    col_btn1, col_btn2, col_btn3 = st.columns(3)
    
    with col_btn1:
        if st.button("🔄 Synchronisation Complète", type="primary", use_container_width=True):
            # Vider la table cloud_data avant réimport
            db_manager.clear_cloud_data()
            success, nb_lignes = importer_donnees_cloud(only_new=False)
            if success:
                st.success(f"✔️ Synchronisation complète réussie : {nb_lignes} lignes de production agrégées et mémorisées !")
                st.toast("🌐 Données cloud synchronisées pour tous les admins !", icon="🌐")
                st.rerun()
    
    with col_btn2:
        if st.button("📥 Importer les Nouvelles Données", type="secondary", use_container_width=True):
            success, nb_lignes = importer_donnees_cloud(only_new=True)
            if success:
                if nb_lignes > 0:
                    st.success(f"✔️ {nb_lignes} nouvelles lignes importées avec succès !")
                    st.toast("📥 Nouvelles données importées pour tous les admins !", icon="📥")
                else:
                    st.info("📋 Aucune nouvelle donnée à importer. Toutes les données sont déjà à jour.")
                st.rerun()
    
    with col_btn3:
        if st.button("🗑️ Vider le Cache Cloud", type="secondary", use_container_width=True):
            db_manager.clear_cloud_data()
            st.session_state["donnees_cloud_centralisees"] = []
            # Sauvegarde automatique supprimée
            # executer_sauvegarde_auto("clear_cloud_cache", st.session_state.user_actif)
            st.success("✔️ Cache cloud vidé avec succès !")
            st.toast("🗑️ Cache cloud vidé pour tous les admins !", icon="🗑️")
            st.rerun()

    # --- AFFICHAGE DU STATUT ET DERNIÈRE SYNCHRONISATION ---
    st.markdown("---")
    st.markdown("### 📊 Statut de la Synchronisation")
    
    cloud_data = db_manager.get_all_cloud_data()
    nb_lignes_actuelles = len(cloud_data)
    
    col_status1, col_status2, col_status3 = st.columns(3)
    col_status1.metric("📊 Lignes en Cache", nb_lignes_actuelles)
    col_status2.metric("📁 Feuilles Connectées", "5")
    col_status3.metric("🔄 Dernière Synchro", "Partagée" if cloud_data else "Jamais")

    # --- AFFICHAGE DES DONNÉES EXISTANTES ---
    if cloud_data:
        df_affichage = pd.DataFrame(cloud_data)
        
        if "date_parsed" in df_affichage.columns:
            df_affichage["date_parsed"] = pd.to_datetime(df_affichage["date_parsed"])
            
            if date_debut is not None:
                df_affichage = df_affichage[df_affichage["date_parsed"].dt.date >= date_debut]
            if date_fin is not None:
                df_affichage = df_affichage[df_affichage["date_parsed"].dt.date <= date_fin]

        st.markdown("---")
        st.markdown("### 🎛️ Filtres de Sélection Multi-Feuilles")
        
        options_feuilles = ["Tout Afficher"] + list(LIENS_FEUILLES.keys())
        feuille_selectionnee = st.selectbox("Sélectionner la feuille / collaborateur à isoler", options_feuilles, index=0)
        
        if feuille_selectionnee != "Tout Afficher":
            df_affichage = df_affichage[df_affichage["source_feuille"] == feuille_selectionnee]

        st.markdown("### 📊 Indicateurs Clés de Production")
        col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
        col_kpi1.metric("Temps Moyen par Traitement", format_duration_hms(df_affichage["duree_num"].mean() * 3600 if not df_affichage.empty else 0))
        col_kpi2.metric("Volume Total d'Heures", format_duration_hms(df_affichage["duree_num"].sum() * 3600 if not df_affichage.empty else 0))
        col_kpi3.metric("Nombre total de Tâches", f"{len(df_affichage)} Actions")

        st.markdown("#### ⏱️ Cumul des Heures de Production")
        tab_jour, tab_semaine, tab_mois = st.tabs(["Par Jour", "Par Semaine", "Par Mois"])
        
        with tab_jour:
            if not df_affichage.empty:
                df_jour = df_affichage.groupby("jour")["duree_num"].sum().reset_index()
                df_jour["Heures_Formatees"] = df_jour["duree_num"].apply(lambda x: format_duration_hms(x * 3600))
                st.dataframe(df_jour[["jour", "Heures_Formatees"]], use_container_width=True, hide_index=True)
            else:
                st.info("Aucune donnée enregistrée.")
                
        with tab_semaine:
            if not df_affichage.empty:
                df_sem = df_affichage.groupby("semaine")["duree_num"].sum().reset_index()
                df_sem["Heures_Formatees"] = df_sem["duree_num"].apply(lambda x: format_duration_hms(x * 3600))
                st.dataframe(df_sem[["semaine", "Heures_Formatees"]], use_container_width=True, hide_index=True)
            else:
                st.info("Aucune donnée enregistrée.")
                
        with tab_mois:
            if not df_affichage.empty:
                df_m = df_affichage.groupby("mois")["duree_num"].sum().reset_index()
                df_m["Heures_Formatees"] = df_m["duree_num"].apply(lambda x: format_duration_hms(x * 3600))
                st.dataframe(df_m[["mois", "Heures_Formatees"]], use_container_width=True, hide_index=True)
            else:
                st.info("Aucune donnée enregistrée.")

        st.markdown("#### 🗂️ Analyse par Catégories (Type de travail)")
        if not df_affichage.empty:
            df_cat = df_affichage.groupby("type_travail").agg(
                Nombre_de_Taches=("type_travail", "count"),
                Duree_Totale_Heures=("duree_num", "sum"),
                Temps_Moyen_Heures=("duree_num", "mean")
            ).reset_index()
            
            df_cat["Durée Totale"] = df_cat["Duree_Totale_Heures"].apply(lambda x: format_duration_hms(x * 3600))
            df_cat["Temps Moyen"] = df_cat["Temps_Moyen_Heures"].apply(lambda x: format_duration_hms(x * 3600))
            
            st.dataframe(
                df_cat[["type_travail", "Nombre_de_Taches", "Durée Totale", "Temps Moyen"]],
                use_container_width=True, hide_index=True
            )
        else:
            st.info("Aucune catégorie disponible.")

        st.markdown("#### 📋 Registre Général & Remarques")
        if not df_affichage.empty:
            df_registre = df_affichage[["date", "source_feuille", "type_travail", "statut", "duree_total", "remarques"]].copy()
            
            # Appliquer le style sur la colonne duree_total (format HH:MM:SS)
            df_registre["duree_total"] = df_registre["duree_total"].apply(lambda x: format_duration_hms(convertir_temps_en_heures(x) * 3600))
            
            style_registre = df_registre.style.map(appliquer_couleur_jours_cloud, subset=["duree_total"])
            
            evenement_selection = st.dataframe(
                style_registre,
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="multi-row"
            )
            
            lignes_selectionnees = evenement_selection.get("selection", {}).get("rows", [])
            
            if lignes_selectionnees:
                df_calcul = df_affichage.iloc[lignes_selectionnees]
                titre_barre = "Sélection"
            else:
                df_calcul = df_affichage
                titre_barre = "Total Global"
                
            if not df_calcul.empty and "duree_num" in df_calcul.columns:
                nb = len(df_calcul)
                somme_h = df_calcul["duree_num"].sum()
                moyenne_h = df_calcul["duree_num"].mean()
                max_h = df_calcul["duree_num"].max()
                min_h = df_calcul["duree_num"].min()
                
                st.markdown(f"""
                    <div style="
                        display: flex;
                        justify-content: flex-end;
                        gap: 15px;
                        background-color: rgba(8, 12, 24, 0.7);
                        color: #d0e4ff;
                        padding: 6px 15px;
                        border-radius: 20px;
                        font-family: 'Inter', monospace;
                        font-size: 13px;
                        font-weight: 500;
                        border: 1px solid rgba(100, 180, 255, 0.08);
                        width: fit-content;
                        margin-left: auto;
                        margin-top: 10px;
                        box-shadow: 0 2px 10px rgba(0,0,0,0.3);
                        animation: fadeSlideUp 0.5s ease-out;
                    ">
                        <span>[ {titre_barre} ]</span>
                        <span>Nombre : {nb}</span>
                        <span>Moyenne : {format_duration_hms(moyenne_h * 3600)}</span>
                        <span>Somme : {format_duration_hms(somme_h * 3600)}</span>
                        <span>Min : {format_duration_hms(min_h * 3600)}</span>
                        <span>Max : {format_duration_hms(max_h * 3600)}</span>
                    </div>
                """, unsafe_allow_html=True)
        else:
            st.info("Le registre est vide.")
    else:
        st.info("💡 Aucune donnée en cache. Cliquez sur 'Synchronisation Complète' pour importer les données depuis les 5 feuilles Google Sheets.")

    # --- ACTUALISATION AUTOMATIQUE À L'OUVERTURE ---
    if not db_manager.get_all_cloud_data():
        with st.spinner("🔄 Actualisation automatique des données cloud..."):
            success, _ = importer_donnees_cloud(only_new=False)
            if success:
                st.toast("✅ Données cloud synchronisées automatiquement à l'ouverture de la page", icon="🔄")
                time.sleep(0.5)
                st.rerun()

# --- GESTION DE LA PAGE CHAT VIA QUERY PARAM ---
# Si l'utilisateur demande la page chat via ?page=chat, on l'affiche
if st.query_params.get("page") == ["chat"]:
    page_chat()
else:
    # --- SYSTEME DE NAVIGATION (sans le chat dans le menu) ---
    if st.session_state.authentifie:
        if st.session_state.user_role == "operateur":
            pg = st.navigation({
                "Menu Principal": [
                    st.Page(page_operateur_dashboard, title="Suivi des Tâches", icon="⏱️"),
                    st.Page(page_operateur_resume, title="Résumé & Planning", icon="📊"),
                    st.Page(page_operateur_stats, title="Statistiques & Analyses", icon="📈"),
                    st.Page(page_operateur_shared_tasks, title="Répartition des tâches", icon="📋"),
                ]
            })
        else:  # admin
            pg = st.navigation({
                "Menu Principal": [
                    st.Page(page_gestion_agents, title="Gestion du Personnel", icon="👥"),
                    st.Page(page_planning, title="Planning par Semaine", icon="🗓️"),
                    st.Page(page_suivi_heures, title="Suivi des Heures", icon="⏱️"),
                    st.Page(page_synchronisation_cloud, title="Synchronisation Cloud", icon="🌐"),
                ]
            })
        
        pg.run()

# --- BOUTON FLOTTANT POUR LE CHAT (apparaît sur toutes les pages sauf le chat) ---
# On affiche le bouton uniquement si on n'est pas déjà sur la page chat
if st.query_params.get("page") != ["chat"]:
    st.markdown("""
        <a href="?page=chat" class="floating-chat" title="Ouvrir le chat">
            💬
            <span class="badge">!</span>
        </a>
    """, unsafe_allow_html=True)
