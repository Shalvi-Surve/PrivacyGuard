# Mathematical model and assumptions

The restricted SQLite employee release path targets record-level pure epsilon
Differential Privacy under add/remove-one-record adjacency. For query function
`f`, global L1 sensitivity is `Delta f = max ||f(D) - f(D')||_1` over adjacent
datasets. The Laplace mechanism returns `f(D) + Lap(0, Delta f / epsilon)`.

COUNT has sensitivity `1` under add/remove-one-record adjacency. Each row
contributes once. SUM contributions are clipped to `[L,U]`. Under add/remove
adjacency, the absent row contributes zero, so `Delta SUM = max(|L|, |U|)`.
Under replace-one adjacency, the change is between two present clipped values,
so sensitivity is `U-L`. This release path uses add/remove adjacency for both
COUNT and SUM: configured salary bounds `[0,300000]` give sensitivity `300000`,
and performance-score bounds `[1,5]` give sensitivity `5`. AVG and grouped
aggregates remain unsupported. These are code-configured bounds for the
registered `employees` table (`salary: [0,300000]`, `performance_score:
[1,5]`); the current executor does not derive contribution bounds from
`DatasetMetadata.sensitivity` or accept per-query bounds. The restricted query
shape and dataset filter ensure one bounded contribution per selected employee
row; joins and grouped sums are rejected. Negative salary and score ranges are
not supported by this schema/configuration, although the sensitivity helper
implements and tests negative intervals for the general formula.

The implemented path applies inverse-CDF Laplace noise at scale
`Delta f / epsilon` using a cryptographic random source. Its production sampler
uses 53 random bits and clamps away from the inverse-CDF endpoints to keep the
floating-point result finite. This creates a discretized, bounded-tail
approximation to ideal Laplace noise; it is not an exact real-valued Laplace
sampler, and no formal pure-epsilon guarantee for that finite-precision
implementation is claimed. The dataset-level accountant composes recorded
epsilon values by addition and reserves the shared budget inside the release
transaction. The current epsilon policy also depends on query-history
heuristics, so the classic fixed-epsilon Laplace theorem alone does not
formally establish the full history-adaptive selection pipeline. No calibrated
attack-risk result or experimental finding is claimed.

## Adaptive policy and accounting status

The implemented policy defines bounded query-history features, a weighted risk
heuristic, and nominal epsilon allocation. History overlap is included once in
`R`; cumulative budget utilization is a separate term. The exact feature
normalizations and defaults are documented in
[adaptive_policy.md](adaptive_policy.md). The allocator's output is a nominal
mechanism parameter and does not itself imply a formal DP guarantee. The
ledger sums nominal epsilon for newly generated distinct releases; cached
exact reuse adds zero. Because finite-precision sampling and the full adaptive
composition have no established formal proof, this sum is not certified
privacy expenditure and no end-to-end formal DP claim is made.
