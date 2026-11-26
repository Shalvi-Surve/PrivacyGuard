# Finite-precision Laplace sampler audit

## Implementation

`laplace_noise` draws `k = secrets.randbelow(2**53)`, a uniformly selected
integer in `[0, 2**53)` under the standard library's operating-system-backed
cryptographic random source. The production path does not use the seeded
`random.Random` helper; that helper is named and documented for controlled
synthetic experiments only. This is a cryptographic pseudorandomness
assumption, not an information-theoretic proof about the physical source.

The uniform transform computes
`u = k / 2**53 - 0.5`, then clamps to the representable open interval using
`nextafter`. For nonzero `k`, the values are paired by `k <-> 2**53-k` and
produce opposite noise in exact arithmetic. The `k=0` word first maps to
`-0.5` and is clamped to `-0.5 + 2**-54`. The largest word maps to
`+0.5 - 2**-53`; the upper clamp is not reached for that word.

For `b = sensitivity / epsilon`, the inverse-CDF expression is
`z = -b sign(u) log1p(-2 |u|)`. Therefore the sampled noise has finite support
and at most `2**53` source outcomes. In exact arithmetic, its extremes are
`-53 ln(2) b` and `+52 ln(2) b`. Each extreme is selected by one source word
(probability `2**-53` before any floating-point collisions). The support is
asymmetric; the idealized grid's mean has a small negative endpoint bias of
`-53 ln(2) b / 2**53`. Floating-point `log1p`, multiplication and the later
aggregate addition can introduce additional rounding and collisions.

The maximum representable tail is about `36.74 b` on the negative side and
`36.04 b` on the positive side. Noise is thus tail-truncated, discretized and
not an ideal continuous Laplace random variable. At very small scales, division
or multiplication can underflow to zero; scale overflow and non-finite final
outputs are rejected. The protected-query configuration currently uses
epsilon in `[0.1, 1]` and sensitivities `1`, `5`, or `300000`, so scale
underflow is not reachable through the supported release route.

## Privacy assessment

The ideal continuous Laplace mechanism's pure-epsilon proof does not transfer
to this sampler. For an additive query whose values differ by nonzero `d`, the
ideal-real sampled noise has finite support `S`, while neighboring outputs have
supports `a+S` and `a+d+S`. A finite set cannot equal a nonzero translate of
itself, so at least one output atom has positive probability under one input
and zero probability under the other. That violates pure epsilon-DP for every
finite epsilon.

For example, under the idealized addition model, compare an empty dataset with
a one-record COUNT dataset. With sensitivity `Delta=1`, choose the endpoint
output for `k=0`. It has probability `2**-53` on the empty dataset and is below
the minimum output on the neighboring dataset, so any approximate-DP claim for
this pair must have `delta >= 2**-53`. The current code has not derived an upper
bound on the hockey-stick divergence
`sum_y max(P(y) - exp(epsilon) Q(y), 0)` for its actual rounded output
distribution. The endpoint bound is necessary, not sufficient; it is not a
claim that the sampler is `(epsilon, 2**-53)`-DP.

Consequently, the current sampler has only an empirical approximation to
ideal Laplace behavior. No pure-epsilon guarantee or nontrivial
`(epsilon, delta)` guarantee is established for the production floating-point
mechanism. Moreover, the adaptive epsilon policy and full system composition
need a separate proof even after replacing the sampler.

## Alternative assessment

1. **Finite-precision continuous sampling:** retain the float-valued output
   while adopting a published construction with a proof that explicitly covers
   the machine arithmetic and output domain. A bounded-tail sampler must either
   be analyzed with a valid delta bound or avoid falsely claiming pure DP. Do
   not treat a generic inverse-CDF implementation or a larger random word as a
   proof. Mironov's analysis documents support and rounding attacks on textbook
   floating-point Laplace sampling.
2. **Discrete Laplace / two-sided geometric:** for integer salary sums, release
   integer noise from a two-sided geometric distribution and keep the result on
   an integer lattice. Its exact probability mass function can be analyzed
   under the integer query sensitivity. For performance scores, first define
   and validate a fixed-point unit (for example tenths) and derive sensitivity
   in those units. The sampler must use unbiased cryptographic integer sampling,
   with termination/runtime and numeric bounds included in the implementation
   review. A truncated geometric sampler is not automatically pure DP.
3. **Audited library implementation:** prefer a pinned, reviewed implementation
   with an explicit finite-arithmetic argument and supported parameter domain.
   Google's differential-privacy library documents a geometric-based Laplace
   implementation and a secure-noise analysis. OpenDP documents both exact
   rational treatment for some float mechanisms and the limitations of APIs
   that assume idealized numerics. Neither should be adopted by name alone:
   verify the chosen API's concrete proof, input domain, output representation,
   version, and composition model before changing this release API.

No production sampler replacement is made by this audit.
