# Manuels Škoda — sauvegarde locale + PDF

Ce projet permet de **récupérer un manuel Škoda en local**, de le **parcourir hors ligne** (sommaire + recherche), et de **l’exporter en PDF complet**.

Chaque modèle de véhicule est sauvegardé dans `manuals/{modèle}/` (ex. `manuals/elroq/`, `manuals/octavia/`).

---

## Sommaire

1. [Usage](#usage)
2. [Détails techniques](#détails-techniques)

---

## Usage

### Usages typiques

- **Sauvegarder** un manuel indépendamment du site officiel
- **Exporter un PDF complet** (sommaire cliquable) pour archivage/partage

### Prérequis

- Python **3.10+**
- Playwright + Chromium
- Un serveur HTTP local (ex. **WAMP**) pour ouvrir le viewer

### Installation (une fois)

Dans un terminal à la racine du projet :

```powershell
pip install playwright
playwright install chromium
python setup_local_env.py
```

### Récupérer un manuel en local (scraping)

1. Démarrer WAMP (Apache)
2. Ouvrir `http://localhost/applis/scrap_manuel_skoda/viewer/`
3. Onglet **Scraper un manuel** → **Ouvrir le navigateur de scraping**
4. Sur le portail Škoda : choisir **VIN** ou **modèle/année + langue**, puis ouvrir le manuel
5. Dans la page du manuel (`…/show/…`) : cliquer **Lancer le scraping**

Le manuel est sauvegardé dans `manuals/{slug}/`.

### Parcourir en local

1. Ouvrir `http://localhost/applis/scrap_manuel_skoda/viewer/`
2. Onglet **Consulter un manuel** → choisir le modèle

### Exporter en PDF

- Depuis le viewer : bouton **Exporter en PDF** (génère `manuals/{slug}/manual.pdf`)
- Ou en ligne de commande (plus direct) :

```powershell
python build_manual_pdf.py --manual <slug>
```

---

## Détails techniques

Le README est volontairement court pour permettre une prise en main rapide.
Pour l’architecture, les scripts, la structure des fichiers et les détails API, voir :

- [`TECHNICAL.md`](TECHNICAL.md)
