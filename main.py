from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
import weaviate
from weaviate.auth import AuthApiKey
import openai
from pydantic import BaseModel
import datetime
import csv
import spacy
from textblob import TextBlob
from rapidfuzz import process as rapidfuzz_process

REWRITE_SYSTEM_PROMPT = """
You are assisting CA Final students in navigating a structured academic question bank to retrieve the most relevant questions from specific categories.

Objective:
Help students reach the correct type of question efficiently by clarifying their input - without changing their intended meaning.

🧠 Task (2 Steps):
1. Correct any spelling or grammar errors in the student’s query.
2. If necessary, rewrite the corrected query in a professional, academic tone using CA Final terminology.

STRICT RULE:
Do NOT change the original question type, purpose, or intent. Your job is to improve clarity - not reframe or reinterpret.

📘 Matching Guide (based on sourceDetails):
- "example" or "examples" -> Conceptual questions
- "illustration" or "illustrations" -> Numerical questions
- "test your knowledge" or "tyk" -> End-of-chapter test questions
- "mtp" or "model question paper" -> Model Test Papers
- "rtp" or "revision test paper" -> Revision Test Papers
- "past paper" or "question paper" -> Past exam questions
"""

command_filters = {
    "%example": ["example"],
    "%illustration": ["illustration"],
    "%testyourknowledge": ["test your knowledge"],
    "%tyk": ["test your knowledge"],
    "%mtp": ["mtp"],
    "%modelquestionpaper": ["mtp"],
    "%rtp": ["rtp"],
    "%revisiontestpaper": ["rtp"],
    "%pastpapers": ["past papers"],
    "%other": ["other"],
    "%all": ["example", "illustration", "test your knowledge", "mtp", "rtp", "past papers", "other"]
}

def correct_spelling(text): return str(TextBlob(text).correct())

def rewrite_query(text):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": f"Rewrite this CA Final query: {text}"}
        ],
        temperature=0.2
    )
    return response.choices[0].message.content.strip()

# ✅ Load .env variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEAVIATE_API_KEY = os.getenv("WEAVIATE_API_KEY")
WEAVIATE_URL = os.getenv("WEAVIATE_URL")

# ✅ Initialize OpenAI client (new API style)
import openai  # ✅ make sure this is also imported at the top
openai.api_key = OPENAI_API_KEY  # usually from os.getenv("OPENAI_API_KEY")


# ✅ Print just to confirm loading
print("🔑 OpenAI Key Start:", OPENAI_API_KEY[:8])
print("🔑 Weaviate URL:", WEAVIATE_URL)

# ✅ Initialize FastAPI app
app = FastAPI()

# ✅ Enable CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # You can restrict this to your frontend later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client_weaviate = weaviate.connect_to_weaviate_cloud(
    cluster_url=WEAVIATE_URL,
    auth_credentials=AuthApiKey(WEAVIATE_API_KEY),
    headers={"X-OpenAI-Api-Key": OPENAI_API_KEY},
)

nlp = spacy.load("en_core_web_sm")  # Load the NLP model
collection = client_weaviate.collections.get("FR_Inventories")  # Replace with your actual class name if different


# ✅ Test route
@app.get("/")
def read_root():
    return {"message": "FastAPI is working!"}

@app.get("/test-connections")
def test_connections():
    try:
        weaviate_ready = client_weaviate.is_ready()
        return {
            "openai_key_start": OPENAI_API_KEY[:8],
            "weaviate_url": WEAVIATE_URL,
            "weaviate_ready": weaviate_ready
        }
    except Exception as e:
        return {"error": str(e)}
    

def normalize_tokens(text):
    return [token.lemma_.lower() for token in nlp(text) if not token.is_stop and not token.is_punct]

def expand_variants(term):
    term = term.lower().strip().replace(",", "")
    return {term, term.replace("-", " "), term.replace(" ", "-"), term.replace("-", "").replace(" ", "")}

def fuzzy_terms_match(query_terms, all_tags, threshold=80):
    results = []
    for term in query_terms:
        matches = rapidfuzz_process.extract(term, all_tags, limit=3)
        results.extend([m[0] for m in matches if m[1] >= threshold])
    return list(set(results))

def log_query(original, rewritten, method, count):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("query_log.csv", "a", newline="") as f:
        writer = csv.writer(f)
        if f.tell() == 0:
            writer.writerow(["Timestamp", "Original", "Rewritten", "Method", "Count"])
        writer.writerow([timestamp, original, rewritten, method, count])
class QueryInput(BaseModel):
    query: str


@app.post("/process")
def process_query(payload: QueryInput):
    raw_query = payload.query.strip()

    results = []

    if raw_query.lower() in command_filters:
        filters = command_filters[raw_query.lower()]
        all_objs = collection.query.fetch_objects(limit=1000).objects
        results = [o.properties for o in all_objs if any(f in o.properties.get("sourceDetails", "").lower() for f in filters)]
        method = "Command Filter"

    elif raw_query.startswith("#"):
        term = correct_spelling(raw_query[1:])
        variants = expand_variants(term)
        all_objs = collection.query.fetch_objects(limit=1000).objects
        for obj in all_objs:
            qtext = obj.properties.get("combinedText", "").lower().replace("-", " ").replace(",", "")
            if any(v in qtext for v in variants):
                results.append(obj.properties)
        method = "Hashtag"

    else:
        spell_checked = correct_spelling(raw_query)
        rewritten = rewrite_query(spell_checked)
        print("✅ Spell Checked Query:", spell_checked)
        print("✅ Rewritten Query:", rewritten)
        method = "Semantic"

        try:
            sem = collection.query.near_text(
                query=rewritten,
                distance=0.7,
                limit=10,
                return_metadata=["certainty"]
            )

            if sem and sem.objects:
                print(f"✅ Semantic results returned: {len(sem.objects)}")
                for obj in sem.objects:
                    certainty = getattr(obj.metadata, "certainty", 0)
                    preview = obj.properties.get("question", "")[:60]
                    print(f"🔷 Certainty: {certainty:.3f} | {preview}")

                objects = [
                    obj for obj in sem.objects
                    if hasattr(obj.metadata, "certainty") and obj.metadata.certainty >= 0.75
                ]
                print(f"🎯 High-certainty matches: {len(objects)}")
            else:
                print("⚠️ Semantic returned no results")
                objects = []

        except Exception as e:
            print("❌ Semantic search failed:", e)
            objects = []

        # ✅ Debug output
        print("✅ Rewritten Query:", rewritten)
        print("✅ Total Semantic Matches:", len(objects))
        for i, obj in enumerate(objects[:5]):
            print(f"{i+1}.", obj.properties.get("question", "")[:80])
        

        if objects:
            results = [obj.properties for obj in objects]
            
        else:
            method = "Fuzzy"
            tokens = normalize_tokens(raw_query)
            all_objs = collection.query.fetch_objects(limit=1000).objects
            tags = list(set(tag for obj in all_objs for tag in obj.properties.get("tags", [])))
            matched_tags = fuzzy_terms_match(tokens, tags)
            results = [obj.properties for obj in all_objs if any(tag in matched_tags for tag in obj.properties.get("tags", []))]

    results = results[:50]  # Limit to 50 results max

    # 🔍 Modified preview format: "1. question preview text"
    preview = [
        f"{idx + 1}. {q.get('question', '')[:50]}"
        for idx, q in enumerate(results)
    ]

    # 🔍 Clean full_data: exclude tags and combinedText
    full_data = {
        str(idx + 1): {k: v for k, v in q.items() if k not in ["tags", "combinedText"]}
        for idx, q in enumerate(results)
    }

    log_query(raw_query, raw_query, method, len(results))

    return {
        "preview": preview,
        "full_data": full_data
    }
