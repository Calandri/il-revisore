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

TurboWrap is a multi-agent code review system. Each agent has a specific role and together they provide a complete review.

### Agent Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         REVIEWER AGENTS                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                        ORCHESTRATOR                              │    │
│  │            Coordinates the complete review process               │    │
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

### Development Agents (Code Writing)

Use them when you need to **write** or **implement** code.

#### `dev_be` - Backend Developer
| Attribute | Value |
|-----------|-------|
| **When to use** | Implement endpoints, DB queries, caching, Lambda functions |
| **Stack** | Python, FastAPI, MySQL, Redis, AWS |
| **Model** | Claude Opus 4.5 |
| **Color** | 🟢 Green |

**Usage examples:**
- "Create an endpoint to fetch reports by site ID"
- "How do I configure Redis caching for user preferences?"
- "The SQL query returns no results, help me debug"

#### `dev_fe` - Frontend Developer
| Attribute | Value |
|-----------|-------|
| **When to use** | Create OASI components, charts, feature flags, theme variants |
| **Stack** | React, Next.js, TypeScript, Tailwind Variants |
| **Model** | Claude Opus 4.5 |
| **Color** | 🔴 Red |

**Usage examples:**
- "Create a chart component for the monitoring section"
- "Add dark/light mode support to this card"
- "Implement lazy loading for this heavy component"

---

### Review Agents (Code Review)

Use them to **verify** existing or newly written code.

#### `reviewer_be` - Backend Reviewer
| Attribute | Value |
|-----------|-------|
| **When to use** | Review Python/FastAPI code |
| **Focus** | Security, performance, architecture, patterns |
| **Model** | Claude Opus 4.5 |
| **Color** | 🟢 Green |

**What it checks:**
- SQL injection, hardcoded secrets
- N+1 queries, missing indexes
- Layer separation (apis → services → repositories)
- Type annotations, error handling

#### `reviewer_fe_architecture` - Frontend Architecture Reviewer
| Attribute | Value |
|-----------|-------|
| **When to use** | Verify structure and patterns of React components |
| **Focus** | Component structure, hook ordering, folder organization |
| **Model** | Claude Opus 4.5 |
| **Color** | 🟠 Orange |

**What it checks:**
- Hook ordering (9-step order)
- Props in `.props.ts` files
- Two-level chart architecture
- No `index.tsx` files
- State management patterns
- i18n usage

#### `reviewer_fe_quality` - Frontend Quality Reviewer
| Attribute | Value |
|-----------|-------|
| **When to use** | Verify quality, performance and security of frontend code |
| **Focus** | TypeScript strictness, performance, security, a11y |
| **Model** | Claude Opus 4.5 |
| **Color** | 🟠 Orange |

**What it checks:**
- Zero tolerance for `any`
- `useMemo`/`useCallback` usage
- Memory leaks in useEffect
- XSS vulnerabilities
- Accessibility (alt text, ARIA)
- Web Vitals optimization

---

### Analysis Agents

#### `analyst_func` - Functional Analyst
| Attribute | Value |
|-----------|-------|
| **When to use** | Verify functional correctness and business logic |
| **Focus** | Requirements, edge cases, user flows, data integrity |
| **Model** | Claude Opus 4.5 |
| **Color** | 🟣 Purple |

**What it checks:**
- Are requirements implemented correctly?
- Are edge cases handled?
- Do user flows work?
- Are calculations/formulas correct?
- Is the API contract respected?

---

### Orchestration

#### `orchestrator` - Review Orchestrator
| Attribute | Value |
|-----------|-------|
| **When to use** | Automatically for complete PR reviews |
| **Focus** | Coordination, results aggregation, unified report |
| **Model** | Claude Opus 4.5 |
| **Color** | 🔵 Blue |

**Workflow:**
1. Detects repository type (BE/FE/Full-stack)
2. Launches appropriate reviewers in parallel
3. Applies Challenger Pattern (Gemini validates review)
4. Aggregates results and deduplicates issues
5. Generates unified report

---

### Decision Matrix: Which Agent to Use?

| Scenario | Agent(s) |
|----------|----------|
| "I need to implement an endpoint" | `dev_be` |
| "I need to create a React component" | `dev_fe` |
| "Review my Python code" | `reviewer_be` |
| "Review my React component" | `reviewer_fe_architecture` + `reviewer_fe_quality` |
| "Does the code do what it should?" | `analyst_func` |
| "Complete review of a PR" | `orchestrator` (launches all) |
| "I have a bug in business logic" | `analyst_func` |
| "I have a memory leak" | `reviewer_fe_quality` |
| "Where do I put props?" | `reviewer_fe_architecture` |

---

### Comparison: Architecture vs Quality vs Analyst

```
                    FRONTEND REVIEW
                          │
      ┌───────────────────┼───────────────────┐
      │                   │                   │
      ▼                   ▼                   ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│  ARCHITECTURE │ │    QUALITY    │ │   ANALYST     │
├───────────────┤ ├───────────────┤ ├───────────────┤
│ HOW it's      │ │ HOW WELL      │ │ WHAT the      │
│ organized     │ │ it's written  │ │ code does     │
├───────────────┤ ├───────────────┤ ├───────────────┤
│ • Hook order  │ │ • TypeScript  │ │ • Requirements│
│ • Folder      │ │ • Performance │ │ • Edge cases  │
│   structure   │ │ • Security    │ │ • User flows  │
│ • Props files │ │ • Memory      │ │ • Calculations│
│ • Patterns    │ │ • A11y        │ │ • Integrations│
└───────────────┘ └───────────────┘ └───────────────┘
```

---

### Challenger Pattern

TurboWrap uses a dual-reviewer system to ensure quality:

```
REVIEWER (Claude Opus)  ──►  CHALLENGER (Gemini)
        │                           │
        │    Initial review         │
        ├──────────────────────────►│
        │                           │ Evaluates completeness
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
