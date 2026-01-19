from fastapi import FastAPI
from google import genai
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI(title="AI Ops GenAI Service")

client = genai.Client(
    api_key=os.getenv("AI_PROVIDER_KEY")
)

@app.post("/analyze")
def analyze(payload: dict):
    text = payload["text"]

    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=text
    )

    return {
        "result": response.text
    }
