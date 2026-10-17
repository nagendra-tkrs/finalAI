import re
import unicodedata

GENERIC_LOCAL_PREFIXES = {
    "info", "contact", "support", "sales", "help", "admin", "desk",
    "team", "jobs", "careers", "hello", "press", "media", "billing",
    "partnerships", "inquiries", "privacy", "compliance", "legal",
    "security", "office", "frontdesk", "reception", "marketing", "pr",
    "hr", "recruiting", "investors", "ir", "webmaster", "postmaster"
}

FREE_EMAIL_PROVIDERS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com",
    "aol.com", "protonmail.com", "proton.me", "icloud.com", "mail.com",
    "zoho.com", "gmx.com", "yandex.com", "fastmail.com", "inbox.com"
}

NICKNAME_MAP = {
    "michael": ["mike", "mikey"],
    "robert": ["bob", "rob", "bobby", "robbie"],
    "william": ["will", "bill", "billy", "liam"],
    "tobias": ["tobi"],
    "alexander": ["alex", "alec"],
    "alexandra": ["alex", "alexa"],
    "daniel": ["dan", "danny"],
    "david": ["dave", "davy"],
    "christopher": ["chris"],
    "richard": ["dick", "rick", "rich"],
    "james": ["jim", "jimmy"],
    "thomas": ["tom", "tommy"],
    "samuel": ["sam", "sammy"],
    "samantha": ["sam", "sammy"],
    "matthew": ["matt"],
    "nicholas": ["nick"],
    "steven": ["steve"],
    "stephen": ["steve"],
    "kenneth": ["ken", "kenny"],
    "edward": ["ed", "eddie", "ted"],
    "joseph": ["joe", "joey"],
    "anthony": ["tony"],
    "charles": ["charlie", "chuck"],
    "benjamin": ["ben", "benny"],
    "jonathan": ["jon", "john"],
}

def normalize_text_token(tok: str) -> str:
    """Removes accents, punctuation, and non-alphanumeric chars."""
    if not tok:
        return ""
    nfkd = unicodedata.normalize("NFKD", tok)
    ascii_str = nfkd.encode("ASCII", "ignore").decode("utf-8")
    return re.sub(r"[^a-z0-9]", "", ascii_str.lower())

INVALID_EMAIL_PLACEHOLDERS = {
    "not publicly available",
    "not publicly verified",
    "not available",
    "n/a",
    "na",
    "none",
    "null",
    "undefined",
    "unknown",
    "no email",
    "pending",
    "tbd"
}

def is_valid_email_format(email: str) -> bool:
    """
    Validates that a string is a well-formed email address and not a placeholder.
    """
    if not email or not isinstance(email, str):
        return False
    clean = email.strip().lower()
    if clean in INVALID_EMAIL_PLACEHOLDERS:
        return False
    if " " in clean or "@" not in clean:
        return False
    parts = clean.split("@")
    if len(parts) != 2:
        return False
    local, dom = parts[0], parts[1]
    if not local or not dom or "." not in dom:
        return False
    if dom.startswith(".") or dom.endswith("."):
        return False
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, clean))

def is_generic_email(email: str) -> bool:
    if not email or "@" not in email:
        return True
    local = email.split("@")[0].lower().strip()
    return local in GENERIC_LOCAL_PREFIXES

def is_free_email(email: str) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.split("@")[1].lower().strip()
    return domain in FREE_EMAIL_PROVIDERS

def validate_domain_match(email: str, company_domain: str, allowed_domains: list[str] = None) -> dict:
    """
    Checks if email domain matches official company domain or allowed corporate domains.
    Returns:
        {"matched": bool, "domain": str, "reason": str}
    """
    if not email or "@" not in email:
        return {"matched": False, "domain": "", "reason": "Invalid email"}

    em_dom = email.split("@")[1].lower().strip()
    c_dom = re.sub(r"^www\.", "", (company_domain or "").lower().strip())

    if not c_dom:
        return {"matched": True, "domain": em_dom, "reason": "No company domain specified to compare"}

    # Exact domain match
    if em_dom == c_dom:
        return {"matched": True, "domain": em_dom, "reason": f"Exact match with official domain @{c_dom}"}

    # Subdomain match (e.g. mail.company.com or uk.company.com matches company.com)
    if em_dom.endswith("." + c_dom):
        return {"matched": True, "domain": em_dom, "reason": f"Subdomain match (@{em_dom} is subdomain of @{c_dom})"}

    # Parent domain match (e.g. company.com matches portal.company.com)
    if c_dom.endswith("." + em_dom):
        return {"matched": True, "domain": em_dom, "reason": f"Parent domain match (@{em_dom} is root of @{c_dom})"}

    # Check allowed corporate domains (e.g. group brand names)
    if allowed_domains:
        for ad in allowed_domains:
            clean_ad = re.sub(r"^www\.", "", ad.lower().strip())
            if clean_ad and (em_dom == clean_ad or em_dom.endswith("." + clean_ad)):
                return {"matched": True, "domain": em_dom, "reason": f"Matched allowed corporate domain @{clean_ad}"}

    return {
        "matched": False,
        "domain": em_dom,
        "reason": f"Email domain (@{em_dom}) does not match company domain (@{c_dom})"
    }

def match_person_to_email(person_name: str, email: str) -> dict:
    """
    Flexible matching of person name to email address.
    Supports middle names, initials, hyphens, nicknames, and multiple surnames.
    Returns:
        {
            "matched": bool,
            "confidence": "HIGH" | "MEDIUM" | "LOW" | "NONE",
            "score": int,
            "pattern": str,
            "reason": str
        }
    """
    if not email or "@" not in email:
        return {"matched": False, "confidence": "NONE", "score": 0, "pattern": "none", "reason": "No valid email provided"}

    if not person_name or not person_name.strip():
        return {"matched": False, "confidence": "NONE", "score": 0, "pattern": "none", "reason": "No person name provided"}

    local_raw = email.split("@")[0].lower().strip()
    if is_generic_email(email):
        return {"matched": False, "confidence": "NONE", "score": 0, "pattern": "none", "reason": f"Generic corporate address ({local_raw}@)"}

    # Clean name parts
    raw_tokens = person_name.replace(",", " ").replace("-", " ").split()
    tokens = [normalize_text_token(t) for t in raw_tokens if normalize_text_token(t)]
    if not tokens:
        return {"matched": False, "confidence": "NONE", "score": 0, "pattern": "none", "reason": "Name tokens empty after normalization"}

    first = tokens[0]
    last = tokens[-1] if len(tokens) > 1 else ""
    middles = tokens[1:-1] if len(tokens) > 2 else []

    f_init = first[0] if first else ""
    l_init = last[0] if last else ""

    # Potential first name variants (including nicknames and compound/hyphenated first names)
    first_variants = [first]
    if first in NICKNAME_MAP:
        first_variants.extend(NICKNAME_MAP[first])
    if middles:
        # e.g. Mary-Jane -> maryjane
        compound_first = f"{first}{middles[0]}"
        if compound_first not in first_variants:
            first_variants.append(compound_first)

    # All prefix initials (e.g. George Raymond Richard -> grr, Mary Jane -> mj)
    all_prefix_inits = "".join(t[0] for t in tokens[:-1]) if len(tokens) > 1 else f_init

    # 1. Delimited formats (. _ -)
    for sep in [".", "_", "-"]:
        if sep in local_raw:
            parts = [normalize_text_token(p) for p in local_raw.split(sep) if normalize_text_token(p)]
            if len(parts) == 2:
                p0, p1 = parts[0], parts[1]
                # first.last
                for fv in first_variants:
                    if p0 == fv and p1 == last:
                        return {"matched": True, "confidence": "HIGH", "score": 95, "pattern": "first.last", "reason": f"Matched {sep.join(parts)} as first.last"}
                # f.last or inits.last
                if p0 == f_init and p1 == last:
                    return {"matched": True, "confidence": "HIGH", "score": 92, "pattern": "f.last", "reason": f"Matched {p0}.{p1} as f.last"}
                if p0 == all_prefix_inits and p1 == last:
                    return {"matched": True, "confidence": "HIGH", "score": 92, "pattern": "inits.last", "reason": f"Matched {p0}.{p1} as inits.last"}
                # first.l
                for fv in first_variants:
                    if p0 == fv and p1 == l_init:
                        return {"matched": True, "confidence": "MEDIUM", "score": 85, "pattern": "first.l", "reason": f"Matched {p0}.{p1} as first.l"}
                # last.first
                for fv in first_variants:
                    if p0 == last and p1 == fv:
                        return {"matched": True, "confidence": "HIGH", "score": 90, "pattern": "last.first", "reason": f"Matched {p0}.{p1} as last.first"}
                # l.first
                for fv in first_variants:
                    if p0 == l_init and p1 == fv:
                        return {"matched": True, "confidence": "MEDIUM", "score": 82, "pattern": "last_init.first", "reason": f"Matched {p0}.{p1} as last_init.first"}

            elif len(parts) == 3 and middles:
                p0, p1, p2 = parts[0], parts[1], parts[2]
                m = middles[0]
                m_init = m[0]
                for fv in first_variants:
                    # first.middle.last or first.m.last
                    if p0 == fv and (p1 == m or p1 == m_init) and p2 == last:
                        return {"matched": True, "confidence": "HIGH", "score": 95, "pattern": "first.m.last", "reason": f"Matched middle name/initial in {local_raw}"}

    # 2. Concatenated / Single Token Formats
    local_clean = normalize_text_token(local_raw)

    # firstlast
    for fv in first_variants:
        if local_clean == f"{fv}{last}":
            return {"matched": True, "confidence": "HIGH", "score": 94, "pattern": "firstlast", "reason": f"Matched {local_clean} as firstlast"}

    # flast
    if last and local_clean == f"{f_init}{last}":
        return {"matched": True, "confidence": "HIGH", "score": 92, "pattern": "flast", "reason": f"Matched {local_clean} as flast"}

    # firstl
    for fv in first_variants:
        if last and local_clean == f"{fv}{l_init}":
            return {"matched": True, "confidence": "MEDIUM", "score": 84, "pattern": "firstl", "reason": f"Matched {local_clean} as firstl"}

    # lastfirst
    for fv in first_variants:
        if local_clean == f"{last}{fv}":
            return {"matched": True, "confidence": "HIGH", "score": 90, "pattern": "lastfirst", "reason": f"Matched {local_clean} as lastfirst"}

    # lfirst
    for fv in first_variants:
        if local_clean == f"{l_init}{fv}":
            return {"matched": True, "confidence": "MEDIUM", "score": 82, "pattern": "lfirst", "reason": f"Matched {local_clean} as lfirst"}

    # with middle: fmlast, firstmlast, or all inits + last (e.g. grrmartin)
    if middles and last:
        m = middles[0]
        m_init = m[0]
        if local_clean == f"{all_prefix_inits}{last}":
            return {"matched": True, "confidence": "HIGH", "score": 92, "pattern": "inits_last", "reason": f"Matched {local_clean} as prefix initials + last"}
        if local_clean == f"{f_init}{m_init}{last}":
            return {"matched": True, "confidence": "HIGH", "score": 90, "pattern": "fmlast", "reason": f"Matched {local_clean} as fmlast"}
        for fv in first_variants:
            if local_clean == f"{fv}{m_init}{last}":
                return {"matched": True, "confidence": "HIGH", "score": 92, "pattern": "firstmlast", "reason": f"Matched {local_clean} as firstmlast"}

    # single name match (e.g. john@company.com)
    for fv in first_variants:
        if len(fv) >= 3 and local_clean == fv:
            return {"matched": True, "confidence": "MEDIUM", "score": 75, "pattern": "first", "reason": f"Matched first name only ({fv})"}

    if len(last) >= 4 and local_clean == last:
        return {"matched": True, "confidence": "MEDIUM", "score": 75, "pattern": "last", "reason": f"Matched last name only ({last})"}

    return {
        "matched": False,
        "confidence": "NONE",
        "score": 0,
        "pattern": "none",
        "reason": f"Email localpart '{local_raw}' does not match name '{person_name}'"
    }


def canonical_person_email_match(person_name: str, email: str, company_domain: str = "") -> dict:
    """
    D6: THE canonical person-to-email matcher.

    All overlapping matchers in the codebase (email_matches_person in the
    decision-maker engine and evaluate_person_email_match in contact_service)
    delegate to this single implementation. It combines:

      - email syntax / generic-mailbox checks
      - company-domain validation (when a company domain is known)
      - the full nickname / middle-name / initials / hyphenated-name / pattern
        matcher (match_person_to_email)

    Returns a dict with keys:
      matched, confidence, score, pattern, reason, personEmailMatch,
      domainMatched, domain
    """
    if not email or "@" not in email:
        return {
            "matched": False, "confidence": "NONE", "score": 0, "pattern": "none",
            "reason": "No valid email address provided", "personEmailMatch": "unknown",
            "domainMatched": False, "domain": "",
        }
    if not person_name or not str(person_name).strip():
        return {
            "matched": False, "confidence": "NONE", "score": 0, "pattern": "none",
            "reason": "No person name provided", "personEmailMatch": "unknown",
            "domainMatched": False, "domain": email.split("@")[1].lower().strip(),
        }
    if is_generic_email(email):
        local = email.split("@")[0].lower().strip()
        return {
            "matched": False, "confidence": "NONE", "score": 0, "pattern": "none",
            "reason": f"Generic corporate address ({local}@)", "personEmailMatch": "false",
            "domainMatched": False, "domain": email.split("@")[1].lower().strip(),
        }

    domain = email.split("@")[1].lower().strip()
    if company_domain:
        dm = validate_domain_match(email, company_domain)
        domain_ok = bool(dm.get("matched"))
    else:
        domain_ok = True

    result = match_person_to_email(person_name, email)
    result["domainMatched"] = domain_ok
    result["domain"] = domain

    if not domain_ok:
        result["matched"] = False
        result["personEmailMatch"] = "false"
        result["reason"] = (
            f"Email domain (@{domain}) does not match company domain: {result.get('reason', '')}"
        )
    else:
        result["personEmailMatch"] = "true" if result.get("matched") else "false"

    return result
