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
        "https://ca-final-frontend.vercel.app"  # 👈 for Vercel frontend
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

        # ✅ Step 1: Semantic Search
        semantic_response = client.query.get("FR_Inventories", [
            "question", "answer", "howToApproach",
            "chapter", "conceptTested", "conceptSummary",
            "sourceDetails", "tags", "combinedText"
        ])\
        .with_near_text({
            "concepts": [user_query],
            "certainty": 0.3
        })\
        .with_limit(50)\
        .do()

        semantic_results = semantic_response.get("data", {}).get("Get", {}).get("FR_Inventories", []) or []

        # ✅ Step 2: Tag Match Search
        tag_filter = {
            "operator": "Or",
            "operands": [{"path": ["tags"], "operator": "Like", "valueText": word} for word in keywords]
        }

        tag_response = client.query.get("FR_Inventories", [
            "question", "answer", "howToApproach",
            "chapter", "conceptTested", "conceptSummary",
            "sourceDetails", "tags", "combinedText"
        ])\
        .with_where(tag_filter)\
        .with_limit(50)\
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

        # ✅ Step 4: Sort by tag match score
        def tag_score(item):
            tags = item.get("tags", "").lower().split(",")
            return sum(1 for word in keywords if word in tags)

        sorted_results = sorted(merged_results, key=tag_score, reverse=True)

        return {"result": sorted_results}

    except Exception as e:
        print("🔥 BACKEND ERROR:", e)
        return {"result": [], "error": str(e)}
