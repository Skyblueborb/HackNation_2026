import json
import sys
from pathlib import Path

from core import process

input_dir = Path(sys.argv[1])
output_dir = Path(sys.argv[2])

for pdf_path in sorted(input_dir.rglob("*.pdf")):
    out_path = output_dir / pdf_path.relative_to(input_dir).with_suffix(".json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(process(pdf_path.read_bytes()), ensure_ascii=False, indent=2))
    print(out_path)
