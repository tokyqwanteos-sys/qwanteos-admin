import json
import os
import glob
from datetime import datetime

class SauvegardeManager:
    """
    Gestionnaire de sauvegarde manuelle (exports JSON ponctuels).
    - Les sauvegardes automatiques sont désactivées.
    - L'état de connexion n'est pas persisté.
    - Seul l'export manuel via bouton est disponible.
    """

    def __init__(self):
        self.dossier_sauvegardes = "sauvegardes"
        self.creer_dossier()

    def creer_dossier(self):
        """Crée le dossier de sauvegarde s'il n'existe pas."""
        if not os.path.exists(self.dossier_sauvegardes):
            os.makedirs(self.dossier_sauvegardes)

    def sauvegarder_donnees_manuelles(self, utilisateur, donnees):
        """
        Exporte les données en JSON horodaté (uniquement via bouton manuel).
        Retourne (succès, nom_fichier ou message d'erreur).
        """
        try:
            horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
            nom_fichier = f"{self.dossier_sauvegardes}/sauvegarde_manuelle_{horodatage}.json"
            with open(nom_fichier, "w", encoding="utf-8") as f:
                json.dump(donnees, f, ensure_ascii=False, indent=4)
            return True, nom_fichier
        except Exception as e:
            return False, str(e)

    def supprimer_anciennes_sauvegardes(self, nombre_a_garder=10):
        """
        Supprime les sauvegardes manuelles les plus anciennes,
        en ne gardant que les `nombre_a_garder` plus récentes.
        """
        try:
            fichiers = glob.glob(f"{self.dossier_sauvegardes}/sauvegarde_manuelle_*.json")
            if len(fichiers) > nombre_a_garder:
                fichiers.sort(key=os.path.getmtime)
                for fichier in fichiers[:-nombre_a_garder]:
                    os.remove(fichier)
            return True
        except Exception:
            return False

# Instance globale (utilisée par app.py pour la sauvegarde manuelle)
gestionnaire_sauvegarde = SauvegardeManager()
