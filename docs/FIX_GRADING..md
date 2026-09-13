# Fix — grading is miscalibrated

A real report came back reading **"C · Score 91/100"**. The letter is defensible; the number is not, and printing both on the cover makes the report contradict itself. This has to be right before it goes to prospects — the whole product rests on the grade being trustworthy.

Do not start coding. Work through steps 1 and 2 and show me your analysis first.

---

## 1. Understand the two faults

### Fault A — severity is diluted to nothing

§9 deducts per finding *within a module*, then takes a weighted mean. A high finding costs 25 points inside its module, but headers carries 16% weight — so a missing HSTS header costs the overall score roughly 4 points.

Work the real example and confirm my arithmetic:

`outsideinteractive.com` — headers module scored 53 (an E) on five separate header failures including a high. DNS 96, email auth 90, everything else 100. Weighted mean lands at ~91, an A. Only the two-high cap pulled it to C.

The caps in step 4 exist to compensate for that dilution. They're a patch over a broken score, and they're blunt: two highs and eight highs both yield C, so `badssl.com` at 82 and this site at 91 receive the same letter despite one being clearly worse. The grade has stopped discriminating.

### Fault B — readiness has weight 0 but caps the grade

`readiness` is weighted **0** in §9 step 2 — declared informational. Yet `READINESS_MANUAL_2027` is severity `high` and feeds step 4's cap. A module that contributes nothing to the score is half the reason this report dropped three bands.

That's incoherent on its own terms. It's also backwards commercially: the March 2027 readiness verdict is the product's core differentiator, and right now it's the finding doing the most damage to our credibility.

---

## 2. Propose a fix — here's my starting point, but validate it

**Principle: the grade must always be the band the score falls into.** No caps that make the letter and number disagree. If a site deserves a C, the score should be in the C range. Fix the score; stop patching the letter.

Suggested shape — a global severity deduction applied alongside the weighted mean, with the final score being the lower of the two:

```
weighted  = existing §9 step 2 weighted mean
global    = 100 − (critical×40 + high×12 + medium×5 + low×1)
score     = min(weighted, global), clamped to [0, 100]
grade     = band(score)        # §9 step 3, unchanged
```

Only one override survives: **any critical finding forces F**, because a hostname-mismatched or expired certificate is a categorical failure, not a matter of degree.

Run it against the four scans we already have and tell me whether the outputs are defensible:

| Domain | Findings | Current | Proposed |
|---|---|---|---|
| sundram.tech | 2 low | A+ 98 | ~A+ 98 |
| google.com | 1 high, 1 med, 3 low | A 90 (letter A) | ~B 80 |
| outsideinteractive.com | 2 high, 2 med, 4 low | **C 91** | ~D 62 |
| badssl.com | 2 high, 3 med, 7 low | C 82 | ~E 54 |

**Check these yourself — I worked them by hand and may have erred.** If D for outsideinteractive.com feels too harsh, say so and propose different coefficients. The targets are: the score and letter always agree, a worse site always scores lower than a better one, and a clean site still reaches A+.

### Readiness weight

Also fix Fault B. Two options — pick one and justify it:

- **Give readiness a real weight** (10–12, with the others rebalanced to 100). It's the product's differentiator and weighting it zero was always odd.
- **Keep it at 0 and drop its findings out of the global deduction**, treating readiness as pure commentary.

I lean toward the first — a hostname on a 198-day manual certificate genuinely is in worse shape than one on automated 89-day renewal, and the grade should say so. But argue it either way.

---

## 3. Validate before locking

Contract §9 says grades cannot drift between releases without an amendment, and this is that amendment. So validate it properly rather than shipping on four samples:

- Run old and new grading across **at least 20 real domains** — the Gate A corpus plus a spread of Indian agency and SMB sites.
- Produce a before/after table: domain, old grade, old score, new grade, new score.
- Flag any result where the new grade feels wrong to you, and say why. I want your judgment, not just the numbers.
- Confirm ordering holds: sort by score, and check that a human reading the findings would agree with the ranking.

Then amend §9 to **v3.1**: the new score formula, the removal of the non-critical caps, the readiness weight decision, and a note that these grades supersede all previously issued ones.

Update the fixed-input grading tests to the new expected values. Update `docs/` anywhere the bands or the capping behaviour are described. Regenerate the four sample PDFs.

---

## One thing to keep

The "capped by N high-severity findings" line was a good addition and it should stay in some form — when a score is dragged down by a small number of serious findings rather than many small ones, saying so is useful. Reword it for whatever the new model does. It just shouldn't be the mechanism that makes the letter and the number disagree.
