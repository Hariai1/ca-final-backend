# ✅ NEW FastAPI BACKEND (full logic from updated Python script, no logic missed)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import datetime
import csv
from dotenv import load_dotenv
from textblob import TextBlob
from rapidfuzz import process

# ✅ Fix spaCy model load with fallback
import spacy
import spacy.cli

try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    spacy.cli.download("en_core_web_sm")
    nlp = spacy.load("en_core_web_sm")

# ✅ Load .env variables
load_dotenv()

# ✅ Initialize FastAPI app
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

# ✅ Load spaCy model
nlp = spacy.load("en_core_web_sm")

# ✅ Setup Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEAVIATE_URL = os.getenv("WEAVIATE_URL")
WEAVIATE_API_KEY = os.getenv("WEAVIATE_API_KEY")
CLASS_NAME = "FR_Inventories"

client_openai = OpenAI(api_key=OPENAI_API_KEY)
client_weaviate = weaviate.connect_to_weaviate_cloud(
    cluster_url=WEAVIATE_URL,
    auth_credentials=AuthApiKey(WEAVIATE_API_KEY),
    headers={"X-OpenAI-Api-Key": OPENAI_API_KEY}
)

# ✅ Direct Filter Map
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

# ✅ Spell check

def correct_spelling(text):
    return str(TextBlob(text).correct())

# ✅ Rewrite with GPT

def rewrite_with_gpt(query):
    prompt = (
        "You are assisting CA Final students. Correct grammar and rewrite into an academic-style query. "
        "Preserve original intent (example, illustration, test your knowledge, mtp, rtp, past paper, etc.)."
    )
    response = client_openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Rewrite: {query}"}
        ],
        temperature=0.2
    )
    return response.choices[0].message.content.strip()

# ✅ NLP helpers

def normalize(text):
    return [token.lemma_.lower() for token in nlp(text) if not token.is_stop and not token.is_punct]

def pluralize(words):
    out = set(words)
    for w in words:
        if w.endswith("s"):
            out.add(w.rstrip("s"))
        else:
            out.add(w + "s")
    return list(out)

def fuzzy_tags(query_terms, all_tags, threshold=80):
    result = []
    for term in query_terms:
        matches = process.extract(term, all_tags, limit=3)
        for match, score, _ in matches:
            if score >= threshold:
                result.append(match)
    return list(set(result))

# ✅ Logging

def log_query(original, rewritten, method, count):
    path = "query_log.csv"
    row = [datetime.datetime.now().isoformat(), original, rewritten, method, count]
    if not os.path.exists(path):
        with open(path, "w", newline="") as f:
            csv.writer(f).writerow(["Timestamp", "Original", "Rewritten", "Method", "Count"])
    with open(path, "a", newline="") as f:
        csv.writer(f).writerow(row)

# ✅ Request body model
class QueryRequest(BaseModel):
    query: str

@app.post("/search")
def search(request: QueryRequest):
    raw_query = request.query.strip()
    collection = client_weaviate.collections.get(CLASS_NAME)

    # ✅ Case 1: Direct Command
    if raw_query.lower() in command_filters:
        keywords = command_filters[raw_query.lower()]
        all_objs = collection.query.fetch_objects(limit=1000).objects
        matches = []

        for obj in all_objs:
            source = obj.properties.get("sourceDetails", "").lower()
            if any(k.lower() in source for k in keywords):
                matches.append(obj.properties)

        log_query(raw_query, raw_query, "Direct Filter", len(matches))
        return {"results": matches}

    # ✅ Case 2: Hashtag Match
    if raw_query.startswith("#"):
        cleaned = correct_spelling(raw_query.lstrip("#")).lower()
        variants = {cleaned, cleaned.replace(",", ""), cleaned.replace("-", " ")}
        if cleaned.replace(",", "").isdigit():
            try:
                variants.add(f"{int(cleaned.replace(',', '')):,}")
            except:
                pass
        all_objs = collection.query.fetch_objects(limit=1000).objects
        matches = [obj.properties for obj in all_objs if any(v in obj.properties.get("question", "").lower() for v in variants)]
        log_query(raw_query, cleaned, "Hashtag Match", len(matches))
        return {"results": matches}

    # ✅ Case 3: Semantic + Fallbacks
    corrected = correct_spelling(raw_query)
    rewritten = rewrite_with_gpt(corrected)
    if not rewritten or len(rewritten.strip()) < 3:
        return {"results": [], "error": "⛔ Could not process query."}

    # Semantic if 4+ words
    word_count = len(rewritten.split())
    if word_count >= 4:
        response = collection.query.near_text(query=rewritten, distance=0.7, limit=10)
        results = response.objects
        if results:
            log_query(raw_query, rewritten, "Semantic", len(results))
            return {"results": [obj.properties for obj in results]}

    # Fallback to fuzzy tag match
    lemmas = normalize(raw_query)
    expanded = pluralize(lemmas)
    all_objs = collection.query.fetch_objects(limit=1000).objects
    all_tags = list(set(tag for obj in all_objs for tag in obj.properties.get("tags", [])))
    fuzzy = fuzzy_tags(expanded, all_tags)
    results = [obj for obj in all_objs if any(tag in fuzzy for tag in obj.properties.get("tags", []))][:10]
    log_query(raw_query, rewritten, "Keyword (Fuzzy)", len(results))
    return {"results": [obj.properties for obj in results]}

# ✅ This FastAPI retains every capability: spelling check, GPT rewriting, direct filters, hashtags, semantic + keyword fallback, and logging.
