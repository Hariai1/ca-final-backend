# ✅ Step-by-step FastAPI Integration for CA Final Query Processor

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
from dotenv import load_dotenv
import datetime
import csv
import weaviate
from weaviate.auth import AuthApiKey
import openai
import spacy
from textblob import TextBlob
from rapidfuzz import process

# ✅ Load .env variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEAVIATE_API_KEY = os.getenv("WEAVIATE_API_KEY")
WEAVIATE_URL = os.getenv("WEAVIATE_URL")
class_name = "FR_Inventories"

openai.api_key = OPENAI_API_KEY


# ✅ Safety check
if not all([OPENAI_API_KEY, WEAVIATE_API_KEY, WEAVIATE_URL]):
    raise EnvironmentError("Missing one or more environment variables.")

# ✅ Initialize FastAPI app
app = FastAPI()
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or replace * with your Vercel URL for more security
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Connect to OpenAI and Weaviate
client_weaviate = weaviate.connect_to_weaviate_cloud(
    cluster_url=WEAVIATE_URL,
    auth_credentials=AuthApiKey(WEAVIATE_API_KEY),
    headers={"X-OpenAI-Api-Key": OPENAI_API_KEY}
)
import spacy.cli

try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    spacy.cli.download("en_core_web_sm")
    nlp = spacy.load("en_core_web_sm")

# ✅ Input schema
class QueryInput(BaseModel):
    query: str

# ✅ Rewriter prompt and filters
REWRITE_SYSTEM_PROMPT = (
    "You are assisting CA Final students in retrieving specific types of academic questions from a structured database.\n\n"
    "Your task has two steps:\n"
    "1. Correct any spelling or grammar errors in the student's input.\n"
    "2. Rewrite the corrected query into a clear, academic-style version using CA Final terminology — only if necessary for improving clarity.\n\n"
    "STRICT RULE: Do NOT alter the student’s original intent or question type. Preserve meaning exactly.\n\n"
    "→ Interpretation Guide:\n"
    "1. 'example' or 'examples': Match conceptual questions with 'example' in sourceDetails.\n"
    "2. 'illustration' or 'illustrations': Match numerical questions with 'illustration' in sourceDetails.\n"
    "3. 'test your knowledge': Match test questions at chapter end.\n"
    "4. 'mtp': Model Test Papers.\n"
    "5. 'rtp': Revision Test Papers.\n"
    "6. 'past paper' or 'question paper': Past exam questions.\n"
    "If verbs like 'explain', 'understand', or 'clarify' are used, match with 'example'.\n"
    "Return original query if already structured clearly."
)

# ✅ Direct command filters
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

# Helpers
def correct_spelling(text):
    return str(TextBlob(text).correct())

def rewrite_query(text):
    response = openai.ChatCompletion.create(  # ✅ FIXED
        model="gpt-4",
        messages=[
            {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": f"Rewrite this CA Final query: {text}"}
        ],
        temperature=0.2
    )
    return response.choices[0].message.content.strip()

def normalize_tokens(text):
    return [token.lemma_.lower() for token in nlp(text) if not token.is_stop and not token.is_punct]

def expand_variants(term):
    term = term.lower().strip()
    term_nocomma = term.replace(",", "")
    variants = {term, term_nocomma}

    # Number formatting
    if term_nocomma.isdigit():
        variants.add(f"{int(term_nocomma):,}")

    # Hyphenation/spacing
    variants.add(term.replace("-", " "))
    variants.add(term.replace(" ", "-"))
    variants.add(term.replace("-", "").replace(" ", ""))

    return set(variants)

def fuzzy_terms_match(query_terms, all_tags, threshold=80):
    results = []
    for term in query_terms:
        matches = process.extract(term, all_tags, limit=3)
        results.extend([m[0] for m in matches if m[1] >= threshold])
    return list(set(results))

def log_query(original, rewritten, method, count):
    log_file = "query_log.csv"
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write_header = not os.path.exists(log_file)
    with open(log_file, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["Timestamp", "Original", "Rewritten", "Method", "Count"])
        writer.writerow([timestamp, original, rewritten, method, count])

def show_preview(results):
    print(f"\n📘 Found {len(results)} matching questions:")
    for i, item in enumerate(results, 1):
        print(f"{i}. {item['question'][:100]}...")
    choice = input("\n📌 Enter result number to view full details: ")
    if choice.isdigit() and 1 <= int(choice) <= len(results):
        item = results[int(choice) - 1]
        for key in ["chapter", "sourceDetails", "conceptTested", "conceptSummary", "question", "answer", "howToApproach"]:
            print(f"{key.title()}: {item.get(key, '')}")
    else:
        print("❌ Invalid selection.")

# ✅ API Route
@app.post("/process-query")
def process_query_api(input_data: QueryInput):
    raw_query = input_data.query.strip()

    # ✅ Add this correction logic here
    corrected_query = str(TextBlob(raw_query).correct())
    print("📝 Raw Query:", raw_query)
    print("✏️ Corrected Query:", corrected_query)

    # Now replace raw_query with corrected_query for further use
    raw_query = corrected_query
    
    # % command
    if raw_query.lower() in command_filters:
        filters = command_filters[raw_query.lower()]
        all_objs = collection.query.fetch_objects(limit=1000).objects
        results = [
            {key: o.properties.get(key) for key in [
                "chapter", "sourceDetails", "sourceType", "conceptTested", "conceptSummary",
                "question", "answer", "howToApproach"
            ]}
            for o in all_objs
            if any(f in o.properties.get("sourceDetails", "").lower() for f in filters)
        ]
        return {"method": "Direct Filter", "matches": results}

    # # command
    if raw_query.startswith("#"):
        term = correct_spelling(raw_query[1:])
        variants = expand_variants(term)
        all_objs = collection.query.fetch_objects(limit=1000).objects
        results = []
        for obj in all_objs:
            qtext = obj.properties.get("question", "").lower().replace("-", " ").replace(",", "")
            if any(v.replace("-", " ").replace(",", "") in qtext for v in variants):
                results.append({key: obj.properties.get(key) for key in [
                    "chapter", "sourceDetails", "sourceType", "conceptTested", "conceptSummary",
                    "question", "answer", "howToApproach"
                ]})

        return {"method": "Hashtag", "matches": results}

    # Spell check + rewrite
    spell_checked = correct_spelling(raw_query)
    rewritten = rewrite_query(spell_checked)

    # Semantic search
    try:
        sem = collection.query.near_text(query=rewritten, distance=0.7, limit=10)
        objects = sem.objects if sem else []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Semantic search failed: {str(e)}")

    if objects:
        log_query(raw_query, rewritten, "Semantic", len(objects))
        return {"method": "Semantic", "rewritten": rewritten, "matches": [
            {key: obj.properties.get(key) for key in [
                "chapter", "sourceDetails", "sourceType", "conceptTested", "conceptSummary",
                "question", "answer", "howToApproach"
            ]} for obj in objects
        ]}


    # Fuzzy fallback
    tokens = normalize_tokens(raw_query)
    all_objs = collection.query.fetch_objects(limit=1000).objects
    tags = list(set(tag for obj in all_objs for tag in obj.properties.get("tags", [])))
    matched_tags = fuzzy_terms_match(tokens, tags)
    filtered = [obj.properties for obj in all_objs if any(tag in matched_tags for tag in obj.properties.get("tags", []))]

    if filtered:
        log_query(raw_query, rewritten, "Fuzzy", len(filtered))
        return {"method": "Fuzzy", "rewritten": rewritten, "matches": [
            {key: obj.get(key) for key in [
                "chapter", "sourceDetails", "sourceType", "conceptTested", "conceptSummary",
                "question", "answer", "howToApproach"
            ]} for obj in filtered[:10]
        ]}
    else:
        log_query(raw_query, rewritten, "No Match", 0)
        return {"method": "No Match", "rewritten": rewritten, "matches": []}

# ✅ Run the app using: uvicorn main:app --reload
