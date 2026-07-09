# Détails techniques — Scrap manuel Škoda

Ce document regroupe les informations techniques (architecture, API, structure des fichiers, scripts, configuration).
Le guide “débutant” est dans [`README.md`](README.md).

---

## Site scrapé

| Élément | URL / détail |
|--------|----------------|
| Portail d'entrée | https://www.skoda.fr/apps/manuals |
| Manuel digital | https://digital-manual.skoda-auto.com |
| API contenu | `https://digital-manual.skoda-auto.com/api/vw-topic/V1/topic?key=…` |
| Médias | `https://digital-manual.skoda-auto.com/default/public/media?…` |
| Sélection véhicule | Au choix : **VIN** *ou* **modèle + date de sortie** (selon écrans du portail) |
| Langue | Français (`fr_FR`) (adaptable) |

Sur le portail Škoda, on peut accéder au manuel de deux façons :
- en saisissant un **VIN** (manuel exact pour le véhicule) ;
- ou en choisissant un **modèle** (et parfois une **date de sortie / année**) + la **langue**.

Lors du scraping, **vous** faites cette sélection dans Chromium ; le script attend ensuite l'ouverture du manuel digital (`…/show/…`) pour démarrer le téléchargement complet.

---

## Méthode de scraping (principe)

Le site ne livre pas le contenu dans le HTML initial : tout passe par des **appels API JSON**. Le scraping ne « parse » donc pas le DOM page par page, il **appelle la même API** que le site officiel.

### Étapes

```
Portail Škoda (vous : cookies, VIN ou modèle, ouverture du manuel)
        ↓
URL digital-manual …/show/…  →  modal « Lancer le scraping »
        ↓
API topic racine  →  arborescence complète (champ "trees")
        ↓
Pour chaque chapitre :
  API vw-topic  →  bodyHtml + métadonnées
  Téléchargement des images référencées
  Réécriture des liens internes (topiclink → #topic/{id})
        ↓
Fichiers locaux + manifest.json + search_index.json
```

### Pourquoi Playwright ?

- Le portail `skoda.fr/apps/manuals` est une SPA (React/MUI) : cookies OneTrust, formulaire VIN, sélecteur de langue.
- Une fois authentifié, Playwright réutilise la **session du navigateur** pour appeler l'API (images protégées, cookies).
- `requests` seul ne suffit pas pour cette phase d'onboarding.

### Ce qui est ignoré

- Les topics de type `tree` (nœuds purement structurels sans contenu HTML).
- Le tracking, les pubs, les scripts tiers (non téléchargés).

---

## Structure des fichiers

```
scrap_manuel_skoda/
├── manual_paths.py           # Chemins + registre manuals/index.json
├── scrape_manual_skoda.py    # Scraping complet (Playwright + API)
├── postprocess_manual.py     # Re-traitement des chapitres existants
├── build_manual_pdf.py       # Export PDF
├── build_search_index.py     # Régénère search_index.json
├── scan_broken_links.py      # Audit des liens topiclink cassés
├── manual_postprocess.py     # Bibliothèque partagée (HTML, liens, manifest, recherche)
├── viewer/                   # Viewer partagé (bibliothèque + lecteur)
│   ├── index.html            # Liste des manuels
│   ├── read.html             # Lecteur (?manual=…)
│   └── generate_pdf.php
│
└── manuals/
    ├── index.json            # Registre des sauvegardes
    └── <slug>/               # Exemple : elroq
        ├── meta.json
        ├── chapters/         # Fichiers HTML
        ├── media/            # Images
        ├── network_log/      # Captures JSON (debug)
        ├── manifest.json     # Arbre + liste plate des topics
        ├── search_index.json # Index plein texte
        ├── manual.pdf        # PDF généré
        └── print/            # HTML intermédiaire PDF
```

---

## Architecture (3 couches)

```
┌─────────────────────────────────────────────────────────┐
│  COUCHE 1 — Scraping (Python + Playwright)              │
│  scrape_manual_skoda.py                                 │
│  Navigation utilisateur → appels API → fichiers bruts    │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│  COUCHE 2 — Post-traitement (Python)                    │
│  manual_postprocess.py                                  │
│  Images locales, liens réécrits, manifest, recherche     │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│  COUCHE 3 — Viewer (HTML/CSS/JS statique)               │
│  viewer/read.html?manual=…                              │
│  Affichage, navigation hash, recherche, surlignage      │
└─────────────────────────────────────────────────────────┘
```

---

## Scripts utilitaires

| Commande | Usage |
|----------|--------|
| `python scan_broken_links.py` | Liste les liens `href="#"` restants (doit afficher 0) |
| `python build_search_index.py --manual <slug>` | Régénère uniquement l'index de recherche |
| `python build_manual_pdf.py --manual <slug>` | Export PDF avec sommaire |
| `python stop_scraper.py` | Arrête le scraper et libère le verrou navigateur |
| `python setup_local_env.py` | Configure Python/Playwright (WAMP) + tâche scraper visible |

---

## Configuration

Pendant le **scraping**, le VIN et la langue sont saisis dans Chromium (comme sur skoda.fr). Pour le **post-traitement** headless, le VIN peut venir de `SCRAPER_VIN`, du localStorage du profil scraper, ou d'un modal.

```python
MANUAL_LANG_LABEL = "Français"
LOCALE = "fr_FR"
```

Pour forcer un dossier de sortie : `--manual <slug>` ou `SCRAPER_MANUAL=<slug>`.

---

## Limites connues

- **Usage personnel / offline** : copie locale d'un contenu sous copyright Škoda.
- Les **vidéos** intégrées ne sont pas téléchargées (liens externes).
- Le scraper nécessite une **fenêtre Chromium visible** : naviguez vous-même sur le portail Škoda avant le téléchargement.
- Si Škoda change l'API ou le portail, les sélecteurs Playwright (`#onetrust-…`, `.MuiSelect-select`, etc.) devront être mis à jour.

