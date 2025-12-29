# MOCKUP TOOL

## ESEGUI QUESTI COMANDI IN ORDINE:

### 1. INIT (fallo SUBITO!)
```bash
python -m turbowrap.scripts.mockup_tool init --project-id PROJECT_ID --name "NOME" --type page
```
(Usa il project-id dal comando. Riceverai un mockup_id.)

### 2. CREA HTML
Scrivi l'HTML in `/tmp/mockup_MOCKUP_ID.html` (non mostrarlo in chat)

### 3. SAVE
```bash
python -m turbowrap.scripts.mockup_tool save --mockup-id MOCKUP_ID --html-file /tmp/mockup_MOCKUP_ID.html
```

### 4. CONFERMA
Dì: "Mockup creato! Vai alla pagina Mockups per vederlo."

---

**REGOLE:**
- Rispondi in italiano
- NON mostrare HTML in chat
- USA il project-id passato nel comando
