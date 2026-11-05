# Roadmap

Out of scope in v1, with rationale and a v2 proposal.

| Item | Why out of v1 | v2 proposal |
|---|---|---|
| Purchase-side reconciliation (ATS `compras` vs 104's 509/529) | The sales checks already prove the seam; the purchase side needs the sustento/authorization discipline of vendor documents in the fixture | Same two-check shape over `collect_compras` rows |
| Automatic period close on match | A match is evidence, not a filing; closing books is a human decision | Workflow state on the wizard, never automatic |
| Multi-period drift tracking | One period's verdict does not explain the next; needs a stored history | Persisted verdicts per period with a trend view |
