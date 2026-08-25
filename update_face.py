#!/usr/bin/env python3
import re

SVGS = ['dark_mode.svg', 'light_mode.svg']
ART = 'face.txt'
FONT = 4.3          
CHAR_W = FONT * 0.6  
MAXCOLS = 137       
MAXROWS = 92        

def load_art():
    """Read face.txt and strip trailing whitespace."""
    lines = [l.rstrip() for l in open(ART, encoding='utf-8').read().splitlines()]
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
    """Build the <text> block with tspan rows and animation delays."""
    if not art:
        return '<text id="ascii_face_placeholder" fill="#c9d1d9" font-size="4.3px"> </text>'
    
    W = max(len(r) for r in art)
    N = len(art)
    spacing = round(FONT * 1.0909, 3)
    
    # Position on the left side of the terminal
    x = 20           
    start_y = round(60 + (320 - (N - 1) * spacing) / 2, 1)  
    rows = []
    
    for i, row in enumerate(art):
        y = round(start_y + i * spacing, 1)
        # Calculate animation delay for the top-to-bottom loading effect
        delay = round(0.90 + i * (0.05 / 1.5), 2)  
        rows.append(f'<tspan x="{x}" y="{y}" class="t" style="animation-delay:{delay}s">{row.ljust(W)}</tspan>')
        
    return (f'<text id="ascii_face_placeholder" x="{x}" y="{start_y}" fill="currentColor" font-size="{FONT}px" '
            f'stroke="currentColor" stroke-width="0.5">\n' + '\n'.join(rows) + '\n</text>')

def main():
    art = crop(load_art())
    block = build_block(art)
    
    # Regex to find the placeholder text block
    pat = re.compile(r'<text[^>]*id="ascii_face_placeholder"[^>]*>.*?</text>', re.S)
    
    for svg_file in SVGS:
        try:
            src = open(svg_file, encoding='utf-8').read()
            m = pat.search(src)
            if not m:
                print(f"Placeholder not found in {svg_file}. Skipping.")
                continue
            
            # Replace placeholder with the new animated text block
            src = src[:m.start()] + block + src[m.end():]
            open(svg_file, 'w', encoding='utf-8').write(src)
            print(f"Successfully embedded face art into {svg_file}")
            
        except FileNotFoundError:
            print(f"Could not find {svg_file}")

if __name__ == '__main__':
    main()