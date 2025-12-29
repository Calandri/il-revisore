# /mockup - Genera Mockup UI

Crea un mockup UI per l'utente.

---

## ISTRUZIONI (esegui in ordine!)

**STEP 1 - INIT** (fallo PRIMA di rispondere!):
```bash
python -m turbowrap.scripts.mockup_tool init --project-id <PROJECT_ID> --name "<nome>" --type page
```

**STEP 2 - CREA HTML**: Scrivi in `/tmp/mockup_<MOCKUP_ID>.html` (NON mostrare in chat!)

**STEP 3 - SAVE**:
```bash
python -m turbowrap.scripts.mockup_tool save --mockup-id <MOCKUP_ID> --html-file /tmp/mockup_<MOCKUP_ID>.html
```

**STEP 4 - CONFERMA**: "Mockup creato! Vai alla pagina Mockups per vederlo."

---

**IMPORTANTE**:
- Il `--project-id` è passato nel comando, USALO!
- Rispondi in italiano
- NON mostrare codice HTML all'utente
