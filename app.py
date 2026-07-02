import streamlit as st
import pandas as pd
import calendar
import time
import json
import os
import glob
import requests
import io
from datetime import datetime, timedelta, time as datetime_time

# --- FONCTION DE TIMEOUT D'INACTIVITÉ ---
def check_inactivity():
    TIMEOUT_MINUTES = 5
    if "last_activity" not in st.session_state:
        st.session_state.last_activity = datetime.now()
    
    # Calculer le temps écoulé
    elapsed = datetime.now() - st.session_state.last_activity
    if elapsed.total_seconds() > (TIMEOUT_MINUTES * 60):
        # Déconnexion
        st.session_state.authentifie = False
        st.session_state.user_actif = ""
        st.warning("⏱️ Session expirée pour inactivité. Veuillez vous reconnecter.")
        st.rerun()
    else:
        # Mettre à jour l'activité
        st.session_state.last_activity = datetime.now()

# --- CONFIGURATION DE L'APPLICATION ---
st.set_page_config(page_title="Qwanteos-Setup Admin", layout="wide", page_icon="💼")



# --- AJOUT D'UN ARRIÈRE-PLAN PROFESSIONNEL ---
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
    }
    
    /* Style du texte pour lisibilité sur fond sombre */
    h1, h2, h3, p, div { color: #e2e8f0 !important; }
    
    </style>
""", unsafe_allow_html=True)
st.markdown("""
    <style>
    .main .block-container {padding-top: 1rem; padding-left: 1rem; padding-right: 1rem;}
    div[data-testid="stDataFrame"] td {padding: 6px 10px !important; font-size: 13px !important;}
    div[data-testid="stDataFrame"] th {padding: 6px 10px !important; font-size: 13px !important;}
    
    .welcome-container {
        text-align: center;
        margin-top: 5%;
        padding: 40px;
        background-color: #1E1E1E;
        border-radius: 15px;
        border: 2px solid #2E7D32;
        box-shadow: 0px 4px 15px rgba(0, 0, 0, 0.5);
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
    </style>
""", unsafe_allow_html=True)


# --- LOGIQUE DE PERSISTANCE DE SESSION & SAUVEGARDE ---
SESSION_FILE = "sauvegardes/session_state.json"

def sauvegarder_etat_connexion(utilisateur, authentifie):
    try:
        if not os.path.exists("sauvegardes"):
            os.makedirs("sauvegardes")
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump({"user_actif": utilisateur, "authentifie": authentifie}, f)
    except Exception:
        pass

def charger_etat_connexion():
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("user_actif", ""), data.get("authentifie", False)
        except Exception:
            return "", False
    return "", False

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
        nom_fichier = f"sauvegardes/sauvegarde_{utilisateur}_{type_evenement}_{horodatage}.json"
        
        with open(nom_fichier, "w", encoding="utf-8") as f:
            json.dump(donnees, f, ensure_ascii=False, indent=4)
            
        nom_fichier_fixe = f"sauvegardes/sauvegarde_{utilisateur}_last.json"
        with open(nom_fichier_fixe, "w", encoding="utf-8") as f:
            json.dump(donnees, f, ensure_ascii=False, indent=4)
            
        return True, nom_fichier
    except Exception as e:
        return False, str(e)


def charger_derniere_sauvegarde(utilisateur):
    try:
        if not os.path.exists("sauvegardes"):
            return False
        
        fichier_last = f"sauvegardes/sauvegarde_{utilisateur}_last.json"
        if os.path.exists(fichier_last):
            dernier_fichier = fichier_last
        else:
            fichiers = glob.glob(f"sauvegardes/sauvegarde_{utilisateur}_*.json")
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
user_stocke, auth_stocke = charger_etat_connexion()

if "authentifie" not in st.session_state:
    st.session_state.authentifie = auth_stocke

if "user_actif" not in st.session_state:
    st.session_state.user_actif = user_stocke

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

if st.session_state.authentifie and st.session_state.user_actif and not st.session_state.planning and not st.session_state.heures:
    charger_derniere_sauvegarde(st.session_state.user_actif)


# --- INTERFACE DE CONNEXION ---
if not st.session_state.authentifie:
    st.markdown("""
        <div class="welcome-container">
            <div class="welcome-title">💼 QWANTEOS-SETUP ADMIN</div>
            <div class="welcome-subtitle">Système Sécurisé de Gestion & Pointage</div>
            <hr style="border-color: #2E7D32; width: 60%; margin: auto; margin-bottom: 20px;">
            <div class="welcome-credit">Created by Toky — Team Lead Setup Qwanteos</div>
        </div>
    """, unsafe_allow_html=True)
    
    st.write("")
    
    col_space, col_form, col_space2 = st.columns([4, 4, 4])
    with col_form:
        with st.form("form_login"):
            st.markdown("### 🔐 Connexion Requise")
            identifiant = st.text_input("Nom d'utilisateur", value="Toky")
            mot_de_passe = st.text_input("Mot de passe", type="password")
            btn_login = st.form_submit_button("🚀 Se connecter et Restaurer", use_container_width=True)
            
            if btn_login:
                if identifiant == "Toky" and mot_de_passe == "Setup2026":
                    st.session_state.authentifie = True
                    st.session_state.user_actif = identifiant
                    
                    sauvegarder_etat_connexion(identifiant, True)
                    restaure = charger_derniere_sauvegarde(identifiant)
                    executer_sauvegarde_auto("login", identifiant)
                    
                    with st.spinner("Synchronisation des bases de données..."):
                        time.sleep(1.2)
                        
                    if restaure:
                        st.toast("📊 Données restaurées avec succès !", icon="🔄")
                    else:
                        st.toast("⚠️ Aucune sauvegarde trouvée. Chargement du profil neuf.", icon="🆕")
                        
                    st.rerun()
                else:
                    st.error("❌ Identifiant ou mot de passe incorrect.")
    st.stop()


# --- BARRE LATÉRALE GLOBALE ---
with st.sidebar:
    st.markdown(f"**👤 Connecté :** `{st.session_state.user_actif}`")
    
    if st.button("💾 Sauvegarder les données", use_container_width=True):
        succes, _ = executer_sauvegarde_auto("manuel", st.session_state.user_actif)
        if succes: st.toast("Données sécurisées localement !", icon="💾")
        
    st.markdown("---")
    st.markdown("### ⚠️ Zone Critique")
    
    confirmer_reset = st.checkbox("Autoriser la remise à zéro")
    if st.button("🚨 Réinitialiser l'interface", type="primary", use_container_width=True, disabled=not confirmer_reset):
        st.session_state.agents = list(AGENTS_PAR_DEFAUT)
        st.session_state.planning = {}
        st.session_state.heures = {}
        st.session_state.donnees_cloud_centralisees = []
        
        executer_sauvegarde_auto("reset", st.session_state.user_actif)
        st.toast("Grilles et compteur réinitialisés !", icon="💥")
        time.sleep(0.5)
        st.rerun()
        
    st.markdown("---")
    if st.button("🚪 Déconnexion", type="secondary", use_container_width=True):
        executer_sauvegarde_auto("logout", st.session_state.user_actif)
        sauvegarder_etat_connexion("", False)
        st.session_state.authentifie = False
        st.session_state.user_actif = ""
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


# --- PAGE 1 : GESTION DES AGENTS ---
def page_gestion_agents():
    check_inactivity()
    st.title("👥 Gestion du Personnel")
    col_kpi, _ = st.columns([1, 3])
    col_kpi.metric("Effectif Total", len(st.session_state.agents))
    st.markdown("---")

    st.sidebar.header("📋 Actions RH")
    with st.sidebar.form("add_agent", clear_on_submit=True):
        st.markdown("### Ajouter un Agent")
        nom = st.text_input("Nom complet")
        poste = st.text_input("Poste")
        if st.form_submit_button("Ajouter l'agent") and nom.strip() and poste.strip():
            st.session_state.agents.append({"Nom": nom.strip(), "Poste": poste.strip()})
            executer_sauvegarde_auto("update_rh", st.session_state.user_actif)
            st.rerun()

    if st.session_state.agents:
        df = pd.DataFrame(st.session_state.agents)
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        st.sidebar.markdown("---")
        nom_suppr = st.sidebar.selectbox("Sélectionner l'agent", [a["Nom"] for a in st.session_state.agents])
        if st.sidebar.button("Supprimer définitivement", type="primary"):
            st.session_state.agents = [a for a in st.session_state.agents if a["Nom"] != nom_suppr]
            executer_sauvegarde_auto("update_rh", st.session_state.user_actif)
            st.rerun()


# --- PAGE 2 : PLANNING ---
def page_planning():
    check_inactivity
    st.title("🗓️ Planning Hebdomadaire")
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
            st.rerun()


# --- PAGE 3 : SUIVI DES HEURES ---
def page_suivi_heures():
    check_inactivity()
    st.title("⏱️ Suivi des Heures de Production")
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
    st.markdown("Cette interface extrait et centralise les données de production depuis vos 5 feuilles de suivi.")

    LIENS_FEUILLES = {
        "Toky": "https://docs.google.com/spreadsheets/d/e/2PACX-1vQU6MvzrX1xe2QrMg8uhBiUQ-sxz8X6F04f_3smdWifA7wXh4fKslIvPgfBJ4gQnWLvxv2iKRPP6Gyq/pub?gid=0&single=true&output=csv",
        "Ny Haingo": "https://docs.google.com/spreadsheets/d/e/2PACX-1vQU6MvzrX1xe2QrMg8uhBiUQ-sxz8X6F04f_3smdWifA7wXh4fKslIvPgfBJ4gQnWLvxv2iKRPP6Gyq/pub?gid=353808453&single=true&output=csv",
        "Zara": "https://docs.google.com/spreadsheets/d/e/2PACX-1vQU6MvzrX1xe2QrMg8uhBiUQ-sxz8X6F04f_3smdWifA7wXh4fKslIvPgfBJ4gQnWLvxv2iKRPP6Gyq/pub?gid=230349377&single=true&output=csv",
        "Isaia": "https://docs.google.com/spreadsheets/d/e/2PACX-1vQU6MvzrX1xe2QrMg8uhBiUQ-sxz8X6F04f_3smdWifA7wXh4fKslIvPgfBJ4gQnWLvxv2iKRPP6Gyq/pub?gid=1868581922&single=true&output=csv",
        "Vanja": "https://docs.google.com/spreadsheets/d/e/2PACX-1vQU6MvzrX1xe2QrMg8uhBiUQ-sxz8X6F04f_3smdWifA7wXh4fKslIvPgfBJ4gQnWLvxv2iKRPP6Gyq/pub?gid=1825784313&single=true&output=csv"
    }

    st.sidebar.header("📅 Filtres de Dates Précis")
    date_debut = st.sidebar.date_input("Date de début", value=None)
    date_fin = st.sidebar.date_input("Date de fin", value=None)

    if st.button("🔄 Actualiser et Importer les nouvelles données", type="primary", use_container_width=True):
        try:
            with st.spinner("Téléchargement instantané via CDN Google Web Publish (Sécurisé)..."):
                liste_dfs = []
                
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
                        
                        liste_dfs.append(df_extrait)
                    except Exception as ex_single:
                        st.warning(f"Saut de l'onglet '{nom_feuille}' suite à une erreur : {str(ex_single)}")
                        continue

                if not liste_dfs:
                    st.error("❌ Aucune feuille n'a pu être récupérée. Vérifiez l'état de la publication web.")
                    return

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

                st.session_state["donnees_cloud_centralisees"] = df_global.to_dict(orient="records")
                executer_sauvegarde_auto("import_multi_sheets", st.session_state.user_actif)
                st.success(f"✔️ Synchronisation réussie : {len(df_global)} lignes de production agrégées et mémorisées !")
                st.rerun()

        except Exception as e:
            st.error(f"Une exception critique est survenue lors de l'intégration : {str(e)}")

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
        st.info("💡 Aucune donnée en cache. Veuillez cliquer sur le bouton ci-dessus pour lancer la première importation de vos 5 feuilles.")


# --- SYSTEME DE NAVIGATION ---
pg = st.navigation({
    "Menu Principal": [
        st.Page(page_gestion_agents, title="Gestion du Personnel", icon="👥"),
        st.Page(page_planning, title="Planning par Semaine", icon="🗓️"),
        st.Page(page_suivi_heures, title="Suivi des Heures", icon="⏱️"),
        st.Page(page_synchronisation_cloud, title="Synchronisation Cloud", icon="🌐"),
    ]
})

pg.run()