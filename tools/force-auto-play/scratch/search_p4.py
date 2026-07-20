import re

with open("/tmp/jili_bundle.js", "r", encoding="utf-8", errors="ignore") as f:
    content = f.read()

# Let's search for definition of p4
matches = []
for m in re.finditer(r'\bp4\b\s*[:=]', content):
    start = max(0, m.start() - 150)
    end = min(len(content), m.end() + 500)
    matches.append(content[start:end])

# Also check occurrences where V7Qn3.p4 is defined
for m in re.finditer(r'\bV7Qn3\.p4\b\s*[:=]', content):
    start = max(0, m.start() - 150)
    end = min(len(content), m.end() + 500)
    matches.append(content[start:end])

print(f"Found {len(matches)} occurrences of p4:")
for idx, match in enumerate(matches):
    print(f"\n--- p4 Definition {idx+1} ---")
    print(match)
