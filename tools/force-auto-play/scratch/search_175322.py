with open("/tmp/jili_bundle.js", "r", encoding="utf-8", errors="ignore") as f:
    content = f.read()

idx = content.find("V7Qn3[175322]")
if idx != -1:
    print("Found V7Qn3[175322] at", idx)
    print(content[idx:idx+1500])
else:
    print("Not found")
