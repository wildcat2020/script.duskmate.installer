"""Build a deterministic Kodi add-on ZIP and SHA-256 sidecar."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile


FILES = (
    "addon.xml",
    "default.py",
    "README.md",
    "LICENSE",
    "icon.png",
    "fanart.jpg",
)
ZIP_TIME = (2020, 1, 1, 0, 0, 0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    addon = ET.parse(root / "addon.xml").getroot()
    addon_id = addon.attrib["id"]
    version = addon.attrib["version"]
    args.output.mkdir(parents=True, exist_ok=True)
    destination = args.output / f"{addon_id}-{version}.zip"

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in FILES:
            source = root / relative
            info = zipfile.ZipInfo(f"{addon_id}/{relative}", ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(destination.suffix + ".sha256").write_text(
        f"{digest}  {destination.name}\n",
        encoding="ascii",
        newline="\n",
    )
    print(destination)


if __name__ == "__main__":
    main()
