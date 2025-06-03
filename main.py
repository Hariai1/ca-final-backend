from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import weaviate
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

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

        # ✅ Step 1: Semantic search (higher certainty for relevance)
        semantic_response = client.query.get("FR_Inventories", [
            "question", "answer", "howToApproach", "chapter",
            "conceptTested", "conceptSummary", "sourceDetails",
            "tags", "combinedText"
        ])\
        .with_near_text({
            "concepts": [user_query],
            "certainty": 0.8
        })\
        .with_limit(30)\
        .do()

        semantic_results = semantic_response.get("data", {}).get("Get", {}).get("FR_Inventories", []) or []

        # ✅ Step 2: Tag-based match
        tag_filter = {
            "operator": "Or",
            "operands": [{"path": ["tags"], "operator": "Like", "valueText": word} for word in keywords]
        }

        tag_response = client.query.get("FR_Inventories", [
            "question", "answer", "howToApproach", "chapter",
            "conceptTested", "conceptSummary", "sourceDetails",
            "tags", "combinedText"
        ])\
        .with_where(tag_filter)\
        .with_limit(30)\
        .do()

        tag_results = tag_response.get("data", {}).get("Get", {}).get("FR_Inventories", []) or []

        # ✅ Step 3: Merge without duplicates
        seen = set()
        merged_results = []

        for item in semantic_results + tag_results:
            q = item.get("question", "").strip().lower()
            if q not in seen:
                merged_results.append(item)
                seen.add(q)

        # ✅ Step 4: Sort by tag match count
        def tag_score(item):
            tags = item.get("tags", "").lower().split(",")
            return sum(1 for word in keywords if word in tags)

        merged_results.sort(key=tag_score, reverse=True)

        # ✅ Step 5: Limit final results
        return {"result": merged_results[:15]}

    except Exception as e:
        print("🔥 BACKEND ERROR:", e)
        return {"result": [], "error": str(e)}
