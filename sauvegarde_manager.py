import json
import os
import glob
from datetime import datetime
import streamlit as st

class SauvegardeManager:
    def __init__(self):
        self.dossier_sauvegardes = "sauvegardes"
        self.fichier_last = f"{self.dossier_sauvegardes}/sauvegarde_last.json"
        self.fichier_users = f"{self.dossier_sauvegardes}/users.json"
        self.creer_dossier()

    def creer_dossier(self):
        """Crée le dossier de sauvegarde s'il n'existe pas"""
        if not os.path.exists(self.dossier_sauvegardes):
            os.makedirs(self.dossier_sauvegardes)

    def sauvegarder_donnees(self, utilisateur, type_evenement):
        """Sauvegarde toutes les données de l'application"""
        try:
            # Récupérer toutes les données de session
            donnees = {
                "timestamp": datetime.now().isoformat(),
                "utilisateur": utilisateur,
                "type_evenement": type_evenement,
                "agents": st.session_state.get("agents", []),
                "planning": st.session_state.get("planning", {}),
                "heures": st.session_state.get("heures", {}),
                "donnees_cloud_centralisees": st.session_state.get("donnees_cloud_centralisees", []),
                "taches_operateur": st.session_state.get("taches_operateur", {}),
                "taches_en_cours": st.session_state.get("taches_en_cours", []),
                "couleurs": st.session_state.get("couleurs", {}),
                "task_id_counter": st.session_state.get("task_id_counter", 0)
            }
            
            # Sauvegarde automatique (dernière sauvegarde)
            with open(self.fichier_last, "w", encoding="utf-8") as f:
                json.dump(donnees, f, ensure_ascii=False, indent=4)
            
            # Sauvegarde historique avec horodatage
            horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
            nom_fichier = f"{self.dossier_sauvegardes}/sauvegarde_{type_evenement}_{horodatage}.json"
            
            with open(nom_fichier, "w", encoding="utf-8") as f:
                json.dump(donnees, f, ensure_ascii=False, indent=4)
            
            return True, nom_fichier
        except Exception as e:
            return False, str(e)

    def charger_derniere_sauvegarde(self):
        """Charge la dernière sauvegarde"""
        try:
            if not os.path.exists(self.fichier_last):
                # Chercher la sauvegarde la plus récente
                fichiers = glob.glob(f"{self.dossier_sauvegardes}/sauvegarde_*.json")
                if not fichiers:
                    return False
                dernier_fichier = max(fichiers, key=os.path.getmtime)
            else:
                dernier_fichier = self.fichier_last
            
            with open(dernier_fichier, "r", encoding="utf-8") as f:
                donnees = json.load(f)
                
            # Restaurer les données dans session_state
            st.session_state.agents = donnees.get("agents", [])
            st.session_state.planning = donnees.get("planning", {})
            st.session_state.heures = donnees.get("heures", {})
            st.session_state.donnees_cloud_centralisees = donnees.get("donnees_cloud_centralisees", [])
            st.session_state.taches_operateur = donnees.get("taches_operateur", {})
            st.session_state.taches_en_cours = donnees.get("taches_en_cours", [])
            st.session_state.couleurs = donnees.get("couleurs", {
                "Travail": "#2E7D32", 
                "OFF": "#757575", 
                "Congé": "#8D6E63", 
                "Maladie": "#C62828", 
                "Formation": "#1565C0"
            })
            st.session_state.task_id_counter = donnees.get("task_id_counter", 0)
            
            return True
        except Exception as e:
            return False

    def sauvegarder_utilisateurs(self, users):
        """Sauvegarde la liste des utilisateurs"""
        try:
            with open(self.fichier_users, "w", encoding="utf-8") as f:
                json.dump(users, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            return False

    def charger_utilisateurs(self):
        """Charge la liste des utilisateurs"""
        try:
            if os.path.exists(self.fichier_users):
                with open(self.fichier_users, "r", encoding="utf-8") as f:
                    return json.load(f)
            return {}
        except Exception as e:
            return {}

    def sauvegarder_etat_connexion(self, utilisateur, authentifie, role="operateur"):
        """Sauvegarde l'état de connexion"""
        try:
            fichier_session = f"{self.dossier_sauvegardes}/session_state.json"
            with open(fichier_session, "w", encoding="utf-8") as f:
                json.dump({
                    "user_actif": utilisateur,
                    "authentifie": authentifie,
                    "role": role,
                    "timestamp": datetime.now().isoformat()
                }, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            return False

    def charger_etat_connexion(self):
        """Charge l'état de connexion"""
        try:
            fichier_session = f"{self.dossier_sauvegardes}/session_state.json"
            if os.path.exists(fichier_session):
                with open(fichier_session, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return (
                        data.get("user_actif", ""),
                        data.get("authentifie", False),
                        data.get("role", "operateur")
                    )
            return "", False, "operateur"
        except Exception as e:
            return "", False, "operateur"

    def supprimer_anciennes_sauvegardes(self, nombre_a_garder=10):
        """Supprime les anciennes sauvegardes pour garder seulement les X plus récentes"""
        try:
            fichiers = glob.glob(f"{self.dossier_sauvegardes}/sauvegarde_*.json")
            if len(fichiers) > nombre_a_garder:
                # Trier par date de modification
                fichiers.sort(key=os.path.getmtime)
                # Supprimer les plus anciens
                for fichier in fichiers[:-nombre_a_garder]:
                    os.remove(fichier)
            return True
        except Exception as e:
            return False

# Instance globale du gestionnaire de sauvegarde
gestionnaire_sauvegarde = SauvegardeManager()