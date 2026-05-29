#!/usr/bin/env python3
"""
refresh_cards.py — Build all_cards.json from a punk-records dataset.

Auto-discovers the English card JSON files so it is robust to small layout
differences. Pass the punk-records root, the english/ dir, or any parent dir.

Usage:
  python refresh_cards.py <punk_records_dir> <output_all_cards.json>
"""

import os
import re
import sys
import json
import glob

RARITY_MAP = {
    'Leader': 'L', 'Common': 'C', 'Uncommon': 'UC', 'Rare': 'R',
    'SuperRare': 'SR', 'SecretRare': 'SEC', 'SpecialRare': 'SP',
    'Special': 'SP', 'TreasureRare': 'TR', 'Promo': 'P',
}
CATEGORY_MAP = {
    'Leader': 'LEADER', 'Character': 'CHARACTER', 'Event': 'EVENT',
    'Stage': 'STAGE', 'Don': 'DON',
}
OFFICIAL_IMG_BASE = 'https://en.onepiece-cardgame.com/images/cardlist/card/'


def looks_like_card(obj):
    return (
        isinstance(obj, dict)
        and 'id' in obj
        and ('name' in obj or 'category' in obj or 'rarity' in obj)
    )


def find_english_root(start):
    candidates = [
        start,
        os.path.join(start, 'english'),
        os.path.join(start, 'punk-records', 'english'),
    ]
    for c in candidates:
        if os.path.isdir(os.path.join(c, 'cards')) or os.path.exists(os.path.join(c, 'packs.json')):
            return c
    for root, dirs, _ in os.walk(start):
        if os.path.basename(root) == 'english' and 'cards' in dirs:
            return root
    for root, dirs, _ in os.walk(start):
        if 'cards' in dirs:
            return root
    return start


def collect_card_files(english_root):
    cards_dir = os.path.join(english_root, 'cards')
    if os.path.isdir(cards_dir):
        files = sorted(glob.glob(os.path.join(cards_dir, '*.json')))
        if files:
            return files
    out = []
    for fp in glob.glob(os.path.join(english_root, '**', '*.json'), recursive=True):
        base = os.path.basename(fp).lower()
        if base in ('manifest.json', 'packs.json', 'by_name.json', 'cards_by_id.json'):
            continue
        out.append(fp)
    return sorted(out)


def load_pack_names(english_root):
    names = {}
    packs_path = os.path.join(english_root, 'packs.json')
    if not os.path.exists(packs_path):
        return names
    try:
        with open(packs_path, encoding='utf-8') as f:
            packs = json.load(f)
    except Exception as e:
        print(f"  WARN: could not read packs.json: {e}", file=sys.stderr)
        return names

    # punk-records may store packs as a list of objects OR a dict keyed by id.
    # Normalize to a list of (id, obj) pairs.
    entries = []
    if isinstance(packs, list):
        for p in packs:
            if isinstance(p, dict):
                entries.append((p.get('id'), p))
    elif isinstance(packs, dict):
        for pid, p in packs.items():
            if isinstance(p, dict):
                # If the value object lacks an id field, fall back to the key
                entries.append((p.get('id') or pid, p))
            elif isinstance(p, str):
                # Some datasets store {id: "Display Name"} directly
                entries.append((pid, {'raw_title': p}))

    for pid, p in entries:
        if not pid:
            continue
        name = p.get('raw_title') or p.get('name') or p.get('title') or ''
        if not name:
            tp = p.get('title_parts') or {}
            name = ' '.join(b for b in [tp.get('prefix'), tp.get('title'), tp.get('label')] if b)
        names[pid] = (name or '').strip()
    return names


def normalize_counter(value):
    if value is None or value == '':
        return '-'
    return value


def to_app_card(card, pack_names):
    cid = card.get('id') or ''
    if not cid:
        return None
    img = card.get('img_full_url') or ''
    if not img:
        rel = card.get('img_url') or ''
        if rel.startswith('http'):
            img = rel
        elif rel:
            img = 'https://en.onepiece-cardgame.com' + (rel if rel.startswith('/') else '/' + rel)
        else:
            img = OFFICIAL_IMG_BASE + cid + '.png'
    colors = card.get('colors') or []
    types = card.get('types') or []
    raw_rarity = card.get('rarity') or ''
    raw_cat = card.get('category') or ''
    pack_id = card.get('pack_id') or ''
    return {
        'id': cid,
        'code': cid,
        'name': card.get('name') or '',
        'rarity': RARITY_MAP.get(raw_rarity, raw_rarity),
        'type': CATEGORY_MAP.get(raw_cat, raw_cat.upper() if raw_cat else ''),
        'cost': card.get('cost') if card.get('cost') is not None else '',
        'power': card.get('power') if card.get('power') is not None else '',
        'counter': normalize_counter(card.get('counter')),
        'color': '/'.join(colors),
        'family': '/'.join(types),
        'ability': card.get('effect') or '',
        'trigger': card.get('trigger') or '',
        'images': {'large': img, 'small': img},
        'set': {'name': pack_names.get(pack_id, pack_id)},
    }


def main():
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    in_dir, output_path = sys.argv[1:3]
    if not os.path.isdir(in_dir):
        print(f"ERROR: input dir not found: {in_dir}", file=sys.stderr)
        sys.exit(1)

    english_root = find_english_root(in_dir)
    print(f"Using english root: {english_root}")

    pack_names = load_pack_names(english_root)
    print(f"Loaded {len(pack_names)} pack names")

    files = collect_card_files(english_root)
    print(f"Found {len(files)} candidate JSON files")
    if not files:
        print("ERROR: no card JSON discovered. Listing tree:", file=sys.stderr)
        for root, dirs, fnames in os.walk(in_dir):
            print(f"  {root} -> dirs={dirs[:10]} files={fnames[:10]}", file=sys.stderr)
        sys.exit(1)

    seen = {}
    skipped = 0
    parsed_files = 0
    for fp in files:
        try:
            with open(fp, encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"  WARN: skip {os.path.basename(fp)}: {e}", file=sys.stderr)
            continue
        arr = None
        if isinstance(data, list):
            arr = data
        elif isinstance(data, dict):
            for key in ('cards', 'data', 'items'):
                if isinstance(data.get(key), list):
                    arr = data[key]
                    break
        if not arr:
            continue
        if not any(looks_like_card(x) for x in arr[:3]):
            continue
        parsed_files += 1
        for raw in arr:
            app_card = to_app_card(raw, pack_names) if looks_like_card(raw) else None
            if not app_card:
                skipped += 1
                continue
            cid = app_card['id']
            if cid not in seen:
                seen[cid] = app_card

    cards = list(seen.values())
    cards.sort(key=lambda c: c['id'])

    if not cards:
        print("ERROR: parsed files but found 0 cards. Sample file head:", file=sys.stderr)
        try:
            with open(files[0], encoding='utf-8') as f:
                print(f.read()[:1000], file=sys.stderr)
        except Exception:
            pass
        sys.exit(1)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(cards, f, ensure_ascii=False, separators=(',', ':'))

    prefixes = {}
    for c in cards:
        m = re.match(r'^([A-Z]+\d+)-', c['id'])
        pre = m.group(1) if m else 'OTHER'
        prefixes[pre] = prefixes.get(pre, 0) + 1

    print(f"\nParsed {parsed_files} card files")
    print(f"Wrote {len(cards)} cards to {output_path} (skipped {skipped} non-cards)")
    print("Set coverage:")
    for pre in sorted(prefixes):
        print(f"  {pre}: {prefixes[pre]}")


if __name__ == '__main__':
    main()
