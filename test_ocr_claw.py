import base64
import requests

TOKEN = "1e9f0b9b3d19562750b36c699edad86fffb10f277e80326a"
PDF_PATH = r"C:\Users\dima\Desktop\LOGOS\local_archive\105_26__2454a906-981b-44e5-b822-439cd602006e\raw\INV_E00033-00001685_09022026.pdf"

with open(PDF_PATH, "rb") as f:
    pdf_b64 = base64.b64encode(f.read()).decode("ascii")

payload = {
    "model": "openclaw/default",
    "input": [
        {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        "Извлеки из PDF весь текст, который сможешь прочитать.\n"
                        "Верни только распознанный текст.\n"
                        "Не пересказывай, не объясняй, не комментируй.\n"
                        "Сохраняй порядок чтения сверху вниз, слева направо.\n"
                        "Сохраняй абзацы и переносы, если возможно.\n"
                        "Нечитаемые места помечай как [unclear]."
                    )
                },
                {
                    "type": "input_file",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "filename": "scan.pdf",
                        "data": pdf_b64
                    }
                }
            ]
        }
    ]
}

r = requests.post(
    "http://127.0.0.1:18789/v1/responses",
    headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    },
    json=payload,
    timeout=300,
)

print(r.status_code)
print(r.text)

data = r.json()

texts = []
for item in data.get("output", []):
    for content in item.get("content", []):
        if content.get("type") == "output_text":
            texts.append(content.get("text", ""))

print("\n--- EXTRACTED TEXT ---\n")
print("\n".join(texts))