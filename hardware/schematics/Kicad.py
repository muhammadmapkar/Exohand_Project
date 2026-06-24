import json

with open("schematic.cir", "r") as f:
    content = f.read()

with open("schematic.json", "w") as f:
    json.dump({"raw": content}, f, indent=2)

print("Done")
