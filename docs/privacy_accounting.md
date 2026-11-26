# Privacy accounting

The initial accountant charges a shared dataset budget using one SQL `UPDATE`
with a balance predicate. It increments consumed epsilon and adds a ledger event
in the caller's transaction. The caller commits only after the protected
output is prepared and rolls back if execution or noise generation fails. The
dataset budget is independent of the requesting account, so separate user
identities do not receive separate copies of this shared budget.

The ledger sums nominal epsilon for distinct newly generated releases. Basic
sequential composition would give `epsilon_total = sum(epsilon_i)` for pure
epsilon-DP mechanisms under its assumptions, but the production finite-
precision sampler and complete adaptive pipeline have no established formal
DP proof. The ledger is therefore marked `nominal_uncertified`, not certified
privacy expenditure. Warning and restriction states use configured
thresholds. The accountant's conditional update is the shared dataset
reservation; release, history, audit and ledger are committed in the same
transaction. Budget metadata is validated; inconsistent or missing accounting
data fails closed for new releases.

## Release reuse

The API uses a stable lookup key over dataset ID and version, canonical query
fingerprint, normalized query including literal parameter values, effective
authorized role scope, policy version, mechanism, sensitivity, clipping bounds,
and adjacency model, including the epsilon selected by the adaptive policy.
The stored release also has a configuration digest. An exact lookup match
returns the stored noisy output and creates history/audit metadata without a
new ledger charge. If history or cumulative spend changes the adaptive epsilon,
the request has a different cache identity and creates a separately charged
release (if affordable). Thus changed allocations cannot reuse incompatible
outputs. All users still charge the same dataset budget. The current dataset
version starts at 1; mutation/version bumping for imported or edited data is
not implemented yet.

The lookup identity uses normalized query values in addition to the structural
fingerprint because the latter intentionally abstracts literal values. Dataset
ID/version and authorization scope prevent cross-dataset, cross-version, or
cross-scope cache reuse. Existing releases created before these cache columns
were introduced have no lookup identity and are not treated as compatible.

The accountant does not itself prove that a release is differentially private.
A valid guarantee also depends on adjacency, sensitivity, clipping, noise
calibration, and correct release handling. History-dependent epsilon selection
is a heuristic and the complete adaptive selection pipeline has no formal DP
proof in this prototype. See [mathematical model](mathematical_model.md) and
[adaptive policy](adaptive_policy.md).
