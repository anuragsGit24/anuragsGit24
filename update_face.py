#!/usr/bin/env python3
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SVGS = [BASE_DIR / 'dark_mode.svg', BASE_DIR / 'light_mode.svg']
ART = BASE_DIR / 'face.txt'
FONT = 7.5
CHAR_W = FONT * 0.6
MAXCOLS = 95
MAXROWS = 92        

def load_art():
    """Read face.txt and strip trailing whitespace."""
    lines = [line.rstrip() for line in ART.read_text(encoding='utf-8').splitlines()]
    content = [l for l in lines if l.strip()]
    left = 0
    while content and all(len(l) > left and l[left] == ' ' for l in content):
        left += 1
    return [l[left:] for l in content]

def crop(art):
    """Crop to fit the left column."""
    if not art:
        return []
    head = art[:max(1, int(len(art) * 0.8))]
    cols = [j for r in head for j, c in enumerate(r) if c != ' ']
    center = sum(cols) // max(1, len(cols))
    x0 = max(0, center - MAXCOLS // 2)
    return [r[x0:x0 + MAXCOLS] for r in art[:MAXROWS]]

def build_block(art):
    """Build the face with relative rows and staggered animation delays."""
    if not art:
        return '<text id="ascii_face_placeholder" class="face" font-family="monospace" font-size="6px"> </text>'
    
    W = max(len(r) for r in art)
    x = 10
    rows = []
    
    for i, row in enumerate(art):
        delay = round(0.10 + (i * 0.04), 3)
        rows.append(f'<tspan x="{x}" dy="1.1em" class="t" style="animation-delay:{delay:.3f}s" xml:space="preserve">{row.ljust(W)}</tspan>')

    return (f'<text id="ascii_face_placeholder" class="face" x="{x}" y="0" '
            f'font-family="monospace" font-size="{FONT}px" stroke-width="0.5" '
            f'xml:space="preserve">\n' + '\n'.join(rows) + '\n</text>')

def main():
    art = crop(load_art())
    block = build_block(art)
    
    pat = re.compile(
        r'<text\b(?=[^>]*\bid=["\']ascii_face_placeholder["\'])[^>]*/>'
        r'|<text\b(?=[^>]*\bid=["\']ascii_face_placeholder["\'])[^>]*>.*?</text>',
        re.S,
    )
    
    for svg_file in SVGS:
        try:
            src = svg_file.read_text(encoding='utf-8')
            m = pat.search(src)
            if not m:
                print(f"Placeholder not found in {svg_file}. Skipping.")
                continue
            
            svg_file.write_text(src[:m.start()] + block + src[m.end():], encoding='utf-8')
            print(f"Successfully embedded face art into {svg_file}")
            
        except FileNotFoundError:
            print(f"Could not find {svg_file}")

if __name__ == '__main__':
    main()