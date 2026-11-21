import json, sys
from pathlib import Path
from core import process

for path in sorted(Path(sys.argv[1]).rglob("*.pdf")):
    print(json.dumps({"file": str(path), **process(path.read_bytes())}, ensure_ascii=False))
