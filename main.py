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

# ✅ Weaviate client setup
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

        # ✅ Semantic search
        semantic_response = client.query.get("FR_Inventories", [
            "question", "answer", "howToApproach", "chapter",
            "conceptTested", "conceptSummary", "sourceDetails",
            "tags", "combinedText"
        ])\
        .with_near_text({
            "concepts": [user_query],
            "certainty": 0.5
        })\
        .with_limit(50)\
        .do()

        semantic_results = semantic_response.get("data", {}).get("Get", {}).get("FR_Inventories", []) or []

        # ✅ Tag filter assuming tags are stored as list (not comma string)
        tag_filter = {
            "operator": "ContainsAny",
            "path": ["tags"],
            "valueTextArray": keywords
        }

        tag_response = client.query.get("FR_Inventories", [
            "question", "answer", "howToApproach", "chapter",
            "conceptTested", "conceptSummary", "sourceDetails",
            "tags", "combinedText"
        ])\
        .with_where(tag_filter)\
        .with_limit(50)\
        .do()

        tag_results = tag_response.get("data", {}).get("Get", {}).get("FR_Inventories", []) or []

        # ✅ Return both separately for debugging or UI comparison
        return {
            "semantic_results": semantic_results,
            "tag_results": tag_results
        }

    except Exception as e:
        print("🔥 BACKEND ERROR:", e)
        return {
            "semantic_results": [],
            "tag_results": [],
            "error": str(e)
        }
