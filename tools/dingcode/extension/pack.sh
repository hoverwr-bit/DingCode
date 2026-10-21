#!/bin/sh
# Copy the page script into a folder Chrome or Edge can load unpacked.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
dist=$root/dist
rm -rf "$dist"
mkdir -p "$dist"
cp "$root/manifest.json" "$root/background.js" "$root/content.js" "$dist/"
cp "$root/../web/anno.js" "$dist/anno.js"
echo "Load unpacked: $dist"
