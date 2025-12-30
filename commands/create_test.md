# /create_test - Generate Tests for Source Code

Generate comprehensive tests for a source file or module within a test suite.

---

## COMMAND ARGUMENTS FORMAT:
```
/create_test --suite-id <UUID> --suite-path <path> --framework <framework> <source_file>
```

Example:
```
/create_test --suite-id abc123 --suite-path tests/ --framework pytest src/services/user.py
```

---

## CRITICAL: FOLLOW THIS FLOW!

**STEP 1 - PARSE ARGUMENTS:**

Extract from COMMAND ARGUMENTS section:
- `--suite-id`: UUID della test suite (REQUIRED)
- `--suite-path`: Path della cartella test (es. `tests/`, `__tests__/`)
- `--framework`: Framework (pytest, vitest, jest, playwright)
- `<source_file>`: File sorgente da testare

If `--suite-id` is missing, ask: "Quale test suite vuoi usare? Vai nella pagina /tests e clicca 'Genera Test' su una suite."

**STEP 2 - READ SOURCE:**

Read the target source file and understand:
- Functions/classes to test
- Dependencies and imports
- Expected behaviors

**STEP 3 - ASK QUESTIONS:**

Ask the user these questions:

Che tipo di test vuoi generare?

Quali scenari vuoi coprire? (happy path, edge cases, error handling, tutti)

Vuoi usare mock per le dipendenze esterne?

**STEP 4 - CREATE BRANCH:**

```bash
git checkout -b feat/test-<module_name>
```

**STEP 5 - GENERATE TESTS:**

Generate comprehensive test code based on the source:

**For Python (pytest):**
```python
import pytest
from unittest.mock import Mock, patch

# Import the module to test
from <module> import <functions>

class Test<ClassName>:
    """Tests for <ClassName>."""

    def test_<function>_success(self):
        """Test successful case."""
        # Arrange
        # Act
        # Assert

    def test_<function>_invalid_input(self):
        """Test with invalid input."""
        with pytest.raises(ValueError):
            ...

    @pytest.mark.parametrize("input,expected", [
        ("case1", "result1"),
        ("case2", "result2"),
    ])
    def test_<function>_parametrized(self, input, expected):
        """Test multiple cases."""
        assert function(input) == expected
```

**For TypeScript (vitest/jest):**
```typescript
import { describe, it, expect, vi } from 'vitest';
import { functionName } from './module';

describe('ModuleName', () => {
  it('should handle success case', () => {
    expect(functionName()).toBe(expected);
  });

  it('should throw on invalid input', () => {
    expect(() => functionName(null)).toThrow();
  });
});
```

**STEP 6 - WRITE FILE:**

Write the test file to the **suite path** from arguments:
- Use `--suite-path` as base directory
- Python: `<suite_path>/test_<module_name>.py`
- TypeScript: `<suite_path>/<module>.test.ts`

Example: If `--suite-path tests/unit/` → write to `tests/unit/test_user_service.py`

Use the Write tool to create the file.

**STEP 7 - RUN TESTS:**

```bash
# Python
pytest tests/test_<module_name>.py -v

# TypeScript
npx vitest run src/__tests__/<module>.test.ts
```

**STEP 8 - REPORT RESULTS:**

```markdown
## Test Generati per `<filename>`

### Sommario
- **File test**: `<test_file_path>`
- **Test totali**: <number>
- **Tipo**: Unit/Integration/Mixed
- **Branch**: `feat/test-<name>`

### Test creati:
1. `test_<function>_success` - Caso normale
2. `test_<function>_error` - Gestione errori
...

### Risultati:
✅ Tutti i test passano / ❌ X test falliti

### Prossimi passi:
1. Rivedi i test generati
2. `git add <test_file>`
3. `git commit -m "test: add tests for <module>"`
```

---

## RULES:
- ALWAYS read the source file FIRST
- Generate RUNNABLE tests (no placeholders!)
- Follow existing test patterns in the project
- Include happy path + edge cases + error handling
- Use descriptive test names
- Add docstrings/comments
- Respond in Italian
