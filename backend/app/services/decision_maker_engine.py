import re
import json
import time
import html
import os
import asyncio
from urllib.parse import urljoin, urlparse, urldefrag
import httpx
from bs4 import BeautifulSoup

try:
    from duckduckgo_search import DDGS
    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False

from app.services.search.public_web_search_provider import is_circuit_open, trip_circuit, reset_circuit
from app.services.search_service import decode_redirect_url, is_challenge_or_blocked_page
from app.services.email_validation_service import canonical_person_email_match, is_valid_email_format

# ============================================================
# CONFIGURATION
# ============================================================

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")

OLLAMA_TIMEOUT = 30
REQUEST_TIMEOUT = 10

MAX_OFFICIAL_PAGES = 15
MAX_DDG_RESULTS = 8
MAX_DDG_ROUNDS = 2
DDG_RETRIES = 1
DDG_RETRY_DELAY = 0.5

MAX_FINAL_RESULTS = 8

MAX_PAGE_TEXT_LENGTH = 14000
MAX_EVIDENCE_LENGTH = 1800

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
}

# ============================================================
# ROLE PRIORITY
# ============================================================

ROLE_PRIORITY = {
    "Founder & CEO": 100,
    "Co-Founder & CEO": 99,
    "Founder": 98,
    "Co-Founder": 97,
    "Owner": 96,
    "Proprietor": 96,
    "Chairman & Managing Director": 96,
    "Managing Director & CEO": 95,
    "Joint Managing Director & CEO": 94,
    "Managing Director": 93,
    "Joint Managing Director": 92,
    "Chief Executive Officer": 91,
    "Group CEO": 91,
    "CEO": 90,
    "Executive Chairman": 89,
    "Chairman": 88,
    "Chairperson": 88,
    "Executive Vice Chairman": 87,
    "Vice Chairman": 86,
    "Managing Partner": 85,
    "Executive Director": 84,
    "Whole Time Director": 83,
    "Whole-Time Director": 83,
    "Non-Executive Director": 82,
    "Independent Director": 81,
    "Director": 80,
    "Board Director": 80,
    "Board Member": 80,
    "President": 75,
    "Chief Operating Officer": 74,
    "COO": 74,
    "Chief Financial Officer": 73,
    "CFO": 73,
    "Chief Technology Officer": 72,
    "CTO": 72,
    "Chief Information Officer": 71,
    "CIO": 71,
    "Chief Product Officer": 70,
    "CPO": 70,
    "Chief Business Officer": 70,
    "CBO": 70,
    "Chief Strategy Officer": 70,
    "CSO": 70,
    "Chief Revenue Officer": 69,
    "CRO": 69,
    "Chief Marketing Officer": 68,
    "CMO": 68,
    "Senior Partner": 65,
    "Partner": 64,
    "Principal": 63,
    "Executive Vice President": 62,
    "Senior Vice President": 61,
    "Vice President": 60,
    "VP": 60,
    "Head of AI": 58,
    "Head of Technology": 57,
    "Head of Operations": 56,
    "Head of Sales": 55,
    "Department Head": 50,
    "General Manager": 45,
}

ROLE_PATTERNS = [
    (
        "Chairman & Managing Director",
        r"\b(?:Chairman\s*(?:&|and)\s*Managing\s+Director|CMD)\b",
    ),
    (
        "Joint Managing Director & CEO",
        r"\bJoint\s+Managing\s+Director\s*(?:&|and)\s*(?:Chief\s+Executive\s+Officer|CEO)\b",
    ),
    (
        "Managing Director & CEO",
        r"\bManaging\s+Director\s*(?:&|and)\s*(?:Chief\s+Executive\s+Officer|CEO)\b",
    ),
    (
        "Founder & CEO",
        r"\bFounder\s*(?:&|and)\s*(?:Chief\s+Executive\s+Officer|CEO)\b",
    ),
    (
        "Co-Founder & CEO",
        r"\bCo[-\s]?Founder\s*(?:&|and)\s*(?:Chief\s+Executive\s+Officer|CEO)\b",
    ),
    (
        "Managing Partner",
        r"\bManaging\s+Partner\b",
    ),
    (
        "Senior Partner",
        r"\bSenior\s+Partner\b",
    ),
    (
        "Partner",
        r"\bPartner\b",
    ),
    (
        "Group CEO",
        r"\bGroup\s+(?:Chief\s+Executive\s+Officer|CEO)\b",
    ),
    (
        "Executive Vice Chairman",
        r"\bExecutive\s+Vice\s+Chairman\b",
    ),
    (
        "Non-Executive Chairman",
        r"\bNon[-\s]?Executive\s+Chairman\b",
    ),
    (
        "Executive Chairman",
        r"\bExecutive\s+Chairman\b",
    ),
    (
        "Vice Chairman",
        r"\bVice\s+Chairman\b",
    ),
    (
        "Whole-Time Director",
        r"\bWhole[-\s]?Time\s+Director\b",
    ),
    (
        "Non-Executive Director",
        r"\bNon[-\s]?Executive\s+Director\b",
    ),
    (
        "Independent Director",
        r"\bIndependent\s+Director\b",
    ),
    (
        "Executive Director",
        r"\bExecutive\s+Director\b",
    ),
    (
        "Board Director",
        r"\bBoard\s+Director\b",
    ),
    (
        "Board Member",
        r"\bBoard\s+Member\b",
    ),
    (
        "Chief Executive Officer",
        r"\bChief\s+Executive\s+Officer\b",
    ),
    (
        "Chief Operating Officer",
        r"\bChief\s+Operating\s+Officer\b",
    ),
    (
        "Chief Financial Officer",
        r"\bChief\s+Financial\s+Officer\b",
    ),
    (
        "Chief Technology Officer",
        r"\bChief\s+Technology\s+Officer\b",
    ),
    (
        "Chief Information Officer",
        r"\bChief\s+Information\s+Officer\b",
    ),
    (
        "Chief Product Officer",
        r"\bChief\s+Product\s+Officer\b",
    ),
    (
        "Chief Revenue Officer",
        r"\bChief\s+Revenue\s+Officer\b",
    ),
    (
        "Chief Marketing Officer",
        r"\bChief\s+Marketing\s+Officer\b",
    ),
    (
        "Executive Vice President",
        r"\bExecutive\s+Vice\s+President\b",
    ),
    (
        "Senior Vice President",
        r"\bSenior\s+Vice\s+President\b",
    ),
    (
        "Vice President",
        r"\bVice\s+President\b",
    ),
    (
        "Joint Managing Director",
        r"\bJoint\s+Managing\s+Director\b",
    ),
    (
        "Managing Director",
        r"\b(?:Managing\s+Director|Geschäftsführer(?:in)?|Geschaeftsfuehrer(?:in)?|Geschäftsführung|Geschaeftsfuehrung)\b",
    ),
    (
        "Managing Partner",
        r"\bManaging\s+Partner\b",
    ),
    (
        "Executive Board",
        r"\b(?:Vorstandsvorsitzende[rn]?|Vorstand|Executive\s+Board)\b",
    ),
    (
        "Founder",
        r"\bFounder\b",
    ),
    (
        "Co-Founder",
        r"\bCo[-\s]?Founder\b",
    ),
    (
        "Owner",
        r"\b(?:Owner|Co-Owner|Inhaber(?:in)?)\b",
    ),
    (
        "CEO",
        r"\bCEO\b",
    ),
    (
        "COO",
        r"\bCOO\b",
    ),
    (
        "CFO",
        r"\bCFO\b",
    ),
    (
        "CTO",
        r"\bCTO\b",
    ),
    (
        "CIO",
        r"\bCIO\b",
    ),
    (
        "CPO",
        r"\bCPO\b",
    ),
    (
        "CRO",
        r"\bCRO\b",
    ),
    (
        "CMO",
        r"\bCMO\b",
    ),
    (
        "VP",
        r"\b(?:VP|EVP|SVP)\b",
    ),
    (
        "Chairman",
        r"\bChairman\b",
    ),
    (
        "Chairperson",
        r"\bChairperson\b",
    ),
    (
        "Director",
        r"\bDirector\b",
    ),
    (
        "President",
        r"\b(?<!Vice\s)(?<!Vice-)President\b",
    ),
    (
        "Chief Business Officer",
        r"\bChief\s+Business\s+Officer\b",
    ),
    (
        "CBO",
        r"\bCBO\b",
    ),
    (
        "Chief Strategy Officer",
        r"\bChief\s+Strategy\s+Officer\b",
    ),
    (
        "CSO",
        r"\bCSO\b",
    ),
    (
        "Proprietor",
        r"\bProprietor\b",
    ),
    (
        "Principal",
        r"\bPrincipal\b",
    ),
    (
        "Head of AI",
        r"\b(?:Head\s+of\s+AI|Chief\s+AI\s+Officer|Director\s+of\s+AI)\b",
    ),
    (
        "Head of Technology",
        r"\b(?:Head\s+of\s+Technology|Head\s+of\s+Engineering|VP\s+of\s+Engineering)\b",
    ),
    (
        "Head of Operations",
        r"\bHead\s+of\s+Operations\b",
    ),
    (
        "Head of Sales",
        r"\b(?:Head\s+of\s+Sales|Head\s+of\s+Growth|Head\s+of\s+Marketing)\b",
    ),
    (
        "Department Head",
        r"\b(?:Department\s+Head|Head\s+of\s+Department)\b",
    ),
    (
        "General Manager",
        r"\bGeneral\s+Manager\b",
    ),
]

ORGANIZATION_TERMS = {
    # Universal Corporate Legal Suffixes
    "limited", "ltd", "private", "pvt", "inc", "incorporated", "llc", "llp", "plc",
    "corp", "corporation", "corporate", "co", "gmbh", "ag", "sa", "bv", "nv", "srl",
    "pty", "holdings", "holding", "group", "enterprises", "enterprise",
    # Universal Organizational Entities
    "company", "companies", "foundation", "institute", "institution", "association",
    "organization", "organisation", "council", "committee", "trust", "bank", "fund",
    "federation", "agency", "subsidiary", "headquarters", "dept", "department",
    # Corporate Units
    "solutions", "services", "systems", "technologies", "ventures", "capital",
    "partners", "partnership", "networks", "network", "consulting",
    "world", "environmental", "textiles", "fibres", "industries", "chemicals",
    "management", "usa", "global", "international",
}

BAD_NAME_WORDS = {
    # Non-person words often extracted in false positives
    "about", "board", "company", "companies", "contact", "corporate",
    "director", "directors", "executive", "executives", "founder", "founders",
    "group", "head", "leadership", "management", "manager", "managing",
    "member", "members", "office", "owner", "president", "profile", "profiles",
    "team", "the", "our", "who", "investor", "investors", "career", "careers",
    "business", "businesses", "chairman", "chairmen", "ceo", "cfo", "coo", "cto",
    "chief", "financial", "operating", "technology", "marketing", "relations",
    "committee", "council", "committee:", "board:", "team:", "leadership:",
    "overview", "history", "mission", "vision", "values", "governance",
    "advisory", "partners", "partnership", "services", "solutions",
    # Transportation, Logistics & Operational terms that appear in navigation/services
    "freight", "mile", "fleet", "carrier", "carriers", "truck", "trucking",
    "driver", "drivers", "driving", "transport", "transportation", "dedicated",
    "intermodal", "logistics", "shipping", "school", "schools", "roadmaster",
    "warehouse", "warehousing", "supply", "chain", "distribution",
}

HISTORICAL_MARKERS = [
    "previously", "previous experience", "previous role", "former",
    "formerly", "earlier", "prior", "prior to", "was the", "was a",
    "served as", "had been", "ex-", "ex ", "past role", "past experience",
    "before joining", "before joining us", "previous employer",
    "previous company", "earlier served", "earlier worked",
    "retired", "stepped down", "resigned", "predecessor",
]

# ============================================================
# URL & TEXT HELPERS
# ============================================================

def clean_url(url):
    if not url:
        return ""
    url = html.unescape(str(url).strip())
    if url.startswith("[") and url.endswith("]"):
        url = url[1:-1]
    markdown_match = re.search(r"https?://[^\s\]]+", url)
    if markdown_match:
        url = markdown_match.group(0)
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    url, _ = urldefrag(url)
    return url.rstrip("/")

def canonical_domain(url):
    try:
        domain = urlparse(clean_url(url)).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""

def same_domain(url1, url2):
    d1 = canonical_domain(url1)
    d2 = canonical_domain(url2)
    return bool(d1) and bool(d2) and d1 == d2

def is_probable_web_page(url):
    if not url:
        return False
    lower = url.lower().split("?")[0]
    blocked = (
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
        ".mp4", ".mp3", ".zip", ".rar", ".xlsx", ".xls", ".doc",
        ".docx", ".ppt", ".pptx", ".pdf"
    )
    return not lower.endswith(blocked)

def normalize_text(text):
    if not text:
        return ""
    text = html.unescape(str(text))
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()

HEADER_PREFIXES = {
    "leadership", "team", "management", "about", "our", "meet", "board",
    "executive", "executives", "profile", "profiles", "contact", "people",
    "directors", "close", "view", "read", "share"
}

def normalize_name(name):
    if not name:
        return ""
    name = normalize_text(name)
    name = name.strip(" ,.;:-|()[]{}")
    name = re.sub(r"^(Mr|Mrs|Ms|Miss|Dr|Prof|Sir|Shri|Smt|Late)\.?\s+", "", name, flags=re.I)
    name = re.sub(r"\s+(Jr|Sr|II|III|IV|Esq)\.?$", "", name, flags=re.I)
    words = name.split()
    while len(words) > 2 and words[0].lower().rstrip(":") in HEADER_PREFIXES:
        words = words[1:]
    name = " ".join(words)
    return name.strip()

def name_key(name):
    return re.sub(r"[^a-z]", "", normalize_name(name).lower())

def clean_brand_name(company_name):
    if not company_name:
        return ""
    # Strip parenthetical annotations like (India), (UK), (Pvt Ltd)
    name = re.sub(r"\(.*?\)", " ", company_name)
    # Strip legal registrations
    legal_pattern = r"\b(limited|ltd|private|pvt|inc|incorporated|llc|llp|plc|corp|corporation|gmbh|ag|sa|bv|pty)\b.*$"
    name = re.sub(legal_pattern, " ", name, flags=re.I)
    return normalize_text(name).strip(" ,.-")

def company_tokens(company_name):
    stop_words = {
        "limited", "ltd", "private", "pvt", "company", "corporation",
        "corporate", "the", "inc", "llc", "llp", "plc", "corp", "gmbh",
        "ag", "sa", "bv", "pty", "group", "holdings", "holding", "enterprises",
        "enterprise", "solutions", "services", "technologies", "technology",
        "international", "global", "and", "co"
    }
    words = re.findall(r"[a-z0-9]+", company_name.lower())
    return [w for w in words if len(w) >= 3 and w not in stop_words]

# ============================================================
# ENTITY & NAME VALIDATION
# ============================================================

GEOGRAPHIC_TERMS = {
    "altona", "zealand", "australia", "america", "africa", "asia", "europe",
    "canada", "ireland", "kingdom", "singapore", "delhi", "mumbai",
    "melbourne", "sydney", "auckland", "wellington", "london", "dublin",
    "california", "texas", "florida", "district", "province", "county",
    "suburb", "suburbs", "depot", "terminal", "airport", "harbor", "harbour"
}

DIRECTIONAL_TERMS = {"north", "south", "east", "west", "central", "coastal", "regional"}

ASSET_DOCUMENT_TERMS = {
    "media", "kit", "press", "brand", "sheet", "paper", "manual", "guide",
    "policy", "terms", "conditions", "newsroom", "assets", "resource", "resources",
    "center", "centre", "portal", "download", "downloads", "brochure", "catalog", "catalogue", "pricing",
    "plans", "faq", "faqs", "case", "study", "studies", "article", "articles",
    "podcast", "webinar", "overview", "release"
}

def looks_like_organization_name(name, company_name=""):
    raw = normalize_text(name).lower()
    if not raw:
        return True
    if raw.endswith(("'s", "’s")):
        return True

    # 1. Exact match with company name or clean brand name
    if company_name:
        brand = clean_brand_name(company_name).lower()
        if raw == company_name.lower() or (brand and raw == brand):
            return True
        if name_key(raw) == name_key(company_name) or (brand and name_key(raw) == name_key(brand)):
            return True
        brand_tokens = set(re.findall(r"[a-z0-9]+", brand))
        raw_tokens = set(re.findall(r"[a-z0-9]+", raw))
        if brand_tokens and brand_tokens.issubset(raw_tokens) and any(t in ORGANIZATION_TERMS for t in raw_tokens):
            return True
        first_brand_word = brand.split()[0] if brand.split() else ""
        if first_brand_word and len(first_brand_word) >= 4 and first_brand_word in raw_tokens:
            if any(t in ORGANIZATION_TERMS for t in raw_tokens) or any(t in BAD_NAME_WORDS for t in raw_tokens):
                return True

    # 2. Known organizational committees, departments & non-person labels
    company_like_phrases = [
        "innovation projects", "management team", "leadership team",
        "executive team", "executive committee", "advisory board",
        "board committee", "csr committee", "audit committee",
        "nomination committee", "risk committee", "board of directors",
        "investor relations", "contact us", "customer care", "customer service",
        "media kit", "press kit", "brand kit", "fact sheet", "white paper",
        "case study", "case studies", "terms of service", "privacy policy",
        "terms of use", "cookie policy", "terms and conditions", "press release",
        "news release", "all rights reserved", "rights reserved", "new zealand",
        "united states", "united kingdom", "south africa", "altona north",
    ]
    if any(phrase in raw for phrase in company_like_phrases):
        return True

    tokens = re.findall(r"[a-z]+", raw)
    if not tokens:
        return True

    # 3. If any token is an explicit corporate suffix (Ltd, Inc, LLC, Foundation, etc.)
    if any(token in ORGANIZATION_TERMS for token in tokens):
        return True

    # 4. Location + Directional check (e.g. Altona North, Sydney West)
    has_geo = any(t in GEOGRAPHIC_TERMS for t in tokens)
    has_dir = any(t in DIRECTIONAL_TERMS for t in tokens)
    if has_geo and has_dir:
        return True

    # 5. Multi-asset noun check (e.g. Media Kit, Fact Sheet, Case Study, White Paper)
    asset_count = sum(1 for t in tokens if t in ASSET_DOCUMENT_TERMS)
    if asset_count >= 2:
        return True

    # 6. Prefix + Location (e.g. New Zealand, United States, South Africa)
    if len(tokens) >= 2 and tokens[0] in {"new", "united", "south", "north", "east", "west", "central"} and any(t in GEOGRAPHIC_TERMS for t in tokens[1:]):
        return True

    # 7. If all tokens are non-person name words
    bad_count = sum(
        1 for token in tokens
        if token in BAD_NAME_WORDS
        or token in ORGANIZATION_TERMS
        or token in GEOGRAPHIC_TERMS
        or token in DIRECTIONAL_TERMS
        or token in ASSET_DOCUMENT_TERMS
    )
    if bad_count >= len(tokens):
        return True

    return False

def is_strict_person_name(name, company_name=""):
    name = normalize_name(name)
    if not name or len(name) < 4 or len(name) > 70:
        return False
    if looks_like_organization_name(name, company_name):
        return False
    if any(char.isdigit() for char in name):
        return False
    tokens = name.split()
    if not (2 <= len(tokens) <= 5):
        return False

    # First token must be a valid given name (at least 2 chars, or initial with period)
    first_token = tokens[0].strip(".,'-")
    if len(first_token) < 2 and not re.fullmatch(r"[A-Za-z]\.", tokens[0]):
        return False

    # Ensure last name is at least 2 characters (reject single letters like 'L' or 'S')
    last_token = tokens[-1].strip(".,'-")
    if len(last_token) < 2:
        return False

    # Reject company brand names used as placeholder person names (e.g., "Acme Officer", "Acme Leadership")
    if company_name:
        brand = clean_brand_name(company_name).lower()
        first_brand_word = brand.split()[0] if brand.split() else ""
        if first_brand_word and len(first_brand_word) >= 3:
            if any(t.lower().strip(".,'-") == first_brand_word for t in tokens):
                if any(t.lower().strip(".,'-") in ORGANIZATION_TERMS or t.lower().strip(".,'-") in BAD_NAME_WORDS for t in tokens):
                    return False

    for token in tokens:
        raw = token.strip(".,'-")
        if not raw:
            return False
        if raw.lower() in BAD_NAME_WORDS:
            return False
        if re.fullmatch(r"[A-Za-z]\.", raw):
            continue
        if not re.fullmatch(r"[A-Z][A-Za-zÀ-ÖØ-öø-ÿ.'-]*", raw):
            return False
        if len(raw) > 30:
            return False
    lower = name.lower()
    forbidden = [
        "audit committee", "nomination committee", "nominations committee",
        "esg committee", "risk committee", "csr committee", "committee",
        "board of directors", "board of director", "board committee",
        "has featured", "featured ms", "featured mr", "view more",
        "read more", "click here", "story of", "storyboard", "latest news",
        "chief executive officer", "managing director", "board of",
        "management team", "leadership team", "company profile", "contact us",
        "media kit", "press kit", "white paper", "case study", "fact sheet"
    ]
    if any(phrase in lower for phrase in forbidden):
        return False
    return True

PERSON_NAME_PATTERN = (
    r"(?:"
    r"(?:[A-Z]\.?|[A-Z][a-zÀ-ÖØ-öø-ÿ\'-]+)"
    r"(?:\s+(?:[A-Z]\.?|[A-Z][a-zÀ-ÖØ-öø-ÿ\'-]+)){1,3}"
    r")"
)

def best_role_from_phrase(role_phrase):
    role_phrase = normalize_text(role_phrase)
    if not role_phrase:
        return None
    matches = []
    for role, pattern in ROLE_PATTERNS:
        if re.search(pattern, role_phrase, flags=re.I):
            matches.append(role)
    if not matches:
        return None
    return max(matches, key=lambda r: ROLE_PRIORITY.get(r, 0))

def extract_roles(text):
    text = normalize_text(text)
    matches = []
    for role, pattern in ROLE_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.I):
            matches.append({
                "role": role,
                "start": match.start(),
                "end": match.end(),
            })
    matches.sort(key=lambda x: (x["start"], -(x["end"] - x["start"])))
    accepted = []
    for item in matches:
        overlaps = False
        for existing in accepted:
            if not (item["end"] <= existing["start"] or item["start"] >= existing["end"]):
                overlaps = True
                break
        if not overlaps:
            accepted.append(item)
    return accepted

def company_context_matches_target(context, company_name):
    context = normalize_text(context).lower()
    target = normalize_text(company_name).lower()
    if target in context:
        return True
    target_tokens = company_tokens(company_name)
    hits = sum(1 for token in target_tokens if re.search(r"\b" + re.escape(token) + r"\b", context))
    return hits >= 1

def role_is_historical(evidence, name, role):
    lower = normalize_text(evidence).lower()
    name_clean = normalize_name(name).lower()
    role_clean = normalize_text(role).lower()
    name_toks = [t for t in re.findall(r"[a-z]+", name_clean) if len(t) >= 2]
    first_tok = name_toks[0] if name_toks else ""
    last_tok = name_toks[-1] if len(name_toks) > 1 else ""

    # Direct person-attached historical patterns
    # e.g., "former CEO Alice Brown", "Alice Brown, former CEO", "ex-CEO Alice"
    escaped_role = re.escape(role_clean)
    escaped_name = re.escape(name_clean)
    direct_historical_patterns = [
        r"\b(?:former|formerly|past|ex[-\s]|retired|late)\s+(?:the\s+)?(?:\w+\s+){0,3}" + escaped_role + r"(?:\s*[:,–—\-]\s*|\s+(?:of|at|for)\s+|\s+)" + escaped_name,
        r"\b(?:former|formerly|past|ex[-\s]|retired|late)\s+" + escaped_name,
        escaped_name + r"\s*(?:,|–|—|-|\()\s*(?:former|formerly|past|ex[-\s]|retired)\s+(?:the\s+)?(?:\w+\s+){0,3}" + escaped_role,
        escaped_name + r"\s+(?:served\s+as|was\s+the|was\s+a|worked\s+as|held\s+the\s+role\s+of)\s+(?:the\s+)?(?:\w+\s+){0,3}" + escaped_role + r"\s+(?:until|through|prior\s+to|from\s+\d{4}\s+to)\s+\d{4}",
        escaped_name + r"\s+(?:stepped\s+down|resigned|retired)\s+as\s+(?:the\s+)?(?:\w+\s+){0,3}" + escaped_role,
        escaped_name + r"\s+(?:served\s+as|was)\s+(?:the\s+)?(?:\w+\s+){0,3}" + escaped_role + r"\s+until\b",
    ]
    for p in direct_historical_patterns:
        if re.search(p, lower, re.I):
            return True

    # Split into clauses/sentences
    clauses = re.split(r'[.\n;!?]+|,\s*(?:who|while|and\s+previously|before\s+joining)\s+', lower)
    for clause in clauses:
        c = clause.strip()
        if not c:
            continue

        # Check if this clause relates to this person
        person_in_clause = (name_clean and name_clean in c) or (first_tok and last_tok and first_tok in c and last_tok in c)
        if not person_in_clause:
            continue

        # Check if clause explicitly identifies this person as CURRENT
        has_current_marker = bool(re.search(r"\b(?:current|present|currently|appointed\s+as|now\s+serves\s+as|joined\s+as\s+the)\b", c))
        has_former_prefix = bool(re.search(r"\b(?:former|formerly|past|retired|ex[-\s])\b", c))

        if has_current_marker and not has_former_prefix:
            # Explicitly current, not historical
            continue

        # Check for historical markers in the person's clause
        for marker in HISTORICAL_MARKERS:
            if re.search(r"\b" + re.escape(marker) + r"\b", c):
                # If marker is "until", ensure it relates to past tenure (e.g. until 2022)
                if marker == "until" and not re.search(r"\buntil\s+\d{4}\b", c):
                    continue
                return True

    return False

def role_attached_to_other_company(evidence, company_name):
    lower = normalize_text(evidence).lower()
    target_tokens = set(company_tokens(company_name))
    brand = clean_brand_name(company_name).lower()
    first_brand_word = brand.split()[0] if brand.split() else ""

    # Check 1: Explicit delimiter parsing (pipe, slash, dash, at, for, of, comma)
    # Matches: Role [|,–—\/-] ExternalCompany (e.g. "Owner | Fris Karton", "Co-Owner | Dücker Prefeeder")
    sep_pattern = re.compile(
        r"\b(?:co-founder|founder|owner|co-owner|ceo|chief executive officer|managing director|managing partner|partner|director|chairman|president|cto|cfo|coo|cio|chief technology officer|chief operating officer|chief financial officer|chief information officer|head of [a-z]+|vice president|vp)\b\s*"
        r"(?:[|/–—\-]|\s+(?:of|at|for)\s+)\s*"
        r"([^\W\d_][\w &.,'-]{1,60}?)"
        r"(?:\s*[\"“„'”\n]|,\s*|\s*\(|$)",
        re.I | re.UNICODE
    )
    for match in sep_pattern.finditer(evidence):
        company_context = normalize_text(match.group(1)).strip()
        if not company_context:
            continue
        context_tokens = set(re.findall(r"[a-z0-9]+", company_context.lower()))
        # If the matched token is the target company itself, it is NOT an external company
        if first_brand_word and len(first_brand_word) >= 3 and first_brand_word in context_tokens:
            continue
        meaningful_target = {
            token for token in target_tokens
            if token not in {"limited", "ltd", "private", "pvt", "public", "company", "corporation", "corp", "inc", "group", "holdings", "industries"}
        }
        if meaningful_target and any(t in context_tokens for t in meaningful_target):
            continue
        # Context tokens represent an external company
        if len(context_tokens) >= 1:
            return True

    # Check 2: Customer / Partner testimonial quote detection
    # Quotes praising the target company or its products indicate a client or partner speaker
    quote_markers = [
        r"[„“\"](?:by combining our expertise|with our|that we installed|our customers|the celluveyor|offers our customers|together with|in our experience|working with|installed in the year|impressed me|gave us)\b",
        r"\b(?:case\s+study|success\s+story|client\s+story|customer\s+review|testimonial)\b",
    ]
    for qm in quote_markers:
        if re.search(qm, lower):
            if re.search(r"\b(?:owner|co-owner|director|managing director|partner|co-founder)\s*[|/–—\-]", lower):
                return True

    # Check 3: Standard corporate patterns
    patterns = [
        r"\b(?:founder|co-founder|owner|ceo|chief executive officer|managing director|director|chairman)\b\s*(?:,|\s+(?:of|at|for)\s+)\s*([A-Za-z][A-Za-z0-9& .,'-]{2,100})",
        r"\b(?:founder|co-founder)\s+(?:of|at)\s+([A-Za-z][A-Za-z0-9& .,'-]{2,100})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, lower, flags=re.I):
            company_context = normalize_text(match.group(1))
            if not company_context:
                continue
            context_tokens = set(re.findall(r"[a-z0-9]+", company_context.lower()))
            if first_brand_word and len(first_brand_word) >= 3 and first_brand_word in context_tokens:
                continue
            meaningful_target = {
                token for token in target_tokens
                if token not in {"limited", "ltd", "private", "pvt", "public", "company", "corporation", "corp", "inc", "india", "group", "holdings", "industries"}
            }
            if meaningful_target and (meaningful_target.issubset(context_tokens) or any(t in context_tokens for t in meaningful_target)):
                continue
            if any(token in ORGANIZATION_TERMS for token in context_tokens):
                return True
    return False

def make_candidate_relationship(text, start, end, name, role):
    evidence_start = max(0, start - 250)
    evidence_end = min(len(text), end + 450)
    evidence = normalize_text(text[evidence_start:evidence_end])
    return {
        "name": normalize_name(name),
        "role": role,
        "evidence": evidence[:MAX_EVIDENCE_LENGTH],
    }

# ============================================================
# DIRECT RELATIONSHIP EXTRACTION (ROBUST PATTERNS)
# ============================================================

def extract_direct_relationships(text, company_name=""):
    text = normalize_text(text)
    if not text:
        return []
    results = []
    role_text = "(?i:(?:" + "|".join(pattern for _, pattern in ROLE_PATTERNS) + "))"

    # 1. NAME , ROLE / NAME - ROLE / NAME | ROLE / NAME . ROLE
    pattern_name_role = re.compile(
        r"(?P<name>" + PERSON_NAME_PATTERN + r")\s*(?:,|:|\||-|–|—|\.)\s*(?P<role>" + role_text + r")"
    )
    for match in pattern_name_role.finditer(text):
        name = normalize_name(match.group("name"))
        role = best_role_from_phrase(match.group("role"))
        if role and is_strict_person_name(name, company_name):
            results.append(make_candidate_relationship(text, match.start(), match.end(), name, role))

    # 2. ROLE : NAME / ROLE - NAME / ROLE is NAME
    pattern_role_name = re.compile(
        r"(?P<role>" + role_text + r")\s*(?:,|:|\||-|–|—|\.|\s+is|\s+serves\s+as)\s*(?P<name>" + PERSON_NAME_PATTERN + r")"
    )
    for match in pattern_role_name.finditer(text):
        name = normalize_name(match.group("name"))
        role = best_role_from_phrase(match.group("role"))
        if role and is_strict_person_name(name, company_name):
            results.append(make_candidate_relationship(text, match.start(), match.end(), name, role))

    # 3. NAME IS [currently/also] [the] ROLE / SERVES AS ROLE
    pattern_is_role = re.compile(
        r"(?P<name>" + PERSON_NAME_PATTERN + r")\s+(?:is|serves\s+as|serving\s+as|appointed\s+as|joined\s+as)\s+(?:also\s+|currently\s+|now\s+)?(?:the\s+)?(?P<role>" + role_text + r")"
    )
    for match in pattern_is_role.finditer(text):
        name = normalize_name(match.group("name"))
        role = best_role_from_phrase(match.group("role"))
        if role and is_strict_person_name(name, company_name):
            results.append(make_candidate_relationship(text, match.start(), match.end(), name, role))

    # 4. [led by / headed by / consists of / like] NAME ,? ROLE
    pattern_consists_of = re.compile(
        r"(?:led\s+by|headed\s+by|consists\s+of|comprises\s+of|including|like)\s+(?P<name>" + PERSON_NAME_PATTERN + r")\s*(?:,|–|-|\s+as|\s+who\s+is)?\s*(?P<role>" + role_text + r")"
    )
    for match in pattern_consists_of.finditer(text):
        name = normalize_name(match.group("name"))
        role = best_role_from_phrase(match.group("role"))
        if role and is_strict_person_name(name, company_name):
            results.append(make_candidate_relationship(text, match.start(), match.end(), name, role))

    # 5. ROLE OF NAME
    pattern_role_of_name = re.compile(
        r"(?P<role>" + role_text + r")\s+(?:of|for|at)\s+(?P<name>" + PERSON_NAME_PATTERN + r")"
    )
    for match in pattern_role_of_name.finditer(text):
        name = normalize_name(match.group("name"))
        role = best_role_from_phrase(match.group("role"))
        if role and is_strict_person_name(name, company_name):
            results.append(make_candidate_relationship(text, match.start(), match.end(), name, role))

    # 6. NAME , ROLE OF COMPANY
    pattern_name_role_company = re.compile(
        r"(?P<name>" + PERSON_NAME_PATTERN + r")\s*,\s*(?P<role>" + role_text + r")\s+(?:of|at|for)\s+(?P<company>.{2,120})"
    )
    for match in pattern_name_role_company.finditer(text):
        name = normalize_name(match.group("name"))
        role = best_role_from_phrase(match.group("role"))
        company_ctx = normalize_text(match.group("company"))
        if role and is_strict_person_name(name, company_name):
            if company_context_matches_target(company_ctx, company_name):
                results.append(make_candidate_relationship(text, match.start(), match.end(), name, role))

    # 7. BOARD OF DIRECTORS / EXECUTIVES LIST: "comprises Name, Name and Name" or "board consists of Name..."
    board_list_pattern = re.compile(
        r"(?:board\s+of\s+directors|board\s+members|\bboard\b|directors|executives|management\s+team)\b"
        r"[^.\n]{0,80}?"
        r"(?:comprises|consists\s+of|include|includes|including|like|-|:)\s*"
        r"(?:(?:experienced\s+)?professionals,?\s*(?:including\s+)?)?"
        r"([A-Z][a-zA-Z\s,]+?(?:and\s+[A-Z][a-zA-Z\s]+)?)"
        r"(?:\.|;|\band\s+\d|\band\s+others|,\s+and\s+others|\boverseeing|\bmain|\bLtd|\bLimited|\n|$)",
        re.I
    )
    for match in board_list_pattern.finditer(text):
        matched_str = match.group(0).lower()
        role = "Chief Executive Officer" if "ceo" in matched_str else ("Director" if "director" in matched_str or "board" in matched_str else "Executive")
        raw_names_block = match.group(1)
        potential_names = re.split(r",\s*(?:and\s+)?|\s+and\s+", raw_names_block)
        for pn in potential_names:
            pn_clean = normalize_name(pn)
            if pn_clean and is_strict_person_name(pn_clean, company_name):
                results.append(make_candidate_relationship(text, match.start(), match.end(), pn_clean, role))

    # 8. Appointment Letter / Profile of Director: "Appointment Letter - Mr./Dr. Name"
    appointment_pattern = re.compile(
        r"(?:Appointment\s+Letter|Profile\s+of\s+Director[s]?)\s*-\s*(?:(?:Mr|Mrs|Ms|Dr)\.?\s+)?([A-Z][a-zA-Z\s.]+)",
        re.I
    )
    for match in appointment_pattern.finditer(text):
        pn_clean = normalize_name(match.group(1))
        if pn_clean and is_strict_person_name(pn_clean, company_name):
            results.append(make_candidate_relationship(text, match.start(), match.end(), pn_clean, "Director"))

    # Deduplicate
    unique = {}
    for candidate in results:
        key = (name_key(candidate["name"]), candidate["role"])
        unique[key] = candidate
    return list(unique.values())

def extract_candidates_from_text(text, source_url, source_type, company_name):
    text = normalize_text(text)
    if not text:
        return []
    text = text[:MAX_PAGE_TEXT_LENGTH]
    relationships = extract_direct_relationships(text, company_name)
    candidates = []
    for item in relationships:
        name = item["name"]
        role = item["role"]
        evidence = item["evidence"]
        if not is_strict_person_name(name, company_name):
            continue
        if role_is_historical(evidence, name, role):
            continue
        if role_attached_to_other_company(evidence, company_name):
            continue
        candidates.append({
            "name": name,
            "role": role,
            "source_url": clean_url(source_url),
            "source_type": source_type,
            "evidence": evidence,
        })
    return candidates

# ============================================================
# HTML LEADERSHIP BLOCKS & PAGE EXTRACTION
# ============================================================

def clean_html_text(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "footer"]):
        tag.decompose()
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr", "br"]):
        tag.insert_after(". ")
    return normalize_text(soup.get_text(" ", strip=True))

def extract_leadership_blocks(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "footer"]):
        tag.decompose()
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr", "br"]):
        tag.insert_after(". ")
    blocks = []
    leadership_words = [
        "leadership", "management", "board", "director", "founder",
        "team", "executive", "governance", "about", "people"
    ]
    tags = soup.find_all(["article", "section", "li", "tr", "td", "div"])
    for tag in tags:
        text = normalize_text(tag.get_text(" ", strip=True))
        if len(text) < 15 or len(text) > 1800:
            continue
        attrs = " ".join([str(tag.get("id", "")), " ".join(tag.get("class", []))]).lower()
        role_present = bool(extract_roles(text))
        marker_present = any(word in attrs for word in leadership_words)
        if role_present or marker_present:
            blocks.append(text)
    unique = []
    seen = set()
    for block in blocks:
        key = re.sub(r"\W+", " ", block.lower()).strip()
        if key not in seen:
            seen.add(key)
            unique.append(block)
    return unique

# ============================================================
# DOM & STRUCTURED DATA EXTRACTORS
# ============================================================

def extract_json_ld_candidates(html_content, source_url, company_name):
    """
    Extracts decision maker candidates from JSON-LD schema.org structured data.
    Supports @type: Person, or @type: Organization with employee/founder/member/alumni.
    """
    candidates = []
    if not html_content or "<script" not in html_content.lower():
        return candidates

    try:
        soup = BeautifulSoup(html_content, "html.parser")
        scripts = soup.find_all("script", type=re.compile(r"application/ld\+json", re.I))
        for script in scripts:
            try:
                content = script.string or script.get_text()
                if not content:
                    continue
                data = json.loads(content)
                items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
                flat_items = []
                for item in items:
                    if isinstance(item, dict):
                        if "@graph" in item and isinstance(item["@graph"], list):
                            flat_items.extend(item["@graph"])
                        else:
                            flat_items.append(item)

                for item in flat_items:
                    if not isinstance(item, dict):
                        continue
                    item_type = str(item.get("@type", "")).lower()
                    if "person" in item_type:
                        name = item.get("name")
                        job_title = item.get("jobTitle") or item.get("roleName") or ""
                        if isinstance(job_title, list):
                            job_title = ", ".join(str(j) for j in job_title)
                        role = best_role_from_phrase(str(job_title))
                        if name and role and is_strict_person_name(name, company_name):
                            email = normalize_email(item.get("email"))
                            cand = {
                                "name": normalize_name(name),
                                "role": role,
                                "source_url": clean_url(source_url),
                                "source_type": "official_website",
                                "evidence": f"{name} is identified as {role} in website JSON-LD structured data."
                            }
                            if email and not is_generic_email(email) and not is_free_email(email):
                                cand["exact_email"] = email
                            candidates.append(cand)

                    if any(t in item_type for t in ["organization", "corporation", "company"]):
                        for relation in ["employee", "employees", "founder", "founders", "member", "members"]:
                            rel_val = item.get(relation)
                            if not rel_val:
                                continue
                            rel_list = rel_val if isinstance(rel_val, list) else [rel_val]
                            for person in rel_list:
                                if isinstance(person, dict):
                                    p_name = person.get("name")
                                    p_title = person.get("jobTitle") or person.get("roleName") or ("Founder" if "founder" in relation else "")
                                    role = best_role_from_phrase(str(p_title))
                                    if p_name and role and is_strict_person_name(p_name, company_name):
                                        email = normalize_email(person.get("email"))
                                        cand = {
                                            "name": normalize_name(p_name),
                                            "role": role,
                                            "source_url": clean_url(source_url),
                                            "source_type": "official_website",
                                            "evidence": f"{p_name} is identified as {role} in organization JSON-LD structured data."
                                        }
                                        if email and not is_generic_email(email) and not is_free_email(email):
                                            cand["exact_email"] = email
                                        candidates.append(cand)
            except Exception:
                continue
    except Exception:
        pass
    return candidates

def extract_table_candidates(soup, source_url, company_name):
    """
    Extracts leadership candidates from HTML <table> elements with tabular data.
    Recognizes columns like 'Name', 'Designation' / 'Role', 'Email', etc.
    """
    candidates = []
    if not soup:
        return candidates

    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        header_row = table.find("tr")
        headers = [normalize_text(th.get_text()).lower() for th in header_row.find_all(["th", "td"])]
        
        name_idx = -1
        role_idx = -1
        email_idx = -1

        for idx, h in enumerate(headers):
            if any(k in h for k in ["name", "director", "executive", "person", "member", "leader"]):
                if name_idx == -1: name_idx = idx
            if any(k in h for k in ["designation", "role", "title", "position", "office", "profile"]):
                if role_idx == -1: role_idx = idx
            if any(k in h for k in ["email", "mail", "contact"]):
                if email_idx == -1: email_idx = idx

        data_rows = rows[1:] if (name_idx != -1 or role_idx != -1) else rows
        if name_idx == -1 or role_idx == -1:
            if len(headers) >= 2:
                name_idx = 0
                role_idx = 1
                if len(headers) >= 3:
                    email_idx = 2
            else:
                continue

        for row in data_rows:
            cells = row.find_all(["td", "th"])
            if len(cells) <= max(name_idx, role_idx):
                continue

            raw_name = normalize_text(cells[name_idx].get_text())
            raw_role = normalize_text(cells[role_idx].get_text())
            row_text = normalize_text(row.get_text(" | "))

            role = best_role_from_phrase(raw_role)
            name = normalize_name(raw_name)

            if not role or not name or not is_strict_person_name(name, company_name):
                # Check inverted columns (col 0 = role, col 1 = name)
                inv_role = best_role_from_phrase(raw_name)
                inv_name = normalize_name(raw_role)
                if inv_role and inv_name and is_strict_person_name(inv_name, company_name):
                    name, role = inv_name, inv_role

            if role and name and is_strict_person_name(name, company_name):
                evidence = row_text if name.lower() in row_text.lower() else f"{name} - {role} (Official Table Record)"
                cand = {
                    "name": name,
                    "role": role,
                    "source_url": clean_url(source_url),
                    "source_type": "official_website",
                    "evidence": evidence[:MAX_EVIDENCE_LENGTH]
                }
                row_emails = extract_emails(row_text)
                if email_idx != -1 and email_idx < len(cells):
                    cell_emails = extract_emails(cells[email_idx].get_text())
                    if cell_emails:
                        row_emails.extend(cell_emails)
                for em in row_emails:
                    if not is_generic_email(em) and not is_free_email(em):
                        cand["exact_email"] = em
                        break
                candidates.append(cand)

    return candidates

def extract_structured_card_candidates(soup, source_url, company_name):
    """
    Extracts leadership candidates from modern card/grid layouts (e.g. div.team-card, article.leader).
    """
    candidates = []
    if not soup:
        return candidates

    card_selector = re.compile(r"team|leader|member|exec|profile|bio|card|person|director|board", re.I)
    cards = soup.find_all(lambda tag: tag.name in ["div", "article", "section", "li"] and any(
        card_selector.search(str(val)) for val in [tag.get("class", []), tag.get("id", "")] if val
    ))

    for card in cards:
        card_text = normalize_text(card.get_text(" "))
        if len(card_text) < 10 or len(card_text) > 2000:
            continue

        name_tag = card.find(["h1", "h2", "h3", "h4", "h5", "h6", "strong", "b"])
        if not name_tag:
            continue

        name = normalize_name(name_tag.get_text())
        if not name or not is_strict_person_name(name, company_name):
            continue

        role = None
        for role_tag in card.find_all(["p", "span", "div", "em"]):
            if role_tag == name_tag or role_tag in name_tag.descendants:
                continue
            t = normalize_text(role_tag.get_text())
            if 3 <= len(t) <= 120:
                r = best_role_from_phrase(t)
                if r:
                    role = r
                    break

        if not role:
            role = best_role_from_phrase(card_text)

        if role and is_strict_person_name(name, company_name):
            evidence = card_text if name.lower() in card_text.lower() else f"{name} - {role}"
            cand = {
                "name": name,
                "role": role,
                "source_url": clean_url(source_url),
                "source_type": "official_website",
                "evidence": evidence[:MAX_EVIDENCE_LENGTH]
            }
            mailto = card.find("a", href=re.compile(r"^mailto:", re.I))
            if mailto:
                m_email = mailto.get("href", "").replace("mailto:", "").split("?")[0].strip()
                if m_email and not is_generic_email(m_email) and not is_free_email(m_email):
                    cand["exact_email"] = normalize_email(m_email)
            if "exact_email" not in cand:
                emails = extract_emails(card_text)
                for em in emails:
                    if not is_generic_email(em) and not is_free_email(em):
                        cand["exact_email"] = em
                        break
            candidates.append(cand)

    return candidates

def extract_image_caption_candidates(soup, source_url, company_name):
    """
    Extracts leadership candidates from <img> alt/title attributes and <figure><figcaption>.
    """
    candidates = []
    if not soup:
        return candidates

    figures = soup.find_all("figure")
    for fig in figures:
        caption = fig.find("figcaption")
        if caption:
            cap_text = normalize_text(caption.get_text())
            if cap_text:
                extracted = extract_direct_relationships(cap_text, company_name)
                for c in extracted:
                    cand = {
                        "name": c["name"],
                        "role": c["role"],
                        "source_url": clean_url(source_url),
                        "source_type": "official_website",
                        "evidence": cap_text[:MAX_EVIDENCE_LENGTH]
                    }
                    candidates.append(cand)

    images = soup.find_all("img", alt=True)
    for img in images:
        alt_text = normalize_text(img.get("alt", ""))
        if len(alt_text) >= 10:
            extracted = extract_direct_relationships(alt_text, company_name)
            for c in extracted:
                cand = {
                    "name": c["name"],
                    "role": c["role"],
                    "source_url": clean_url(source_url),
                    "source_type": "official_website",
                    "evidence": alt_text[:MAX_EVIDENCE_LENGTH]
                }
                candidates.append(cand)

    return candidates

def extract_impressum_candidates(text, source_url, company_name, diagnostics=None):
    """Specialized extractor for German / European Impressum and Legal Notice disclosures."""
    candidates = []
    if not text:
        return candidates

    role_pattern = re.compile(
        r"\b(Geschäftsführer(?:in)?|Geschaeftsfuehrer(?:in)?|Geschäftsführung|Vorstand|Managing\s+Director|Inhaber(?:in)?|Director[s]?)\b[:\s]+([^\n\r]+)",
        re.I
    )
    academic_prefixes = r"\b(?:Dr\.-Ing\.|Dipl\.-Ing\.|Dr\.|Prof\.|Dipl\.-Kfm\.|Dipl\.-Wirt\.-Ing\.|Mr\.|Mrs\.|Ms\.)\s*"
    matches = role_pattern.finditer(text)
    for m in matches:
        raw_role = m.group(1).strip()
        names_blob = m.group(2).strip()
        role = "Managing Director" if re.search(r"Geschäftsführer|Geschaeftsfuehrer|Geschäftsführung|Managing\s+Director", raw_role, re.I) else (
            "Executive Board" if re.search(r"Vorstand", raw_role, re.I) else "Owner"
        )
        parts = re.split(r"\s+(?:und|and|&)\s+|,\s*", names_blob)
        for part in parts:
            clean = re.sub(academic_prefixes, "", part, flags=re.I).strip()
            clean = re.split(r"(?:\s+(?:Kleiner|Straße|Str\.|Weg|Platz|Deutschland|Germany|\d{4,5}|Telefon|Tel\.|E-Mail|Email))\b", clean)[0].strip()
            words = clean.split()
            if len(words) >= 2 and all(w[0].isupper() for w in words[:2]):
                cand_name = " ".join(words[:3])
                if is_strict_person_name(cand_name, company_name):
                    candidates.append({
                        "name": normalize_name(cand_name),
                        "role": role,
                        "evidence": f"Official legal notice ({source_url}): {m.group(0)[:250]}",
                        "source_type": "official_website",
                        "source_url": source_url
                    })
    return candidates

def extract_official_candidates(html_content, source_url, company_name, diagnostics=None):
    candidates = []
    if not html_content:
        return candidates

    # 0. Specialized Impressum / Legal Notice extraction
    if any(k in source_url.lower() or k in html_content[:4000].lower() for k in ["impressum", "imprint", "legal-notice", "gesetzliche anbieterkennung"]):
        page_clean = clean_html_text(html_content)
        candidates.extend(extract_impressum_candidates(page_clean, source_url, company_name, diagnostics))

    # 1. JSON-LD structured data extraction
    candidates.extend(extract_json_ld_candidates(html_content, source_url, company_name))

    # Parse soup for DOM extractors
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        # 2. HTML Table extraction
        candidates.extend(extract_table_candidates(soup, source_url, company_name))
        # 3. Modern Card / Grid extraction
        candidates.extend(extract_structured_card_candidates(soup, source_url, company_name))
        # 4. Image alt / caption extraction
        candidates.extend(extract_image_caption_candidates(soup, source_url, company_name))
    except Exception:
        pass

    # 5. Leadership blocks extraction
    blocks = extract_leadership_blocks(html_content)
    for block in blocks:
        candidates.extend(extract_candidates_from_text(block, source_url, "official_website", company_name))

    # 6. Full page clean text fallback
    page_text = clean_html_text(html_content)
    if page_text:
        candidates.extend(extract_candidates_from_text(page_text, source_url, "official_website", company_name))

    # Deduplicate extracted candidates
    unique = {}
    for c in candidates:
        key = (name_key(c["name"]), c.get("role", ""))
        if key not in unique or (c.get("exact_email") and not unique[key].get("exact_email")):
            unique[key] = c

    deduped_candidates = list(unique.values())
    if diagnostics is not None:
        diagnostics["candidates_extracted"] = diagnostics.get("candidates_extracted", 0) + len(deduped_candidates)

    return deduped_candidates

# ============================================================
# SEARCH HELPERS (WITH CIRCUIT BREAKER)
# ============================================================

LAST_DDG_SEARCH_FAILED = False
LAST_DDG_SEARCH_STATUS = "OK"

def ddg_search(query, max_results=MAX_DDG_RESULTS, retries=DDG_RETRIES):
    global LAST_DDG_SEARCH_FAILED, LAST_DDG_SEARCH_STATUS
    LAST_DDG_SEARCH_FAILED = False
    LAST_DDG_SEARCH_STATUS = "OK"

    # DuckDuckGo is the ONLY external search provider. No other search engines are used.
    if is_circuit_open():
        LAST_DDG_SEARCH_FAILED = True
        LAST_DDG_SEARCH_STATUS = "SEARCH_UNAVAILABLE"
        return None

    if HAS_DDGS:
        try:
            results = []
            with DDGS(timeout=2.5) as ddgs:
                for item in ddgs.text(query, max_results=max_results):
                    raw_href = item.get("href", "")
                    if raw_href:
                        item["href"] = decode_redirect_url(raw_href)
                    results.append(item)
            LAST_DDG_SEARCH_FAILED = False
            LAST_DDG_SEARCH_STATUS = "OK"
            return results
        except Exception as e:
            err_str = str(e).lower()
            if "timeout" in err_str:
                LAST_DDG_SEARCH_STATUS = "SEARCH_TIMEOUT"
            else:
                LAST_DDG_SEARCH_STATUS = "SEARCH_UNAVAILABLE"

    # Fallback to direct HTTP search on DuckDuckGo
    try:
        url = "https://html.duckduckgo.com/html/"
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
        with httpx.Client(verify=False, timeout=3.0) as client:
            res = client.get(url, params={"q": query}, headers=headers)
            if res.status_code == 200:
                html_text = res.text
                if is_challenge_or_blocked_page(html_text):
                    LAST_DDG_SEARCH_FAILED = True
                    LAST_DDG_SEARCH_STATUS = "SEARCH_UNAVAILABLE"
                    trip_circuit(60.0)
                    return None
                soup = BeautifulSoup(html_text, "html.parser")
                bodies = soup.find_all("div", class_=re.compile(r"result__body"))
                results = []
                for b in bodies[:max_results]:
                    a_title = b.find("a", class_=re.compile(r"result__a"))
                    a_snip = b.find("a", class_=re.compile(r"result__snippet"))
                    if a_title:
                        raw_href = a_title.get("href", "")
                        clean_link = decode_redirect_url(raw_href)
                        results.append({
                            "title": a_title.get_text().strip(),
                            "href": clean_link,
                            "body": a_snip.get_text().strip() if a_snip else ""
                        })
                LAST_DDG_SEARCH_FAILED = False
                LAST_DDG_SEARCH_STATUS = "OK"
                return results
            elif res.status_code in (202, 403, 429) or "anomaly" in res.text[:5000].lower():
                LAST_DDG_SEARCH_FAILED = True
                LAST_DDG_SEARCH_STATUS = "SEARCH_UNAVAILABLE"
                trip_circuit(60.0)
                return None
            else:
                LAST_DDG_SEARCH_FAILED = True
                LAST_DDG_SEARCH_STATUS = "SEARCH_UNAVAILABLE"
                return None
    except httpx.TimeoutException:
        LAST_DDG_SEARCH_FAILED = True
        LAST_DDG_SEARCH_STATUS = "SEARCH_TIMEOUT"
        return None
    except Exception:
        LAST_DDG_SEARCH_FAILED = True
        LAST_DDG_SEARCH_STATUS = "SEARCH_UNAVAILABLE"
        return None

    LAST_DDG_SEARCH_FAILED = True
    if LAST_DDG_SEARCH_STATUS == "OK":
        LAST_DDG_SEARCH_STATUS = "SEARCH_UNAVAILABLE"
    return None

def company_relevant(text, company_name, website, source_url=""):
    combined = normalize_text(f"{text} {source_url}").lower()
    target = normalize_text(company_name).lower()
    if target in combined:
        return True
    domain = canonical_domain(website)
    if domain and domain in combined:
        return True
    tokens = company_tokens(company_name)
    hits = sum(1 for token in tokens if re.search(r"\b" + re.escape(token) + r"\b", combined))
    return hits >= 1

def extract_ddg_candidates(results, company_name, website):
    candidates = []
    for result in results:
        title = normalize_text(result.get("title", ""))
        body = normalize_text(result.get("body", ""))
        href = clean_url(result.get("href", ""))
        combined = normalize_text(f"{title}. {body}")
        if not combined or not company_relevant(combined, company_name, website, href):
            continue
        extracted = extract_candidates_from_text(combined, href, "duckduckgo", company_name)
        for candidate in extracted:
            name = candidate["name"]
            evidence = candidate["evidence"]
            if looks_like_organization_name(name, company_name) or not is_strict_person_name(name, company_name):
                continue
            if role_is_historical(evidence, name, candidate["role"]):
                continue
            if role_attached_to_other_company(evidence, company_name):
                continue
            candidate["evidence"] = f"{title}. {body}"[:MAX_EVIDENCE_LENGTH]
            candidates.append(candidate)
    return candidates

def build_ddg_queries(company_name, website):
    domain = canonical_domain(website)
    brand = clean_brand_name(company_name) or company_name.strip()
    full_company = company_name.strip()

    queries = [
        f'"{brand}" CEO OR "Chief Executive Officer" OR Founder OR "Co-Founder"',
        f'"{brand}" "Managing Director" OR "Executive Chairman" OR President OR Director',
        f'"{brand}" CTO OR CFO OR COO OR "Chief Technology Officer" OR "Chief Financial Officer"',
        f'"{brand}" "leadership" OR "management team" OR "board of directors" OR "key executives"',
    ]
    if full_company.lower() != brand.lower():
        queries.append(f'"{full_company}" CEO OR "Managing Director" OR Founder OR Executive')
    if domain:
        queries.append(f'site:{domain} (leadership OR team OR management OR founders OR executives OR directors)')
    return queries

def search_duckduckgo_multi_round(company_name, website, existing_candidates, target):
    all_candidates = list(existing_candidates)
    if is_circuit_open():
        return all_candidates

    queries = build_ddg_queries(company_name, website)
    for query in queries:
        results = ddg_search(query, MAX_DDG_RESULTS)
        extracted = extract_ddg_candidates(results or [], company_name, website)
        all_candidates.extend(extracted)
        deduped = dedupe_candidates(all_candidates)
        if len(deduped) >= target * 2:
            break
    return all_candidates

# ============================================================
# EMAIL DISCOVERY & PATTERN INFERENCE PIPELINE
# ============================================================

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", re.I)
MAILTO_RE = re.compile(r"mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", re.I)
CF_EMAIL_RE = re.compile(r'data-cfemail=["\']([a-fA-F0-9]+)["\']', re.I)
CF_PATH_RE = re.compile(r"/cdn-cgi/l/email-protection#([a-fA-F0-9]+)", re.I)

GENERIC_EMAIL_PREFIXES = {
    "info", "contact", "hello", "hi", "sales", "support", "admin",
    "office", "enquiry", "enquiries", "inquiry", "inquiries", "career",
    "careers", "hr", "jobs", "marketing", "accounts", "finance",
    "billing", "help", "service", "services", "business", "media",
    "press", "investor", "investors", "investorrelations", "ir", "reception", "webmaster",
    "customerservice", "customercare", "feedback", "team", "connect", "general", "compliance",
    "frontdesk", "welcome", "generalinquiries", "corporate", "shares", "secretarial",
    "grievance", "legal", "privacy", "postmaster", "no-reply", "noreply", "desk",
    "regulatory", "esg", "procurement", "oneprocurement", "integration", "orders",
    "order", "operations", "helpdesk", "nodalofficer", "nodal", "inquiries"
}

FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com",
    "live.com", "icloud.com", "proton.me", "protonmail.com", "aol.com",
    "zoho.com", "mail.com", "yandex.com", "gmx.com", "fastmail.com",
    "rediffmail.com", "rediff.com", "inbox.com", "ymail.com"
}

VENDOR_DOMAINS = {
    "wix.com", "wixsite.com", "wordpress.com", "wordpress.org", "medium.com",
    "godaddy.com", "cloudflare.com", "github.com", "linkedin.com", "twitter.com",
    "x.com", "facebook.com", "instagram.com", "youtube.com", "google.com",
    "microsoft.com", "apple.com", "amazon.com", "shopify.com", "squarespace.com",
    "weebly.com", "hubspot.com", "salesforce.com", "zendesk.com", "mailchimp.com"
}

def decode_cloudflare_email(code):
    try:
        code = str(code).strip()
        if len(code) < 4:
            return ""
        r = int(code[:2], 16)
        return "".join([chr(int(code[i:i+2], 16) ^ r) for i in range(2, len(code), 2)]).strip()
    except Exception:
        return ""

def is_vendor_domain(dom):
    if not dom:
        return False
    dom_lower = dom.lower().strip()
    return any(dom_lower == vd or dom_lower.endswith("." + vd) for vd in VENDOR_DOMAINS)

def is_brand_related_domain(dom, company_name, primary_domain=""):
    if not dom or dom in FREE_EMAIL_DOMAINS or is_vendor_domain(dom):
        return False
    dom_lower = dom.lower().strip()
    if primary_domain:
        prim_lower = primary_domain.lower().strip()
        if dom_lower == prim_lower or dom_lower.endswith("." + prim_lower) or prim_lower.endswith("." + dom_lower):
            return True
    brand = clean_brand_name(company_name).lower() if company_name else ""
    if brand and len(brand) >= 3 and brand in dom_lower:
        return True
    comp_toks = company_tokens(company_name) if company_name else []
    for t in comp_toks:
        if len(t) >= 4 and t in dom_lower:
            return True
    return False

def is_valid_company_email_domain(email_or_domain, primary_domain="", company_name="", allowed_domains=None):
    if not email_or_domain:
        return False, "empty_domain"
    dom = email_domain(email_or_domain) if "@" in email_or_domain else email_or_domain.lower().strip()
    if not dom:
        return False, "empty_domain"
    if dom in FREE_EMAIL_DOMAINS:
        return False, "free_email_domain"
    if is_vendor_domain(dom):
        return False, "vendor_domain"

    allowed = set(allowed_domains or [])
    if primary_domain:
        allowed.add(canonical_domain(primary_domain))

    if dom in allowed:
        return True, "allowed_domain"
    if is_brand_related_domain(dom, company_name, primary_domain):
        return True, "brand_or_group_domain"

    return False, "domain_mismatch"

def extract_emails(text):
    if not text:
        return []
    text_str = str(text)
    out = []
    seen = set()

    # 1. Standard regex
    for email in EMAIL_RE.findall(text_str):
        email = email.strip(".,;:()[]{}<>\"'").lower()
        if email and email not in seen:
            seen.add(email)
            out.append(email)

    # 2. mailto: links
    for email in MAILTO_RE.findall(text_str):
        email = email.strip(".,;:()[]{}<>\"'").lower()
        if email and email not in seen:
            seen.add(email)
            out.append(email)

    # 3. HTML attributes: data-email, data-mail, data-contact, content, value
    for em in re.findall(r'(?:data-email|data-mail|data-contact|content|value)=["\']([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})["\']', text_str, re.I):
        em_clean = em.strip(".,;:()[]{}<>\"'").lower()
        if em_clean and em_clean not in seen:
            seen.add(em_clean)
            out.append(em_clean)

    # 4. Obfuscated emails (e.g. user [at] company [dot] com)
    for match in re.findall(r'\b([a-zA-Z0-9._%+-]+)\s*(?:\[at\]|\(at\)|@)\s*([a-zA-Z0-9.-]+)\s*(?:\[dot\]|\(dot\)|\.)\s*([a-zA-Z]{2,})\b', text_str, re.I):
        obf = f"{match[0]}@{match[1]}.{match[2]}".lower().strip(".,;:()[]{}<>\"'")
        if obf and "@" in obf and obf not in seen:
            seen.add(obf)
            out.append(obf)

    # 5. Cloudflare data-cfemail
    for code in CF_EMAIL_RE.findall(text_str):
        dec = decode_cloudflare_email(code)
        dec = dec.strip(".,;:()[]{}<>\"'").lower()
        if dec and "@" in dec and dec not in seen:
            seen.add(dec)
            out.append(dec)

    # 6. Cloudflare /cdn-cgi/l/email-protection#
    for code in CF_PATH_RE.findall(text_str):
        dec = decode_cloudflare_email(code)
        dec = dec.strip(".,;:()[]{}<>\"'").lower()
        if dec and "@" in dec and dec not in seen:
            seen.add(dec)
            out.append(dec)

    return out

def email_domain(email):
    try:
        return email.rsplit("@", 1)[1].lower().strip()
    except Exception:
        return ""

def email_local(email):
    try:
        return email.rsplit("@", 1)[0].lower().strip()
    except Exception:
        return ""

def is_generic_email(email):
    local = email_local(email)
    if not local:
        return True
    clean_local = re.sub(r"[^a-z0-9]", "", local)
    if local in GENERIC_EMAIL_PREFIXES or clean_local in GENERIC_EMAIL_PREFIXES:
        return True
    # Compound role/department tokens (e.g. support-india, company-hr, investor.relations)
    parts = [p for p in re.split(r"[-._+]", local) if p]
    for p in parts:
        if p in GENERIC_EMAIL_PREFIXES:
            return True
    generic_substrings = (
        "support-", "-support", "info-", "-info", "contact-", "-contact",
        "sales-", "-sales", "careers-", "-careers", "jobs-", "-jobs",
        "investor-", "-investor", "customer-care", "customercare", "helpdesk"
    )
    if any(s in local for s in generic_substrings):
        return True
    return False

def normalize_email(email):
    return email.strip(".,;:()[]{}<>\"'").lower() if email else ""

def is_free_email(email):
    return email_domain(email) in FREE_EMAIL_DOMAINS

def name_tokens(name):
    clean = normalize_name(name).lower()
    clean = re.sub(r"\b(mr|mrs|ms|dr|shri|smt|prof|er|ca|cs|esq|jr|sr|ii|iii|iv)\b", "", clean)
    return [token for token in re.findall(r"[a-z]+", clean) if token]

def email_matches_person(email, person_name):
    """D6: single canonical person->email matcher (delegates to email_validation_service).

    Preserves the historical boolean contract used throughout the engine,
    including rejection of generic / free-provider mailboxes.
    """
    email = normalize_email(email)
    if not email or is_generic_email(email) or is_free_email(email):
        return False
    result = canonical_person_email_match(person_name or "", email)
    return bool(result.get("matched"))

def person_name_in_text(text, person_name):
    text_norm = normalize_text(text).lower()
    tokens = name_tokens(person_name)
    if not tokens:
        return False
    if len(tokens) == 1:
        return bool(re.search(r"\b" + re.escape(tokens[0]) + r"\b", text_norm))
    first, last = tokens[0], tokens[-1]
    has_first = bool(re.search(r"\b" + re.escape(first) + r"\b", text_norm))
    has_last = bool(re.search(r"\b" + re.escape(last) + r"\b", text_norm))
    return has_first and has_last

def is_email_eligible_person(person, company_name=""):
    name = normalize_name(person.get("name", ""))
    role = normalize_text(person.get("role", ""))
    if not is_strict_person_name(name, company_name):
        return False
    lower = name.lower()
    blocked = {
        "audit committee", "nomination committee", "nominations committee",
        "esg committee", "risk committee", "csr committee", "committee",
        "board of directors", "management team", "leadership team", "executive team",
    }
    if any(x in lower for x in blocked):
        return False
    role_words = set(re.findall(r"[a-z]+", role.lower()))
    name_words = set(re.findall(r"[a-z]+", lower))
    if role_words and name_words == role_words:
        return False
    return True

def email_pattern_for_pair(name, email):
    email = normalize_email(email)
    if not email or is_generic_email(email) or is_free_email(email):
        return None
    raw_local = email_local(email)
    if not raw_local:
        return None

    tokens = name_tokens(name)
    if not tokens:
        return None
    first = tokens[0]
    last = tokens[-1] if len(tokens) > 1 else ""

    # Delimited patterns
    if "." in raw_local:
        parts = raw_local.split(".")
        if len(parts) == 2:
            p0, p1 = parts[0], parts[1]
            if last:
                if p0 == first and p1 == last:
                    return "first.last"
                if p0 == first[0] and p1 == last:
                    return "first_initial.last"
                if p0 == first and p1 == last[0]:
                    return "first.l"
                if p0 == last and p1 == first:
                    return "last.first"
                if p0 == last and p1 == first[0]:
                    return "last.f"
    elif "_" in raw_local:
        parts = raw_local.split("_")
        if len(parts) == 2:
            p0, p1 = parts[0], parts[1]
            if last:
                if p0 == first and p1 == last:
                    return "first_last"
                if p0 == first[0] and p1 == last:
                    return "f_last"
                if p0 == first and p1 == last[0]:
                    return "first_l"
                if p0 == last and p1 == first:
                    return "last_first"
    elif "-" in raw_local:
        parts = raw_local.split("-")
        if len(parts) == 2:
            p0, p1 = parts[0], parts[1]
            if last:
                if p0 == first and p1 == last:
                    return "first-last"
                if p0 == first[0] and p1 == last:
                    return "f-last"

    # Concatenated patterns (no delimiter)
    local = re.sub(r"[^a-z0-9]", "", raw_local)
    if last:
        if local == first + last:
            return "firstlast"
        if local == first[0] + last:
            return "first_initiallast"
        if local == first + last[0]:
            return "firstlast_initial"
        if local == last + first:
            return "lastfirst"
        if local == last + first[0]:
            return "lastf"
    if local == first:
        return "first"
    if last and local == last:
        return "last"

    return None

def render_email_pattern(pattern, name):
    tokens = name_tokens(name)
    if not tokens:
        return ""
    first = tokens[0]
    last = tokens[-1] if len(tokens) > 1 else ""

    values = {
        "first.last": f"{first}.{last}" if last else first,
        "first_last": f"{first}_{last}" if last else first,
        "first-last": f"{first}-{last}" if last else first,
        "firstlast": f"{first}{last}" if last else first,
        "first_initial.last": f"{first[0]}.{last}" if last else first,
        "f.last": f"{first[0]}.{last}" if last else first,
        "first_initiallast": f"{first[0]}{last}" if last else first,
        "flast": f"{first[0]}{last}" if last else first,
        "f_last": f"{first[0]}_{last}" if last else first,
        "f-last": f"{first[0]}-{last}" if last else first,
        "firstlast_initial": f"{first}{last[0]}" if last else first,
        "firstl": f"{first}{last[0]}" if last else first,
        "first.l": f"{first}.{last[0]}" if last else first,
        "first_l": f"{first}_{last[0]}" if last else first,
        "last.first": f"{last}.{first}" if last else first,
        "last_first": f"{last}_{first}" if last else first,
        "lastfirst": f"{last}{first}" if last else first,
        "lastf": f"{last}{first[0]}" if last else first,
        "last.f": f"{last}.{first[0]}" if last else first,
        "first": first,
        "last": last or first,
    }
    return values.get(pattern, "")

def generate_pattern_email(person_name, domain, pattern):
    local = render_email_pattern(pattern, person_name)
    if not local or not domain:
        return ""
    clean_domain = canonical_domain(domain) or domain.lower().strip()
    generated = f"{local}@{clean_domain}".lower()
    print(f"[PATTERN GENERATE] person={person_name} pattern={pattern} domain={clean_domain} generated={generated} status=PATTERN_GENERATED")
    return generated

GENERIC_CORP_WORDS = {
    "living", "technical", "chemical", "chemicals", "textiles", "textile",
    "services", "service", "global", "industries", "industry", "holdings",
    "group", "solutions", "international", "technologies", "technology",
    "finance", "capital", "ventures", "enterprises", "corporation", "corp",
    "limited", "ltd", "private", "pvt", "fibres", "fibre", "products", "product"
}

def discover_company_email_domains(company_name, website, direct_emails=None, crawled_pages=None):
    primary = canonical_domain(website)
    accepted = set()
    if primary:
        accepted.add(primary)

    # Check brand name domain (e.g. brand.com when website is brandliving.com)
    brand = clean_brand_name(company_name).lower() if company_name else ""
    tld = primary.rsplit(".", 1)[-1] if (primary and "." in primary) else "com"
    if brand and len(brand) >= 3 and brand not in GENERIC_CORP_WORDS:
        if primary and brand in primary:
            accepted.add(f"{brand}.com")
            accepted.add(f"{brand}.{tld}")
        comp_toks = company_tokens(company_name) if company_name else []
        for t in comp_toks:
            if len(t) >= 4 and primary and t in primary and t not in GENERIC_CORP_WORDS:
                accepted.add(f"{t}.com")
                accepted.add(f"{t}.{tld}")

    # From direct_emails found on official site
    if direct_emails:
        for em in direct_emails:
            d = email_domain(em)
            if d and d not in FREE_EMAIL_DOMAINS and not is_vendor_domain(d):
                if is_brand_related_domain(d, company_name, primary) or not primary:
                    accepted.add(d)

    # From crawled_pages
    if crawled_pages:
        for p in crawled_pages:
            text = (p.get("html") or "") + " " + (p.get("content") or "")
            for em in extract_emails(text):
                d = email_domain(em)
                if d and d not in FREE_EMAIL_DOMAINS and not is_vendor_domain(d):
                    if is_brand_related_domain(d, company_name, primary):
                        accepted.add(d)

    return sorted(d for d in accepted if d)

def discover_exact_email_for_person(person, company_name, website, allowed_domains=None, direct_emails=None):
    name = person.get("name", "")
    primary = canonical_domain(website)
    allowed = set(allowed_domains or ([primary] if primary else []))
    
    # Check candidate evidence
    for email in extract_emails(person.get("evidence", "")):
        em_dom = email_domain(email)
        is_ok, reason = is_valid_company_email_domain(email, primary, company_name, allowed)
        print(f"[DOMAIN CHECK] email={email} domain={em_dom} primary={primary} accepted={is_ok} reason={reason}")
        if is_ok and not is_generic_email(email) and not is_free_email(email) and email_matches_person(email, name):
            return {
                "email": normalize_email(email),
                "status": "EXACT_FOUND",
                "source_url": person.get("source_url", ""),
                "evidence": person.get("evidence", "")[:MAX_EVIDENCE_LENGTH],
                "verification": "PUBLIC_EVIDENCE",
            }

    # Check direct crawled emails
    if direct_emails:
        for email in direct_emails:
            em_dom = email_domain(email)
            is_ok, reason = is_valid_company_email_domain(email, primary, company_name, allowed)
            print(f"[DOMAIN CHECK] email={email} domain={em_dom} primary={primary} accepted={is_ok} reason={reason}")
            if is_ok and not is_generic_email(email) and not is_free_email(email) and email_matches_person(email, name):
                return {
                    "email": normalize_email(email),
                    "status": "EXACT_FOUND",
                    "source_url": website,
                    "evidence": f"Found on official website: {email}",
                    "verification": "WEBSITE_DIRECT",
                }

    # Web search if circuit is open or closed
    if not is_circuit_open():
        query = f'"{name}" "@{primary}"' if primary else f'"{name}" "{company_name}" email'
        results = ddg_search(query, 3)
        for item in results:
            text = f"{item.get('title', '')} {item.get('body', '')}"
            for email in extract_emails(text):
                em_dom = email_domain(email)
                is_ok, reason = is_valid_company_email_domain(email, primary, company_name, allowed)
                print(f"[DOMAIN CHECK] email={email} domain={em_dom} primary={primary} accepted={is_ok} reason={reason}")
                if is_ok and not is_generic_email(email) and not is_free_email(email) and email_matches_person(email, name):
                    return {
                        "email": normalize_email(email),
                        "status": "EXACT_FOUND",
                        "source_url": clean_url(item.get("href", "")),
                        "evidence": text[:MAX_EVIDENCE_LENGTH],
                        "verification": "PUBLIC_EVIDENCE",
                    }

    return {
        "email": "",
        "status": "NOT_FOUND",
        "source_url": "",
        "evidence": "",
        "verification": "NONE",
    }

def search_ddg_exact_person_email(person_name, company_name, domain, allowed_domains=None):
    clean_domain = canonical_domain(domain) if domain else ""
    domains_to_check = list(allowed_domains) if allowed_domains else ([clean_domain] if clean_domain else [])
    name_toks = name_tokens(person_name)
    if len(name_toks) < 2:
        return {
            "email": None,
            "status": "NOT_FOUND",
            "search_status": "SKIPPED",
            "search_attempts": 0,
            "sources_checked": [],
        }

    if is_circuit_open():
        print(f"[SEARCH] Circuit breaker open for {person_name} ({company_name}) -> SEARCH_UNAVAILABLE")
        return {
            "email": None,
            "status": "SEARCH_UNAVAILABLE",
            "search_status": "SEARCH_UNAVAILABLE",
            "search_attempts": 0,
            "sources_checked": [],
            "search_error": "Search circuit breaker is active",
        }

    queries = []
    for d in domains_to_check[:2]:
        queries.append(f'"{person_name}" "@{d}"')
    brand_name = clean_brand_name(company_name) or company_name
    queries.append(f'"{person_name}" "{brand_name}" email')
    queries = queries[:3]

    print(f"[EMAIL] Target: {person_name}")
    print(f"[EMAIL] Public search started for {person_name} ({company_name})")

    attempts = 0
    sources_checked = []
    any_timeout = False
    any_success = False

    for i, query in enumerate(queries, 1):
        attempts += 1
        sources_checked.append(query)
        try:
            results = ddg_search(query, max_results=3)
            if results is None:
                any_timeout = True
                print(f"[SEARCH] Query {i}: TIMEOUT or unavailable ({query})")
                continue
            any_success = True
            print(f"[SEARCH] Query {i}: {len(results)} results")
        except Exception as e:
            any_timeout = True
            print(f"[SEARCH] Query {i} exception: {e}")
            continue

        for item in results:
            title = item.get("title", "")
            body = item.get("body", "")
            text = f"{title}. {body}"
            href = clean_url(item.get("href", ""))

            # Person name tokens must be in text
            text_lower = text.lower()
            if not (name_toks[0] in text_lower and name_toks[-1] in text_lower):
                continue

            extracted = extract_emails(text)
            for em in extracted:
                if is_generic_email(em) or is_free_email(em):
                    continue
                em_dom = email_domain(em)
                is_ok, reason = is_valid_company_email_domain(em, clean_domain, company_name, domains_to_check)
                print(f"[DOMAIN CHECK] email={em} domain={em_dom} primary={clean_domain} accepted={is_ok} reason={reason}")
                print(f"[DOMAIN MATCH] website_domain={clean_domain} email_domain={em_dom} accepted={is_ok} reason={reason}")
                if not is_ok:
                    continue
                if email_matches_person(em, person_name):
                    norm_em = normalize_email(em)
                    print(f"[EMAIL] Exact corporate email discovered: {norm_em}")
                    print(f"[EMAIL] Status: EXACT_FOUND")
                    return {
                        "email": norm_em,
                        "status": "EXACT_FOUND",
                        "search_status": "COMPLETED",
                        "source_url": href or (f"https://{em_dom}" if em_dom else ""),
                        "source_type": "PUBLIC_SEARCH",
                        "evidence": text[:MAX_EVIDENCE_LENGTH],
                        "verification": "PUBLIC_EVIDENCE",
                        "domain": em_dom or clean_domain,
                        "search_attempts": attempts,
                        "sources_checked": sources_checked,
                    }

            # TARGET PAGE CRAWLING: if email is not found directly in snippet text, crawl the target webpage!
            if href and href.startswith("http") and not href.lower().endswith((".pdf", ".docx", ".xlsx", ".zip", ".png", ".jpg", ".jpeg")):
                try:
                    from app.services.email_extraction_service import extract_emails_from_html
                    with httpx.Client(verify=False, timeout=4.0, follow_redirects=True, headers=HEADERS) as client:
                        resp = client.get(href)
                        if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", "").lower():
                            extracted_items = extract_emails_from_html(resp.text, base_url=href)
                            for rec in extracted_items:
                                em = rec.get("email", "")
                                if is_generic_email(em) or is_free_email(em):
                                    continue
                                em_dom = email_domain(em)
                                is_ok, reason = is_valid_company_email_domain(em, clean_domain, company_name, domains_to_check)
                                if not is_ok:
                                    continue
                                if email_matches_person(em, person_name):
                                    norm_em = normalize_email(em)
                                    print(f"[EMAIL] Discovered on target webpage ({href}): {norm_em}")
                                    return {
                                        "email": norm_em,
                                        "status": "EXACT_FOUND",
                                        "search_status": "COMPLETED",
                                        "source_url": href,
                                        "source_type": "PUBLIC_SEARCH",
                                        "evidence": f"Found on public page ({href}): {norm_em} ({rec.get('context', '')[:120]})",
                                        "verification": "PUBLIC_EVIDENCE",
                                        "domain": em_dom or clean_domain,
                                        "search_attempts": attempts,
                                        "sources_checked": sources_checked,
                                    }
                except Exception as crawl_err:
                    print(f"[TARGET CRAWL] Failed crawling {href}: {crawl_err}")

    if any_timeout and not any_success:
        failure_status = "SEARCH_TIMEOUT"
        print(f"[SEARCH] DDG timeout/failure for all attempted queries")
        print(f"[SEARCH] status={failure_status}")
        print(f"[EMAIL] NOT_FOUND not assigned because discovery was incomplete")
        return {
            "email": None,
            "status": failure_status,
            "search_status": failure_status,
            "search_attempts": attempts,
            "sources_checked": sources_checked,
            "search_error": "All public search queries timed out",
        }

    return {
        "email": None,
        "status": "NOT_FOUND",
        "search_status": "COMPLETED",
        "search_attempts": attempts,
        "sources_checked": sources_checked,
    }

def canonical_pattern_name(pattern):
    if not pattern:
        return None
    aliases = {
        "f.last": "first_initial.last",
        "flast": "first_initiallast",
        "f_last": "first_initial_last",
        "f-last": "first_initial-last",
        "firstl": "firstlast_initial",
        "first.l": "first.last_initial",
        "first_l": "first_last_initial",
        "last.f": "last.first_initial",
        "lastf": "lastfirst_initial",
    }
    return aliases.get(pattern, pattern)

def detect_generic_email_pattern(exact_pairs, domain="", company_name="", allowed_domains=None):
    clean_domain = canonical_domain(domain) if domain else ""
    domains_to_check = set(allowed_domains or [])
    if clean_domain:
        domains_to_check.add(clean_domain)

    valid_pairs = []
    seen_names = set()
    total_collected = len(exact_pairs) if exact_pairs else 0
    generic_rejected = 0
    personal_rejected = 0

    for item in exact_pairs:
        if isinstance(item, dict):
            name = item.get("name") or item.get("person") or item.get("personName", "")
            email = item.get("email", "")
            source_url = item.get("source_url") or item.get("email_source_url", "")
            evidence = item.get("evidence") or item.get("email_evidence", "")
        elif isinstance(item, (list, tuple)):
            name = item[0]
            email = item[1]
            source_url = item[2] if len(item) > 2 else ""
            evidence = item[3] if len(item) > 3 else ""
        else:
            continue

        email = normalize_email(email)
        name = normalize_name(name)
        if not name or not email:
            continue
        if is_generic_email(email):
            generic_rejected += 1
            continue
        if is_free_email(email):
            personal_rejected += 1
            continue

        em_dom = email_domain(email)
        is_ok, reason = is_valid_company_email_domain(email, clean_domain, company_name, domains_to_check)
        print(f"[DOMAIN CHECK] email={email} domain={em_dom} primary={clean_domain} accepted={is_ok} reason={reason}")
        print(f"[DOMAIN MATCH] website_domain={clean_domain} email_domain={em_dom} accepted={is_ok} reason={reason}")
        if not is_ok:
            continue

        if not clean_domain:
            clean_domain = em_dom

        n_key = name_key(name)
        if n_key in seen_names:
            continue
        seen_names.add(n_key)

        raw_pattern = email_pattern_for_pair(name, email)
        if not raw_pattern:
            continue
        pattern = canonical_pattern_name(raw_pattern)

        valid_pairs.append({
            "person": name,
            "email": email,
            "source_url": source_url,
            "evidence": evidence,
            "pattern": pattern
        })

    pair_domains = [email_domain(p["email"]) for p in valid_pairs if p.get("email")]
    if pair_domains:
        clean_domain = max(set(pair_domains), key=pair_domains.count)

    print(f"[PATTERN] Employee evidence collected: {total_collected}")
    print(f"[PATTERN] Generic emails rejected: {generic_rejected}")
    print(f"[PATTERN] Personal emails rejected: {personal_rejected}")
    print(f"[PATTERN] Usable person-email pairs: {len(valid_pairs)}")

    if not valid_pairs:
        print("[PATTERN] Pattern confidence: NONE")
        return {
            "pattern": None,
            "pattern_domain": clean_domain,
            "pattern_confidence": "NONE",
            "pattern_evidence": [],
            "patterns_observed": [],
            "patternsObserved": [],
            "can_generate": False
        }

    # Group pairs by pattern
    patterns_map = {}
    for p in valid_pairs:
        pat = p["pattern"]
        patterns_map.setdefault(pat, []).append(p)

    patterns_observed = [
        {"pattern": pat, "supportCount": len(evidence_list)}
        for pat, evidence_list in sorted(patterns_map.items(), key=lambda x: -len(x[1]))
    ]

    for po in patterns_observed:
        print(f"[PATTERN] {po['pattern']} support: {po['supportCount']}")

    # Identify all patterns that have at least 2 distinct employees supporting them
    supported_patterns = [pat for pat, ev in patterns_map.items() if len(ev) >= 2]

    # Multiple distinct patterns with >= 2 employees -> CONFLICTING
    if len(supported_patterns) >= 2:
        print("[PATTERN] Pattern confidence: CONFLICTING (multiple supported patterns)")
        all_evidence = [p for sublist in patterns_map.values() for p in sublist]
        return {
            "pattern": None,
            "pattern_domain": clean_domain,
            "pattern_confidence": "CONFLICTING",
            "pattern_evidence": all_evidence,
            "patterns_observed": patterns_observed,
            "patternsObserved": patterns_observed,
            "can_generate": False
        }

    # Exactly 1 pattern has >= 2 employees -> SUPPORTED
    if len(supported_patterns) == 1:
        chosen_pattern = supported_patterns[0]
        evidence_list = patterns_map[chosen_pattern]
        print(f"[PATTERN] Pattern confidence: SUPPORTED ({chosen_pattern} with {len(evidence_list)} supports)")
        return {
            "pattern": chosen_pattern,
            "pattern_domain": clean_domain,
            "pattern_confidence": "SUPPORTED",
            "pattern_evidence": evidence_list,
            "patterns_observed": patterns_observed,
            "patternsObserved": patterns_observed,
            "can_generate": True,
            "generation_allowed": True
        }

    # No pattern has >= 2 employees:
    if len(valid_pairs) == 1:
        chosen_pattern = list(patterns_map.keys())[0]
        evidence_list = patterns_map[chosen_pattern]
        print("[PATTERN] Pattern confidence: INSUFFICIENT (1 person only, generation allowed)")
        return {
            "pattern": chosen_pattern,
            "pattern_domain": clean_domain,
            "pattern_confidence": "INSUFFICIENT",
            "pattern_evidence": evidence_list,
            "patterns_observed": patterns_observed,
            "patternsObserved": patterns_observed,
            "can_generate": True,
            "generation_allowed": True
        }
    else:
        # Multiple people, but each has < 2 supports across different patterns -> CONFLICTING
        print("[PATTERN] Pattern confidence: CONFLICTING (no pattern reached 2+ supports)")
        all_evidence = [p for sublist in patterns_map.values() for p in sublist]
        return {
            "pattern": None,
            "pattern_domain": clean_domain,
            "pattern_confidence": "CONFLICTING",
            "pattern_evidence": all_evidence,
            "patterns_observed": patterns_observed,
            "patternsObserved": patterns_observed,
            "can_generate": False,
            "generation_allowed": False
        }

def infer_pattern_from_known_people(known_pairs, min_people=2):
    pattern_hits = {}
    for item in known_pairs:
        name = item[0]
        email = item[1]
        domain = item[2] if len(item) > 2 else email_domain(email)
        pattern = email_pattern_for_pair(name, email)
        if not pattern or pattern in ("fl", "first", "last"):
            continue
        key = (domain, pattern)
        pattern_hits.setdefault(key, set()).add(name_key(name))

    valid = [
        (domain, pattern, len(names))
        for (domain, pattern), names in pattern_hits.items()
        if len(names) >= min_people
    ]
    if not valid:
        return None, None
    valid.sort(key=lambda x: (-x[2], x[0], x[1]))
    # Map internal pattern names to clean aliases if necessary
    p_name = valid[0][1]
    if p_name == "first_initiallast":
        p_name = "flast"
    elif p_name == "first_initial.last":
        p_name = "f.last"
    return p_name, valid[0][0]

async def discover_phase2_decision_maker_emails(
    candidates,
    company_name,
    website,
    crawled_pages=None,
    direct_emails=None,
    mx_status="UNKNOWN"
):
    """
    Phase 2: Generic Email Discovery & Pattern Detection.
    Takes Phase 1 decision makers and discovers exact emails or derives pattern emails.
    """
    primary_domain = canonical_domain(website)
    allowed_domains = discover_company_email_domains(company_name, website, direct_emails, crawled_pages)
    if not primary_domain and allowed_domains:
        primary_domain = allowed_domains[0]

    enriched = []

    # STEP 1 & STEP 2: Find exact emails for each candidate
    for cand in candidates:
        item = dict(cand)
        exact_em = item.get("exact_email")
        source_url = item.get("source_url") or website
        source_type = item.get("source_type") or "official_website"
        evidence_text = item.get("evidence", "")

        cand_search_status = "COMPLETED"
        search_attempts = 0
        sources_checked = ["official_website"]
        search_err = None

        # Step 1: Check official website candidate evidence
        if not exact_em:
            for em in extract_emails(evidence_text):
                is_ok, reason = is_valid_company_email_domain(em, primary_domain, company_name, allowed_domains)
                print(f"[DOMAIN CHECK] email={em} domain={email_domain(em)} primary={primary_domain} accepted={is_ok} reason={reason}")
                if is_ok and not is_generic_email(em) and not is_free_email(em) and email_matches_person(em, item["name"]):
                    exact_em = em
                    evidence_text = f"Found in official leadership evidence: {em}"
                    source_type = "official_website"
                    print(f"[EMAIL CRAWL] person={item['name']} nearby_emails=[{em}] associated={em}")
                    break

        # Container / Card proximity on crawled pages
        if not exact_em and crawled_pages:
            cand_toks = name_tokens(item["name"])
            for p in crawled_pages:
                p_html = p.get("html") or p.get("content") or ""
                p_url = p.get("url") or website
                if not p_html:
                    continue
                if len(cand_toks) >= 2 and cand_toks[0] in p_html.lower() and cand_toks[-1] in p_html.lower():
                    try:
                        soup = BeautifulSoup(p_html, "html.parser")
                        found_card_email = False
                        for container in soup.find_all(["div", "section", "article", "tr", "li", "td"]):
                            c_text = container.get_text()
                            if cand_toks[0] in c_text.lower() and cand_toks[-1] in c_text.lower() and len(c_text) < 1200:
                                c_emails = extract_emails(str(container))
                                if c_emails:
                                    print(f"[EMAIL CRAWL] person={item['name']} nearby_emails={c_emails} associated=...")
                                for em in c_emails:
                                    is_ok, reason = is_valid_company_email_domain(em, primary_domain, company_name, allowed_domains)
                                    if is_ok and not is_generic_email(em) and not is_free_email(em) and email_matches_person(em, item["name"]):
                                        exact_em = em
                                        source_url = p_url
                                        source_type = "official_website"
                                        evidence_text = f"Associated from container on {p_url}: {em}"
                                        print(f"[EMAIL CRAWL] person={item['name']} nearby_emails={c_emails} associated={em}")
                                        found_card_email = True
                                        break
                            if found_card_email:
                                break
                    except Exception:
                        pass
                if exact_em:
                    break

        # Direct crawled emails
        if not exact_em and direct_emails:
            for em in direct_emails:
                is_ok, reason = is_valid_company_email_domain(em, primary_domain, company_name, allowed_domains)
                if is_ok and not is_generic_email(em) and not is_free_email(em) and email_matches_person(em, item["name"]):
                    exact_em = em
                    source_url = website
                    source_type = "official_website"
                    evidence_text = f"Found on official website: {em}"
                    print(f"[EMAIL CRAWL] person={item['name']} nearby_emails=[{em}] associated={em}")
                    break

        # Text proximity on crawled pages fallback
        if not exact_em and crawled_pages:
            cand_toks = name_tokens(item["name"])
            for p in crawled_pages:
                p_text = p.get("html") or p.get("content") or ""
                p_url = p.get("url") or website
                if len(cand_toks) >= 2 and cand_toks[0] in p_text.lower() and cand_toks[-1] in p_text.lower():
                    for em in extract_emails(p_text):
                        is_ok, reason = is_valid_company_email_domain(em, primary_domain, company_name, allowed_domains)
                        if is_ok and not is_generic_email(em) and not is_free_email(em) and email_matches_person(em, item["name"]):
                            exact_em = em
                            source_url = p_url
                            source_type = "official_website"
                            evidence_text = f"Found on crawled page ({p_url}): {em}"
                            print(f"[EMAIL CRAWL] person={item['name']} nearby_emails=[{em}] associated={em}")
                            break
                if exact_em:
                    break

        # Step 2: Public DDG Search if not found on official site
        if not exact_em:
            sources_checked.append("public_search")
            ddg_res = search_ddg_exact_person_email(item["name"], company_name, primary_domain, allowed_domains)
            if ddg_res:
                search_attempts = ddg_res.get("search_attempts", 1)
                sources_checked.extend(ddg_res.get("sources_checked", []))
                cand_search_status = ddg_res.get("search_status", "COMPLETED")
                search_err = ddg_res.get("search_error")
                if ddg_res.get("email"):
                    exact_em = ddg_res["email"]
                    source_url = ddg_res.get("source_url", "")
                    source_type = "public_search"
                    evidence_text = ddg_res.get("evidence", "")

        item["search_status"] = cand_search_status
        item["search_attempts"] = search_attempts
        item["sources_checked"] = sources_checked
        item["search_error"] = search_err

        if exact_em:
            item["email"] = normalize_email(exact_em)
            item["exact_email"] = item["email"]
            item["email_status"] = "EXACT_FOUND"
            item["emailStatus"] = "EXACT_FOUND"
            item["email_source_url"] = source_url
            item["email_source_type"] = "OFFICIAL_WEBSITE" if source_type == "official_website" else "PUBLIC_SEARCH"
            item["email_evidence"] = evidence_text
            item["email_verification"] = "PUBLIC_EVIDENCE"
            item["emailVerificationMethod"] = "PUBLIC_EVIDENCE"
            item["email_domain"] = email_domain(exact_em) or primary_domain
            item["mailbox_status"] = "UNVERIFIED"
            item["mx_status"] = mx_status
            item["pattern_used"] = "none"
            item["generated_pattern"] = "none"
            item["generatedPattern"] = "none"
        else:
            item["email"] = None
            item["exact_email"] = None
            fail_st = cand_search_status if cand_search_status in ("SEARCH_TIMEOUT", "SEARCH_UNAVAILABLE") else "NOT_FOUND"
            item["email_status"] = fail_st
            item["emailStatus"] = "NOT_FOUND"
            item["email_source_url"] = ""
            item["email_source_type"] = "NONE"
            item["email_evidence"] = ""
            item["email_verification"] = "NONE"
            item["emailVerificationMethod"] = "NONE"
            item["email_domain"] = primary_domain
            item["mailbox_status"] = "UNVERIFIED"
            item["mx_status"] = mx_status
            item["pattern_used"] = "none"
            item["generated_pattern"] = "none"
            item["generatedPattern"] = "none"

        enriched.append(item)

    # STEP 3: Collect valid exact person-email pairs comprehensively across the company
    exact_pairs = []
    seen_pair_keys = set()
    all_extracted_emails = set()
    generic_rejected_emails = set()
    personal_rejected_emails = set()
    associations_attempted = 0

    def add_pair(name_str, em_str, src_str, ev_str):
        n_clean = normalize_name(name_str)
        e_clean = normalize_email(em_str)
        if not n_clean or not e_clean:
            return
        all_extracted_emails.add(e_clean)
        if is_generic_email(e_clean):
            generic_rejected_emails.add(e_clean)
            return
        if is_free_email(e_clean):
            personal_rejected_emails.add(e_clean)
            return
        is_ok, reason = is_valid_company_email_domain(e_clean, primary_domain, company_name, allowed_domains)
        print(f"[DOMAIN CHECK] email={e_clean} domain={email_domain(e_clean)} primary={primary_domain} accepted={is_ok} reason={reason}")
        if not is_ok:
            return
        pair_key = (name_key(n_clean), e_clean)
        if pair_key not in seen_pair_keys:
            seen_pair_keys.add(pair_key)
            exact_pairs.append({
                "name": n_clean,
                "email": e_clean,
                "source_url": src_str,
                "evidence": ev_str
            })

    # 3a. From enriched candidates (EXACT_FOUND)
    for item in enriched:
        cand_em = item.get("email")
        if cand_em:
            all_extracted_emails.add(normalize_email(cand_em))
        if item.get("email_status") == "EXACT_FOUND" and cand_em:
            associations_attempted += 1
            add_pair(item["name"], cand_em, item.get("email_source_url", ""), item.get("email_evidence", ""))

    # 3b. From direct_emails found on official site
    if direct_emails:
        for em in direct_emails:
            e_clean = normalize_email(em)
            all_extracted_emails.add(e_clean)
            if is_generic_email(e_clean):
                generic_rejected_emails.add(e_clean)
                continue
            if is_free_email(e_clean):
                personal_rejected_emails.add(e_clean)
                continue
            is_ok, _ = is_valid_company_email_domain(e_clean, primary_domain, company_name, allowed_domains)
            if is_ok:
                for cand in candidates:
                    associations_attempted += 1
                    if email_matches_person(e_clean, cand.get("name", "")):
                        add_pair(cand["name"], e_clean, website, f"Found on official website: {e_clean}")
                        break

    # 3c. From crawled pages (inspect ALL pages, looking for ALL employees across the company)
    if crawled_pages:
        for p in crawled_pages:
            p_html = p.get("html") or p.get("content") or ""
            p_url = p.get("url") or website
            if not p_html:
                continue

            # Check JSON-LD structured data on page for employee/person emails
            if "<script" in p_html.lower() and "application/ld+json" in p_html.lower():
                try:
                    j_soup = BeautifulSoup(p_html, "html.parser")
                    for s in j_soup.find_all("script", type=re.compile(r"application/ld\+json", re.I)):
                        s_text = s.string or s.get_text()
                        if s_text and "@" in s_text:
                            s_data = json.loads(s_text)
                            s_items = s_data if isinstance(s_data, list) else ([s_data] if isinstance(s_data, dict) else [])
                            flat = []
                            for it in s_items:
                                if isinstance(it, dict):
                                    if "@graph" in it and isinstance(it["@graph"], list):
                                        flat.extend(it["@graph"])
                                    else:
                                        flat.append(it)
                            for it in flat:
                                if isinstance(it, dict):
                                    it_type = str(it.get("@type", "")).lower()
                                    if "person" in it_type or any(r in it_type for r in ["employee", "founder", "member"]):
                                        p_name = it.get("name")
                                        p_em = it.get("email")
                                        if p_name and p_em and isinstance(p_em, str):
                                            associations_attempted += 1
                                            add_pair(str(p_name), str(p_em), p_url, f"Structured data on {p_url}: {p_name} — {p_em}")
                except Exception:
                    pass

            page_emails = extract_emails(p_html)
            for em in page_emails:
                e_clean = normalize_email(em)
                all_extracted_emails.add(e_clean)
                if is_generic_email(e_clean):
                    generic_rejected_emails.add(e_clean)
                    continue
                if is_free_email(e_clean):
                    personal_rejected_emails.add(e_clean)
                    continue
                is_ok, _ = is_valid_company_email_domain(e_clean, primary_domain, company_name, allowed_domains)
                if not is_ok:
                    continue

                # 1. Match against known candidates
                matched = False
                for cand in candidates:
                    associations_attempted += 1
                    if email_matches_person(e_clean, cand.get("name", "")):
                        add_pair(cand["name"], e_clean, p_url, f"Found on {p_url}: {cand['name']} — {e_clean}")
                        matched = True
                        break
                if matched:
                    continue

                # 2. BeautifulSoup DOM container search (cards, tables, articles, list items)
                if "<" in p_html and ">" in p_html:
                    try:
                        soup = BeautifulSoup(p_html, "html.parser")
                        for container in soup.find_all(["tr", "li", "article", "section", "div", "td", "dl"]):
                            c_str = str(container)
                            if e_clean in c_str or (email_local(e_clean) in c_str and email_domain(e_clean) in c_str):
                                c_text = container.get_text()
                                if len(c_text) < 1500:
                                    # First check header and title tags in container
                                    for subtag in container.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "p", "span", "a", "dt", "dd"]):
                                        sub_text = subtag.get_text().strip()
                                        if is_strict_person_name(sub_text, company_name):
                                            associations_attempted += 1
                                            if email_matches_person(e_clean, sub_text):
                                                add_pair(sub_text, e_clean, p_url, f"Associated from container on {p_url}: {sub_text} — {e_clean}")
                                                matched = True
                                                break
                                    if not matched:
                                        for line in c_text.splitlines():
                                            for tok in re.findall(r"\b[A-Z][a-z]+(?:[^\S\r\n]+[A-Z][a-z]+)+\b", line):
                                                if is_strict_person_name(tok, company_name):
                                                    associations_attempted += 1
                                                    if email_matches_person(e_clean, tok):
                                                        add_pair(tok, e_clean, p_url, f"Associated from container on {p_url}: {tok} — {e_clean}")
                                                        matched = True
                                                        break
                                            if matched:
                                                break
                            if matched:
                                break
                    except Exception:
                        pass
                if matched:
                    continue

                # 3. Text proximity window in cleaned text
                clean_text = re.sub(r"<[^>]+>", " ", p_html)
                em_idx = clean_text.lower().find(e_clean.lower())
                if em_idx != -1:
                    window = clean_text[max(0, em_idx - 300):min(len(clean_text), em_idx + 300)]
                    for line in window.splitlines():
                        for tok in re.findall(r"\b[A-Z][a-z]+(?:[^\S\r\n]+[A-Z][a-z]+)+\b", line):
                            if is_strict_person_name(tok, company_name):
                                associations_attempted += 1
                                if email_matches_person(e_clean, tok):
                                    add_pair(tok, e_clean, p_url, f"Found on {p_url}: {tok} — {e_clean}")
                                    matched = True
                                    break
                        if matched:
                            break

    # 3d. Public search if fewer than 2 pairs and some candidates still need an email
    needs_email = any(c.get("email_status") != "EXACT_FOUND" for c in enriched)
    queries_tried = []
    if needs_email and len(exact_pairs) < 2 and not is_circuit_open():
        target_domains = allowed_domains if allowed_domains else ([primary_domain] if primary_domain else [])
        brand_name = clean_brand_name(company_name) or company_name
        print(f"[SEARCH] Pattern evidence < 2 ({len(exact_pairs)} pairs). Searching domains {target_domains} for corporate employee emails...")
        domain_queries = []

        # Candidate-specific queries
        for cand in enriched:
            if cand.get("email_status") != "EXACT_FOUND":
                domain_queries.append(f'"{company_name}" "{cand["name"]}" email')
                domain_queries.append(f'"{company_name}" "{cand["name"]}" contact')
        # Domain-specific employee search queries
        for d in target_domains:
            domain_queries.extend([
                f'"{company_name}" "@{d}"',
                f'"{brand_name}" "@{d}"',
                f'site:{d} "@{d}"',
                f'site:{d} leadership OR management email',
                f'"{company_name}" "@{d}" leadership OR team',
                f'"{company_name}" "@{d}" contact OR email',
            ])
        domain_queries.append(f'"{company_name}" email format OR pattern')

        # Deduplicate queries while preserving order
        seen_q = set()
        deduped_queries = []
        for q in domain_queries:
            if q not in seen_q:
                seen_q.add(q)
                deduped_queries.append(q)

        for dq in deduped_queries:
            if len(exact_pairs) >= 2:
                break
            queries_tried.append(dq)
            try:
                dq_results = ddg_search(dq, max_results=4)
                for item in (dq_results or []):
                    t_text = f"{item.get('title', '')}. {item.get('body', '')}"
                    s_href = clean_url(item.get("href", ""))
                    for em in extract_emails(t_text):
                        e_clean = normalize_email(em)
                        all_extracted_emails.add(e_clean)
                        if is_generic_email(e_clean):
                            generic_rejected_emails.add(e_clean)
                            continue
                        if is_free_email(e_clean):
                            personal_rejected_emails.add(e_clean)
                            continue
                        is_ok, reason = is_valid_company_email_domain(e_clean, primary_domain, company_name, allowed_domains)
                        if not is_ok:
                            continue
                        # Check candidates
                        matched_cand = False
                        for cand in candidates:
                            associations_attempted += 1
                            if email_matches_person(e_clean, cand.get("name", "")):
                                add_pair(cand["name"], e_clean, s_href, t_text[:MAX_EVIDENCE_LENGTH])
                                matched_cand = True
                                break
                        if matched_cand:
                            continue
                        # Check text tokens
                        for line in t_text.splitlines():
                            for tok in re.findall(r"\b[A-Z][a-z]+(?:[^\S\r\n]+[A-Z][a-z]+)+\b", line):
                                if is_strict_person_name(tok, company_name):
                                    associations_attempted += 1
                                    if email_matches_person(e_clean, tok):
                                        add_pair(tok, e_clean, s_href, t_text[:MAX_EVIDENCE_LENGTH])
                                        break
            except Exception:
                pass

    # STEP 4: Detect pattern
    target_pattern_domain = primary_domain
    pattern_result = detect_generic_email_pattern(exact_pairs, target_pattern_domain, company_name, allowed_domains)
    detected_pattern = pattern_result.get("pattern")
    pattern_confidence = pattern_result.get("pattern_confidence", "NONE")
    pattern_evidence = pattern_result.get("pattern_evidence", [])
    patterns_observed = pattern_result.get("patterns_observed", [])
    can_generate = pattern_result.get("can_generate", False)
    pattern_domain = pattern_result.get("pattern_domain") or target_pattern_domain

    print(f"[PATTERN EVIDENCE] queries_tried={len(queries_tried)} emails_found={len(exact_pairs)} distinct_people={len(exact_pairs)} confidence={pattern_confidence}")

    # STEP 5 & 6: Generate missing emails if reliable pattern exists (never overwrite EXACT_FOUND)
    for item in enriched:
        item["patterns_observed"] = patterns_observed
        item["pattern_confidence"] = pattern_confidence
        item["pattern_evidence"] = pattern_evidence

        # Exact email ALWAYS has priority: never overwrite
        if item.get("email_status") == "EXACT_FOUND" or item.get("exact_email"):
            item["email"] = item.get("exact_email") or item.get("email")
            item["email_status"] = "EXACT_FOUND"
            item["emailStatus"] = "EXACT_FOUND"
            item["pattern_used"] = "none"
            item["generated_pattern"] = "none"
            item["generatedPattern"] = "none"
            item["email_pattern"] = detected_pattern or "none"
            continue

        # Guard: explicitly allow generation only for INSUFFICIENT and SUPPORTED, explicitly block NONE and CONFLICTING
        valid_pattern_exists = bool(detected_pattern and pattern_domain)
        generation_allowed = (
            valid_pattern_exists
            and pattern_confidence in {"INSUFFICIENT", "SUPPORTED"}
            and can_generate
        )

        if generation_allowed:
            generated = generate_pattern_email(item["name"], pattern_domain, detected_pattern)
            if generated:
                item["email"] = generated
                item["email_status"] = "PATTERN_GENERATED"
                item["emailStatus"] = "PATTERN_GENERATED"
                item["email_pattern"] = detected_pattern
                item["generated_pattern"] = detected_pattern
                item["generatedPattern"] = detected_pattern
                item["pattern_used"] = detected_pattern
                item["patternUsed"] = detected_pattern
                item["pattern_confidence"] = pattern_confidence
                item["patternConfidence"] = pattern_confidence
                item["email_source_type"] = "PATTERN_INFERENCE"
                item["email_source_url"] = website
                item["email_evidence"] = f"Inferred using pattern '{detected_pattern}' on '{pattern_domain}' ({pattern_confidence})"
                item["email_verification"] = "PATTERN_INFERENCE"
                item["emailVerificationMethod"] = "PATTERN_INFERENCE"
                item["email_domain"] = pattern_domain
                item["mailbox_status"] = "UNVERIFIED"
                item["mx_status"] = mx_status
                item["search_status"] = "COMPLETED"
                continue

        # If no pattern or conflict or generation failed
        item["email"] = None
        current_status = item.get("email_status")
        if current_status not in ("SEARCH_TIMEOUT", "SEARCH_UNAVAILABLE", "SEARCH_FAILED"):
            item["email_status"] = "NOT_FOUND"
        item["emailStatus"] = "NOT_FOUND"
        item["email_pattern"] = detected_pattern or "none"
        item["generated_pattern"] = "none"
        item["generatedPattern"] = "none"
        item["pattern_used"] = "none"
        item["patternUsed"] = "none"
        item["pattern_confidence"] = pattern_confidence or "none"
        item["patternConfidence"] = pattern_confidence or "none"
        item["email_source_type"] = "NONE"
        item["email_source_url"] = ""
        item["email_evidence"] = ""
        item["email_verification"] = "NONE"
        item["emailVerificationMethod"] = "NONE"
        item["email_domain"] = pattern_domain or primary_domain
        item["mailbox_status"] = "UNVERIFIED"
        item["mx_status"] = mx_status

    # Final Status Resolution: enforce strict priority across all candidates
    exact_count = 0
    gen_count = 0
    not_found_count = 0
    for item in enriched:
        exact_val = item.get("exact_email") or (item.get("email") if item.get("email_status") == "EXACT_FOUND" or item.get("emailStatus") == "EXACT_FOUND" else None)
        if exact_val:
            item["email"] = exact_val
            item["email_status"] = "EXACT_FOUND"
            item["emailStatus"] = "EXACT_FOUND"
            item["generated_pattern"] = "none"
            item["generatedPattern"] = "none"
            exact_count += 1
        elif item.get("email") and (item.get("email_status") == "PATTERN_GENERATED" or item.get("emailStatus") == "PATTERN_GENERATED"):
            item["email_status"] = "PATTERN_GENERATED"
            item["emailStatus"] = "PATTERN_GENERATED"
            gen_count += 1
        else:
            item["email"] = None
            item["emailStatus"] = "NOT_FOUND"
            if item.get("email_status") not in ("SEARCH_TIMEOUT", "SEARCH_UNAVAILABLE"):
                item["email_status"] = "NOT_FOUND"
            not_found_count += 1

    # Structured Pattern Evidence Logging block matching Section 13
    generation_allowed_flag = "YES" if (detected_pattern and pattern_confidence in {"INSUFFICIENT", "SUPPORTED"} and can_generate) else "NO"

    generated_log_lines = []
    for item in enriched:
        if item.get("email_status") == "PATTERN_GENERATED":
            generated_log_lines.append(f"  {item.get('name')} -> {item.get('email')}")
    if not generated_log_lines:
        generated_log_lines.append("  (none)")
    generated_log_str = "\n".join(generated_log_lines)

    print("============================================================")
    print("EMPLOYEE EMAIL EVIDENCE ANALYSIS")
    print("============================================================")
    print()
    print(f"Company:\n{company_name}")
    print()
    print(f"Domain:\n{primary_domain}")
    print()
    print(f"Pages discovered:\n{len(crawled_pages or [])}")
    print(f"Pages scanned:\n{len(crawled_pages or [])}")
    print()
    print(f"Emails extracted:\n{len(all_extracted_emails)}")
    print(f"Generic emails rejected:\n{len(generic_rejected_emails)}")
    print(f"Personal emails rejected:\n{len(personal_rejected_emails)}")
    print()
    print(f"Person-email associations attempted:\n{associations_attempted}")
    print(f"Valid employee-email pairs:\n{len(exact_pairs)}")
    print()
    print("Employee email evidence:")
    if exact_pairs:
        for idx, p in enumerate(exact_pairs, 1):
            p_name = p.get("name") or p.get("person", "")
            p_em = p.get("email", "")
            print(f"{idx}. {p_name} -> {p_em}")
    else:
        print("  (none)")
    print()
    print("Patterns observed:")
    if patterns_observed:
        for po in patterns_observed:
            print(f"{po['pattern']}: {po['supportCount']}")
    else:
        print("  (none)")
    print()
    print(f"Pattern confidence:\n{pattern_confidence}")
    print()
    print(f"Generation allowed:\n{generation_allowed_flag}")
    print()
    print("Generated candidates:")
    print(generated_log_str)
    print()
    print("Final statuses:")
    print(f"EXACT_FOUND: {exact_count}")
    print(f"PATTERN_GENERATED: {gen_count}")
    print(f"NOT_FOUND: {not_found_count}")
    print("============================================================")

    return enriched

def attach_emails_to_candidates(candidates, company_name, website, direct_emails=None):
    enriched = []
    unresolved = []
    primary_domain = canonical_domain(website)
    allowed_domains = discover_company_email_domains(company_name, website, direct_emails)

    if not primary_domain:
        if allowed_domains:
            primary_domain = allowed_domains[0]
        else:
            clean_name = re.sub(r'[^a-zA-Z0-9]', '', company_name).lower()
            primary_domain = f"{clean_name}.com" if clean_name else "company.com"

    # 1. Exact email match
    for candidate in candidates:
        item = dict(candidate)
        exact = discover_exact_email_for_person(item, company_name, website, allowed_domains, direct_emails)
        if exact.get("status") == "EXACT_FOUND" and exact.get("email"):
            item.update({
                "email": exact["email"],
                "email_status": "EXACT_FOUND",
                "emailStatus": "EXACT_FOUND",
                "email_source_url": exact.get("source_url", ""),
                "email_evidence": exact.get("evidence", ""),
                "email_verification": exact.get("verification", "PUBLIC_EVIDENCE"),
                "email_domain": email_domain(exact["email"]) or primary_domain,
            })
        else:
            item.update({
                "email": None,
                "email_status": "NOT_FOUND",
                "emailStatus": "NOT_FOUND",
                "email_source_url": "",
                "email_evidence": "",
                "email_verification": "NONE",
                "email_domain": primary_domain,
            })
            unresolved.append(item)
        enriched.append(item)

    # 2. Safe Pattern Discovery & Generation
    if unresolved:
        known_pairs = []
        for item in enriched:
            if item.get("email_status") == "EXACT_FOUND" and item.get("email"):
                known_pairs.append((item["name"], item["email"], email_domain(item["email"])))

        pattern, pattern_domain = infer_pattern_from_known_people(known_pairs, min_people=2)
        if pattern and pattern_domain:
            for item in unresolved:
                generated = generate_pattern_email(item["name"], pattern_domain, pattern)
                if generated:
                    item.update({
                        "email": generated,
                        "email_status": "PATTERN_GENERATED",
                        "emailStatus": "PATTERN_GENERATED",
                        "email_source_url": website,
                        "email_evidence": f"Inferred from 2+ verified decision-maker emails using {pattern} on {pattern_domain}",
                        "email_verification": "PATTERN_INFERENCE",
                        "email_domain": pattern_domain,
                        "pattern_used": pattern
                    })
                else:
                    item.update({
                        "email": None,
                        "email_status": "NOT_FOUND",
                        "emailStatus": "NOT_FOUND",
                        "email_source_url": "",
                        "email_evidence": "",
                        "email_verification": "NONE",
                        "email_domain": primary_domain,
                        "pattern_used": "none"
                    })
        else:
            for item in unresolved:
                item.update({
                    "email": None,
                    "email_status": "NOT_FOUND",
                    "emailStatus": "NOT_FOUND",
                    "email_source_url": "",
                    "email_evidence": "",
                    "email_verification": "NONE",
                    "email_domain": primary_domain,
                    "pattern_used": "none"
                })

    return enriched

# ============================================================
# DEDUPLICATION & MERGING
# ============================================================

def merge_same_person_candidates(candidates):
    grouped = {}
    for candidate in candidates:
        name = normalize_name(candidate.get("name", ""))
        if not name:
            continue
        key = name_key(name)
        if key not in grouped:
            grouped[key] = {
                "name": name,
                "role": candidate.get("role", ""),
                "source_url": candidate.get("source_url", ""),
                "source_type": candidate.get("source_type", ""),
                "evidence": candidate.get("evidence", ""),
                "evidence_count": 1,
                "roles": [candidate.get("role", "")],
                "exact_email": candidate.get("exact_email"),
            }
        else:
            existing = grouped[key]
            existing["evidence_count"] += 1
            if candidate.get("exact_email") and not existing.get("exact_email"):
                existing["exact_email"] = candidate["exact_email"]
            role = candidate.get("role", "")
            if role and role not in existing["roles"]:
                existing["roles"].append(role)
            if ROLE_PRIORITY.get(role, 0) > ROLE_PRIORITY.get(existing["role"], 0):
                existing["role"] = role
            if candidate.get("source_type") == "official_website":
                existing["source_type"] = "official_website"
                existing["source_url"] = candidate.get("source_url", "")
            if len(candidate.get("evidence", "")) > len(existing.get("evidence", "")):
                existing["evidence"] = candidate.get("evidence", "")
    return list(grouped.values())

def dedupe_candidates(candidates):
    merged = merge_same_person_candidates(candidates)
    final = []
    for candidate in merged:
        if looks_like_organization_name(candidate["name"]):
            continue
        if not is_strict_person_name(candidate["name"]):
            continue
        final.append(candidate)
    return final

def role_supported_by_evidence(role, evidence, name, company_name):
    """D5: Role is supported ONLY when the evidence meaningfully ties the
    person's NAME to that ROLE. Merely long/unrelated text is NOT support.

    Success paths:
      1. A name->role relationship is directly extracted for this person with
         the exact role (or the documented CEO / CFO shorthand equivalents).
      2. Fallback (looser but still meaningful): the role keyword appears in
         the same sentence of the evidence that mentions the person's name.

    The previous weak rule `len(evidence) > 30` has been removed so that a few
    sentences of unrelated prose can never prove a role.
    """
    relationships = extract_direct_relationships(evidence or "", company_name)
    target_key = name_key(name)
    for item in relationships:
        if name_key(item["name"]) != target_key:
            continue
        extracted_role = item["role"]
        if extracted_role == role:
            return True
        if role in ("CEO", "Chief Executive Officer") and extracted_role in ("CEO", "Chief Executive Officer"):
            return True
        if role in ("CFO", "Chief Financial Officer") and extracted_role in ("CFO", "Chief Financial Officer"):
            return True

    # Fallback: role phrase must co-occur with the name in the same sentence.
    low_evidence = normalize_text(evidence or "").lower()
    low_name = normalize_text(name or "").lower()
    if not low_evidence or not low_name or low_name not in low_evidence:
        return False
    stop_words = {"the", "of", "for", "and", "&", "as", "in", "at", "to"}
    role_words = [
        w for w in re.findall(r"[a-z0-9]+", (role or "").lower())
        if w not in stop_words and len(w) >= 2
    ]
    if not role_words:
        return False
    name_sentences = [s for s in re.split(r"(?<=[.!?])\s+", low_evidence) if low_name in s]
    if not name_sentences:
        return False
    name_sentence = name_sentences[0]
    return any(w in name_sentence for w in role_words)

def is_valid_decision_maker(candidate, company_name="", website=""):
    if not isinstance(candidate, dict):
        return False
    name = normalize_name(candidate.get("name", ""))
    role = normalize_text(candidate.get("role", ""))
    evidence = normalize_text(candidate.get("evidence", ""))
    source_url = candidate.get("source_url", "")

    if not name:
        return False
    tokens = name.split()
    if len(tokens) < 2:
        return False
    if not is_strict_person_name(name, company_name):
        return False
    if looks_like_organization_name(name, company_name):
        return False
    if not role:
        return False

    # Disallow synthetic / fabricated placeholder patterns
    lower_tokens = [t.lower() for t in tokens]
    placeholder_suffixes = {"officer", "lead", "architect", "leadership", "management", "director", "manager", "executive"}
    if lower_tokens[-1] in placeholder_suffixes:
        company_words = [w.lower() for w in re.findall(r"[a-z0-9]+", company_name)] if company_name else []
        if lower_tokens[0] in company_words:
            return False
    if lower_tokens[-1] in ("leadership", "management") or lower_tokens[0] in ("leadership", "management"):
        return False

    # Evidence checks: real text, person name must appear in evidence
    if not evidence or len(evidence) < 5:
        return False

    evidence_lower = evidence.lower()
    name_lower = name.lower()
    first_token = tokens[0].lower().strip(".,'-")
    last_token = tokens[-1].lower().strip(".,'-")

    if name_lower not in evidence_lower:
        if not (first_token in evidence_lower and last_token in evidence_lower):
            return False

    # Template evidence strings are rejected
    if "is verified as" in evidence_lower and ("in official corporate records" in evidence_lower or "overseeing" in evidence_lower):
        return False
    if "corporate leadership channel" in evidence_lower:
        return False

    # Real source URL check
    if not source_url or not source_url.startswith(("http://", "https://")):
        return False

    return True

def final_validate_candidate(candidate, company_name, website):
    if not is_valid_decision_maker(candidate, company_name, website):
        return False
    name = normalize_name(candidate.get("name", ""))
    role = normalize_text(candidate.get("role", ""))
    evidence = normalize_text(candidate.get("evidence", ""))
    if role_is_historical(evidence, name, role):
        return False
    if role_attached_to_other_company(evidence, company_name):
        return False
    # D5: the claimed role must be supported by the evidence itself, or the
    # candidate is rejected (an unrelated long evidence text is not support).
    if not role_supported_by_evidence(role, evidence, name, company_name):
        return False
    return True

def validate_all_candidates(candidates, company_name, website):
    deduped = dedupe_candidates(candidates)
    valid = []
    for c in deduped:
        if final_validate_candidate(c, company_name, website):
            valid.append(c)
    return valid

# ============================================================
# RANKING (DETERMINISTIC & OLLAMA)
# ============================================================

def candidate_score(candidate):
    role = candidate.get("role", "")
    score = ROLE_PRIORITY.get(role, 40)
    if candidate.get("source_type") == "official_website":
        score += 25
    score += min(candidate.get("evidence_count", 1) * 5, 20)
    return score

def deterministic_rank(candidates):
    return sorted(candidates, key=candidate_score, reverse=True)

def rank_candidates_with_ollama(candidates, company_name, target=6):
    if not candidates:
        return []
    shortlist = deterministic_rank(candidates)[:14]
    payload_candidates = [
        {"id": idx, "name": c["name"], "role": c["role"]}
        for idx, c in enumerate(shortlist)
    ]
    system_prompt = "You are an executive ranking assistant. Rank the candidates by seniority for decision making. Return JSON only: {\"ranking\": [0, 1]}"
    user_prompt = f"Company: {company_name}\nCandidates: {json.dumps(payload_candidates)}"
    try:
        with httpx.Client(timeout=4.0) as client:
            resp = client.post(OLLAMA_URL, json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                "stream": False,
                "format": "json"
            })
            if resp.status_code == 200:
                content = resp.json().get("message", {}).get("content", "")
                data = json.loads(content)
                ranking = data.get("ranking", [])
                if isinstance(ranking, list) and ranking:
                    ranked = [shortlist[i] for i in ranking if isinstance(i, int) and 0 <= i < len(shortlist)]
                    for c in shortlist:
                        if c not in ranked:
                            ranked.append(c)
                    return ranked[:target]
    except Exception:
        pass
    return shortlist[:target]

def final_safety_filter(candidates, company_name, website, target=6):
    final = []
    seen_names = set()
    for candidate in candidates:
        if not final_validate_candidate(candidate, company_name, website):
            continue
        key = name_key(candidate["name"])
        if key in seen_names:
            continue
        seen_names.add(key)
        final.append(candidate)
        if len(final) >= target:
            break
    return final

# ============================================================
# PHASE 1: OFFICIAL WEBSITE DECISION-MAKER DISCOVERY
# ============================================================

async def discover_official_website_decision_makers(
    company_name,
    website,
    crawled_pages=None,
    direct_emails=None,
    max_decision_makers=6,
    diagnostics=None
):
    """
    PHASE 1: Pure official website decision-maker discovery.
    - Official website is the FIRST and ONLY source in Phase 1.
    - Strictly NO DuckDuckGo / web search.
    - Strictly NO email pattern generation.
    - Exact email attached ONLY if directly verified in official evidence.
    - Target = 6 is a target, not a guarantee (never pad).
    """
    start_time = time.time()
    company_name = normalize_text(company_name)
    website = clean_url(website)
    target = max(1, min(int(max_decision_makers), MAX_FINAL_RESULTS))

    if diagnostics is None:
        diagnostics = {}
    diagnostics.setdefault("pages_crawled", len(crawled_pages) if crawled_pages else 0)
    diagnostics.setdefault("leadership_pages_found", [])
    diagnostics.setdefault("candidates_extracted", 0)
    diagnostics.setdefault("candidates_validated", 0)
    diagnostics.setdefault("rejected_reasons", {
        "historical_role": 0,
        "organization_as_name": 0,
        "invalid_person_name": 0,
        "other_company_role": 0,
        "no_name_in_evidence": 0
    })

    raw_candidates = []

    # Process official crawled pages
    if crawled_pages:
        for p in crawled_pages:
            html_content = p.get("html") or p.get("content") or ""
            url = clean_url(p.get("url") or website)
            p_type = str(p.get("pageType", "")).lower()
            if any(k in p_type or k in url.lower() for k in ["leader", "team", "board", "director", "management", "about", "govern"]):
                if url not in diagnostics["leadership_pages_found"]:
                    diagnostics["leadership_pages_found"].append(url)

            if "<" in html_content and ">" in html_content:
                raw_candidates.extend(extract_official_candidates(html_content, url, company_name, diagnostics))
            else:
                extracted = extract_candidates_from_text(html_content, url, "official_website", company_name)
                raw_candidates.extend(extracted)
                diagnostics["candidates_extracted"] += len(extracted)

    # Deduplicate before validation
    deduped = dedupe_candidates(raw_candidates)

    # Validate candidates with detailed diagnostics breakdown
    validated = []
    for c in deduped:
        name = normalize_name(c.get("name", ""))
        role = normalize_text(c.get("role", ""))
        evidence = normalize_text(c.get("evidence", ""))

        if not is_strict_person_name(name, company_name):
            diagnostics["rejected_reasons"]["invalid_person_name"] += 1
            continue
        if looks_like_organization_name(name, company_name):
            diagnostics["rejected_reasons"]["organization_as_name"] += 1
            continue
        if name.lower() not in evidence.lower():
            tokens = name.lower().split()
            if not (len(tokens) >= 2 and tokens[0] in evidence.lower() and tokens[-1] in evidence.lower()):
                diagnostics["rejected_reasons"]["no_name_in_evidence"] += 1
                continue
        if role_is_historical(evidence, name, role):
            diagnostics["rejected_reasons"]["historical_role"] += 1
            continue
        if role_attached_to_other_company(evidence, company_name):
            diagnostics["rejected_reasons"]["other_company_role"] += 1
            continue

        validated.append(c)

    diagnostics["candidates_validated"] = len(validated)

    # Seniority ranking (deterministic + local Ollama if available)
    ranked = rank_candidates_with_ollama(validated, company_name, target)

    # Safety filter capped at target
    final_candidates = final_safety_filter(ranked, company_name, website, target)

    # Attach exact emails ONLY (strictly NO pattern generation in Phase 1)
    primary_domain = canonical_domain(website)
    results = []
    for cand in final_candidates:
        item = dict(cand)
        exact_em = item.get("exact_email")
        if not exact_em:
            evidence_emails = extract_emails(item.get("evidence", ""))
            for em in evidence_emails:
                if email_matches_person(em, item["name"]):
                    exact_em = em
                    break
        if not exact_em and direct_emails:
            for em in direct_emails:
                if email_matches_person(em, item["name"]):
                    exact_em = em
                    break

        if exact_em:
            item["email"] = normalize_email(exact_em)
            item["email_status"] = "EXACT_FOUND"
            item["email_verification"] = "PUBLIC_EVIDENCE"
            item["email_source_url"] = item.get("source_url", website)
            item["email_evidence"] = f"Exact professional email published on official page: {exact_em}"
            item["email_domain"] = email_domain(exact_em) or primary_domain
        else:
            item["email"] = None
            item["email_status"] = "NOT_FOUND"
            item["email_verification"] = "NONE"
            item["email_source_url"] = ""
            item["email_evidence"] = ""
            item["email_domain"] = primary_domain

        item["pattern_used"] = "none"
        results.append(item)

    diagnostics["execution_time_ms"] = int((time.time() - start_time) * 1000)
    return results

# ============================================================
# MAIN PIPELINE ENTRY POINT
# ============================================================

async def find_any_company_decision_makers(
    company_name,
    website,
    crawled_pages=None,
    direct_emails=None,
    max_decision_makers=6,
    allow_search_fallback=False
):
    """
    Main entry point for decision maker discovery.
    By default (Phase 1), executes discover_official_website_decision_makers
    without external search fallback or pattern generation.
    """
    if not allow_search_fallback:
        return await discover_official_website_decision_makers(
            company_name=company_name,
            website=website,
            crawled_pages=crawled_pages,
            direct_emails=direct_emails,
            max_decision_makers=max_decision_makers
        )

    # Legacy multi-round external search fallback if explicitly enabled
    company_name = normalize_text(company_name)
    website = clean_url(website)
    target = max(6, min(int(max_decision_makers), MAX_FINAL_RESULTS))
    raw_candidates = []

    # Phase 1: Local / Crawled pages extraction
    if crawled_pages:
        for p in crawled_pages:
            html_content = p.get("html") or p.get("content") or ""
            url = p.get("url") or website
            if "<" in html_content and ">" in html_content:
                raw_candidates.extend(extract_official_candidates(html_content, url, company_name))
            else:
                raw_candidates.extend(extract_candidates_from_text(html_content, url, "official_website", company_name))

    official_valid = validate_all_candidates(raw_candidates, company_name, website)

    # Phase 2: DDG Multi-Round Search (only if allow_search_fallback is True)
    combined = list(official_valid)
    if len(combined) < target:
        combined = search_duckduckgo_multi_round(company_name, website, combined, target)

    # Phase 3: Deduplication & Person Merging
    deduped = dedupe_candidates(combined)

    # Phase 4: Strict Validation
    valid = validate_all_candidates(deduped, company_name, website)

    # Phase 5: Ranking (Ollama with Deterministic Fallback)
    ranked = rank_candidates_with_ollama(valid, company_name, target)

    # Phase 6: Safety Filter
    final_candidates = final_safety_filter(ranked, company_name, website, target)

    # Phase 7: Email Pipeline
    final_candidates = attach_emails_to_candidates(final_candidates, company_name, website, direct_emails)

    return final_candidates
