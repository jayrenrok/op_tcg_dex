#!/usr/bin/env python3
"""
Build the One Piece DEX HTML by injecting:
  - Card data from all_cards.json into __CARDS_DATA__
  - Supabase URL into __SUPABASE_URL__
  - Supabase anon key into __SUPABASE_ANON_KEY__

Reads Supabase values from environment variables:
  SUPABASE_URL          — your Supabase project URL
  SUPABASE_ANON_KEY     — your Supabase anon (public) key

These must be set in GitHub Secrets for the workflow,
or in your local shell for manual builds.

Usage:
  python build_html.py template.html all_cards.json output.html
"""

import os
import sys
import json


def main():
    if len(sys.argv) != 4:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    template_path, cards_path, output_path = sys.argv[1:4]

    # Required env vars — fail loudly if missing
    sb_url = os.environ.get('SUPABASE_URL', '').strip()
    sb_key = os.environ.get('SUPABASE_ANON_KEY', '').strip()

    if not sb_url or not sb_key:
        print("WARNING: SUPABASE_URL and SUPABASE_ANON_KEY env vars not set.", file=sys.stderr)
        print("Building with empty values — auth will be disabled in the app.", file=sys.stderr)

    # Load template
    with open(template_path, encoding='utf-8') as f:
        html = f.read()

    # Load and slim card data
    with open(cards_path, encoding='utf-8') as f:
        cards = json.load(f)

    keep_fields = {
        'id', 'code', 'rarity', 'type', 'name', 'images', 'cost',
        'power', 'counter', 'color', 'family', 'ability', 'set',
    }
    slim_cards = [{k: v for k, v in c.items() if k in keep_fields} for c in cards]
    cards_json = json.dumps(slim_cards, ensure_ascii=False, separators=(',', ':'))

    # Inject everything
    html = html.replace('__CARDS_DATA__', cards_json)
    html = html.replace('__SUPABASE_URL__', sb_url)
    html = html.replace('__SUPABASE_ANON_KEY__', sb_key)

    # Write output
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Built {output_path} ({size_mb:.2f} MB, {len(slim_cards)} cards)")
    print(f"  Supabase URL: {'configured' if sb_url else 'MISSING'}")
    print(f"  Supabase anon key: {'configured' if sb_key else 'MISSING'}")


if __name__ == '__main__':
    main()
