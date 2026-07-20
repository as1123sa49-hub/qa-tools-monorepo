import re

with open("/tmp/jili_bundle.js", "r", encoding="utf-8", errors="ignore") as f:
    content = f.read()

# Let's search for functions defined on V7Qn3 like V7Qn3.xxx = function
matches = []
for m in re.finditer(r'\bV7Qn3\.[a-zA-Z0-9_$]+\s*=\s*function\b', content):
    start = max(0, m.start() - 50)
    end = min(len(content), m.end() + 200)
    matches.append(content[start:end])

print(f"Found {len(matches)} properties defined on V7Qn3:")
for idx, match in enumerate(matches):
    print(f"\n--- Property {idx+1} ---")
    print(match)
