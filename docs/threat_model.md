# Threat model and security boundary

## Protected-query adversary

The principal modeled adversary is an authenticated, authorized but curious
user who combines aggregate responses and may have auxiliary information to
infer facts about a person. The documented protected API restricts query forms,
enforces authentication/RBAC and dataset grants, applies sensitivity-aware
noise and shares a dataset budget across authorized users. SQL text is parsed
and compiled to allowlisted SQLAlchemy operations. Exact cached releases are
scoped by dataset/version, query identity and relevant release configuration.

## Research evaluator boundary

The experiment engine accepts only predefined scenario/configuration inputs,
generates synthetic in-memory data, and does not use registered production
datasets or the protected release ledger. Run retrieval/export are authorized
and owner scoped. It is a controlled evaluator, not a production attack
simulation or proof that attacks against arbitrary databases are blocked.

## Implemented controls and limits

| Threat | Implemented control | Remaining limitation |
|---|---|---|
| Spoofing | Hashed passwords, signed expiring JWTs, active-user checks | Logout is client token disposal; server-side token revocation is not implemented |
| Elevation of privilege | Backend RBAC dependencies, dataset grants, owner-scoped experiment access | Authorization correctness is tested in application code; this is not a third-party penetration test |
| SQL tampering/injection | SQLGlot validation, restricted query subset, bound SQLAlchemy operations | Arbitrary SQL, joins, groups and unsupported aggregates are rejected/not in scope |
| Inference through repeated outputs | Shared dataset nominal budget, release identity and exact cache reuse | History features are heuristic and cannot detect all inference strategies; DP guarantee is not established |
| Data disclosure in research records | No raw aggregate answers or employee rows in experiment records; minimal synthetic evidence is owner-scoped | Persisted target/inference evidence is still research-sensitive metadata and requires access controls |
| Availability/resource exhaustion | Input limits constrain experiment rows/trials/repetitions | Execution is synchronous; no background queue or comprehensive rate limiting/concurrency capacity result |
| Database compromise / trusted host | Out of scope | Host, OS, database administrator and credential compromise are not mitigated by this prototype |

## Privacy claim boundary

Production finite-precision Laplace sampling has no established formal
pure-ε or (ε,δ) guarantee. Adaptive epsilon allocation is heuristic, and the
full pipeline has no established end-to-end composition proof. Epsilon records
are `nominal_uncertified`. Do not describe the current system as formally DP
certified, or the synthetic attack evaluations as proof of attack prevention.
See `privacy_accounting.md`, `laplace_sampler_audit.md`,
`adaptive_policy.md` and `RESEARCH_LIMITATIONS.md`.
