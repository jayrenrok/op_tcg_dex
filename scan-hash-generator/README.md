# Scan Card — reference hash generator

This is a one-time (well — rerun whenever new cards are added) script that
builds the data file the in-app camera scanner needs to recognize a card by
its **artwork** instead of trying to read its printed text.

## Why this exists

The original Scan Card feature used OCR (Tesseract.js) to read the printed
card code off a photo. Real-world testing showed this wasn't reliable enough
— small print, foil glare, and the fact that many cards share the same name
across different reprints made OCR-based matching guess wrong often enough
to not be useful.

This replaces that approach with **perceptual image hashing**: every
reference card image gets a compact fingerprint ("dHash") computed once,
ahead of time. When you scan a physical card, the app computes the same kind
of fingerprint from the live camera frame and finds the closest match by
comparing fingerprints — no text reading involved.

## Setup

```bash
cd scan-hash-generator
npm install
node generate-hashes.js ./all_cards.json ./card_hashes.json
```

- Takes **roughly 10-30 minutes** for ~4,500 cards, depending on your
  connection — it's downloading every card's reference image once.
- Total download is **~350-400MB** (one-time cost; the output file itself is
  small, well under 1MB).
- Safe to interrupt and re-run — it saves progress every 100 cards and skips
  IDs it already has a hash for, unless you pass `--force`.
- If some images fail (network blip, a card temporarily missing from the
  CDN), the script prints their IDs at the end. Just run it again — it'll
  retry only those.

## Running it via GitHub Actions instead

Since this repo already has a scheduled Action for scraping 4D results, the
same pattern works here — add a workflow that runs this script and commits
`card_hashes.json` back to the repo whenever `all_cards.json` changes (or on
a manual trigger / new card-set release). That avoids running this on your
own machine at all. Ask Claude to wire this up as a `.github/workflows/`
file if you'd like that — it's a short addition once you confirm the script
works locally first.

## After generating

Upload `card_hashes.json` to the same place `all_cards.json` and
`prices.json` already live (your GitHub Pages repo root). `template.html`
fetches it at runtime the same way it already fetches `prices.json` — no
build step needed.

## Important: keep the algorithm in sync

The hashing math in `generate-hashes.js` (the `dHashFromBuffer` function)
**must stay identical** to the matching math in `template.html`
(`matchCardFromImage` / its hash function). They're two implementations of
the same algorithm — one in Node for bulk reference generation, one in
browser JS for live scanning — and Hamming-distance comparisons only mean
anything if both sides hash images the exact same way. If you ever ask
Claude to tune the algorithm, both files need to change together, and
`card_hashes.json` needs to be regenerated from scratch (`--force`) since
old hashes won't be comparable to new ones.

## Realistic accuracy expectations

Perceptual hashing is meaningfully better suited to this problem than OCR
was — it's matching a *picture* against a database of pictures, not trying
to read small printed text under foil glare. But it is **not** a 98%-always
guarantee:

- It's robust to lighting/brightness changes and mild blur
- It is **not** rotation-invariant — a card held at a noticeable angle will
  hash differently than the flat reference scan, which costs accuracy
- Near-identical alt-art / parallel versions of the same card can hash very
  close to each other, same as they look very close to a human eye
- Heavy glare washing out a large portion of the card will degrade the match

The candidate-picker UI (showing top matches to tap, not auto-committing to
one guess) stays in place for exactly this reason — it's the safety net for
the cases that don't hit top-1.
