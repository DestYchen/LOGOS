from openai import OpenAI

client = OpenAI(
    api_key="".strip(),
    base_url="https://openrouter.ai/api/v1",
    default_headers={
        "HTTP-Referer": "http://localhost:8001",  # то, что указано в OpenRouter
        "X-Title": "Test OCR Adapter",
    },
)

resp = client.models.list()
print(resp)
