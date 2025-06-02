from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import weaviate
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# ✅ Allow both local and deployed frontend (Vercel)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://ca-final-frontend.vercel.app"  # 👈 added this
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Weaviate v3 client setup
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

        # ✅ Create OR filter for tags
        tag_filters = {
            "operator": "Or",
            "operands": [{"path": ["tags"], "operator": "Like", "valueText": word} for word in keywords]
        }

        response = client.query.get("FR_Inventories", [
            "question", "answer", "howToApproach",
            "chapter", "conceptTested", "conceptSummary",
            "sourceDetails", "tags", "combinedText"
        ])\
        .with_near_text({
            "concepts": [user_query],
            "certainty": 0.4
        })\
        .with_where(tag_filters)\
        .with_limit(10)\
        .do()

        raw_result = response.get("data", {}).get("Get", {}).get("FR_Inventories")

        if not raw_result:
            return {"result": []}

        # ✅ Sort: highest keyword match in tags
        def tag_match_score(item):
            tags = item.get("tags", "").lower().split(",")
            return sum(1 for kw in keywords if kw in tags)

        sorted_results = sorted(raw_result, key=tag_match_score, reverse=True)

        return {"result": sorted_results}

    except Exception as e:
        print("🔥 BACKEND ERROR:", e)
        return {"result": [], "error": str(e)}
