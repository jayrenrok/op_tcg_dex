#!/usr/bin/env node
/**
 * generate-hashes.js
 * ---------------------------------------------------------------
 * One-time (well — re-run whenever new cards are added) script that builds
 * the reference perceptual-hash database used by the "Scan Card" image-match
 * feature in template.html.
 *
 * WHY THIS EXISTS / WHY IT CAN'T RUN INSIDE THE CHAT SANDBOX:
 * Claude's code-execution sandbox has no general internet access (only a
 * small allowlist of hosts), so it cannot bulk-download ~4,500 card images
 * from en.onepiece-cardgame.com to build this database. This script does
 * that part — run it somewhere WITH normal internet access (your laptop, or
 * a GitHub Action, same as the existing 4D-scraper workflow in this repo).
 *
 * WHAT IT DOES:
 *   1. Reads all_cards.json (same file the app already uses)
 *   2. Downloads each card's reference image
 *   3. Computes a 256-bit "dHash" (difference hash) perceptual fingerprint
 *   4. Writes card_hashes.json — a single small file: { "OP05-119": "a1f9...", ... }
 *
 * The hash algorithm here MUST stay byte-for-byte identical to the one in
 * template.html's matchCardFromImage() — both sides hash images the same
 * way so Hamming-distance comparisons between a live scan and a reference
 * hash are meaningful. If you ever change one, change both, and regenerate.
 *
 * USAGE:
 *   npm install
 *   node generate-hashes.js ./all_cards.json ./card_hashes.json
 *
 * Takes a while (4,500 image downloads) — expect 10-30 minutes depending on
 * connection and rate limiting. Safe to re-run; it resumes by skipping IDs
 * already present in the output file unless --force is passed.
 * ---------------------------------------------------------------
 */

const fs = require('fs');
const path = require('path');
const sharp = require('sharp');
const pLimit = require('p-limit');

const INPUT_PATH = process.argv[2] || './all_cards.json';
const OUTPUT_PATH = process.argv[3] || './card_hashes.json';
const FORCE = process.argv.includes('--force');

const HASH_SIZE = 16;          // produces a 16*16 = 256-bit hash
const CONCURRENCY = 8;         // parallel downloads — polite, not aggressive
const RETRY_COUNT = 3;
const RETRY_DELAY_MS = 1500;

// ---- dHash (difference hash) ----
// Resize to (HASH_SIZE+1) x HASH_SIZE grayscale, then record whether each
// pixel is brighter than its neighbor to the right. This produces a hash
// that's robust to brightness/contrast shifts (since it compares RELATIVE
// pixel values, not absolute ones) and reasonably robust to mild blur and
// JPEG-style compression artifacts. It is NOT rotation-invariant — see
// README.md in this folder for what that means for scan accuracy.
async function dHashFromBuffer(buffer) {
  const { data, info } = await sharp(buffer)
    .resize(HASH_SIZE + 1, HASH_SIZE, { fit: 'fill' })
    .grayscale()
    .raw()
    .toBuffer({ resolveWithObject: true });

  const bits = [];
  const w = info.width; // HASH_SIZE + 1
  for (let y = 0; y < info.height; y++) {
    for (let x = 0; x < w - 1; x++) {
      const left = data[y * w + x];
      const right = data[y * w + x + 1];
      bits.push(right > left ? 1 : 0);
    }
  }
  // Pack bits into a hex string for compact storage (256 bits -> 64 hex chars)
  let hex = '';
  for (let i = 0; i < bits.length; i += 4) {
    const nibble = (bits[i] << 3) | (bits[i + 1] << 2) | (bits[i + 2] << 1) | bits[i + 3];
    hex += nibble.toString(16);
  }
  return hex;
}

async function fetchWithRetry(url) {
  for (let attempt = 1; attempt <= RETRY_COUNT; attempt++) {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return Buffer.from(await res.arrayBuffer());
    } catch (e) {
      if (attempt === RETRY_COUNT) throw e;
      await new Promise(r => setTimeout(r, RETRY_DELAY_MS * attempt));
    }
  }
}

async function main() {
  if (!fs.existsSync(INPUT_PATH)) {
    console.error(`Input file not found: ${INPUT_PATH}`);
    process.exit(1);
  }
  const cards = JSON.parse(fs.readFileSync(INPUT_PATH, 'utf8'));
  console.log(`Loaded ${cards.length} cards from ${INPUT_PATH}`);

  let existing = {};
  if (!FORCE && fs.existsSync(OUTPUT_PATH)) {
    existing = JSON.parse(fs.readFileSync(OUTPUT_PATH, 'utf8'));
    console.log(`Resuming — ${Object.keys(existing).length} hashes already present, will skip those.`);
  }

  const limit = pLimit(CONCURRENCY);
  const results = { ...existing };
  let done = 0, skipped = 0, failed = 0;
  const total = cards.length;
  const failedIds = [];

  const tasks = cards.map(card => limit(async () => {
    const id = card.id || card.code;
    const url = card.images?.large || card.images?.small;
    if (!id || !url) { skipped++; return; }
    if (results[id] && !FORCE) { skipped++; return; }

    try {
      const buffer = await fetchWithRetry(url);
      const hash = await dHashFromBuffer(buffer);
      results[id] = hash;
      done++;
    } catch (e) {
      failed++;
      failedIds.push(id);
      console.error(`  FAILED ${id}: ${e.message}`);
    }

    const processed = done + skipped + failed;
    if (processed % 100 === 0 || processed === total) {
      console.log(`Progress: ${processed}/${total} (done=${done} skipped=${skipped} failed=${failed})`);
      // Save incrementally so a crash/interrupt doesn't lose all progress
      fs.writeFileSync(OUTPUT_PATH, JSON.stringify(results));
    }
  }));

  await Promise.all(tasks);
  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(results));

  console.log('\n=== Done ===');
  console.log(`Total cards: ${total}`);
  console.log(`Newly hashed: ${done}`);
  console.log(`Skipped (already had hash): ${skipped}`);
  console.log(`Failed: ${failed}`);
  if (failedIds.length) {
    console.log('Failed IDs (re-run the script to retry just these — it resumes automatically):');
    console.log(failedIds.join(', '));
  }
  console.log(`\nOutput written to ${OUTPUT_PATH}`);
  console.log('Next step: upload this file to your GitHub Pages repo (e.g. as card_hashes.json')
  console.log('next to all_cards.json) — template.html fetches it at runtime, same pattern as prices.json.');
}

main().catch(e => {
  console.error('Fatal error:', e);
  process.exit(1);
});
