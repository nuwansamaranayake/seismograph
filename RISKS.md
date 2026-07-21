# Risk Register — Seismograph

A living register for a probabilistic system. Each risk has an owner, a concrete tripwire (an
observable signal that fires *before* the risk becomes an incident), and a status. Reviewed each
release; new risks are appended rather than edited away.

| Risk | Owner | Tripwire | Status |
|---|---|---|---|
| Embedding-model drift silently corrupts the consistency baseline, so a stable system reads as changed — or a changed one reads as stable — and every downstream metric inherits the error. | eng lead | Re-embedding the frozen baseline probe set diverges from the stored baseline vectors beyond a set cosine tolerance, **or** the pinned embedding-model version string changes between two baseline windows. | open |
| Metamorphic variants subtly change meaning, so an "invariance" failure is really the variant asking a different question — a false alarm that erodes trust in the gate. | eng lead | The back-check rejection rate on generated variants moves outside its historical band, **or** a sampled audit of accepted variants falls below the NLI-entailment / embedding-similarity floor. | open |

Mitigations are tracked in the linked issues: pin embedding versions per baseline window and
re-baseline explicitly (never silently); route every variant through the deterministic
embedding-plus-NLI back-check and log every reject to the failure gallery.
