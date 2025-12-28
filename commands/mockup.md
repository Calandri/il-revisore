# /mockup - Generate UI Mockup

Generate a UI mockup using AI. This command guides you through a series of questions to understand exactly what you need, then generates a complete HTML/CSS/JS mockup.

## Step 1: Component Type

Ask the user what type of UI component they want to create:

**Domanda**: "Che tipo di componente UI vuoi creare?"

Options:
1. **Pagina completa** (`page`) - Una pagina web completa (landing, dashboard, form page)
2. **Componente** (`component`) - Un componente riutilizzabile (card, header, footer)
3. **Modal/Dialog** (`modal`) - Una finestra modale con contenuto
4. **Form** (`form`) - Un form con validazione e campi
5. **Tabella/Data Grid** (`table`) - Una tabella dati con sorting/filtering

## Step 2: Design System

Ask about the styling framework:

**Domanda**: "Quale design system/framework CSS preferisci?"

Options:
1. **Tailwind CSS** (Recommended) - Utility-first, moderno, flessibile
2. **Bootstrap 5** - Componenti pronti, grid system classico
3. **Material Design** - Stile Google, elevation, ripple effects
4. **CSS Custom** - CSS puro con variabili custom, senza framework

## Step 3: Details (Based on Component Type)

### For `page`:
**Domanda**: "Descrivi la pagina che vuoi creare. Includi:"
- Scopo della pagina (landing, dashboard, profilo, etc.)
- Sezioni principali (hero, features, pricing, etc.)
- Elementi chiave (navbar, footer, sidebar)
- Stile desiderato (minimal, corporate, creative, tech)

### For `component`:
**Domanda**: "Descrivi il componente. Includi:"
- Tipo di componente (card prodotto, card utente, stat card, etc.)
- Dati da mostrare (immagine, titolo, descrizione, prezzo, etc.)
- Azioni disponibili (pulsanti, link, icone)
- Varianti (dark mode, sizes, states)

### For `modal`:
**Domanda**: "Descrivi il modal. Includi:"
- Scopo (conferma, form, dettagli, wizard)
- Contenuto principale
- Pulsanti/azioni nel footer
- Dimensione (small, medium, large, full-screen)

### For `form`:
**Domanda**: "Descrivi il form. Includi:"
- Tipo (login, registrazione, contatto, checkout, filtri)
- Campi necessari (nome, email, password, etc.)
- Validazione richiesta
- Layout (single column, multi-column, wizard steps)

### For `table`:
**Domanda**: "Descrivi la tabella. Includi:"
- Tipo di dati (utenti, ordini, prodotti, logs)
- Colonne principali
- Funzionalità (sorting, filtering, pagination, actions)
- Stile righe (striped, hover, selectable)

## Step 4: Extra Features

**Domanda**: "Vuoi funzionalità aggiuntive?"

Options (multi-select):
1. **Dark Mode** - Supporto per tema scuro
2. **Animazioni** - Hover effects, transizioni, micro-interactions
3. **Responsive** - Ottimizzato per mobile/tablet
4. **Accessibilità** - ARIA labels, focus states, semantic HTML
5. **Skeleton Loading** - Placeholder durante caricamento

## Step 5: Generate

Use the gathered information to create a complete, standalone HTML file with:

### TurboWrap Color Palette

```css
:root {
  /* Primary */
  --tw-primary: #6366f1;
  --tw-primary-light: #818cf8;
  --tw-primary-dark: #4f46e5;

  /* Status */
  --tw-success: #10b981;
  --tw-warning: #f59e0b;
  --tw-error: #ef4444;
  --tw-info: #3b82f6;

  /* Text */
  --tw-text-dark: #1f2937;
  --tw-text-light: #6b7280;
  --tw-text-muted: #9ca3af;

  /* Background */
  --tw-bg-light: #f9fafb;
  --tw-bg-card: #ffffff;
  --tw-bg-dark: #111827;
}
```

### Output Format

Generate a COMPLETE, STANDALONE HTML file:

```html
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>[Mockup Name]</title>
    <!-- Design system CDN -->
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- or Bootstrap/Material CSS -->
    <style>
        /* Custom styles and TurboWrap palette */
    </style>
</head>
<body>
    <!-- Component HTML -->

    <script>
        /* JavaScript for interactivity */
    </script>
</body>
</html>
```

## Response Format

After generating the mockup, respond with:

```markdown
## Mockup Generato

**Nome**: [nome descrittivo del mockup]
**Tipo**: [component type]
**Design System**: [framework usato]

### Preview
Il mockup è stato generato con successo.

Per visualizzarlo:
1. Vai alla pagina **Mockups** nell'interfaccia TurboWrap
2. Seleziona il progetto e clicca sul mockup
3. Usa il pannello Preview per vedere il risultato

### Dettagli Tecnici
- **Tokens utilizzati**: Input: X, Output: Y
- **LLM**: Claude/Gemini/Grok

### Codice
[Mostra un'anteprima del codice HTML generato]

### Prossimi Passi
- Clicca su un elemento nel preview per modificarlo
- Usa il pulsante "Modifica" per cambiare il mockup
- Esporta il codice per usarlo nel tuo progetto
```

## Important Notes

- **Rispondi SEMPRE in italiano** (lingua dell'utente)
- Genera HTML **completo e funzionante** - deve aprirsi direttamente nel browser
- Usa **immagini placeholder** da https://placehold.co/ quando servono immagini
- Aggiungi **dati realistici** come placeholder text
- Assicurati che il mockup sia **responsive** di default
- Includi **hover states** e **transizioni** per UX professionale

**IMPORTANT: Respond in Italian (the user's default language).**
