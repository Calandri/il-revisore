# Mockup System - AI-Generated UI Prototypes

## Overview

Il Mockup System permette di generare UI mockup completi (HTML/CSS/JS) tramite AI.
I mockup sono file HTML standalone che funzionano direttamente nel browser.

**LLM Supportati**: Claude (Sonnet), Gemini, Grok
**Design Systems**: Tailwind CSS, Bootstrap, Material, Custom
**Storage**: S3 per HTML/CSS/JS

---

## Architettura

```
┌─────────────────────────────────────────────────────────────────────┐
│                           CHAT CLI                                   │
│              (user: "crea una dashboard utenti")                     │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      /mockup COMMAND                                 │
│                    (commands/mockup.md)                              │
└─────────────────────────────────────────────────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
        ▼                          ▼                          ▼
┌───────────────┐      ┌───────────────────┐      ┌──────────────────┐
│ mockup_tool   │      │ MockupService     │      │      S3          │
│ init          │      │ generate_mockup() │      │  HTML Storage    │
│ save          │      │ modify_mockup()   │      │                  │
│ fail          │      │                   │      │                  │
└───────────────┘      └───────────────────┘      └──────────────────┘
        │                          │                          │
        └──────────────────────────┼──────────────────────────┘
                                   ▼
                        ┌───────────────────┐
                        │    SSE Events     │
                        │  Real-time UI     │
                        └───────────────────┘
```

---

## Workflow Completo

### 1. Creazione Progetto

Prima di creare mockup, serve un progetto:

```json
POST /api/mockups/projects
{
  "repository_id": "uuid",
  "name": "Dashboard Redesign",
  "description": "Nuovo design per la dashboard utenti",
  "design_system": "tailwind",
  "color": "#6366f1",
  "icon": "layout"
}
```

### 2. Generazione Mockup (via Chat CLI)

L'utente usa il comando `/mockup` nella chat:

```
User: /mockup --project-id abc123

User: Crea una dashboard con:
- Header con logo e user menu
- Sidebar con navigazione
- Griglia di card con statistiche
- Grafico a barre
```

### 3. Workflow Interno

Il comando `/mockup` esegue questi step:

**STEP 1 - INIT:**
```bash
python -m turbowrap.scripts.mockup_tool init \
  --project-id abc123 \
  --name "Dashboard Utenti" \
  --type page
```

Output: `mockup_id` + placeholder HTML in S3

**STEP 2 - CREATE HTML:**
L'LLM genera l'HTML e lo salva in `/tmp/mockup_<ID>.html`

**STEP 3 - SAVE:**
```bash
python -m turbowrap.scripts.mockup_tool save \
  --mockup-id <ID> \
  --html-file /tmp/mockup_<ID>.html
```

Il placeholder in S3 viene sovrascritto con l'HTML reale.

**STEP 4 - NOTIFY:**
SSE event `save` inviato al frontend per aggiornare la UI.

### 4. Visualizzazione

L'utente può vedere il mockup nella pagina `/mockups`:
- Preview iframe
- Download HTML
- Modifica con `/mockup_modify`

---

## Modifica Mockup

Per modificare un elemento specifico:

```
User: /mockup_modify --mockup-id abc123 --selector "div.card > h2.title" --description "cambia il colore in rosso"
```

### Workflow Modifica

1. **Fetch HTML**: Scarica HTML corrente da S3
2. **Find Element**: Trova elemento tramite selector CSS
3. **Apply Changes**: L'LLM modifica solo l'elemento specificato
4. **Save**: Crea nuova versione (version + 1)
5. **Notify**: SSE event per aggiornare preview

---

## Database Models

### MockupProject
```python
class MockupProject(Base):
    id: str                    # UUID
    repository_id: str         # FK to repositories
    name: str                  # Project name
    description: str | None
    design_system: str         # tailwind, bootstrap, material, custom
    color: str                 # Theme color (hex)
    icon: str                  # Lucide icon name
    created_at: datetime
    updated_at: datetime
```

### Mockup
```python
class Mockup(Base):
    id: str                    # UUID
    project_id: str            # FK to mockup_projects
    name: str                  # Mockup name
    description: str | None
    component_type: str        # page, component, modal, form, table
    status: MockupStatus       # generating, completed, failed

    # LLM Metadata
    llm_type: str              # claude, gemini, grok
    llm_model: str | None      # Specific model used
    prompt_used: str | None
    tokens_in: int
    tokens_out: int

    # S3 Storage
    s3_html_url: str | None
    s3_css_url: str | None
    s3_js_url: str | None
    s3_prompt_url: str | None

    # Versioning
    version: int               # Starting from 1
    parent_mockup_id: str | None  # For modifications

    # Error tracking
    error_message: str | None

    # Chat session link
    chat_session_id: str | None
```

### MockupStatus
```python
class MockupStatus(str, Enum):
    GENERATING = "generating"  # Placeholder visible, LLM working
    COMPLETED = "completed"    # HTML ready
    FAILED = "failed"          # Generation failed
```

---

## API Endpoints

### Projects

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/mockups/projects` | Lista progetti |
| POST | `/api/mockups/projects` | Crea progetto |
| GET | `/api/mockups/projects/{id}` | Dettaglio progetto |
| PUT | `/api/mockups/projects/{id}` | Aggiorna progetto |
| DELETE | `/api/mockups/projects/{id}` | Elimina progetto (soft) |

### Mockups

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/mockups` | Lista mockup |
| POST | `/api/mockups` | Crea e genera mockup |
| GET | `/api/mockups/{id}` | Dettaglio mockup |
| GET | `/api/mockups/{id}/content` | HTML/CSS/JS content da S3 |
| POST | `/api/mockups/{id}/modify` | Modifica mockup (nuova versione) |
| PUT | `/api/mockups/{id}` | Aggiorna metadata |
| DELETE | `/api/mockups/{id}` | Elimina mockup (soft) |

### LLM Tool Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/mockups/init` | Init mockup (status: generating) |
| PUT | `/api/mockups/{id}/save` | Save HTML (status: completed) |
| PUT | `/api/mockups/{id}/fail` | Mark as failed |

### SSE

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/mockups/events` | SSE stream per real-time updates |
| POST | `/api/mockups/notify` | Broadcast event a tutti i client |

---

## SSE Events

| Event | Trigger | Data |
|-------|---------|------|
| `connected` | Client connects | `{}` |
| `init` | Mockup initialized | `{mockup_id, project_id}` |
| `save` | Mockup saved | `{mockup_id, project_id}` |
| `fail` | Mockup failed | `{mockup_id, project_id}` |

---

## CLI Tool (mockup_tool.py)

Tool Python per operazioni mockup senza HTTP:

```bash
# Initialize
python -m turbowrap.scripts.mockup_tool init \
  --project-id UUID \
  --name "Nome" \
  --description "Descrizione" \
  --type page \
  --llm claude

# Save
python -m turbowrap.scripts.mockup_tool save \
  --mockup-id UUID \
  --html-file /tmp/mockup.html \
  --llm-model "claude-sonnet"

# Fail
python -m turbowrap.scripts.mockup_tool fail \
  --mockup-id UUID \
  --error "Error message"
```

### Output JSON

```json
{
  "success": true,
  "mockup_id": "abc123",
  "status": "completed",
  "s3_url": "https://bucket.s3.region.amazonaws.com/mockups/abc123/preview.html",
  "message": "Mockup saved! View at /mockups page."
}
```

---

## Design System Prompts

### Tailwind (default)
```
Use Tailwind CSS utility classes for all styling.
Include the Tailwind CDN: <script src="https://cdn.tailwindcss.com"></script>
Follow Tailwind best practices with responsive classes (sm:, md:, lg:).
```

### Bootstrap
```
Use Bootstrap 5 for styling.
Include Bootstrap CSS and JS from CDN.
Use Bootstrap grid system and components.
```

### Material
```
Use Material Design principles with custom CSS.
Include Material Icons from Google Fonts.
Use Material Design color palette and elevation shadows.
```

### Custom
```
Use custom CSS with modern best practices.
Include CSS custom properties (CSS variables) for theming.
Use flexbox and grid for layouts.
```

---

## TurboWrap Color Palette

I mockup usano automaticamente i colori brand:

```css
/* TurboWrap Brand Colors */
--primary: #6366f1;        /* Indigo */
--primary-light: #818cf8;
--primary-dark: #4f46e5;
--success: #10b981;        /* Emerald */
--warning: #f59e0b;        /* Amber */
--error: #ef4444;          /* Red */
--text-dark: #1f2937;
--text-light: #6b7280;
--background: #f9fafb;
--card-background: #ffffff;
```

---

## Storage

### S3 Structure
```
mockups/
├── {mockup_id}/
│   └── preview.html      # Unico file, sovrascritto da save
└── {year}/{month}/{day}/
    └── {mockup_id}/
        └── mockup.html   # Path alternativo (API service)
```

### Path Fisso per Mockup

Il `mockup_tool` usa un path fisso `mockups/{mockup_id}/preview.html`:
- `init`: Carica placeholder
- `save`: Sovrascrive con HTML reale

Questo garantisce che la preview funzioni immediatamente dopo `init`.

---

## Placeholder HTML

Durante `init`, viene caricato un placeholder animato:

```html
<!DOCTYPE html>
<html lang="it">
<head>
    <title>Nome - Generating...</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gradient-to-br from-indigo-50 to-violet-100 min-h-screen flex items-center justify-center">
    <div class="text-center p-8">
        <div class="w-20 h-20 mx-auto mb-6 bg-white rounded-2xl shadow-lg flex items-center justify-center">
            <svg class="w-10 h-10 text-indigo-500 animate-spin">...</svg>
        </div>
        <h1 class="text-2xl font-bold text-gray-800">Nome Mockup</h1>
        <p class="text-indigo-600">Generazione in corso...</p>
    </div>
</body>
</html>
```

L'utente vede questo mentre l'LLM genera il vero mockup.

---

## Component Types

| Type | Description | Use Case |
|------|-------------|----------|
| `page` | Full page layout | Dashboard, Landing, Settings |
| `component` | Reusable UI element | Card, Button, Alert |
| `modal` | Dialog/popup | Confirm, Form, Info |
| `form` | Input form | Login, Register, Contact |
| `table` | Data table | List, Grid, Report |

---

## LLM Selection

| LLM | Model | Use Case | Speed | Cost |
|-----|-------|----------|-------|------|
| Claude | Sonnet | Complex layouts | Medium | Medium |
| Gemini | Flash | Quick mockups | Fast | Low |
| Grok | - | Alternative | Fast | Medium |

---

## Commands (Chat CLI)

### /mockup

Crea un nuovo mockup:

```
/mockup --project-id <UUID>
```

Poi descrivi cosa vuoi creare.

### /mockup_modify

Modifica un elemento esistente:

```
/mockup_modify --mockup-id <UUID> --selector "div.card" --description "cambia colore sfondo"
```

---

## Versioning

Ogni modifica crea una nuova versione:

```
Mockup v1 (original)
  └── Mockup v2 (modified header)
        └── Mockup v3 (added footer)
```

Campi versioning:
- `version`: Numero versione (1, 2, 3...)
- `parent_mockup_id`: Link al mockup padre

---

## Best Practices

### Per gli Utenti

1. **Descrivi dettagliatamente** - Più dettagli = risultato migliore
2. **Specifica componenti** - "card con icona, titolo, descrizione, bottone"
3. **Indica colori** - "usa tonalità blu" o "palette dark mode"
4. **Menziona responsive** - "mobile-first" o "desktop-only"

### Per le Modifiche

1. **Selector preciso** - Usa selettori CSS specifici
2. **Una modifica alla volta** - Non modificare troppi elementi insieme
3. **Check versioni** - Verifica quale versione stai modificando

### Per lo Sviluppo

1. **HTML standalone** - Il file deve funzionare senza server
2. **CDN per librerie** - Tailwind, Bootstrap, etc. da CDN
3. **Placeholder images** - Usa placehold.co per immagini

---

## Troubleshooting

### Mockup stuck su "generating"

```bash
# Mark as failed
python -m turbowrap.scripts.mockup_tool fail \
  --mockup-id <ID> \
  --error "Timeout"
```

### Preview non si aggiorna

1. Verifica che SSE sia connesso
2. Force refresh della pagina
3. Check S3 che il file sia aggiornato

### HTML non valido

L'LLM potrebbe non wrappare in ```html. Il sistema cerca:
1. ```` ```html ... ``` ````
2. `<!DOCTYPE html>...</html>`
3. `<html>...</html>`

### S3 upload failed

1. Verifica credenziali AWS
2. Check bucket permissions
3. Verifica regione corretta
