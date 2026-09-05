"""Small live retrieval evaluation, independent of generation. Requires an indexed book."""

import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

cases = json.loads((Path(__file__).parent.parent / "backend/tests/retrieval_cases.json").read_text())
passed = 0
for case in cases:
    request = Request(
        "http://127.0.0.1:8000/api/textbook/search",
        data=json.dumps({"query": case["query"], "top_k": 5}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=180) as response:
        results = json.load(response)["results"]
    hit = any(
        any(keyword in result["section"].lower() for keyword in case["section_keywords"])
        for result in results
    )
    passed += int(hit)
    print(("PASS" if hit else "FAIL") + ": " + case["query"])
    for result in results[:3]:
        print(f"  {result['score']:.3f} {result['chapter']} / {result['section']}")
print(
    f"\nSection hit@5: {passed}/{len(cases)}. This is a smoke benchmark, not a comprehensive quality evaluation."
)
sys.exit(0 if passed == len(cases) else 1)
