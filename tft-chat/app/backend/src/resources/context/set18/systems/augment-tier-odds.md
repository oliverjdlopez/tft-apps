---
name: set-18-reference-systems-augment-tier-odds
description: Silver, Gold and Prismatic augment sequences and conditional branches. Use for augment-tier odds; rounded published totals are inconsistent.
kind: reference
sets: 18
---

# Augment tier sequences

Set 18 / patch 18.2 reference supplied September 20, 2026. Source revisions differ; this is not a guarantee of synchronization to 18.2b. Published disagreements and unspecified probabilities remain unresolved.

S = Silver, G = Gold, P = Prismatic. These are LBB’s displayed baseline sequences, before encounter-specific overrides.

| First | Second | Third | Listed sequence chance |
| --- | --- | --- | --- |
| S | S | G | 5% |
| S | S | P | 5% |
| S | G | G | 11% |
| S | G | P | 5% |
| S | P | P | 1% |
| G | S | G | 17% |
| G | S | P | 2% |
| G | G | G | 20% |
| G | G | P | 11% |
| G | P | S | 6% |
| G | P | G | 9% |
| G | P | P | 1% |
| P | S | G | 4% |
| P | S | P | 1% |
| P | G | G | 2% |
| P | G | P | 1% |
| P | P | G | 1% |
| P | P | P | 1% |

LBB separately displays these conditional branches:

| First (listed chance) | Second, conditional on first | Third, conditional on first two |
| --- | --- | --- |
| S (26%) | S 36%; G 61%; P 4% | SS: G/P 50%/50%; SG: G/P 71%/29%; SP: P 100% |
| G (65%) | S 28%; G 48%; P 24% | GS: G/P 90%/10%; GG: G/P 65%/35%; GP: S/G/P 35%/59%/6% |
| P (9%) | S 50%; G 30%; P 20% | PS: G/P 80%/20%; PG: G/P 67%/33%; PP: G/P 50%/50% |

**Source consistency flag:** sequence percentages total 103%; first-tier percentages total 100%, and the Silver second-tier branches total 101%. These are the graphic’s rounded published fields, not a reconstructed exact probability model. Do not renormalize them or derive precise conditional odds from the rounded sequence column. Encounter-conditioned distributions remain unresolved.
