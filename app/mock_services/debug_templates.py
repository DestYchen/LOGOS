# debug_templates.py
from app.core.enums import DocumentType
from app.mock_services import templates
from app.mock_services.templates.loader import load_template_definition
from app.mock_services.templates.loader import _BASE_DIR as LOADER_BASE
from app.mock_services.templates.loader import _DOC_MAPPING as LOADER_MAP
import json
from pathlib import Path

def main():
    dt = DocumentType.INVOICE
    print("=== DEBUG Template Loader ===")
    print("DocumentType:", dt, "value:", dt.value)
    print("Mapping has INVOICE:", dt in LOADER_MAP)
    print("Mapped filename:", LOADER_MAP.get(dt))

    print("Base dir (loader):", LOADER_BASE)
    p = Path(LOADER_BASE) / LOADER_MAP.get(dt, "???")
    print("Full path:", p, "exists:", p.exists())

    if p.exists():
        try:
            raw = p.read_text(encoding="utf-8")
            print("File head:", raw[:200].replace("\n","\\n"))
        except Exception as e:
            print("Read error:", e)

    tpl1 = load_template_definition(dt)
    print("load_template_definition(fields keys):", list(tpl1.get("fields", {}).keys()))
    print("Has product_template:", "product_template" in tpl1)

    tpl2 = templates.get_template_definition(dt)
    print("get_template_definition(fields keys):", list(tpl2.get("fields", {}).keys()))
    print("Has product_template:", "product_template" in tpl2)

    print("JSON pretty (fields only):")
    print(json.dumps(tpl2.get("fields", {}), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
