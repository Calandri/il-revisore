# /mockup - Generate UI Mockup

Create a UI mockup for the user.

---

## CRITICAL: EXECUTE THESE STEPS IN ORDER!

**STEP 1 - INIT (DO THIS FIRST, BEFORE ANY RESPONSE!):**

Look at the COMMAND ARGUMENTS section below. Extract the `--project-id` value and use it:

```bash
python -m turbowrap.scripts.mockup_tool init --project-id <PROJECT_ID_FROM_ARGS> --name "<mockup_name>" --type page
```

This will output a `mockup_id`. Save it for step 3.

**STEP 2 - CREATE HTML:**

Write the HTML to `/tmp/mockup_<MOCKUP_ID>.html`

DO NOT show HTML code in chat!

**STEP 3 - SAVE:**

```bash
python -m turbowrap.scripts.mockup_tool save --mockup-id <MOCKUP_ID> --html-file /tmp/mockup_<MOCKUP_ID>.html
```

**STEP 4 - CONFIRM:**

Say: "Mockup creato! Vai alla pagina Mockups per vederlo."

---

## RULES:
- The `--project-id` is in the COMMAND ARGUMENTS below - USE IT!
- Respond in Italian
- DO NOT show HTML code to the user
- Run the init command BEFORE asking questions or generating content
