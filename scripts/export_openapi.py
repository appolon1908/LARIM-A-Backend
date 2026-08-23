import json
from larimia.main import app
with open("openapi.generated.json", "w", encoding="utf-8") as f:
    json.dump(app.openapi(), f, ensure_ascii=False, indent=2)
print("wrote openapi.generated.json")
