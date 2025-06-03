from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import weaviate
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# ✅ Allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://ca-final-frontend.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Connect to Weaviate
WEAVIATE_URL = os.getenv("WEAVIATE_URL")
WEAVIATE_API_KEY = os.getenv("WEAVIATE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = weaviate.Client(
    url=WEAVIATE_URL,
    auth_client_secret=weaviate.auth.AuthApiKey(api_key=WEAVIATE_API_KEY),
    additional_headers={"X-Openai-Api-Key": OPENAI_API_KEY}
)

@app.post("/search")
def search(query: dict):
    try:
        user_query = query.get("query", "")
        keywords = user_query.lower().split()

        # ✅ Build OR filter on tags
        tag_filter = {
            "operator": "Or",
            "operands": [{"path": ["tags"], "operator": "Like", "valueText": kw} for kw in keywords]
        }

        response = client.query.get("FR_Inventories", [
            "question", "answer", "howToApproach", "chapter",
            "conceptTested", "conceptSummary", "sourceDetails",
            "tags", "combinedText"
        ])\
        .with_where(tag_filter)\
        .with_limit(50)\
        .do()

        tag_results = response.get("data", {}).get("Get", {}).get("FR_Inventories", []) or []

        return {"result": tag_results}

    except Exception as e:
        print("🔥 BACKEND ERROR:", e)
        return {"result": [], "error": str(e)}
