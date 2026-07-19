#!/usr/bin/env python3
import os, re, shutil, datetime, argparse
from xml.etree import ElementTree as ET

# Strict bank filename pattern: MarshalPOS-<12 hex>.xml (case-insensitive)
STRICT_BANK_RE = re.compile(r'^MarshalPOS[-_]?([0-9A-Fa-f]{12})\.xml$', re.IGNORECASE)

# Generic MAC patterns as fallback
GENERIC_MAC_RE = re.compile(
    r'([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})'        # AA:BB:CC:DD:EE:FF or AA-BB-...
    r'|([0-9A-Fa-f]{12})'                             # AABBCCDDEEFF
    r'|([0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4})'  # aabb.ccdd.eeff
)

def norm_mac(s: str) -> str:
    """Normalize to 12 uppercase hex chars."""
    return re.sub(r'[^0-9A-Fa-f]', '', s).upper()

def find_mac_from_filename(filename: str):
    """
    Prefer strict bank pattern: MarshalPOS-<MAC>.XML
    Else fall back to generic MAC detection in filename.
    """
    m = STRICT_BANK_RE.match(filename)
    if m:
        return norm_mac(m.group(1))
    # fallback: any MAC-like token in filename
    m2 = GENERIC_MAC_RE.search(filename)
    return norm_mac(m2.group(0)) if m2 else None

def find_mac_in_text(text: str):
    m = GENERIC_MAC_RE.search(text or "")
    return norm_mac(m.group(0)) if m else None

def main():
    parser = argparse.ArgumentParser(description="Stage bank XMLs -> pos-configs/<MAC>.xml")
    parser.add_argument('--source', required=True, help='Folder where you dropped bank XML files')
    parser.add_argument('--repo-root', default=os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    args = parser.parse_args()

    src_dir = os.path.abspath(args.source)
    repo = os.path.abspath(args.repo_root)
    pos_configs = os.path.join(repo, 'pos-configs')
    archive_dir = os.path.join(repo, 'incoming', 'archive', datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))

    os.makedirs(pos_configs, exist_ok=True)
    os.makedirs(archive_dir, exist_ok=True)

    files = [f for f in os.listdir(src_dir) if f.lower().endswith('.xml')]
    if not files:
        print("No XML files found in", src_dir)
        return

    impacted = set()
    for fn in files:
        full = os.path.join(src_dir, fn)
        data = open(full, 'rb').read()

        # Validate well-formed XML
        try:
            ET.fromstring(data)
        except ET.ParseError as e:
            print(f"[SKIP] Malformed XML: {fn}: {e}")
            continue

        # Prefer strict bank pattern (MarshalPOS-<MAC>.XML), fallback to generic
        mac = find_mac_from_filename(fn)
        if not mac:
            try:
                mac = find_mac_in_text(data.decode('utf-8', errors='ignore'))
            except Exception:
                mac = None

        if not mac:
            print(f"[SKIP] No MAC found in filename/content: {fn}")
            continue

        dest = os.path.join(pos_configs, f"{mac}.xml")
        with open(dest, 'wb') as out:
            out.write(data)

        shutil.move(full, os.path.join(archive_dir, fn))
        impacted.add(mac)
        print(f"[OK] {fn} → pos-configs/{mac}.xml")

    if impacted:
        print("Staged for MACs:", ", ".join(sorted(impacted)))
    else:
        print("No files staged.")

if __name__ == '__main__':
    main()
