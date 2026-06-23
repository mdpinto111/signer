# PDF Signer

Visually sign and annotate PDF documents — click to place a signature image or add text anywhere on any page. Available as a **desktop app** (Tkinter) and a **web app** (FastAPI + vanilla JS).

---

## Features

- **Visual placement** — signature and text follow your cursor before you place them
- **Drag to resize** — draw a rectangle on the PDF to set the signature size on the fly
- **Hebrew / RTL support** — Hebrew and Arabic text placed with correct right-to-left alignment
- **Transparent signature** — near-white pixels are automatically stripped so the signature blends cleanly
- **Multi-page PDF** — all pages rendered in a continuous scroll view
- **Any image format** — PNG, JPG, BMP, TIFF supported as signature
- **Undo / Remove** — undo the last placement or delete any specific item

---

## Option 1 — Desktop app

### Requirements

```
Python 3.10+
pymupdf
Pillow
```

```bash
pip install pymupdf Pillow
```

### Run

```bash
python app.py
```

The app auto-loads the first PDF and PNG found in the same folder.

### How to use

**Placing a signature**
1. Select **Place Signature** in the toolbar
2. Click **Browse signature file...** in the sidebar to load an image
3. Set the size with the **W / H** spinboxes, or **drag on the PDF** to draw the area directly
4. Click (or drag) on the PDF page where you want the signature

**Adding text**
1. Select **Add Text** in the toolbar
2. Type your text in the **Text to insert** field in the sidebar (Hebrew supported)
3. Adjust font size and color
4. Click on the PDF — the text preview follows your cursor in real time

**Saving**
Click **Save PDF** → choose output location → done.

**Tips**
- **Undo** removes the last placement; **Remove selected** deletes a specific item from the list
- Type a page number in the **Go to page** field at the bottom to jump to that page
- Signature background is auto-stripped — no need to pre-edit your PNG

---

## Option 2 — Web app

A browser-based version with the same features, built with FastAPI (backend) and vanilla JS (frontend). No installation needed for end users — just open the URL.

### Requirements

```
Python 3.10+
```

```bash
cd web
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### Run locally

```bash
cd web
python main.py
```

Then open **http://localhost:8000** in your browser.

### How to use (web)

**Load a PDF**
- Click **Open PDF** in the top bar, or drag & drop a PDF onto the canvas

**Placing a signature**
1. Click **Signature** mode (left sidebar)
2. Click **Browse image...** to load your signature file, or drag & drop an image onto the canvas
3. Set **W / H** or drag on the PDF to draw the area
4. Click or drag on the PDF to place the signature

**Adding text**
1. Click **Text** mode (left sidebar)
2. Type your text in the textarea (Hebrew and Latin supported)
3. Adjust font size and color
4. Click on the PDF — the text follows your cursor live

**Saving**
Click **Save PDF** in the top bar → the signed PDF downloads automatically.

**Tips**
- All pages are shown in a continuous scroll — no page flipping
- The × button on each placement in the list removes it individually
- Undo removes the last placement
- Drag & drop works for both PDFs and signature images

### Deploy with Docker

```bash
cd web
docker-compose up --build
```

The app will be available on port **8000**.

To deploy on a server (VPS, cloud), just expose port 8000 or put a reverse proxy (nginx, Caddy) in front of it.

---

## Comment ça fonctionne techniquement (version web)

### Architecture générale

L'application est découpée en deux parties :

```
Navigateur (Frontend)          Serveur (Backend)
─────────────────────          ─────────────────
HTML + CSS + JS          ←→    FastAPI (Python)
Canvas API                     PyMuPDF (fitz)
Fetch API                      Pillow
```

Le frontend est du HTML/CSS/JS pur (pas de framework). Le backend est un serveur Python FastAPI qui fait tout le traitement PDF.

---

### Ce qui se passe étape par étape

**1. Chargement du PDF**

L'utilisateur sélectionne un PDF. Le navigateur l'envoie en `multipart/form-data` à `POST /api/upload-pdf`.

Le serveur :
- Génère un `session_id` (UUID) unique pour cet utilisateur
- Ouvre le PDF avec PyMuPDF
- Rend chaque page en image PNG (zoom ×1.5 pour la qualité)
- Sauvegarde les PNG et le PDF original dans un dossier temporaire (`/tmp/pdf_signer/{session_id}/`)
- Retourne les dimensions de chaque page en JSON

Le frontend affiche ensuite les pages dans un `<canvas>` HTML en les empilant verticalement.

**2. Chargement de la signature**

L'image est envoyée à `POST /api/upload-signature`. Le serveur :
- Convertit l'image en RGBA
- Rend transparent tous les pixels quasi-blancs (R>220, G>220, B>220)
- Retourne directement le PNG modifié

Le frontend affiche la prévisualisation dans la sidebar.

**3. Placement interactif**

Tout le placement visuel se fait côté navigateur dans un `<canvas>` via la Canvas 2D API :
- `mousemove` → dessine le "fantôme" (signature ou texte) qui suit le curseur
- `mousedown` + `mousemove` → dessine le rectangle de sélection orange (drag-to-resize)
- `mouseup` → enregistre le placement en mémoire (liste JS)

Aucun appel réseau n'est fait pendant cette phase — tout est local au navigateur.

**4. Sauvegarde**

Quand l'utilisateur clique sur "Save PDF", le frontend envoie à `POST /api/sign` :
```json
{
  "session_id": "...",
  "placements": [
    {"type": "signature", "page": 0, "cx": 120, "cy": 450, "w": 150, "h": 60},
    {"type": "text", "page": 1, "cx": 300, "cy": 600, "text": "שלום", "size": 14, "color": "#000000"}
  ]
}
```

Le serveur :
- Rouvre le PDF original avec PyMuPDF
- Pour chaque placement :
  - **Signature** → `page.insert_image(rect, stream=png_bytes)`
  - **Texte hébreu (RTL)** → `page.insert_htmlbox(...)` avec `text-align:right`
  - **Texte latin (LTR)** → `page.insert_text(point, ...)` avec Arial
- Retourne le PDF modifié en streaming

Le navigateur reçoit le PDF comme un `Blob` et déclenche automatiquement le téléchargement.

---

### Pourquoi deux méthodes pour le texte ?

- **Texte latin** : `insert_text` de PyMuPDF donne un positionnement pixel-parfait
- **Texte hébreu (RTL)** : PyMuPDF ne supporte pas nativement le sens droite-gauche dans `insert_text`, donc on utilise `insert_htmlbox` qui s'appuie sur le moteur de rendu HTML intégré de MuPDF, lequel gère le BiDi (algorithme de bidirectionnalité Unicode)

---

### Sessions et données temporaires

Chaque visiteur obtient un `session_id` UUID. Les fichiers sont stockés dans `/tmp/pdf_signer/{session_id}/` :
```
source.pdf       PDF original
page_0.png       Page 1 rendue
page_1.png       Page 2 rendue
...
signature.png    Signature traitée (fond transparent)
```

Ces fichiers ne sont pas supprimés automatiquement — sur un déploiement en production il faudrait ajouter une tâche de nettoyage périodique.

---

## Déploiement sur le web

### Option A — VPS (DigitalOcean, OVH, Hetzner…)

1. Louer un serveur Linux (Ubuntu 22.04 recommandé)
2. Installer Docker :
```bash
curl -fsSL https://get.docker.com | sh
```
3. Copier les fichiers du dossier `web/` sur le serveur :
```bash
scp -r web/ user@ton-serveur:/opt/pdf-signer/
```
4. Lancer l'application :
```bash
cd /opt/pdf-signer
docker-compose up -d --build
```
5. L'app tourne sur le port 8000. Pour la rendre accessible sur le port 80/443, installer Caddy :
```bash
apt install caddy
```
Et créer `/etc/caddy/Caddyfile` :
```
ton-domaine.com {
    reverse_proxy localhost:8000
}
```
Caddy gère automatiquement le certificat HTTPS (Let's Encrypt).

---

### Option B — Railway / Render (hébergement gratuit, zero config)

**Railway :**
1. Créer un compte sur [railway.app](https://railway.app)
2. "New Project" → "Deploy from GitHub repo"
3. Pointer vers le dossier `web/` (ou mettre le `Dockerfile` à la racine du repo)
4. Railway détecte le Dockerfile automatiquement et déploie
5. Assigner un domaine dans les settings

**Render :**
1. Créer un compte sur [render.com](https://render.com)
2. "New Web Service" → connecter le repo GitHub
3. Build command : `pip install -r requirements.txt`
4. Start command : `uvicorn main:app --host 0.0.0.0 --port 10000`
5. Environment : `Python 3.11`

---

### Option C — Fly.io

```bash
# Installer flyctl
curl -L https://fly.io/install.sh | sh

# Dans le dossier web/
cd web
fly launch        # configure automatiquement
fly deploy        # déploie
```

L'app sera accessible sur `https://ton-app.fly.dev`.

---

## File structure

```
app.py               Desktop app (Tkinter)
sign_pdf.py          CLI script — auto-places signature next to the word חתימה
sign.png             Default signature image (replace with your own)
README.md            This file

web/
├── main.py          FastAPI backend
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── static/
    ├── index.html
    ├── app.js
    └── style.css
```
