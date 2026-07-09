# Manuels Škoda — versions locales

Ce projet télécharge les **manuels d'utilisation numériques** Škoda depuis le site officiel, les transforme en fichiers HTML/images consultables **sans connexion**, et fournit un **viewer web** (sommaire, navigation, recherche plein texte, export PDF).

Chaque modèle de véhicule est sauvegardé dans `manuals/{modèle}/` (ex. `manuals/elroq/`, `manuals/octavia/`).

---

## Sommaire

1. [Usage](#usage)
2. [But du projet](#but-du-projet)
3. [Site scrapé](#site-scrapé)
4. [Méthode de scraping](#méthode-de-scraping)
5. [Créer / mettre à jour la version locale](#créer--mettre-à-jour-la-version-locale)
6. [Consulter la version locale](#consulter-la-version-locale)
7. [Structure des fichiers](#structure-des-fichiers)
8. [Documentation technique](#documentation-technique)
9. [Scripts utilitaires](#scripts-utilitaires)

---

## Usage

### Usages typiques

- **Consulter hors ligne** le manuel (garage, voiture, zones sans réseau).
- **Rechercher rapidement** (plein texte) dans tout le manuel.
- **Exporter un PDF complet** (avec sommaire cliquable) pour archivage/partage.

### Prérequis

- **Python 3.10+**
- **Playwright** + navigateur Chromium
- **WAMP** (ou un serveur HTTP local) pour utiliser le viewer

### Installation (une fois)

```powershell
pip install playwright
playwright install chromium
python setup_local_env.py
```

### Récupérer un manuel en local (scraping)

1. Ouvrir `http://localhost/applis/scrap_manuel_skoda/viewer/`
2. Onglet **Scraper un manuel** → **Ouvrir le navigateur de scraping**
3. Sur le portail Škoda : **VIN ou modèle/année + langue**, puis ouvrir le manuel
4. Dans la page du manuel (`…/show/…`) : cliquer **Lancer le scraping**

Le manuel est sauvegardé dans `manuals/{slug}/`.

### Parcourir en local

- Ouvrir le viewer : `http://localhost/applis/scrap_manuel_skoda/viewer/`
- Onglet **Consulter un manuel** → choisir le modèle

### Exporter en PDF

- Dans le lecteur : bouton **Exporter en PDF** (génère `manuals/{slug}/manual.pdf`)
- Ou en ligne de commande :

```powershell
python build_manual_pdf.py --manual <slug>
```

---

## But du projet

Le manuel Škoda en ligne est une application web (SPA) : le contenu n'est pas accessible avec un simple téléchargement de page. Ce projet :

- **récupère** les ~709 chapitres via l'API JSON du manuel digital ;
- **télécharge** les images localement ;
- **réécrit** les liens internes pour qu'ils fonctionnent hors ligne ;
- **indexe** tout le texte pour une recherche plein texte ;
- **affiche** le tout dans un viewer statique servi par WAMP (ou tout serveur HTTP local).

Usages typiques : sauvegarder le manuel sans dépendre du site Škoda, le consulter hors ligne, l'ajouter comme source dans NotebookLM pour l'interroger en langage naturel.

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

## Méthode de scraping

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

## Créer / mettre à jour la version locale

### Prérequis

```powershell
pip install playwright
playwright install chromium
```

Python 3.10+ recommandé. WAMP (ou Apache/Nginx) pour servir le viewer.

### Scraping complet (première fois ou re-scrape)

**Configuration initiale (une fois)** — Python/Playwright pour WAMP + navigateur visible depuis le viewer :

```powershell
python setup_local_env.py
# ou double-clic : setup_local_env.bat
```

**Via l'interface web** (recommandé) :

1. Ouvrir **http://localhost/applis/scrap_manuel_skoda/viewer/**
2. Onglet **Scraper un manuel** → **Ouvrir le navigateur de scraping**
3. Dans la fenêtre Chromium : saisir le VIN ou choisir un modèle (comme sur skoda.fr)
4. Quand le manuel s'affiche (`…/show/…`), cliquer **Lancer le scraping** dans le navigateur

**En ligne de commande :**

```powershell
cd c:\wamp64\www\applis\scrap_manuel_skoda
python scrape_manual_skoda.py
```

Déroulement :

1. Chromium s'ouvre sur le portail Škoda (`headless=False`).
2. **Vous** acceptez les cookies, saisissez le VIN ou sélectionnez un modèle, ouvrez le manuel.
3. Dès que l'URL contient `digital-manual.skoda-auto.com/…/show/…`, le modal **Lancer le scraping** apparaît.
4. Téléchargement des chapitres dans `manuals/{modèle}/`.

Variables d'environnement utiles :

| Variable | Effet |
|----------|--------|
| `SCRAPER_MANUAL=elroq` | Force le dossier de sauvegarde (sinon détecté depuis le manuel ouvert) |
| `SCRAPER_LIMIT=10` | Ne télécharge que les N premiers chapitres (test) |
| `SCRAPER_AUTO_START=1` | Clique automatiquement sur « Lancer le scraping » après 3 s |

Le VIN détermine le **modèle** via l'API Škoda ; la sauvegarde va dans `manuals/{slug}/` (ex. `elroq`). Un nouveau scrape du même modèle **écrase** la sauvegarde existante.

### Post-traitement seul (chapitres déjà téléchargés)

Utile après une modification du code de liens ou de recherche, sans re-scraper :

```powershell
python postprocess_manual.py --manual elroq
python postprocess_manual.py --manual elroq --links-only
python postprocess_manual.py --manual elroq --limit 10
```

Le post-traitement se ré-authentifie via Playwright (headless) pour retélécharger les images manquantes.

### Index de recherche seul

```powershell
python build_search_index.py --manual elroq
```

---

## Consulter la version locale

1. Démarrer WAMP (Apache).
2. Ouvrir dans le navigateur :

   **http://localhost/applis/scrap_manuel_skoda/viewer/**

Onglet **Consulter un manuel** pour la bibliothèque, ou directement :

   **http://localhost/applis/scrap_manuel_skoda/viewer/read.html?manual=elroq**

### Fonctions du viewer

| Fonction | Description |
|----------|-------------|
| **Sommaire** (colonne gauche) | Arborescence repliable, clic → `#topic/{id}` |
| **Fil d'Ariane** | Segments cliquables pour remonter dans la hiérarchie |
| **Recherche** | Plein texte sur tout le manuel ; suggestions de termes + pages ; surlignage jaune dans la page (disparaît quand on vide le champ) |
| **Précédent / Suivant** | Navigation linéaire dans l'ordre du sommaire |
| **Liens internes** | Liens du manuel ouvrent d'autres chapitres localement |

Le viewer est **100 % statique** (HTML + CSS + JS) : il charge `manifest.json`, `search_index.json` et les chapitres via `fetch()`.

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
│   ├── read.html             # Lecteur (?manual=elroq)
│   └── generate_pdf.php
│
└── manuals/
    ├── index.json            # Registre des sauvegardes
    └── elroq/                # Exemple : Škoda Elroq
        ├── meta.json         # VIN, modèle, dates
        ├── chapters/         # Fichiers HTML
        ├── media/            # Images
        ├── network_log/      # Captures JSON (debug)
        ├── manifest.json     # Arbre + liste plate des topics
        ├── search_index.json # Index plein texte
        ├── manual.pdf        # PDF généré
        └── print/              # HTML intermédiaire PDF
```

Chaque chapitre HTML commence par un commentaire `<!-- topicId: … -->` et un `<h1>` avec le titre.

---

## Documentation technique

Cette section décrit **comment le code est organisé**, pour quelqu'un qui connaît Python et le web de base mais découvre le projet.

### Vue d'ensemble : 3 couches

```
┌─────────────────────────────────────────────────────────┐
│  COUCHE 1 — Scraping (Python + Playwright)              │
│  scrape_manual_skoda.py                                 │
│  Authentification VIN → appels API → fichiers bruts     │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│  COUCHE 2 — Post-traitement (Python)                    │
│  manual_postprocess.py                                  │
│  Images locales, liens réécrits, manifest, index recherche│
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│  COUCHE 3 — Viewer (HTML/CSS/JS statique)               │
│  viewer/read.html?manual=…                              │
│  Affichage, navigation hash, recherche, surlignage      │
└─────────────────────────────────────────────────────────┘
```

---

### `scrape_manual_skoda.py` — le scraper

**Rôle :** orchestrer Playwright et produire tous les fichiers dans `manuals/{modèle}/`.

Fonctions clés :

| Fonction | Rôle |
|----------|------|
| `wait_for_manual_visible()` | Attend l'URL `digital-manual…/show/…` après navigation utilisateur |
| `detect_vehicle_from_manual_page()` | Détecte modèle / slug depuis la page ou l'API Škoda |
| `show_scraping_modal_and_wait()` | Modal « Lancer le scraping » dans le navigateur |
| `launch_scraper_browser()` | Contexte Chromium persistant (`.scraper_browser_data/`) |
| `accept_cookies()` / `fill_vin_form()` / `resolve_vin()` | Utilisés par `postprocess_manual.py` (auth headless pour images) |
| `get_chapter_tree()` | Appelle l'API topic racine, extrait le champ `trees` |
| `fetch_topic()` | GET `/api/vw-topic/V1/topic?key={topicId}` → JSON avec `bodyHtml` |
| `scrape_chapter()` | Pour un topic : récupère HTML, post-traite, sauvegarde en fichier |
| `scrape_all_chapters()` | Boucle sur la liste plate des chapitres |

**Identifiant d'un chapitre :** chaque page a un `topicId` du type `7368ed9e6e2597eaac14452562de6b9a_2_fr_FR` (hash + version + locale). C'est la clé primaire partout dans le projet.

**Arborescence :** l'API renvoie un arbre JSON (`trees`) avec des nœuds `{ label, linkTarget, children }`. `parse_topic_trees()` le transforme en :
- une **liste plate** (tous les chapitres feuilles, pour le scraping) ;
- un **arbre nested** (pour le sommaire du viewer).

---

### `manual_postprocess.py` — la bibliothèque de traitement

Centralise tout ce qui touche au HTML et aux métadonnées. Importée par le scraper et le post-traitement.

#### Téléchargement des images — `process_html()`

1. Cherche les URLs `digital-manual.skoda-auto.com/.../media?...` dans le HTML.
2. Télécharge chaque image une seule fois (cache en mémoire).
3. Remplace l'URL distante par `../media/nom_fichier.png`.
4. Appelle `rewrite_topic_links()` pour les liens internes.
5. Active les `data-src` → `src` sur les `<img>` (lazy loading du site original).

#### Liens internes — `LinkResolver` + `rewrite_topic_links()`

Sur le site officiel, les liens entre chapitres sont des ancres `<a class="topiclink" href="#">` : le JavaScript du site résout dynamiquement la destination. Hors ligne, ça ne marche pas.

**Stratégie de résolution** (dans l'ordre) :

1. **Hint du tableau** — pour les pages Simply Clever (colonne centrale du `<tr>`).
2. **Hint de légende** — texte du `<dd>` parent (schémas véhicule).
3. **Hint du paragraphe** — texte avant le lien dans le `<p>`.
4. **Texte du lien** — libellé visible dans le `<span>`.
5. **Alias** — table `TITLE_ALIASES` (ex. « Phonebox » → « Phone box »).
6. **Correspondance floue** — inclusion de chaîne ou mots communs.

Quand un chapitre cible est trouvé, le lien devient :

```html
<a href="#topic/7fa443d30f6f84a40c368839b607bac0_3_fr_FR"
   data-topic-id="7fa443d30f6f84a40c368839b607bac0_3_fr_FR"
   class="local-topic-link …">
```

#### Manifest — `build_manifest()`

Produit `manifest.json` en croisant :
- l'arbre nested (`tree`) ;
- la liste plate des topics ;
- l'index des fichiers scrapés (`scraped_index.json`).

Chaque topic du viewer reçoit : `topicId`, `title`, `file`, `path` (fil d'Ariane).

#### Recherche — `build_search_index()`

Pour chaque chapitre :
- extrait le texte visible (`html_to_plain_text()` : supprime balises, normalise) ;
- stocke `{ topicId, title, path, text }` ;
- collecte tous les mots ≥ 3 caractères dans `terms[]` (autocomplétion).

Résultat : `search_index.json` (~0,8 Mo, 709 pages, ~5000 termes).

---

### `postprocess_manual.py` — re-traitement sans re-scrape

Même logique de traitement HTML, mais lit les fichiers déjà présents dans `chapters/`.

Particularité : il relance Playwright en **headless** uniquement pour l'authentification VIN (nécessaire au téléchargement d'images).

L'arborescence est lue depuis `sommaire_tree.json`, `manifest.json` ou `network_log/` (capture du topic racine).

---

### Viewer — `viewer/`

Application **single-page** sans framework (vanilla JS).

#### Chargement initial — `init()`

```javascript
fetch("../manuals/{slug}/manifest.json")
fetch("../manuals/{slug}/search_index.json")
```

Construit :
- le sommaire (`renderTree()`) ;
- l'index fil d'Ariane (`buildPathIndex()` : chemin → topicId).

#### Navigation — hash URL

```
http://localhost/.../viewer/#topic/7368ed9e6e2597eaac14452562de6b9a_2_fr_FR
```

- `onHashChange()` → `openTopic(topicId)`
- `openTopic()` charge `../chapters/0004_Vue_d_ensemble….html` via `fetch()`, injecte le HTML dans `#content`
- `prepareChapterImages()` ajuste la taille des images (icônes 19×19, symboles, grandes images…)

#### Recherche — `onSearchInput()`

1. Normalise la requête (minuscules, espaces).
2. **`findTerms()`** — filtre `search_index.terms` (suggestions type « soleil », « pare-soleil »).
3. **`findPages()`** — cherche la requête dans `topic.text` et `topic.title`, score et extrait un snippet.
4. Affiche une liste déroulante ; clic → `openTopic()` + surlignage jaune (`<mark class="search-hit">`).
5. Vider le champ → `clearSearchHighlights()` retire les surlignages sans recharger.

#### Fil d'Ariane cliquable — `renderBreadcrumb()`

Chaque segment (sauf le dernier) est un bouton qui appelle `navigateToTopic()`. Pour les dossiers sans page propre, l'index pointe vers le premier chapitre enfant.

#### Fichiers CSS

| Fichier | Contenu |
|---------|---------|
| `style.css` | Layout (sidebar + contenu), recherche, fil d'Ariane, thème gris foncé |
| `manual-content.css` | Styles hérités du site Škoda : tableaux, symboles blancs, alertes, liens visités |

---

### Flux de données (résumé)

```
API Škoda                    Fichiers locaux              Viewer
─────────                    ───────────────              ──────
trees (JSON)        →        sommaire_tree.json    →      sidebar #tree
bodyHtml (JSON)     →        chapters/*.html       →      #content (fetch)
media (binaire)     →        media/*               →      <img src="../media/…">
(flat + tree +      →        manifest.json         →      navigation, breadcrumb
 scraped_index)
(chapters text)     →        search_index.json     →      barre de recherche
```

---

## Scripts utilitaires

| Commande | Usage |
|----------|--------|
| `python scan_broken_links.py` | Liste les liens `href="#"` restants (doit afficher 0) |
| `python build_search_index.py` | Régénère uniquement l'index de recherche |
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
