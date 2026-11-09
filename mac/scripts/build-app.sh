#!/bin/bash
# Build, sign and package mac/build/VideoMentor.app from the Swift package.
# Usage: mac/scripts/build-app.sh   (does not run, install or open the app)
set -euo pipefail

# Signing identity: VM_SIGN_IDENTITY if set, else the first valid "Apple Development"
# identity in the keychain, else ad-hoc ("-").
IDENTITY="${VM_SIGN_IDENTITY:-}"
if [ -z "$IDENTITY" ]; then
  IDENTITY="$(security find-identity -v -p codesigning 2>/dev/null \
    | sed -n 's/^ *[0-9][0-9]*) [0-9A-F]* "\(Apple Development: .*\)".*/\1/p' | head -n 1)"
fi
if [ -z "$IDENTITY" ]; then
  IDENTITY="-"
fi

MAC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_DIR="$(cd "$MAC_DIR/.." && pwd)"
BUILD_DIR="$MAC_DIR/build"
APP="$BUILD_DIR/VideoMentor.app"
ICON_SRC="$REPO_DIR/docs/brand/videomentor-icon-1024.png"

# Version from web/package.json; build ID from the engine ("" falls back to the version).
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$REPO_DIR/web/package.json")"
BUILD="$(cd "$REPO_DIR" && uv run vm launch-info --json | python3 -c 'import json,sys; print(json.load(sys.stdin).get("build",""))')"
[ -n "$BUILD" ] || BUILD="$VERSION"
echo "Version $VERSION, build $BUILD"

echo "Building (release)..."
(cd "$MAC_DIR" && swift build -c release)
BIN_DIR="$(cd "$MAC_DIR" && swift build -c release --show-bin-path)"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN_DIR/VideoMentorMenu" "$APP/Contents/MacOS/VideoMentor"

sed -e "s/@VERSION@/$VERSION/" -e "s/@BUILD@/$BUILD/" \
    "$MAC_DIR/Resources/Info.plist" > "$APP/Contents/Info.plist"
plutil -lint "$APP/Contents/Info.plist"

# App icon: AppIcon.icns from the 1024 px brand PNG.
ICONSET="$BUILD_DIR/AppIcon.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z "$s" "$s" "$ICON_SRC" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z "$((s * 2))" "$((s * 2))" "$ICON_SRC" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
rm -rf "$ICONSET"

if [ "$IDENTITY" = "-" ]; then
  echo "Signing as: ad-hoc (no identity)"
  echo "WARNING: ad-hoc signing means macOS permissions (Start at Login and similar) may not survive rebuilds."
  echo "         Set VM_SIGN_IDENTITY to a certificate name, or add an Apple Development certificate in Xcode."
else
  echo "Signing as: $IDENTITY"
fi
codesign --force --options runtime --timestamp=none --sign "$IDENTITY" "$APP"
codesign --verify --deep --strict "$APP"
echo "Built $APP"
