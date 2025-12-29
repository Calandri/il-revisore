# /mockup_modify - Modify UI Mockup Component

Modify a specific component in an existing mockup.

---

## COMMAND ARGUMENTS

The command contains these arguments:
- `--mockup-id`: UUID of the mockup to modify
- `--selector`: CSS selector of the element (e.g., `div.card > h2.title`)
- `--description`: Description of the requested modification

**EXTRACT these values from the COMMAND ARGUMENTS section below before proceeding!**

---

## EXECUTE THESE STEPS IN ORDER:

### STEP 1 - READ CURRENT HTML

```bash
curl -s "http://127.0.0.1:8000/api/mockups/<MOCKUP_ID>/content" | jq -r '.html' > /tmp/mockup_<MOCKUP_ID>_original.html
```

Replace `<MOCKUP_ID>` with the value from arguments.

### STEP 2 - FIND THE ELEMENT

Open `/tmp/mockup_<MOCKUP_ID>_original.html` and find the element matching the **selector**.
The selector is in CSS format (e.g., `div.grid > div.card > h2.title`).

### STEP 3 - APPLY MODIFICATION

- Modify ONLY the specified element according to `--description`
- DO NOT change other parts of the mockup
- Keep Tailwind CSS styling
- Save result to `/tmp/mockup_<MOCKUP_ID>.html`

### STEP 4 - SAVE MOCKUP

```bash
python -m turbowrap.scripts.mockup_tool save --mockup-id <MOCKUP_ID> --html-file /tmp/mockup_<MOCKUP_ID>.html
```

### STEP 5 - CONFIRM

Respond:
```
✅ Modifica completata!

**Elemento:** `<SELECTOR>`
**Modifica:** brief description of what was changed

Ricarica la preview per vedere le modifiche.
```

---

## RULES
- Respond in Italian
- DO NOT show the entire HTML in chat
- Show only the modified snippet (max 10 lines before/after)
- If selector doesn't find elements, ask for clarification
- If description is vague, ask for specific details
