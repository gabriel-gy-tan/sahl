#!/bin/sh
# Runs Sahl for a demo with invented documents only, so no real person's details can appear on the projector.
#   sh demo/pitch.sh          start (the app, a clean demo vault, and the sample portal)
#   sh demo/pitch.sh reset    the same, after wiping the demo vault (forgets what was told in the last run)
# The demo vault lives in ~/SahlDemo; your own vault and documents are not touched. The local AI models already
# downloaded are reused (SAHL_MODELS), so nothing is downloaded again.
set -e
here=$(cd "$(dirname "$0")" && pwd)
demo="$HOME/SahlDemo"
[ "$1" = reset ] && rm -rf "$demo"
mkdir -p "$demo/home" "$demo/library"

# the invented resident: a passport and both sides of an Emirates ID, confirmed by their check digits with no AI
# (demo/make_samples.py draws them)
cp "$here/samples/passport.png" "$here/samples/emirates_id_card.png" "$demo/library/"

case "$(uname)" in
  Darwin) models="$HOME/Library/Application Support/Sahl/models" ;;
  *) models="${APPDATA:-$HOME/.config}/Sahl/models" ;;
esac
export SAHL_HOME="$demo/home" SAHL_LIBRARY="$demo/library" SAHL_MODELS="$models"

# the sample portal, served over http so the browser extension can read it (8077: 8000 is often taken already)
port=8077
url="http://127.0.0.1:$port/refund-portal.html"
curl -fs -o /dev/null "$url" || (python3 -m http.server "$port" --bind 127.0.0.1 --directory "$here" >/dev/null 2>&1 &)
sleep 1
if curl -fs -o /dev/null "$url"; then echo "Sample portal: $url"; else echo "Couldn't serve the sample portal on port $port: something else is using it." >&2; fi

if [ -d /Applications/Sahl.app ] && [ "$1" != dev ] && [ "$2" != dev ]; then
  open -n -a /Applications/Sahl.app --env SAHL_HOME="$SAHL_HOME" --env SAHL_LIBRARY="$SAHL_LIBRARY" --env SAHL_MODELS="$SAHL_MODELS"
else
  (cd "$here/../app" && npm run tauri dev)
fi
