# Symptom rule sources and review status

## Current status: zero active rules

`backend/symptom_rules.json` intentionally contains **zero active rules**
right now. No symptom-triage content in this project has been reviewed or
sourced by a qualified clinical source. This is a deliberate safety
decision, not an oversight - see the Phase 5.3 design notes.

The triage engine (`backend/symptom_triage.py`) is fully implemented and
tested against **synthetic fixture data only** (see
`backend/tests/test_symptom_triage.py`, whose fixtures are clearly labeled
"TEST MESSAGE" / "synthetic test fixture" and are never loaded by the
production path). Against the real, empty production rules file, every
input currently classifies as `"unknown"`.

## What must happen before any rule is added here

Before adding a single rule to `backend/symptom_rules.json`:

1. The specific symptom keywords, the assigned `urgency` tier, and the
   `message` wording must be reviewed by a qualified source - e.g. a
   licensed clinician, or adapted from a publicly published, appropriately
   licensed clinical triage guideline (for example, a national health
   service's published triage criteria). No such review has happened yet
   for this project, and this document does not claim one has.
2. The rule's `reference` field must point to that real, specific source
   (a document title, a URL, a named reviewer) - never a placeholder, and
   never fabricated. `symptom_triage.load_rules()` requires `reference` to
   be a non-empty string but does **not** verify its content is a genuine
   source; that verification is a human review step, not something this
   codebase can check automatically.
3. The addition should be reviewed the same way any other change to
   safety-relevant logic would be - not merged as routine content.

## Rule review tracking

No rules exist yet, so there is nothing to track. Once a rule is proposed,
record it here:

| Rule ID | Urgency | Source | Reviewed by | Date |
|---|---|---|---|---|
| *(none yet)* | | | | |

## Why this file exists

To make the "not yet clinically reviewed" status impossible to miss, and to
give future contributors (or an AI assistant working on a later phase) an
explicit, unambiguous gate to check before treating any rule content as
real guidance.
