#!/usr/bin/env python3
"""Test script for Claude agent prompts.

Tests both linear_question_generator and linear_finalizer agents.
"""

import json
import subprocess
import sys


def test_question_generator():
    """Test the question generator agent."""
    print("=" * 80)
    print("TEST 1: Linear Question Generator")
    print("=" * 80)

    input_text = """Titolo: Fix login button UI
Descrizione: Il bottone di login non risponde al click su mobile
Figma: https://figma.com/file/example
Sito: https://app.example.com/login

Analisi Gemini:
Screenshot mostra un form con email/password e bottone blu 'Login'.
Il bottone sembra avere padding inconsistente e non ha feedback visivo al tap.
Su iPhone 12 il bottone appare più piccolo del target touch raccomandato (44x44px).
"""

    print("\nInput:")
    print("-" * 80)
    print(input_text)
    print("-" * 80)

    try:
        result = subprocess.run(
            ["claude", "--agent", "agents/linear_question_generator.md"],
            input=input_text,
            capture_output=True,
            text=True,
            timeout=120,
        )

        output = result.stdout.strip()

        print("\nOutput:")
        print("-" * 80)
        print(output)
        print("-" * 80)

        # Try to parse as JSON
        try:
            data = json.loads(output)
            questions = data.get("questions", [])

            print(f"\n✅ Valid JSON with {len(questions)} questions:")
            for q in questions:
                print(f"   {q['id']}. {q['question']}")
                print(f"      Why: {q['why']}")

            return True
        except json.JSONDecodeError as e:
            print(f"\n❌ Invalid JSON: {e}")
            print("Expected JSON format, but got text response")
            return False

    except subprocess.TimeoutExpired:
        print("\n❌ Test timed out after 120s")
        return False
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return False


def test_finalizer():
    """Test the finalizer agent."""
    print("\n\n" + "=" * 80)
    print("TEST 2: Linear Issue Finalizer")
    print("=" * 80)

    input_text = """Titolo: Fix login button UI
Descrizione iniziale: Il bottone di login non risponde al click su mobile
Figma: https://figma.com/file/example
Sito: https://app.example.com/login

Analisi Gemini:
Screenshot mostra un form con email/password e bottone blu 'Login'.
Il bottone ha padding inconsistente e non ha feedback visivo al tap.
Su iPhone 12 il bottone appare più piccolo del target touch raccomandato (44x44px).

Risposte utente:
1: Solo mobile, desktop già funziona
2: Deve funzionare anche offline con form validation lato client
3: Compatibilità iOS 14+ e Android 10+, browser Safari e Chrome
4: Target touch 44x44px minimo secondo Apple HIG
5: Feedback visivo: cambio colore + leggero scale down al tap
"""

    print("\nInput:")
    print("-" * 80)
    print(input_text)
    print("-" * 80)

    try:
        result = subprocess.run(
            ["claude", "--agent", "agents/linear_finalizer.md"],
            input=input_text,
            capture_output=True,
            text=True,
            timeout=120,
        )

        output = result.stdout.strip()

        print("\nOutput:")
        print("-" * 80)
        print(output)
        print("-" * 80)

        # Check if output is markdown
        required_sections = ["Problema", "Acceptance Criteria", "Approccio Tecnico"]
        has_sections = all(section in output for section in required_sections)

        if has_sections:
            print("\n✅ Valid markdown with required sections:")
            for section in required_sections:
                print(f"   ✓ {section}")
            return True
        print("\n❌ Missing required sections")
        missing = [s for s in required_sections if s not in output]
        print(f"   Missing: {missing}")
        return False

    except subprocess.TimeoutExpired:
        print("\n❌ Test timed out after 120s")
        return False
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return False


if __name__ == "__main__":
    print("\n🧪 Testing Claude Agent Prompts\n")

    test1 = test_question_generator()
    test2 = test_finalizer()

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Question Generator: {'✅ PASS' if test1 else '❌ FAIL'}")
    print(f"Finalizer:          {'✅ PASS' if test2 else '❌ FAIL'}")
    print()

    sys.exit(0 if (test1 and test2) else 1)
