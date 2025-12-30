# Live View - Production Site Interaction

## Overview

Live View permette di visualizzare e interagire con i siti di produzione dei repository frontend direttamente da TurboWrap. È possibile creare issue, feature request o discutere elementi con l'AI cliccando direttamente sul sito.

**Modalità**: Iframe (se permesso) o Screenshot (se bloccato)
**Screenshot Engine**: Playwright
**Storage**: S3 per screenshot

---

## Architettura

```
┌─────────────────────────────────────────────────────────────────────┐
│                          LIVE VIEW PAGE                             │
│                    /live-view (live_view.html)                      │
└─────────────────────────────────────────────────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
        ▼                          ▼                          ▼
┌───────────────┐      ┌───────────────────┐      ┌──────────────────┐
│  Repository   │      │  Iframe Check     │      │  Screenshot      │
│  Selector     │      │  X-Frame-Options  │      │  Service         │
│  (Frontend)   │      │  CSP Headers      │      │  (Playwright)    │
└───────────────┘      └───────────────────┘      └──────────────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
                    ▼                     ▼
            ┌───────────────┐     ┌───────────────┐
            │   Iframe      │     │  Screenshot   │
            │   Mode        │     │  Mode         │
            │   (Live)      │     │  (Static)     │
            └───────────────┘     └───────────────┘
                    │                     │
                    └──────────┬──────────┘
                               ▼
                    ┌───────────────────┐
                    │  Element Click    │
                    │  → Action Modal   │
                    └───────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
        ▼                      ▼                      ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│ Create Issue  │      │Create Feature │      │ Send to Chat  │
└───────────────┘      └───────────────┘      └───────────────┘
```

---

## Workflow

### 1. Repository Selection

La pagina mostra solo repository **frontend** o **fullstack** che hanno un link di produzione configurato.

```
Repository List
├── Frontend repos con link production
└── Fullstack repos con link production
```

### 2. Iframe Compatibility Check

Quando si seleziona un repository, il sistema verifica se il sito può essere embeddato:

**Check eseguiti:**
1. **X-Frame-Options** header
   - `DENY` → Bloccato
   - `SAMEORIGIN` → Bloccato
   - Non presente → Permesso

2. **Content-Security-Policy** header
   - `frame-ancestors 'none'` → Bloccato
   - `frame-ancestors 'self'` → Bloccato
   - Non presente → Permesso

**Risultati:**
- ✅ `Iframe OK` → Mostra iframe live
- ❌ `Iframe Bloccato` → Mostra screenshot

### 3. Visualizzazione

#### Iframe Mode (quando permesso)
- Sito caricato in tempo reale
- Interazione diretta con gli elementi
- Click handler per selezionare elementi

#### Screenshot Mode (quando bloccato)
- Screenshot statico del sito
- Catturato con Playwright
- Click sullo screenshot restituisce coordinate (x%, y%)

### 4. Element Selection & Actions

Quando si clicca su un elemento:

1. **Selector catturato** (iframe mode) o coordinate (screenshot mode)
2. **Action Modal** appare con 3 opzioni:
   - 🐛 **Crea Issue** - Segnala bug/problema
   - 💡 **Crea Feature** - Richiedi funzionalità
   - 💬 **Invia alla Chat** - Discuti con AI

---

## Database Models

### LiveViewScreenshot
```python
class LiveViewScreenshot(Base):
    id: str                    # UUID
    repository_id: str         # FK to repositories
    external_link_id: str      # FK to external links
    s3_url: str                # Pre-signed S3 URL
    captured_at: datetime
    viewport_width: int        # Default: 1920
    viewport_height: int       # Default: 1080
    created_at: datetime
    updated_at: datetime
```

**Note:** Un solo screenshot per external_link (l'ultimo sovrascrive il precedente).

---

## API Endpoints

### Repository List
```
GET /api/live-view/repos

Response:
[
  {
    "id": "uuid",
    "name": "my-frontend",
    "slug": "my-frontend",
    "repo_type": "frontend",
    "production_link": {
      "id": "link-uuid",
      "url": "https://myapp.com",
      "label": "Production"
    }
  }
]
```

### Iframe Compatibility Check
```
POST /api/live-view/{repo_id}/check-iframe
{
  "url": "https://myapp.com"
}

Response:
{
  "url": "https://myapp.com",
  "can_embed": true,
  "blocked_reason": null,
  "headers": {
    "x-frame-options": "(not set)"
  }
}

// Or when blocked:
{
  "url": "https://myapp.com",
  "can_embed": false,
  "blocked_reason": "X-Frame-Options: DENY",
  "headers": {
    "x-frame-options": "DENY"
  }
}
```

### Get Screenshot
```
GET /api/live-view/{repo_id}/screenshot?external_link_id={link_id}

Response:
{
  "id": "screenshot-uuid",
  "s3_url": "https://bucket.s3.region.amazonaws.com/...",
  "captured_at": "2025-01-15T10:30:00Z",
  "viewport_width": 1920,
  "viewport_height": 1080
}
```

### Capture Screenshot
```
POST /api/live-view/{repo_id}/screenshot
{
  "external_link_id": "link-uuid",
  "viewport_width": 1920,
  "viewport_height": 1080
}

Response:
{
  "id": "new-screenshot-uuid",
  "s3_url": "https://...",
  "captured_at": "2025-01-15T10:35:00Z",
  "viewport_width": 1920,
  "viewport_height": 1080
}
```

### Perform Action
```
POST /api/live-view/action
{
  "repository_id": "repo-uuid",
  "action": "create_issue",  // "create_issue" | "create_feature" | "send_to_chat"
  "selector": "div.card > h2.title",
  "element_info": {
    "tag": "H2",
    "text": "Dashboard"
  },
  "title": "Bug nel titolo",
  "description": "Il titolo non si aggiorna"
}

Response (create_issue):
{
  "action": "create_issue",
  "success": true,
  "redirect": "/issues/LV-20250115-ABC123",
  "entity_id": "issue-uuid",
  "message": "Issue LV-20250115-ABC123 created"
}

Response (send_to_chat):
{
  "action": "send_to_chat",
  "success": true,
  "command": "/live-context --repo \"my-frontend\" --selector \"div.card\" --description \"fix this\"",
  "message": "Ready to discuss: Dashboard"
}
```

---

## Screenshot Service

Il servizio usa **Playwright** per catturare screenshot:

```python
class ScreenshotService:
    async def capture_and_upload(
        self,
        url: str,
        repo_slug: str,
        viewport_width: int = 1920,
        viewport_height: int = 1080,
    ) -> str:  # Returns S3 URL
```

### Processo di Capture

1. **Launch Chromium** (headless)
2. **Set viewport** (default: 1920x1080)
3. **Navigate** con `wait_until="networkidle"`
4. **Wait** 1 secondo per lazy-loaded content
5. **Capture** full-page PNG
6. **Upload** a S3
7. **Return** pre-signed URL

### Requisiti

```bash
pip install playwright
playwright install chromium
```

---

## Storage

### S3 Structure
```
live-view-screenshots/
└── {year}/{month}/{day}/
    └── screenshot_{repo_slug}_{timestamp}.png
```

### Database
- `live_view_screenshots` - Un record per external_link
- Il vecchio screenshot viene eliminato quando se ne cattura uno nuovo

---

## Actions

### Create Issue

Crea una nuova Issue dal selettore cliccato:

```python
issue = Issue(
    issue_code="LV-YYYYMMDD-XXXXXX",  # Auto-generated
    repository_id=repo_id,
    severity="MEDIUM",
    category="ui",
    rule="live_view",
    file=selector,  # CSS selector come "file"
    title=title or f"UI Issue: {selector[:50]}",
    description="""
    ## Element Details
    **Selector:** `div.card > h2`
    **Element Info:**
    ```json
    {"tag": "H2", "text": "Dashboard"}
    ```
    ---
    *Created from Live View*
    """,
    status="open",
)
```

### Create Feature

Crea una nuova Feature request:

```python
feature = Feature(
    title=title or f"Feature: {selector[:50]}",
    description=description or f"Feature request from Live View.\n\nElement: `{selector}`",
    priority=3,
    status="analysis",
)

# Link to repository
feature_repo = FeatureRepository(
    feature_id=feature.id,
    repository_id=repo_id,
    role="primary",
)
```

### Send to Chat

Genera un comando per la Chat CLI:

```
/live-context --repo "my-frontend" --selector "div.card" --description "fix the color"
```

---

## UI Components

### Repository Selector
- Lista repository frontend/fullstack con link production
- Avatar con iniziale del nome
- Badge tipo repository (frontend/fullstack)
- URL production visibile

### Live View Panel
- **Header**: Nome repo, URL, status iframe
- **Content**: Iframe o Screenshot
- **Footer**: Selector selezionato, bottone "Azione"

### Action Modal
- Input titolo (opzionale)
- Input descrizione (opzionale)
- 3 bottoni azione con icone colorate
- Bottone annulla

---

## Configuration

### Prerequisiti Repository

Per apparire in Live View, un repository deve:
1. Essere di tipo `frontend` o `fullstack`
2. Avere un external link con `link_type = "production"`

```python
# Aggiungere link production
external_link = RepositoryExternalLink(
    repository_id=repo_id,
    link_type="production",
    url="https://myapp.com",
    label="Production Site",
)
```

### Viewport Defaults
```python
DEFAULT_VIEWPORT_WIDTH = 1920
DEFAULT_VIEWPORT_HEIGHT = 1080
```

### Timeout Settings
```python
IFRAME_CHECK_TIMEOUT = 10  # seconds
SCREENSHOT_NAVIGATION_TIMEOUT = 30000  # ms
SCREENSHOT_LAZY_LOAD_WAIT = 1000  # ms
```

---

## Limitazioni

### Iframe Mode
- **Cross-origin restrictions**: Non si può iniettare JavaScript in iframe cross-origin
- **Click handling**: Richiede cooperazione dal sito target
- Funziona meglio con siti che implementano `postMessage`

### Screenshot Mode
- **Statico**: Non si può interagire con elementi
- **Coordinate**: Click restituisce solo x%, y%, non il vero selector
- **Latenza**: Cattura screenshot richiede 5-10 secondi

### Headers Detection
- Alcuni siti usano JavaScript per blocking invece di headers
- Il check headers potrebbe dare falso positivo

---

## Best Practices

### Per gli Utenti

1. **Configura link production** - Assicurati che il repository abbia un link di tipo "production"
2. **Usa screenshot per siti bloccati** - Se iframe non funziona, cattura uno screenshot
3. **Descrivi bene l'azione** - Più dettagli dai, migliore sarà l'issue/feature creata

### Per gli Sviluppatori

1. **Permettere iframe** - Se vuoi usare Live View in iframe, non impostare X-Frame-Options
2. **PostMessage** - Implementa postMessage per migliore interazione
3. **CSP permissivo** - Usa `frame-ancestors` con domini permessi invece di 'none'

---

## Troubleshooting

### Screenshot non si carica

1. Verifica che Playwright sia installato: `playwright install chromium`
2. Controlla S3 credentials e bucket permissions
3. Verifica che il sito sia raggiungibile

### Iframe sempre bloccato

1. Controlla headers con browser DevTools
2. Alcuni siti usano JavaScript blocking
3. Usa screenshot mode come fallback

### Action non funziona

1. Verifica che il repository esista
2. Controlla che external_link_id sia corretto
3. Verifica permessi database

### Performance lenta

1. Screenshot capture richiede 5-10 secondi
2. Prima navigazione può essere lenta
3. Considera caching più aggressivo degli screenshot
