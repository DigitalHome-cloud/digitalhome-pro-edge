#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copy the DigitalHome.Cloud ontology this edge validates with, from a
# darkfactory checkout:
#
#   tbox/dhc-core.ttl            the domain T-Box (circuit types, norms …)
#   cbox/<norm>.shapes.ttl       the norm rules (NF C 15-100, NF C 14-100, RGIE):
#                                ADVISORY here — they produce the report, they
#                                never refuse a save (ADR-0001)
#   cbox/cbox-manifest.json      which norm file is which
#
# shapes/ is NOT copied: it holds this edge's structural design shapes, which
# do refuse a save. They belong upstream in darkfactory eventually.
#
#   scripts/sync-ontology.sh [path/to/digitalhome-cloud-darkfactory]
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
src="${1:-$HOME/digitalhomeCloud/digitalhome-cloud-darkfactory}/repos/core/schema"
dst="$here/digitalhome_pro_edge/edge/ontology"
[[ -f "$src/tbox/dhc-core.ttl" ]] || { echo "no darkfactory schema at $src" >&2; exit 1; }
mkdir -p "$dst/tbox" "$dst/cbox"
cp "$src/tbox/dhc-core.ttl" "$dst/tbox/"
for f in nfc15100-2015 nfc14100-2008 rgie-1981; do
  cp "$src/cbox/electrical/$f.shapes.ttl" "$dst/cbox/"
done
cp "$src/cbox/cbox-manifest.json" "$dst/cbox/"
echo "copied from $src ($(git -C "$src" log -1 --format=%h 2>/dev/null || echo '?'))"
