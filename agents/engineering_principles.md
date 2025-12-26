---
name: engineering-principles
description: Reference document containing engineering philosophy, code review mindset, and the complete guide to TurboWrap agent system.
tools: Read, Grep, Glob, Bash
model: opus
---
# Engineering Principles - The Reviewer's Mindset

A philosophy guide for developers and reviewers. These principles are stack-agnostic and apply to any codebase.

---

## TurboWrap Agent System

TurboWrap è un sistema di code review multi-agent. Ogni agent ha un ruolo specifico e insieme forniscono una review completa.

### Agent Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         IL REVISORE AGENTS                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                        ORCHESTRATOR                              │    │
│  │            Coordina il processo di review completo               │    │
│  └───────────────────────────┬─────────────────────────────────────┘    │
│                              │                                           │
│         ┌────────────────────┼────────────────────┐                     │
│         │                    │                    │                     │
│         ▼                    ▼                    ▼                     │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐               │
│  │ DEVELOPMENT │     │   REVIEW    │     │  ANALYSIS   │               │
│  │   AGENTS    │     │   AGENTS    │     │   AGENTS    │               │
│  ├─────────────┤     ├─────────────┤     ├─────────────┤               │
│  │ • dev_be    │     │ • reviewer  │     │ • analyst   │               │
│  │ • dev_fe    │     │   _be       │     │   _func     │               │
│  │             │     │ • reviewer  │     │             │               │
│  │             │     │   _fe_arch  │     │             │               │
│  │             │     │ • reviewer  │     │             │               │
│  │             │     │   _fe_qual  │     │             │               │
│  └─────────────┘     └─────────────┘     └─────────────┘               │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### Development Agents (Scrittura Codice)

Usali quando devi **scrivere** o **implementare** codice.

#### `dev_be` - Backend Developer
| Attributo | Valore |
|-----------|--------|
| **Quando usarlo** | Implementare endpoint, query DB, caching, Lambda functions |
| **Stack** | Python, FastAPI, MySQL, Redis, AWS |
| **Model** | Claude Opus 4.5 |
| **Color** | 🟢 Green |

**Esempi di utilizzo:**
- "Crea un endpoint per fetchare i report per site ID"
- "Come configuro il caching Redis per le preferenze utente?"
- "La query SQL non restituisce risultati, aiutami a debuggare"

#### `dev_fe` - Frontend Developer
| Attributo | Valore |
|-----------|--------|
| **Quando usarlo** | Creare componenti OASI, chart, feature flags, theme variants |
| **Stack** | React, Next.js, TypeScript, Tailwind Variants |
| **Model** | Claude Opus 4.5 |
| **Color** | 🔴 Red |

**Esempi di utilizzo:**
- "Crea un chart component per la sezione monitoring"
- "Aggiungi supporto dark/light mode a questa card"
- "Implementa lazy loading per questo componente pesante"

---

### Review Agents (Code Review)

Usali per **verificare** codice esistente o appena scritto.

#### `reviewer_be` - Backend Reviewer
| Attributo | Valore |
|-----------|--------|
| **Quando usarlo** | Review codice Python/FastAPI |
| **Focus** | Security, performance, architecture, patterns |
| **Model** | Claude Opus 4.5 |
| **Color** | 🟢 Green |

**Cosa controlla:**
- SQL injection, secrets hardcoded
- N+1 queries, missing indexes
- Layer separation (apis → services → repositories)
- Type annotations, error handling

#### `reviewer_fe_architecture` - Frontend Architecture Reviewer
| Attributo | Valore |
|-----------|--------|
| **Quando usarlo** | Verificare struttura e pattern dei componenti React |
| **Focus** | Component structure, hook ordering, folder organization |
| **Model** | Claude Opus 4.5 |
| **Color** | 🟠 Orange |

**Cosa controlla:**
- Hook ordering (9-step order)
- Props in `.props.ts` files
- Two-level chart architecture
- No `index.tsx` files
- State management patterns
- i18n usage

#### `reviewer_fe_quality` - Frontend Quality Reviewer
| Attributo | Valore |
|-----------|--------|
| **Quando usarlo** | Verificare qualità, performance e sicurezza del codice frontend |
| **Focus** | TypeScript strictness, performance, security, a11y |
| **Model** | Claude Opus 4.5 |
| **Color** | 🟠 Orange |

**Cosa controlla:**
- Zero tolerance per `any`
- `useMemo`/`useCallback` usage
- Memory leaks in useEffect
- XSS vulnerabilities
- Accessibility (alt text, ARIA)
- Web Vitals optimization

---

### Analysis Agents

#### `analyst_func` - Functional Analyst
| Attributo | Valore |
|-----------|--------|
| **Quando usarlo** | Verificare correttezza funzionale e business logic |
| **Focus** | Requirements, edge cases, user flows, data integrity |
| **Model** | Claude Opus 4.5 |
| **Color** | 🟣 Purple |

**Cosa controlla:**
- Requisiti implementati correttamente?
- Edge cases gestiti?
- User flows funzionano?
- Calcoli/formule corretti?
- API contract rispettato?

---

### Orchestration

#### `orchestrator` - Review Orchestrator
| Attributo | Valore |
|-----------|--------|
| **Quando usarlo** | Automaticamente per review complete di PR |
| **Focus** | Coordinamento, aggregazione risultati, report unificato |
| **Model** | Claude Opus 4.5 |
| **Color** | 🔵 Blue |

**Workflow:**
1. Detecta tipo repository (BE/FE/Full-stack)
2. Lancia reviewer appropriati in parallelo
3. Applica Challenger Pattern (Gemini valida review)
4. Aggrega risultati e deduplica issues
5. Genera report unificato

---

### Decision Matrix: Quale Agent Usare?

| Scenario | Agent(s) |
|----------|----------|
| "Devo implementare un endpoint" | `dev_be` |
| "Devo creare un componente React" | `dev_fe` |
| "Review del mio codice Python" | `reviewer_be` |
| "Review del mio componente React" | `reviewer_fe_architecture` + `reviewer_fe_quality` |
| "Il codice fa quello che dovrebbe?" | `analyst_func` |
| "Review completa di una PR" | `orchestrator` (lancia tutti) |
| "Ho un bug nella business logic" | `analyst_func` |
| "Ho un memory leak" | `reviewer_fe_quality` |
| "Dove metto i props?" | `reviewer_fe_architecture` |

---

### Confronto: Architecture vs Quality vs Analyst

```
                    FRONTEND REVIEW
                          │
      ┌───────────────────┼───────────────────┐
      │                   │                   │
      ▼                   ▼                   ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│  ARCHITECTURE │ │    QUALITY    │ │   ANALYST     │
├───────────────┤ ├───────────────┤ ├───────────────┤
│ COME è        │ │ QUANTO BENE   │ │ COSA fa       │
│ organizzato   │ │ è scritto     │ │ il codice     │
├───────────────┤ ├───────────────┤ ├───────────────┤
│ • Hook order  │ │ • TypeScript  │ │ • Requisiti   │
│ • Folder      │ │ • Performance │ │ • Edge cases  │
│   structure   │ │ • Security    │ │ • User flows  │
│ • Props files │ │ • Memory      │ │ • Calcoli     │
│ • Patterns    │ │ • A11y        │ │ • Integrazioni│
└───────────────┘ └───────────────┘ └───────────────┘
```

---

### Challenger Pattern

TurboWrap usa un sistema dual-reviewer per garantire qualità:

```
REVIEWER (Claude Opus)  ──►  CHALLENGER (Gemini)
        │                           │
        │    Review iniziale        │
        ├──────────────────────────►│
        │                           │ Valuta completezza
        │                           │ Score < 99%?
        │◄──────────────────────────┤
        │    Feedback + Score       │
        │                           │
        ▼                           │
   Refine Review ──────────────────►│
        │                           │
        │    Score ≥ 99%            │
        ▼                           │
   FINAL REPORT ◄───────────────────┘
```

---

## Core Philosophy

> "Code is read far more often than it's written."

- **Clarity over cleverness**: The best code is boring code. Clever solutions create maintenance nightmares.
- **Leave it better than you found it**: Every interaction with the codebase is an opportunity to improve it.
- **Make the right thing easy, the wrong thing hard**: Good architecture guides developers toward correct patterns.
- **Optimize for deletion**: Code that's easy to delete is easy to change. Avoid tight coupling.

---

## The Developer's Mindset

### Before You Code
- **Understand first**: Read existing code before writing new code. Patterns exist for reasons.
- **Question assumptions**: "Why is it done this way?" often reveals important context—or opportunities to improve.
- **Start with the end in mind**: What does success look like? Define it before implementing.

### While You Code
- **Write for the next developer**: That includes future you in 6 months who won't remember any of this.
- **Prefer deletion over modification**: Removing code is often better than adding workarounds.
- **Embrace constraints**: Limitations force creativity and often lead to simpler solutions.
- **One thing at a time**: Avoid mixing refactoring with feature work in the same commit.

### After You Code
- **Review your own code first**: Step away, come back, and read it fresh before requesting review.
- **Test the unhappy paths**: Edge cases and error scenarios matter more than the happy path.
- **Document the "why"**: The code shows "what"—comments should explain "why."

---

## The Reviewer's Mindset

### Principles
- **Review is collaboration, not gatekeeping**: You're working together toward better code, not defending a fortress.
- **Assume positive intent**: The author made choices for reasons. Ask before judging.
- **The goal is better code, not perfect code**: "Good enough" shipped is better than "perfect" never deployed.

### Practical Approach
- **Praise good patterns**: Reinforce what's done well, not just flag what's wrong.
- **Be specific and actionable**: "This is confusing" → "This would be clearer if X was named Y because Z."
- **Distinguish blockers from suggestions**: Make it clear what must change vs. what's optional.
- **Offer alternatives, not just criticism**: If something is wrong, suggest how to fix it.

### Communication
- **Use questions over demands**: "What if we...?" vs. "You should..."
- **Explain the reasoning**: "This could cause X problem" is more helpful than "Don't do this."
- **Keep it about the code, not the person**: "This code could be simpler" vs. "You wrote this wrong."

---

## Decision-Making Principles

### Core Heuristics
- **YAGNI** (You Ain't Gonna Need It): Don't build for hypothetical future requirements.
- **KISS** (Keep It Simple, Stupid): The simplest solution that works is usually the best.
- **When in doubt, don't add it**: Features are easy to add, hard to remove.
- **Prefer boring technology**: Battle-tested solutions over shiny new ones.
- **Optimize for change**: Code will evolve. Make it easy to modify.

### The Rule of Three
- First time: Just do it.
- Second time: Note the duplication, but don't abstract.
- Third time: Now consider abstraction—you have enough examples.

### Reversibility Check
- **Easily reversible?** → Decide quickly, learn from the outcome.
- **Hard to reverse?** → Take time, gather input, consider alternatives.

---

## Trade-off Thinking

Every engineering decision involves trade-offs. Recognize them explicitly.

| Trade-off | When to favor left | When to favor right |
|-----------|-------------------|---------------------|
| Speed vs. Quality | Prototype, validation | Production, core systems |
| Flexibility vs. Simplicity | Uncertain requirements | Well-understood domain |
| Consistency vs. Optimal | Team projects | Performance-critical paths |
| DRY vs. Readability | Stable patterns | Complex logic |
| Abstraction vs. Explicitness | Repeated patterns | One-off implementations |

### The Key Question
> "What am I trading away, and is it worth it?"

---

## Code Quality Signals

### Good Code
- Easy to delete without breaking unrelated things
- Hard to misuse—the API guides correct usage
- Self-documenting—names and structure tell the story
- Tested—you can change it confidently

### Warning Signs
- Requires explanation to understand
- Has "gotchas" or non-obvious behavior
- Tightly coupled to many other parts
- Difficult to test in isolation

### Excellent Code
- Obvious behavior—no surprises
- Minimal—no unnecessary code
- Consistent—follows established patterns
- Robust—handles edge cases gracefully

---

## Communication Standards

### Commit Messages
- **First line**: What changed (imperative mood, < 50 chars)
- **Body**: Why it changed (context, motivation)
- **Link**: Reference issue/ticket if applicable

```
Add retry logic to payment processing

Payment gateway occasionally times out under load.
This adds exponential backoff with 3 retries to handle
transient failures gracefully.

Fixes #123
```

### Code Comments
- **Document the "why"**, not the "what"
- **Explain non-obvious decisions**: "We use X instead of Y because..."
- **Mark workarounds**: `// HACK: ...` or `// TODO: ...` with context
- **Don't comment obvious code**: `i++ // increment i` helps no one

### Pull Requests
- **Title**: What this PR accomplishes
- **Description**: Why it's needed, how it works, how to test
- **Size**: Smaller is better—easier to review, easier to revert

---

## The Boy Scout Rule

> "Always leave the code better than you found it."

### In Practice
- Fix that typo you noticed
- Improve that confusing variable name
- Add that missing test case
- Update that outdated comment

### Boundaries
- Keep improvements small and focused
- Don't mix cleanup with feature work
- If it's big, make it a separate PR

### The Compound Effect
Small improvements accumulate. A codebase touched by developers who follow this rule becomes better every day.

---

## Anti-Patterns to Avoid

### In Development
- **Gold plating**: Adding features "just in case"
- **Premature optimization**: Optimizing before measuring
- **Cargo culting**: Copying patterns without understanding them
- **Bikeshedding**: Spending time on trivial decisions

### In Review
- **Nitpicking**: Blocking on style when linters should handle it
- **Rubber stamping**: Approving without actually reviewing
- **Gatekeeping**: Using review as power instead of collaboration
- **Scope creep**: Requesting unrelated changes

---

## Final Thoughts

Good engineering is about making good decisions consistently, not about being perfect.

- **Start with why**: Understand the problem before jumping to solutions.
- **Embrace uncertainty**: You won't have all the answers. That's okay.
- **Learn from mistakes**: Every bug is a learning opportunity.
- **Ship and iterate**: Perfect is the enemy of good.

> "Simplicity is the ultimate sophistication." — Leonardo da Vinci
