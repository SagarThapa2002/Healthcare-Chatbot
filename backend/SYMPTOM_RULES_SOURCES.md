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

## Emergency signposting (live) - separate from the triage rules above

`backend/emergency_signposting.py` is live, and is **not** the triage engine
above (which stays disconnected, with zero rules). It exists because the chat
must never answer an emergency message with an ordinary reply: before this
existed, "crushing chest pain" was told to "keep an eye on it", and "I can't
breathe", "I want to kill myself" and "my child swallowed bleach" got a
greeting.

**What it does:** for a Symptom Check or General FAQ message - the only
requests that carry the user's own text - it checks a deliberately small set
of explicit red-flag phrases *before* the ordinary symptom reply and before
any LLM call. A match returns a fixed reply pointing to 999, NHS 111 or
Samaritans. It never calls an LLM, never diagnoses or names a condition,
gives no treatment advice beyond two NHS "do not" warnings for poisoning, and
never echoes or logs the user's text.

**What it is not:** a clinical triage system or an emergency detector. The
rule set is intentionally small; **no match never means a situation is safe**.
The chatbot is not an emergency service and cannot contact anyone. Anyone who
thinks there is an emergency should call 999 directly.

**Scope: UK only.** 999, NHS 111 and Samaritans 116 123 are UK services; every
reply says "(UK numbers.)".

**Known limits:**
- Only free text sent as a symptom or general question is checked. Text typed
  into a booking, cancellation or update step (for example as a name) is
  treated as that field and is not checked.
- Phrases are matched literally (case, punctuation and spacing do not
  matter); different wording of the same emergency may not match.
- Plain "chest pain" with none of the NHS 999 qualifiers (tight, heavy,
  squeezing, spreading to the arms, neck or jaw) is not matched; it gets the
  ordinary symptom reply, which itself points to NHS 111 and 999.

### Categories and sources

All sources were accessed on 3 October 2026. The "reviewed" dates in the
table are each page's own "page last reviewed" date, not the access date.
Reply wording is paraphrased from these sources, not copied; the poisoning
reply's "do not try to make them sick or give them anything to eat or drink"
closely follows the NHS poisoning page's own warnings.

| Category | Phrases (summary) | Reply points to | Source |
|---|---|---|---|
| Physical emergency | chest pain that is crushing, squeezing, tight or heavy, or with the arm, neck or jaw; can't breathe, severe difficulty breathing, gasping, choking, not breathing; lips, skin or face blue or grey; unconscious or unresponsive | 999 now; NHS 111 if unsure it is an emergency | NHS, *Heart attack* (reviewed 31 Mar 2026) https://www.nhs.uk/conditions/heart-attack/ ; NHS, *Shortness of breath* (reviewed 30 Jan 2024) https://www.nhs.uk/conditions/shortness-of-breath/ ; NHS, *Poisoning* (unconscious, not breathing) |
| Poisoning | swallowed, drank or ate bleach, poison, weedkiller, antifreeze, detergent, a cleaning product or a button battery; overdose; took too many pills | 999 if unconscious, not breathing, severe difficulty breathing or a seizure, otherwise NHS 111 straight away; do not make them sick or give food or drink | NHS, *Poisoning* (reviewed 12 Jun 2025) https://www.nhs.uk/conditions/poisoning/ ; NHS, *Where to get urgent help for mental health* (overdose) |
| Crisis (suicide, self-harm) | kill myself; end or take my (own) life; commit suicide; suicidal; want to die; don't want to live or be alive; hurt, harm or cut myself; self-harm | 999 if hurt, might act on the thoughts or can't keep safe; Samaritans 116 123 (free, any time); NHS 111 mental health option | NHS, *Where to get urgent help for mental health* (reviewed 26 Apr 2023) https://www.nhs.uk/nhs-services/mental-health-services/where-to-get-urgent-help-for-mental-health/ ; Samaritans, *Contact a Samaritan* https://www.samaritans.org/how-we-can-help/contact-samaritan/ |

General service descriptions: NHS, *When to call 999* (reviewed 3 Feb 2023)
https://www.nhs.uk/nhs-services/urgent-and-emergency-care-services/when-to-call-999/
and *When to use 111* (reviewed 14 Nov 2022)
https://www.nhs.uk/nhs-services/urgent-and-emergency-care-services/when-to-use-111/ .

Crisis phrases cover explicit statements of suicidal intent or self-harm only,
not low mood. If a message contains crisis wording together with a physical
or poisoning red flag, the physical/poisoning reply is given with the
Samaritans number added.

Any change to these phrases or replies is a safety change: check it against
the sources above and update `backend/tests/test_emergency_signposting.py`.
