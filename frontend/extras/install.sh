#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DIST="$HERE/../dist"
cp "$HERE/new-film.js" "$DIST/assets/new-film.js"
cp "$HERE/scene-extras.js" "$DIST/assets/scene-extras.js"
python3 - "$DIST/index.html" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
s = p.read_text()
tags = [
    '<script defer src="/assets/new-film.js?v=20261120-3"></script>',
    '<script defer src="/assets/scene-extras.js?v=20261120-5"></script>',
]
missing = [t for t in tags if t.split('src="')[1].split('?')[0] not in s]
if not missing:
    print("already patched:", p)
else:
    s = s.replace("</body>", "    " + "\n    ".join(missing) + "\n  </body>")
    p.write_text(s)
    print("patched:", p)
PY
