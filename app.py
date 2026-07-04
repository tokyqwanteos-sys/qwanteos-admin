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
    """Charge les utilisateurs depuis le fichier"""
    users_file = "sauvegardes/users.json"
    if os.path.exists(users_file):
        try:
            with open(users_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_users(users):
    """Sauvegarde les utilisateurs dans le fichier"""
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
        "timestamp": datetime.now().isoformat(),
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
        
        # Garder seulement les 1000 derniers logs
        if len(logs) > 1000:
            logs = logs[-1000:]
        
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
        "created_at": datetime.now().isoformat(),
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
        if datetime.now() < lock_time:
            remaining = (lock_time - datetime.now()).seconds // 60
            return False, f"Compte bloqué pour {remaining} minutes"
    
    # Vérifier le mot de passe
    if user["password"] == hash_password(password):
        # Réinitialiser les tentatives
        user["login_attempts"] = 0
        user["locked_until"] = None
        user["last_login"] = datetime.now().isoformat()
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
            user["locked_until"] = (datetime.now() + timedelta(minutes=15)).isoformat()
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

# --- CONFIGURATION DE L'APPLICATION ---
st.set_page_config(page_title="Qwanteos-Setup Admin", layout="wide", page_icon="💼")

# --- AJOUT D'UN ARRIÈRE-PLAN PROFESSIONNEL AVEC ANIMATIONS UNIQUEMENT VISUELLES ---
st.markdown("""
    <style>
    /* Gradient animé pour un effet professionnel */
    .stApp {
        background: linear-gradient(-45deg, #0f172a, #1e293b, #0f172a, #1e293b);
        background-size: 400% 400%;
        animation: gradient 15s ease infinite;
    }
    
    @keyframes gradient {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }

    /* Ajustement de la transparence des blocs pour laisser voir le fond */
    div[data-testid="stDataFrame"], .main .block-container {
        background: rgba(255, 255, 255, 0.03);
        border-radius: 15px;
        padding: 20px !important;
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.1);
        animation: fadeSlideUp 0.6s ease-out;
    }
    
    @keyframes fadeSlideUp {
        from {
            opacity: 0;
            transform: translateY(20px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    
    /* Animation des métriques */
    div[data-testid="stMetric"] {
        animation: fadeSlideUp 0.8s ease-out;
        transition: all 0.3s ease;
    }
    
    div[data-testid="stMetric"]:hover {
        transform: translateY(-5px);
        box-shadow: 0 10px 30px rgba(46, 125, 50, 0.2);
    }
    
    div[data-testid="stMetricValue"] {
        animation: pulseGlow 2s ease-in-out infinite;
    }
    
    @keyframes pulseGlow {
        0%, 100% { transform: scale(1); }
        50% { transform: scale(1.03); }
    }
    
    /* Animation des boutons */
    .stButton button {
        transition: all 0.3s ease;
        border-radius: 12px !important;
        font-weight: 600 !important;
    }
    
    .stButton button:hover {
        transform: scale(1.02);
        box-shadow: 0 8px 25px rgba(46, 125, 50, 0.3);
    }
    
    /* Style des titres */
    h1, h2, h3 {
        color: #e2e8f0 !important;
        font-weight: 700 !important;
    }
    
    h1::after {
        content: '';
        display: block;
        width: 60px;
        height: 3px;
        background: linear-gradient(90deg, #2E7D32, #1565C0);
        border-radius: 2px;
        margin-top: 5px;
        animation: slideExpand 1s ease-out;
    }
    
    @keyframes slideExpand {
        from { width: 0; }
        to { width: 60px; }
    }
    
    /* Badge de statut animé */
    .status-badge {
        display: inline-block;
        padding: 6px 16px;
        border-radius: 20px;
        background: linear-gradient(135deg, #2E7D32, #1B5E20);
        color: white;
        font-weight: 600;
        font-size: 13px;
        animation: pulseBadge 2s ease-in-out infinite;
    }
    
    @keyframes pulseBadge {
        0%, 100% { box-shadow: 0 0 20px rgba(46, 125, 50, 0.3); }
        50% { box-shadow: 0 0 40px rgba(46, 125, 50, 0.6); }
    }
    
    .status-dot {
        display: inline-block;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        margin-right: 8px;
        animation: pulseDot 1.5s ease-in-out infinite;
    }
    
    .status-dot.online {
        background: #4CAF50;
        box-shadow: 0 0 20px rgba(76, 175, 80, 0.5);
    }
    
    @keyframes pulseDot {
        0%, 100% { transform: scale(1); opacity: 1; }
        50% { transform: scale(1.3); opacity: 0.7; }
    }
    
    /* Animation des alertes */
    .stAlert {
        animation: slideInRight 0.5s ease-out;
        border-radius: 12px !important;
    }
    
    @keyframes slideInRight {
        from {
            opacity: 0;
            transform: translateX(50px);
        }
        to {
            opacity: 1;
            transform: translateX(0);
        }
    }
    
    /* Sidebar améliorée */
    .css-1d391kg {
        background: rgba(10, 14, 26, 0.95) !important;
        backdrop-filter: blur(20px);
        border-right: 1px solid rgba(255, 255, 255, 0.05);
    }
    
    /* Animation des inputs */
    .stTextInput input, .stSelectbox select {
        transition: all 0.3s ease;
        border-radius: 12px !important;
    }
    
    .stTextInput input:focus, .stSelectbox select:focus {
        border-color: #2E7D32 !important;
        box-shadow: 0 0 20px rgba(46, 125, 50, 0.15);
        transform: scale(1.01);
    }
    
    /* Style du texte pour lisibilité sur fond sombre */
    h1, h2, h3, p, div { color: #e2e8f0 !important; }
    
    /* Welcome page */
    .welcome-container {
        text-align: center;
        margin-top: 5%;
        padding: 40px;
        background: rgba(30, 30, 30, 0.9);
        backdrop-filter: blur(30px);
        border-radius: 15px;
        border: 2px solid #2E7D32;
        box-shadow: 0px 4px 15px rgba(0, 0, 0, 0.5);
        animation: fadeSlideUp 0.8s ease-out;
    }
    .welcome-title {
        color: #ffffff;
        font-size: 42px;
        font-weight: bold;
        margin-bottom: 5px;
    }
    .welcome-subtitle {
        color: #A0A0A0;
        font-size: 18px;
        margin-bottom: 25px;
    }
    .welcome-credit {
        color: #2E7D32;
        font-size: 22px;
        font-weight: bold;
        text-transform: uppercase;
        letter-spacing: 2px;
        margin-top: 20px;
    }
    
    /* Scrollbar personnalisée */
    ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }
    
    ::-webkit-scrollbar-track {
        background: rgba(255, 255, 255, 0.02);
        border-radius: 10px;
    }
    
    ::-webkit-scrollbar-thumb {
        background: linear-gradient(135deg, #2E7D32, #1565C0);
        border-radius: 10px;
    }
    
    ::-webkit-scrollbar-thumb:hover {
        background: linear-gradient(135deg, #1B5E20, #0D47A1);
    }
    
    /* Animation des onglets */
    .stTabs [data-baseweb="tab"] {
        transition: all 0.3s ease;
        border-radius: 10px 10px 0 0;
    }
    
    .stTabs [data-baseweb="tab"]:hover {
        background: rgba(46, 125, 50, 0.1);
        transform: translateY(-2px);
    }
    
    .stTabs [data-baseweb="tab-panel"] {
        animation: fadeSlideUp 0.4s ease-out;
    }
    
    /* Style du formulaire de login */
    .login-form {
        background: rgba(20, 20, 30, 0.95);
        backdrop-filter: blur(20px);
        border-radius: 20px;
        padding: 30px;
        border: 1px solid rgba(46, 125, 50, 0.3);
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
        animation: fadeSlideUp 0.6s ease-out;
    }
    
    .login-form h3 {
        color: #e2e8f0 !important;
        margin-bottom: 20px;
    }
    
    /* Style des onglets login/register */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: rgba(255, 255, 255, 0.05);
        border-radius: 12px;
        padding: 4px;
    }
    
    .stTabs [data-baseweb="tab"] {
        border-radius: 10px;
        padding: 8px 20px;
        color: #94a3b8 !important;
        transition: all 0.3s ease;
    }
    
    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        background: rgba(46, 125, 50, 0.2);
        color: #4CAF50 !important;
    }
    
    .stTabs [data-baseweb="tab"]:hover {
        background: rgba(255, 255, 255, 0.05);
        color: #e2e8f0 !important;
    }
    
    /* Responsive */
    @media (max-width: 768px) {
        .welcome-title {
            font-size: 32px;
        }
        .welcome-container {
            padding: 30px;
        }
    }
    </style>
""", unsafe_allow_html=True)

# --- LOGIQUE DE PERSISTANCE DE SESSION & SAUVEGARDE ---
SESSION_FILE = "sauvegardes/session_state.json"

def sauvegarder_etat_connexion(utilisateur, authentifie, role="operateur"):
    try:
        if not os.path.exists("sauvegardes"):
            os.makedirs("sauvegardes")
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump({"user_actif": utilisateur, "authentifie": authentifie, "role": role}, f)
    except Exception:
        pass

def charger_etat_connexion():
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("user_actif", ""), data.get("authentifie", False), data.get("role", "operateur")
        except Exception:
            return "", False, "operateur"
    return "", False, "operateur"

def executer_sauvegarde_auto(type_evenement, utilisateur):
    try:
        if not os.path.exists("sauvegardes"):
            os.makedirs("sauvegardes")
            
        donnees = {
            "agents": st.session_state.get("agents", []),
            "planning": st.session_state.get("planning", {}),
            "heures": st.session_state.get("heures", {}),
            "donnees_cloud_centralisees": st.session_state.get("donnees_cloud_centralisees", [])
        }
        
        horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
        nom_fichier = f"sauvegardes/sauvegarde_{type_evenement}_{horodatage}.json"
        
        with open(nom_fichier, "w", encoding="utf-8") as f:
            json.dump(donnees, f, ensure_ascii=False, indent=4)
            
        nom_fichier_fixe = "sauvegardes/sauvegarde_last.json"
        with open(nom_fichier_fixe, "w", encoding="utf-8") as f:
            json.dump(donnees, f, ensure_ascii=False, indent=4)
            
        return True, nom_fichier
    except Exception as e:
        return False, str(e)

def charger_derniere_sauvegarde():
    """Charge la sauvegarde partagée (commune à tous les admins)"""
    try:
        if not os.path.exists("sauvegardes"):
            return False
        
        fichier_last = "sauvegardes/sauvegarde_last.json"
        if os.path.exists(fichier_last):
            dernier_fichier = fichier_last
        else:
            fichiers = glob.glob("sauvegardes/sauvegarde_*.json")
            if not fichiers:
                return False
            dernier_fichier = max(fichiers, key=os.path.getmtime)
        
        with open(dernier_fichier, "r", encoding="utf-8") as f:
            donnees = json.load(f)
            
        st.session_state.agents = donnees.get("agents", [])
        st.session_state.planning = donnees.get("planning", {})
        st.session_state.heures = donnees.get("heures", {})
        st.session_state.donnees_cloud_centralisees = donnees.get("donnees_cloud_centralisees", [])
        return True
    except Exception:
        return False

# --- INITIALISATION DE SESSION ---
user_stocke, auth_stocke, role_stocke = charger_etat_connexion()

if "authentifie" not in st.session_state:
    st.session_state.authentifie = auth_stocke

if "user_actif" not in st.session_state:
    st.session_state.user_actif = user_stocke

if "user_role" not in st.session_state:
    st.session_state.user_role = role_stocke

AGENTS_PAR_DEFAUT = [
    {"Nom": "Jean Doe", "Poste": "Setup Operator"},
    {"Nom": "Alice Smith", "Poste": "Team Leader"},
    {"Nom": "Isaïa", "Poste": "Setup Operator"},
    {"Nom": "Elizara", "Poste": "Setup Operator"}
]

if "agents" not in st.session_state: st.session_state.agents = list(AGENTS_PAR_DEFAUT)
if "planning" not in st.session_state: st.session_state.planning = {}
if "heures" not in st.session_state: st.session_state.heures = {}
if "donnees_cloud_centralisees" not in st.session_state: st.session_state.donnees_cloud_centralisees = []
if "couleurs" not in st.session_state:
    st.session_state.couleurs = {
        "Travail": "#2E7D32", "OFF": "#757575", "Congé": "#8D6E63", "Maladie": "#C62828", "Formation": "#1565C0"
    }

# Charger la sauvegarde partagée pour tous les admins
if st.session_state.authentifie and st.session_state.user_role == "admin" and not st.session_state.planning and not st.session_state.heures:
    charger_derniere_sauvegarde()

# --- INTERFACE DE CONNEXION ---
if not st.session_state.authentifie:
    st.markdown("""
        <div class="welcome-container">
            <div class="welcome-title">💼 QWANTEOS-SETUP ADMIN</div>
            <div class="welcome-subtitle">Système Sécurisé de Gestion & Pointage</div>
            <hr style="border-color: #2E7D32; width: 60%; margin: auto; margin-bottom: 20px;">
            <div class="welcome-credit">Created by Toky — Team Lead Setup Qwanteos</div>
            <div style="margin-top: 20px;">
                <span class="status-dot online"></span>
                <span style="color: #4CAF50; font-weight: 500;">Système opérationnel</span>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    st.write("")
    
    col_space, col_form, col_space2 = st.columns([4, 4, 4])
    with col_form:
        with st.container():
            st.markdown('<div class="login-form">', unsafe_allow_html=True)
            
            tab1, tab2 = st.tabs(["🔐 Connexion", "📝 Inscription"])
            
            # --- ONGLET CONNEXION ---
            with tab1:
                with st.form("form_login"):
                    st.markdown("### 🔐 Connexion")
                    identifiant = st.text_input("Nom d'utilisateur", value="")
                    mot_de_passe = st.text_input("Mot de passe", type="password")
                    btn_login = st.form_submit_button("🚀 Se connecter", use_container_width=True)
                    
                    if btn_login:
                        if identifiant and mot_de_passe:
                            success, message = authenticate_user(identifiant, mot_de_passe)
                            if success:
                                st.session_state.authentifie = True
                                st.session_state.user_actif = identifiant
                                st.session_state.user_role = get_user_role(identifiant)
                                
                                sauvegarder_etat_connexion(identifiant, True, st.session_state.user_role)
                                
                                # Charger la sauvegarde partagée si admin
                                if st.session_state.user_role == "admin":
                                    restaure = charger_derniere_sauvegarde()
                                else:
                                    restaure = False
                                
                                executer_sauvegarde_auto("login", identifiant)
                                
                                with st.spinner("Synchronisation des bases de données..."):
                                    time.sleep(1.2)
                                    
                                if restaure:
                                    st.toast("📊 Données partagées restaurées avec succès !", icon="🔄")
                                else:
                                    st.toast("⚠️ Aucune sauvegarde trouvée. Chargement du profil neuf.", icon="🆕")
                                    
                                st.rerun()
                            else:
                                st.error(f"❌ {message}")
                        else:
                            st.warning("⚠️ Veuillez remplir tous les champs")
            
            # --- ONGLET INSCRIPTION ---
            with tab2:
                with st.form("form_register"):
                    st.markdown("### 📝 Créer un compte")
                    st.info("🔒 Mot de passe : 8 caractères min, 1 majuscule, 1 minuscule, 1 chiffre")
                    
                    new_username = st.text_input("Nom d'utilisateur")
                    new_fullname = st.text_input("Nom complet (optionnel)")
                    
                    # Sélection du rôle (plus que 2 rôles)
                    role_options = ["operateur", "admin"]
                    role_labels = {
                        "operateur": "🔵 Opérateur - Accès limité (en développement)",
                        "admin": "🟢 Administrateur - Contrôle total"
                    }
                    selected_role = st.selectbox(
                        "Choisir le rôle du compte",
                        options=role_options,
                        format_func=lambda x: role_labels[x],
                        help="Sélectionnez le niveau d'accès souhaité"
                    )
                    
                    # Code d'accès pour admin uniquement
                    code_acces = ""
                    if selected_role == "admin":
                        code_acces = st.text_input(
                            "🔑 Code d'accès Admin", 
                            type="password",
                            placeholder="Entrez le code d'accès admin",
                            help="Code d'accès requis pour créer un compte Administrateur !"
                        )
                        st.caption("📌 Code d'accès requis")
                    else:
                        st.caption("✅ Aucun code requis pour un compte Opérateur")
                    
                    new_password = st.text_input("Mot de passe", type="password")
                    confirm_password = st.text_input("Confirmer le mot de passe", type="password")
                    
                    btn_register = st.form_submit_button("📝 S'inscrire", use_container_width=True)
                    
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

# --- PAGE POUR OPÉRATEUR (DASHBOARD VIDE) ---
def page_operateur_dashboard():
    st.title("👋 Bienvenue, Opérateur")
    
    st.markdown("""
        <div style="
            text-align: center;
            padding: 60px 20px;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 20px;
            border: 2px dashed rgba(46, 125, 50, 0.3);
            margin-top: 30px;
        ">
            <div style="font-size: 80px; margin-bottom: 20px;">🚧</div>
            <h2 style="color: #4CAF50;">Dashboard Opérateur en Construction</h2>
            <p style="color: #94a3b8; font-size: 18px; max-width: 600px; margin: 20px auto;">
                Un tableau de bord spécialement conçu pour les opérateurs est actuellement en développement.
            </p>
            <p style="color: #64748b; font-size: 16px;">
                Vous pourrez bientôt suivre vos performances, consulter votre planning 
                et accéder à vos statistiques personnelles.
            </p>
            <div style="
                margin-top: 30px;
                display: inline-block;
                padding: 8px 24px;
                background: rgba(46, 125, 50, 0.15);
                border-radius: 30px;
                border: 1px solid rgba(46, 125, 50, 0.3);
                color: #4CAF50;
                font-weight: 500;
            ">
                ⏳ Arrivée prévue : Prochainement
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    # Informations de base sur l'utilisateur
    st.markdown("---")
    st.markdown("### 📋 Vos Informations")
    
    col_info1, col_info2, col_info3 = st.columns(3)
    with col_info1:
        st.metric("👤 Nom d'utilisateur", st.session_state.user_actif)
    with col_info2:
        st.metric("🔑 Rôle", "Opérateur 🔵")
    with col_info3:
        users = load_users()
        if st.session_state.user_actif in users:
            created_at = datetime.fromisoformat(users[st.session_state.user_actif]["created_at"]).strftime("%d/%m/%Y")
            st.metric("📅 Compte créé le", created_at)

# --- BARRE LATÉRALE GLOBALE AVEC AFFICHAGE DU RÔLE ---
with st.sidebar:
    # Afficher le rôle de l'utilisateur
    role_emoji = {
        "operateur": "🔵",
        "admin": "🟢"
    }
    role_label = {
        "operateur": "Opérateur",
        "admin": "Administrateur"
    }
    
    st.markdown(f"""
        <div style="margin-bottom: 20px;">
            <span class="status-dot online"></span>
            <span style="color: #e2e8f0; font-weight: 500;">👤 Connecté :</span>
            <span style="color: #4CAF50; font-weight: 600;">`{st.session_state.user_actif}`</span>
            <br>
            <span style="color: #94a3b8; font-size: 12px;">{role_emoji.get(st.session_state.user_role, '🔵')} {role_label.get(st.session_state.user_role, 'Opérateur')}</span>
        </div>
    """, unsafe_allow_html=True)
    
    # --- AFFICHAGE DES STATISTIQUES DE SÉCURITÉ ---
    users = load_users()
    if st.session_state.user_actif in users:
        user_data = users[st.session_state.user_actif]
        if user_data.get("last_login"):
            last_login = datetime.fromisoformat(user_data["last_login"]).strftime("%d/%m/%Y %H:%M")
            st.markdown(f"""
                <div style="font-size: 12px; color: #94a3b8; margin-bottom: 10px;">
                    🕐 Dernière connexion: {last_login}
                </div>
            """, unsafe_allow_html=True)
    
    # --- ACTIONS SELON LE RÔLE ---
    # Sauvegarde - accessible à tous les admins
    if st.session_state.user_role == "admin":
        if st.button("💾 Sauvegarder les données", use_container_width=True):
            succes, _ = executer_sauvegarde_auto("manuel", st.session_state.user_actif)
            if succes: 
                st.toast("Données partagées sauvegardées ! Tous les admins verront les modifications.", icon="💾")
    
    # Zone critique - accessible à tous les admins
    if st.session_state.user_role == "admin":
        st.markdown("---")
        st.markdown("### ⚠️ Zone Critique")
        
        confirmer_reset = st.checkbox("Autoriser la remise à zéro")
        if st.button("🚨 Réinitialiser l'interface", type="primary", use_container_width=True, disabled=not confirmer_reset):
            st.session_state.agents = list(AGENTS_PAR_DEFAUT)
            st.session_state.planning = {}
            st.session_state.heures = {}
            st.session_state.donnees_cloud_centralisees = []
            
            executer_sauvegarde_auto("reset", st.session_state.user_actif)
            st.toast("Grilles et compteur réinitialisés pour tous les admins !", icon="💥")
            time.sleep(0.5)
            st.rerun()
    
    st.markdown("---")
    if st.button("🚪 Déconnexion", type="secondary", use_container_width=True):
        executer_sauvegarde_auto("logout", st.session_state.user_actif)
        sauvegarder_etat_connexion("", False, "operateur")
        st.session_state.authentifie = False
        st.session_state.user_actif = ""
        st.session_state.user_role = "operateur"
        st.rerun()
    st.markdown("---")

# --- FONCTIONS DE CALCUL ---
def calculer_heures_nuit(dt_e, dt_s, dt_dp=None, dt_fp=None):
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

# --- FORMATAGE ---
def formater_en_duree(val_float):
    try:
        val = float(val_float)
        if val <= 0:
            return "00h00"
        heures = int(val)
        minutes = int(round((val - heures) * 60))
        if minutes == 60:
            heures += 1
            minutes = 0
        return f"{heures:02d}h{minutes:02d}"
    except (ValueError, TypeError):
        return "00h00"

def formater_en_ecart(val_float):
    try:
        val = float(val_float)
        signe = "+" if val > 0 else ("-" if val < 0 else "")
        val_abs = abs(val)
        heures = int(val_abs)
        minutes = int(round((val_abs - heures) * 60))
        if minutes == 60:
            heures += 1
            minutes = 0
        if heures == 0 and minutes == 0:
            return "00h00"
        return f"{signe}{heures:02d}h{minutes:02d}"
    except (ValueError, TypeError):
        return "00h00"

# --- STYLES DES GRILLES ---
def appliquer_couleur_jours_cloud(val_str):
    try:
        if ":" in val_str:
            parts = val_str.split(":")
            heures = int(parts[0])
            minutes = int(parts[1])
        elif "h" in val_str:
            parts = val_str.lower().split('h')
            heures = int(parts[0])
            minutes = int(parts[1]) if len(parts) > 1 and parts[1].strip() else 0
        else:
            total_heures = float(val_str)
            heures, minutes = int(total_heures), int((total_heures - int(total_heures)) * 60)
            
        total_heures = heures + (minutes / 60.0)
        
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
    except Exception:
        return "text-align: center;"

def appliquer_couleur_jours_suivi_brut(val_str):
    try:
        heures = int(val_str.split('h')[0])
        minutes = int(val_str.split('h')[1])
        total_heures = heures + (minutes / 60.0)
        if total_heures >= 8.0:
            return "background-color: #2E7D32; color: white; font-weight: bold; text-align: center;"
        elif total_heures > 0.0:
            return "background-color: #FBC02D; color: black; font-weight: bold; text-align: center;"
        else:
            return "background-color: #C62828; color: white; text-align: center;"
    except Exception:
        return "text-align: center;"

def appliquer_couleur_totaux_ecart(val_str):
    try:
        if val_str.startswith("+"):
            return "background-color: #2E7D32; color: white; font-weight: bold; text-align: center;"
        elif val_str.startswith("-"):
            return "background-color: #C62828; color: white; font-weight: bold; text-align: center;"
        else:
            return "background-color: white; color: black; font-weight: bold; text-align: center;"
    except Exception:
        return "text-align: center;"

def appliquer_style_nuit(val_str):
    if val_str != "00h00" and "h" in val_str:
        return "background-color: #0D47A1; color: white; font-weight: bold; text-align: center;"
    return "text-align: center;"

def convertir_temps_en_heures(val_str):
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

# --- FONCTIONS POUR L'ANALYSE DES PERFORMANCES ---
def calculer_stats_agent(donnees_cloud, nom_agent, date_debut=None, date_fin=None):
    if not donnees_cloud:
        return None
    
    df = pd.DataFrame(donnees_cloud)
    df_agent = df[df["Source_Feuille"] == nom_agent]
    
    if df_agent.empty:
        return None
    
    if date_debut and "Date_Parsed" in df_agent.columns:
        df_agent = df_agent[df_agent["Date_Parsed"] >= pd.to_datetime(date_debut)]
    if date_fin and "Date_Parsed" in df_agent.columns:
        df_agent = df_agent[df_agent["Date_Parsed"] <= pd.to_datetime(date_fin)]
    
    if df_agent.empty:
        return None
    
    stats = {
        "nom": nom_agent,
        "total_taches": len(df_agent),
        "total_heures": df_agent["Duree_Num"].sum(),
        "moyenne_heures": df_agent["Duree_Num"].mean(),
        "max_heures": df_agent["Duree_Num"].max(),
        "min_heures": df_agent["Duree_Num"].min(),
        "types_travail": df_agent["Type_Travail"].value_counts().to_dict(),
        "taches_par_jour": df_agent.groupby("Jour").size().to_dict(),
        "heures_par_jour": df_agent.groupby("Jour")["Duree_Num"].sum().to_dict(),
        "statuts": df_agent["Statut"].value_counts().to_dict() if "Statut" in df_agent.columns else {}
    }
    
    vitesse_par_type = {}
    for type_travail in df_agent["Type_Travail"].unique():
        df_type = df_agent[df_agent["Type_Travail"] == type_travail]
        if not df_type.empty:
            vitesse = len(df_type) / df_type["Duree_Num"].sum() if df_type["Duree_Num"].sum() > 0 else 0
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
    
    if date_debut and "Date_Parsed" in df.columns:
        df = df[df["Date_Parsed"] >= pd.to_datetime(date_debut)]
    if date_fin and "Date_Parsed" in df.columns:
        df = df[df["Date_Parsed"] <= pd.to_datetime(date_fin)]
    
    if df.empty:
        return {}
    
    stats_tous = {}
    for agent in df["Source_Feuille"].unique():
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
    
    # Métriques principales
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Effectif Total", len(st.session_state.agents))
    col2.metric("Agents Actifs", len([a for a in st.session_state.agents if a.get("actif", True)]))
    
    if st.session_state.get("donnees_cloud_centralisees"):
        df_cloud = pd.DataFrame(st.session_state["donnees_cloud_centralisees"])
        total_taches = len(df_cloud)
        total_heures = df_cloud["Duree_Num"].sum() if "Duree_Num" in df_cloud.columns else 0
        col3.metric("Tâches Totales", total_taches)
        col4.metric("Heures Totales", formater_en_duree(total_heures))
    else:
        col3.metric("Tâches Totales", "0")
        col4.metric("Heures Totales", "00h00")
    
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
    
    if st.session_state.get("donnees_cloud_centralisees"):
        stats_tous = calculer_stats_tous_agents(
            st.session_state["donnees_cloud_centralisees"],
            date_debut_perf,
            date_fin_perf
        )
        
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
                    "Heures Total": formater_en_duree(stats["total_heures"]),
                    "Moyenne/H": formater_en_duree(stats["moyenne_heures"]),
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
    
    if st.session_state.get("donnees_cloud_centralisees"):
        df_cloud = pd.DataFrame(st.session_state["donnees_cloud_centralisees"])
        
        if date_debut_perf and "Date_Parsed" in df_cloud.columns:
            df_cloud = df_cloud[df_cloud["Date_Parsed"] >= pd.to_datetime(date_debut_perf)]
        if date_fin_perf and "Date_Parsed" in df_cloud.columns:
            df_cloud = df_cloud[df_cloud["Date_Parsed"] <= pd.to_datetime(date_fin_perf)]
        
        if not df_cloud.empty:
            fig1 = px.pie(
                df_cloud, 
                names="Source_Feuille", 
                title="Répartition des Tâches par Agent",
                color_discrete_sequence=px.colors.qualitative.Set3
            )
            fig1.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#e2e8f0',
                legend=dict(font=dict(color='#e2e8f0'))
            )
            st.plotly_chart(fig1, use_container_width=True)
            
            if "Date_Parsed" in df_cloud.columns:
                df_heures = df_cloud.groupby(["Source_Feuille", "Jour"])["Duree_Num"].sum().reset_index()
                fig2 = px.line(
                    df_heures,
                    x="Jour",
                    y="Duree_Num",
                    color="Source_Feuille",
                    title="Évolution des Heures Travaillées par Agent",
                    labels={"Duree_Num": "Heures", "Jour": "Date"}
                )
                fig2.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font_color='#e2e8f0',
                    legend=dict(font=dict(color='#e2e8f0')),
                    xaxis=dict(gridcolor='rgba(255,255,255,0.1)'),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.1)')
                )
                st.plotly_chart(fig2, use_container_width=True)
            
            df_types = df_cloud.groupby(["Source_Feuille", "Type_Travail"]).size().reset_index(name="Nombre")
            fig3 = px.bar(
                df_types,
                x="Source_Feuille",
                y="Nombre",
                color="Type_Travail",
                title="Types de Tâches par Agent",
                barmode="group"
            )
            fig3.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#e2e8f0',
                legend=dict(font=dict(color='#e2e8f0')),
                xaxis=dict(gridcolor='rgba(255,255,255,0.1)'),
                yaxis=dict(gridcolor='rgba(255,255,255,0.1)')
            )
            st.plotly_chart(fig3, use_container_width=True)
            
            if "Duree_Num" in df_cloud.columns and "Source_Feuille" in df_cloud.columns:
                df_perf = df_cloud.groupby("Source_Feuille").agg({
                    "Duree_Num": "sum",
                    "Type_Travail": "count"
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
                    font_color='#e2e8f0',
                    legend=dict(font=dict(color='#e2e8f0')),
                    xaxis=dict(gridcolor='rgba(255,255,255,0.1)'),
                    yaxis=dict(gridcolor='rgba(255,255,255,0.1)')
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
            st.session_state.agents.append({"Nom": nom.strip(), "Poste": poste.strip()})
            executer_sauvegarde_auto("update_rh", st.session_state.user_actif)
            st.toast("✅ Agent ajouté ! Tous les admins verront ce changement.", icon="👤")
            st.rerun()

    if st.session_state.agents:
        df = pd.DataFrame(st.session_state.agents)
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        st.sidebar.markdown("---")
        nom_suppr = st.sidebar.selectbox("Sélectionner l'agent", [a["Nom"] for a in st.session_state.agents])
        if st.sidebar.button("Supprimer définitivement", type="primary"):
            st.session_state.agents = [a for a in st.session_state.agents if a["Nom"] != nom_suppr]
            executer_sauvegarde_auto("update_rh", st.session_state.user_actif)
            st.toast("🗑️ Agent supprimé ! Tous les admins verront ce changement.", icon="🗑️")
            st.rerun()

# --- PAGE 2 : PLANNING ---
def page_planning():
    check_inactivity()
    st.title("🗓️ Planning Hebdomadaire")
    
    if st.session_state.user_role == "operateur":
        st.warning("🚫 Accès non autorisé.")
        return
    
    if not st.session_state.agents:
        st.warning("Veuillez d'abord ajouter des agents dans la page 'Gestion du Personnel'.")
        return

    col1, col2, col3, _ = st.columns([2, 2, 3, 3])
    with col1:
        annee_sel = st.selectbox("Année", [2026, 2027], index=0, key="plan_yr")
    with col2:
        mois_options = {1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril", 5: "Mai", 6: "Juin", 7: "Juillet", 8: "Août", 9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre"}
        mois_sel = st.selectbox("Mois", list(mois_options.keys()), format_func=lambda x: mois_options[x], index=datetime.now().month - 1, key="plan_mo")

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
    for agent in st.session_state.agents:
        nom_agent = agent["Nom"]
        row = {"Agent": nom_agent, "Poste": agent["Poste"]}
        for nom_col in colonnes_semaine:
            date_cle = f"{annee_sel}-{mois_sel:02d}-{mapping_jours[nom_col]:02d}"
            row[nom_col] = st.session_state.planning.get(date_cle, {}).get(nom_agent, "Travail")
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
    for agent in st.session_state.agents:
        nom_agent = agent["Nom"]
        stats_compteur = {"Travail": 0, "OFF": 0, "Congé": 0, "Maladie": 0, "Formation": 0}
        jours_total = 0
        
        for nom_col in colonnes_semaine:
            date_cle = f"{annee_sel}-{mois_sel:02d}-{mapping_jours[nom_col]:02d}"
            statut = st.session_state.planning.get(date_cle, {}).get(nom_agent, "Travail")
            if statut in stats_compteur:
                stats_compteur[statut] += 1
            jours_total += 1
        
        recap_row = {
            "Agent": nom_agent,
            "Poste": agent["Poste"],
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

    st.caption(f"👥 {len(st.session_state.agents)} agents concernés sur {len(colonnes_semaine)} jours ouvrés")

    st.markdown("---")
    st.markdown("### ⚡ Modifier un statut pour cette semaine")
    
    col_a, col_j, col_s, col_btn = st.columns([3, 2, 3, 2])
    with col_a:
        agent_choisi = st.selectbox("Agent", [a["Nom"] for a in st.session_state.agents], key="mod_ag")
    with col_j:
        jour_choisi = st.selectbox("Jour", [mapping_jours[c] for c in colonnes_semaine], format_func=lambda x: f"{x:02d}", key="mod_jr")
    with col_s:
        statut_choisi = st.selectbox("Nouveau Statut", ["Travail", "OFF", "Congé", "Maladie", "Formation"], key="mod_st")
    with col_btn:
        st.write(""); st.write("")
        if st.button("Appliquer", type="primary", use_container_width=True, key="btn_apply_plan"):
            date_cle = f"{annee_sel}-{mois_sel:02d}-{jour_choisi:02d}"
            if date_cle not in st.session_state.planning: st.session_state.planning[date_cle] = {}
            st.session_state.planning[date_cle][agent_choisi] = statut_choisi
            executer_sauvegarde_auto("update_planning", st.session_state.user_actif)
            st.toast("✅ Statut mis à jour ! Tous les admins verront ce changement.", icon="📋")
            st.rerun()

# --- PAGE 3 : SUIVI DES HEURES ---
def page_suivi_heures():
    check_inactivity()
    st.title("⏱️ Suivi des Heures de Production")
    
    if st.session_state.user_role == "operateur":
        st.warning("🚫 Accès non autorisé.")
        return
    
    if not st.session_state.agents:
        st.warning("Veuillez d'abord ajouter des agents dans la page 'Gestion du Personnel'.")
        return

    col1, col2, col3, _ = st.columns([2, 2, 3, 3])
    with col1:
        annee_sel = st.selectbox("Année", [2026, 2027], index=0, key="hrs_yr")
    with col2:
        mois_options = {1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril", 5: "Mai", 6: "Juin", 7: "Juillet", 8: "Août", 9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre"}
        mois_sel = st.selectbox("Mois", list(mois_options.keys()), format_func=lambda x: mois_options[x], index=datetime.now().month - 1, key="hrs_mo")

    cal = calendar.Calendar(firstweekday=0)
    semaines_du_mois = cal.monthdayscalendar(annee_sel, mois_sel)
    
    options_semaines = {}
    for idx, sem in enumerate(semaines_du_mois):
        jours_valides = [j for j in sem if j != 0]
        if jours_valides:
            options_semaines[idx] = f"Semaine {idx + 1} (Du {jours_valides[0]:02d} au {jours_valides[-1]:02d})"
            
    with col3:
        semaine_idx = st.selectbox("Sélectionner la Semaine", list(options_semaines.keys()), format_func=lambda x: options_semaines[x], key="hrs_wk")

    st.markdown("---")
    
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
                        if date_cle not in st.session_state.heures:
                            st.session_state.heures[date_cle] = {}
                        st.session_state.heures[date_cle][agent_nom] = {
                            "total": heures_calculées,
                            "nuit": heures_nuit_calculées
                        }
                        compteur_updates += 1
                        
                executer_sauvegarde_auto("import_pointeuse", st.session_state.user_actif)
                st.sidebar.success(f"✔️ {compteur_updates} fiches journalières extraites !")
                st.toast("📊 Pointage importé ! Tous les admins verront ces données.", icon="📊")
                st.rerun()
                
        except Exception as e:
            st.sidebar.error(f"Erreur d'analyse du fichier : {str(e)}")

    st.sidebar.markdown("---")
    
    st.sidebar.header("📝 Pointage Manuel")
    agent_h = st.sidebar.selectbox("Agent", [a["Nom"] for a in st.session_state.agents], key="input_hr_ag")
    semaine_choisie = semaines_du_mois[semaine_idx]
    jours_dispos = [j for j in semaine_choisie if j != 0]
    jour_h = st.sidebar.selectbox("Jour", jours_dispos, format_func=lambda x: f"{x:02d}", key="input_hr_jr")
    
    h_entree = st.sidebar.time_input("Heure d'entrée", value=datetime.strptime("08:00", "%H:%M").time())
    h_deb_pause = st.sidebar.time_input("Début Pause (Optionnel)", value=datetime.strptime("12:00", "%H:%M").time())
    h_fin_pause = st.sidebar.time_input("Fin Pause (Optionnel)", value=datetime.strptime("13:00", "%H:%M").time())
    h_sortie = st.sidebar.time_input("Heure de sortie", value=datetime.strptime("17:00", "%H:%M").time())
    
    exclure_pause = st.sidebar.checkbox("Exclure la pause du calcul", value=True)
    
    if st.sidebar.button("Calculer et Enregistrer", use_container_width=True):
        d_base = datetime(2026, 1, 1)
        dt_e = datetime.combine(d_base, h_entree)
        dt_s = datetime.combine(d_base, h_sortie)
        
        if dt_s <= dt_e:
            dt_s += timedelta(days=1)
            
        total_brut = (dt_s - dt_e).total_seconds() / 3600.0
        
        dt_dp, dt_fp = None, None
        duree_pause = 0.0
        if exclure_pause:
            dt_dp = datetime.combine(d_base, h_deb_pause)
            dt_fp = datetime.combine(d_base, h_fin_pause)
            if dt_dp < dt_e:
                dt_dp += timedelta(days=1)
            if dt_fp <= dt_dp:
                dt_fp += timedelta(days=1)
            duree_pause = (dt_fp - dt_dp).total_seconds() / 3600.0
            
        heures_finales = round(max(0.0, total_brut - duree_pause), 2)
        heures_nuit_finales = calculer_heures_nuit(dt_e, dt_s, dt_dp, dt_fp)
        
        date_cle_h = f"{annee_sel}-{mois_sel:02d}-{jour_h:02d}"
        if date_cle_h not in st.session_state.heures: 
            st.session_state.heures[date_cle_h] = {}
            
        st.session_state.heures[date_cle_h][agent_h] = {
            "total": heures_finales,
            "nuit": heures_nuit_finales
        }
        
        executer_sauvegarde_auto("pointage_manuel", st.session_state.user_actif)
        st.toast("⏱️ Pointage manuel enregistré ! Tous les admins verront ces données.", icon="⏱️")
        st.rerun()

    st.markdown(f"### 📊 Récapitulatif global d'Heures — {options_semaines[semaine_idx]}")
    
    noms_jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    colonnes_semaine = [f"{noms_jours[i]} {j:02d}" for i, j in enumerate(semaine_choisie) if j != 0]

    rows_heures = []
    rows_dispatch_nuit = []
    rows_weekend = []
    
    for agent in st.session_state.agents:
        nom_agent = agent["Nom"]
        row = {"Agent": nom_agent, "Poste": agent["Poste"]}
        row_nuit = {"Agent": nom_agent, "Poste": agent["Poste"]}
        row_we = {"Agent": nom_agent, "Poste": agent["Poste"]}
        
        total_semaine = 0.0
        nuit_semaine = 0.0
        ecart_semaine = 0.0
        samedi_semaine = 0.0
        dimanche_semaine = 0.0
        
        for i, j in enumerate(semaine_choisie):
            if j != 0:
                nom_col = f"{noms_jours[i]} {j:02d}"
                d_cle = f"{annee_sel}-{mois_sel:02d}-{j:02d}"
                
                donnee_brute = st.session_state.heures.get(d_cle, {}).get(nom_agent, 0.0)
                if isinstance(donnee_brute, dict):
                    hrs = donnee_brute.get("total", 0.0)
                    hrs_nuit = donnee_brute.get("nuit", 0.0)
                else:
                    hrs = float(donnee_brute)
                    hrs_nuit = 0.0
                    
                row[nom_col] = formater_en_duree(hrs)
                row_nuit[nom_col] = formater_en_duree(hrs_nuit)
                
                total_semaine += hrs
                nuit_semaine += hrs_nuit
                if hrs > 0:
                    ecart_semaine += (hrs - 8.0)
                    
                if noms_jours[i] == "Samedi":
                    samedi_semaine += hrs
                elif noms_jours[i] == "Dimanche":
                    dimanche_semaine += hrs
        
        row["Total Semaine"] = formater_en_duree(total_semaine)
        row["Écart Semaine"] = formater_en_ecart(ecart_semaine)
        row_nuit["Total Nuit Semaine"] = formater_en_duree(nuit_semaine)
        
        row_we["Samedi (Semaine)"] = formater_en_duree(samedi_semaine)
        row_we["Dimanche (Semaine)"] = formater_en_duree(dimanche_semaine)
        row_we["Total WE Semaine"] = formater_en_duree(samedi_semaine + dimanche_semaine)
        
        total_mois = 0.0
        nuit_mois = 0.0
        ecart_mois = 0.0
        samedi_mois = 0.0
        dimanche_mois = 0.0
        
        _, max_jours_mois = calendar.monthrange(annee_sel, mois_sel)
        for j_mois in range(1, max_jours_mois + 1):
            d_cle_mois = f"{annee_sel}-{mois_sel:02d}-{j_mois:02d}"
            donnee_mois = st.session_state.heures.get(d_cle_mois, {}).get(nom_agent, 0.0)
            if isinstance(donnee_mois, dict):
                hrs_m = donnee_mois.get("total", 0.0)
                hrs_n_m = donnee_mois.get("nuit", 0.0)
            else:
                hrs_m = float(donnee_mois)
                hrs_n_m = 0.0
                
            total_mois += hrs_m
            nuit_mois += hrs_n_m
            if hrs_m > 0:
                ecart_mois += (hrs_m - 8.0)
                
            dt_obj = datetime(annee_sel, mois_sel, j_mois)
            if dt_obj.weekday() == 5:
                samedi_mois += hrs_m
            elif dt_obj.weekday() == 6:
                dimanche_mois += hrs_m
            
        row["Total Mois"] = formater_en_duree(total_mois)
        row["Écart Mois"] = formater_en_ecart(ecart_mois)
        row_nuit["Total Nuit Mois"] = formater_en_duree(nuit_mois)
        
        row_we["Samedi (Mois)"] = formater_en_duree(samedi_mois)
        row_we["Dimanche (Mois)"] = formater_en_duree(dimanche_mois)
        row_we["Total WE Mois"] = formater_en_duree(samedi_mois + dimanche_mois)
        
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
                if only_new and st.session_state.get("donnees_cloud_centralisees"):
                    df_existant = pd.DataFrame(st.session_state["donnees_cloud_centralisees"])
                    if not df_existant.empty:
                        donnees_existantes = df_existant.apply(
                            lambda row: f"{row.get('Date', '')}_{row.get('Source_Feuille', '')}_{row.get('Type_Travail', '')}_{row.get('Statut', '')}_{row.get('Duree_Total', '')}", 
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

                if only_new and st.session_state.get("donnees_cloud_centralisees"):
                    df_existant = pd.DataFrame(st.session_state["donnees_cloud_centralisees"])
                    df_final = pd.concat([df_existant, df_global], ignore_index=True)
                    df_final = df_final.drop_duplicates(subset=["Date", "Source_Feuille", "Type_Travail", "Statut", "Duree_Total"])
                    st.session_state["donnees_cloud_centralisees"] = df_final.to_dict(orient="records")
                else:
                    st.session_state["donnees_cloud_centralisees"] = df_global.to_dict(orient="records")
                
                executer_sauvegarde_auto("import_multi_sheets", st.session_state.user_actif)
                return True, nouvelles_lignes

        except Exception as e:
            st.error(f"Une exception critique est survenue lors de l'intégration : {str(e)}")
            return False, 0

    # --- BOUTONS D'IMPORTATION ---
    st.sidebar.header("📅 Filtres de Dates Précis")
    date_debut = st.sidebar.date_input("Date de début", value=None)
    date_fin = st.sidebar.date_input("Date de fin", value=None)
    
    st.markdown("### 🚀 Actions d'Importation")
    
    col_btn1, col_btn2, col_btn3 = st.columns(3)
    
    with col_btn1:
        if st.button("🔄 Synchronisation Complète", type="primary", use_container_width=True):
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
            st.session_state["donnees_cloud_centralisees"] = []
            executer_sauvegarde_auto("clear_cloud_cache", st.session_state.user_actif)
            st.success("✔️ Cache cloud vidé avec succès !")
            st.toast("🗑️ Cache cloud vidé pour tous les admins !", icon="🗑️")
            st.rerun()

    # --- AFFICHAGE DU STATUT ET DERNIÈRE SYNCHRONISATION ---
    st.markdown("---")
    st.markdown("### 📊 Statut de la Synchronisation")
    
    nb_lignes_actuelles = len(st.session_state.get("donnees_cloud_centralisees", []))
    
    col_status1, col_status2, col_status3 = st.columns(3)
    col_status1.metric("📊 Lignes en Cache", nb_lignes_actuelles)
    col_status2.metric("📁 Feuilles Connectées", "5")
    col_status3.metric("🔄 Dernière Synchro", "Partagée" if st.session_state.get("donnees_cloud_centralisees") else "Jamais")

    # --- AFFICHAGE DES DONNÉES EXISTANTES ---
    if st.session_state["donnees_cloud_centralisees"]:
        df_affichage = pd.DataFrame(st.session_state["donnees_cloud_centralisees"])
        
        if "Date_Parsed" in df_affichage.columns:
            df_affichage["Date_Parsed"] = pd.to_datetime(df_affichage["Date_Parsed"])
            
            if date_debut is not None:
                df_affichage = df_affichage[df_affichage["Date_Parsed"].dt.date >= date_debut]
            if date_fin is not None:
                df_affichage = df_affichage[df_affichage["Date_Parsed"].dt.date <= date_fin]

        st.markdown("---")
        st.markdown("### 🎛️ Filtres de Sélection Multi-Feuilles")
        
        options_feuilles = ["Tout Afficher"] + list(LIENS_FEUILLES.keys())
        feuille_selectionnee = st.selectbox("Sélectionner la feuille / collaborateur à isoler", options_feuilles, index=0)
        
        if feuille_selectionnee != "Tout Afficher":
            df_affichage = df_affichage[df_affichage["Source_Feuille"] == feuille_selectionnee]

        st.markdown("### 📊 Indicateurs Clés de Production")
        col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
        col_kpi1.metric("Temps Moyen par Traitement", formater_en_duree(df_affichage["Duree_Num"].mean() if not df_affichage.empty else 0))
        col_kpi2.metric("Volume Total d'Heures", formater_en_duree(df_affichage["Duree_Num"].sum() if not df_affichage.empty else 0))
        col_kpi3.metric("Nombre total de Tâches", f"{len(df_affichage)} Actions")

        st.markdown("#### ⏱️ Cumul des Heures de Production")
        tab_jour, tab_semaine, tab_mois = st.tabs(["Par Jour", "Par Semaine", "Par Mois"])
        
        with tab_jour:
            if not df_affichage.empty:
                df_jour = df_affichage.groupby("Jour")["Duree_Num"].sum().reset_index()
                df_jour["Heures_Formatees"] = df_jour["Duree_Num"].apply(formater_en_duree)
                st.dataframe(df_jour[["Jour", "Heures_Formatees"]], use_container_width=True, hide_index=True)
            else:
                st.info("Aucune donnée enregistrée.")
                
        with tab_semaine:
            if not df_affichage.empty:
                df_sem = df_affichage.groupby("Semaine")["Duree_Num"].sum().reset_index()
                df_sem["Heures_Formatees"] = df_sem["Duree_Num"].apply(formater_en_duree)
                st.dataframe(df_sem[["Semaine", "Heures_Formatees"]], use_container_width=True, hide_index=True)
            else:
                st.info("Aucune donnée enregistrée.")
                
        with tab_mois:
            if not df_affichage.empty:
                df_m = df_affichage.groupby("Mois")["Duree_Num"].sum().reset_index()
                df_m["Heures_Formatees"] = df_m["Duree_Num"].apply(formater_en_duree)
                st.dataframe(df_m[["Mois", "Heures_Formatees"]], use_container_width=True, hide_index=True)
            else:
                st.info("Aucune donnée enregistrée.")

        st.markdown("#### 🗂️ Analyse par Catégories (Type de travail)")
        if not df_affichage.empty:
            df_cat = df_affichage.groupby("Type_Travail").agg(
                Nombre_de_Taches=("Type_Travail", "count"),
                Duree_Totale_Heures=("Duree_Num", "sum"),
                Temps_Moyen_Heures=("Duree_Num", "mean")
            ).reset_index()
            
            df_cat["Durée Totale"] = df_cat["Duree_Totale_Heures"].apply(formater_en_duree)
            df_cat["Temps Moyen"] = df_cat["Temps_Moyen_Heures"].apply(formater_en_duree)
            
            st.dataframe(
                df_cat[["Type_Travail", "Nombre_de_Taches", "Durée Totale", "Temps Moyen"]],
                use_container_width=True, hide_index=True
            )
        else:
            st.info("Aucune catégorie disponible.")

        st.markdown("#### 📋 Registre Général & Remarques")
        if not df_affichage.empty:
            df_registre = df_affichage[["Date", "Source_Feuille", "Type_Travail", "Statut", "Duree_Total", "Remarques"]].copy()
            
            style_registre = df_registre.style.map(appliquer_couleur_jours_cloud, subset=["Duree_Total"])
            
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
                
            if not df_calcul.empty and "Duree_Num" in df_calcul.columns:
                nb = len(df_calcul)
                somme_h = df_calcul["Duree_Num"].sum()
                moyenne_h = df_calcul["Duree_Num"].mean()
                max_h = df_calcul["Duree_Num"].max()
                min_h = df_calcul["Duree_Num"].min()
                
                def formater_en_hms(val_float):
                    if val_float <= 0: return "00:00:00"
                    h = int(val_float)
                    m = int((val_float - h) * 60)
                    s = int(round((((val_float - h) * 60) - m) * 60))
                    if s == 60: m += 1; s = 0
                    if m == 60: h += 1; m = 0
                    return f"{h:02d}:{m:02d}:{s:02d}"

                st.markdown(f"""
                    <div style="
                        display: flex;
                        justify-content: flex-end;
                        gap: 15px;
                        background-color: #E8F5E9;
                        color: #1B5E20;
                        padding: 6px 15px;
                        border-radius: 20px;
                        font-family: monospace;
                        font-size: 13px;
                        font-weight: bold;
                        border: 1px solid #A5D6A7;
                        width: fit-content;
                        margin-left: auto;
                        margin-top: 10px;
                        box-shadow: 0px 2px 5px rgba(0,0,0,0.1);
                        animation: fadeSlideUp 0.5s ease-out;
                    ">
                        <span>[ {titre_barre} ]</span>
                        <span>Nombre : {nb}</span>
                        <span>Moyenne : {formater_en_hms(moyenne_h)}</span>
                        <span>Somme : {formater_en_hms(somme_h)}</span>
                        <span>Min : {formater_en_hms(min_h)}</span>
                        <span>Max : {formater_en_hms(max_h)}</span>
                    </div>
                """, unsafe_allow_html=True)
        else:
            st.info("Le registre est vide.")
    else:
        st.info("💡 Aucune donnée en cache. Cliquez sur 'Synchronisation Complète' pour importer les données depuis les 5 feuilles Google Sheets.")

    # --- ACTUALISATION AUTOMATIQUE À L'OUVERTURE ---
    if "donnees_cloud_centralisees" not in st.session_state or not st.session_state["donnees_cloud_centralisees"]:
        with st.spinner("🔄 Actualisation automatique des données cloud..."):
            success, _ = importer_donnees_cloud(only_new=False)
            if success:
                st.toast("✅ Données cloud synchronisées automatiquement à l'ouverture de la page", icon="🔄")
                time.sleep(0.5)
                st.rerun()

# --- SYSTEME DE NAVIGATION ---
if st.session_state.authentifie:
    if st.session_state.user_role == "operateur":
        pg = st.navigation({
            "Menu Principal": [
                st.Page(page_operateur_dashboard, title="Mon Dashboard", icon="📊"),
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