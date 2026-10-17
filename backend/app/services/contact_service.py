import re
import os
import asyncio
import httpx
import dns.resolver
from datetime import datetime, timezone
from fastapi import HTTPException
from app.config.database import get_db
from app.utils.bson_utils import to_object_id, serialize_doc
from app.utils.company_matcher import validate_company_match
from app.services.ai_service import get_ai_config, call_ai, can_use_ai
from app.services.search.search_provider import get_active_search_provider_config
from app.services.decision_maker_engine import (
    find_any_company_decision_makers,
    discover_official_website_decision_makers,
    discover_phase2_decision_maker_emails,
    detect_generic_email_pattern,
    is_valid_decision_maker,
    is_strict_person_name,
    decode_cloudflare_email,
    search_duckduckgo_multi_round,
    dedupe_candidates,
    validate_all_candidates,
    rank_candidates_with_ollama,
    final_safety_filter,
)
from app.services.email_discovery_service import discover_decision_maker_emails
from app.services.email_validation_service import is_valid_email_format
from app.services.web_search_service import (
    clean_executive,
    fetch_authoritative_public_records,
    search_web_for_leadership,
    extract_executives_from_snippets,
    search_online_for_person_email,
    search_online_for_generated_email,
    search_company_employee_emails
)

def categorize_role(title: str = '', department: str = '') -> dict:
    t = (title or '').lower()
    d = (department or '').lower()

    if re.search(r'\b(ceo|chief executive officer|co-ceo|chief executive)\b', t, re.I):
        return {'roleCategory': 'ceo', 'seniority': 'executive', 'cleanTitle': 'Chief Executive Officer'}
    if re.search(r'\b(co-founder|cofounder)\b', t, re.I):
        return {'roleCategory': 'co_founder', 'seniority': 'executive', 'cleanTitle': 'Co-Founder'}
    if re.search(r'\b(founder|founding partner|owner|proprietor)\b', t, re.I):
        return {'roleCategory': 'founder', 'seniority': 'executive', 'cleanTitle': 'Founder'}
    if re.search(r'\b(chairman|chairperson)\b', t, re.I):
        return {'roleCategory': 'president', 'seniority': 'executive', 'cleanTitle': title or 'Chairman'}
    if re.search(r'\b(president)\b', t, re.I) and not re.search(r'\b(vice president|vp)\b', t, re.I):
        return {'roleCategory': 'president', 'seniority': 'executive', 'cleanTitle': 'President'}
    if re.search(r'\b(managing director|md)\b', t, re.I):
        return {'roleCategory': 'managing_director', 'seniority': 'executive', 'cleanTitle': 'Managing Director'}
    if re.search(r'\b(coo|chief operating officer|chief operations officer)\b', t, re.I):
        return {'roleCategory': 'coo', 'seniority': 'executive', 'cleanTitle': 'Chief Operating Officer'}
    if re.search(r'\b(cfo|chief financial officer|chief finance officer|head of finance)\b', t, re.I):
        return {'roleCategory': 'cfo', 'seniority': 'executive', 'cleanTitle': 'Chief Financial Officer'}
    if re.search(r'\b(cto|chief technology officer|chief technical officer)\b', t, re.I):
        return {'roleCategory': 'cto', 'seniority': 'executive', 'cleanTitle': 'Chief Technology Officer'}
    if re.search(r'\b(cio|chief information officer)\b', t, re.I):
        return {'roleCategory': 'cio', 'seniority': 'executive', 'cleanTitle': 'Chief Information Officer'}
    if re.search(r'\b(cdo|chief digital officer|chief data officer)\b', t, re.I):
        return {'roleCategory': 'cdo', 'seniority': 'executive', 'cleanTitle': 'Chief Digital Officer'}

    # D1: Specialized functional/executive roles MUST be classified BEFORE the
    # generic "director" / "vice president" rules, otherwise roles such as
    # "Director of AI", "Director of Data", "VP of Engineering", "VP of Sales"
    # would be downgraded to the generic categories.
    if re.search(r'\b(head of ai|director of ai|vp of ai|vice president of ai|head of machine learning|lead ai architect|chief ai officer|caio)\b', t, re.I) or 'ai' in d or 'machine learning' in d:
        return {'roleCategory': 'head_of_ai', 'seniority': 'director', 'cleanTitle': 'Head of AI'}
    if re.search(r'\b(head of data|director of data|vp of data|vice president of data|head of analytics|head of data science|data engineering lead|head of bi)\b', t, re.I) or 'data' in d or 'analytics' in d:
        return {'roleCategory': 'head_of_data', 'seniority': 'director', 'cleanTitle': 'Head of Data'}
    if re.search(r'\b(vp of engineering|vice president of engineering|head of engineering|director of engineering|vp of technology|vice president of technology|director of technology|head of technology|head of it|director of it|vp of it|head of information technology|chief information officer)\b', t, re.I) or 'technology' in d or 'engineering' in d or 'it' in d:
        return {'roleCategory': 'head_of_technology', 'seniority': 'director', 'cleanTitle': 'Head of Technology'}
    if re.search(r'\b(head of sales|director of sales|vp of sales|vice president of sales|chief revenue officer|cro|head of revenue|director of revenue|head of business development|director of business development)\b', t, re.I) or 'sales' in d or 'business development' in d:
        return {'roleCategory': 'head_of_sales', 'seniority': 'director', 'cleanTitle': 'Head of Sales'}
    if re.search(r'\b(head of product|director of product|vp of product|vice president of product|chief product officer|cpo|head of product management|director of product management)\b', t, re.I) or 'product' in d:
        return {'roleCategory': 'head_of_product', 'seniority': 'director', 'cleanTitle': 'Head of Product'}
    if re.search(r'\b(head of operations|director of operations|vp of operations|vice president of operations)\b', t, re.I) or d == 'operations':
        return {'roleCategory': 'head_of_operations', 'seniority': 'director', 'cleanTitle': 'Head of Operations'}
    if re.search(r'\b(head of marketing|director of marketing|vp of marketing|chief marketing officer|cmo)\b', t, re.I) or 'marketing' in d:
        return {'roleCategory': 'head_of_marketing', 'seniority': 'director', 'cleanTitle': 'Head of Marketing'}
    if re.search(r'\b(head of hr|director of hr|vp of hr|chief human resources officer|chief people officer|head of people)\b', t, re.I) or d in ('hr', 'human resources'):
        return {'roleCategory': 'head_of_hr', 'seniority': 'director', 'cleanTitle': 'Head of HR'}
    if re.search(r'\b(head of legal|general counsel|chief legal officer|director of legal)\b', t, re.I) or 'legal' in d:
        return {'roleCategory': 'head_of_legal', 'seniority': 'director', 'cleanTitle': 'Head of Legal'}
    if re.search(r'\b(head of finance|director of finance|vp of finance)\b', t, re.I) or d == 'finance':
        return {'roleCategory': 'head_of_finance', 'seniority': 'director', 'cleanTitle': 'Head of Finance'}

    # Generic role levels -- AFTER specialized roles (D1 precedence)
    if re.search(r'\b(director)\b', t, re.I) and not re.search(r'\b(managing director|md)\b', t, re.I):
        return {'roleCategory': 'director', 'seniority': 'director', 'cleanTitle': title or 'Director'}
    if re.search(r'\b(vice president|vp|executive vice president|evp|senior vice president|svp)\b', t, re.I):
        return {'roleCategory': 'vp', 'seniority': 'executive', 'cleanTitle': title or 'Vice President'}
    if re.search(r'\b(head of|department head)\b', t, re.I):
        return {'roleCategory': 'dept_head', 'seniority': 'director', 'cleanTitle': title or 'Department Head'}
    if re.search(r'\b(manager|team lead|group head|unit head)\b', t, re.I):
        return {'roleCategory': 'manager', 'seniority': 'manager', 'cleanTitle': title or 'Manager'}
    if re.search(r'\b(lead|senior consultant|consultant|analyst)\b', t, re.I):
        return {'roleCategory': 'lead', 'seniority': 'staff', 'cleanTitle': title or 'Lead'}
    if re.search(r'\b(desk|inbox|support|info|sales|contact|team|general)\b', t, re.I) or 'inquiries' in t:
        return {'roleCategory': 'general', 'seniority': 'general', 'cleanTitle': title or 'Company Inbox'}

    return {'roleCategory': 'other', 'seniority': 'staff', 'cleanTitle': title or 'Executive'}

async def check_domain_mx(domain: str) -> dict:
    if not domain:
        return {
            'mxStatus': 'UNKNOWN',
            'mxProvider': '',
            'hasMxRecords': None,
            'mxState': 'UNKNOWN'
        }

    clean_domain = re.sub(r'^https?://', '', domain)
    clean_domain = re.sub(r'^www\.', '', clean_domain).split('/')[0].lower()

    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = 2.0
        answers = resolver.resolve(clean_domain, 'MX')
        if answers:
            primary_exchange = str(answers[0].exchange).lower()
            provider_name = 'Active Mail Server'
            if 'google' in primary_exchange or 'l.google.com' in primary_exchange:
                provider_name = 'Google Workspace MX'
            elif 'outlook' in primary_exchange or 'microsoft' in primary_exchange:
                provider_name = 'Microsoft 365 Exchange'
            elif 'zoho' in primary_exchange:
                provider_name = 'Zoho Mail'
            elif 'protonmail' in primary_exchange:
                provider_name = 'ProtonMail MX'

            return {
                'mxStatus': 'MX_ACTIVE',
                'mxProvider': f"{provider_name} ({primary_exchange})",
                'hasMxRecords': True,
                'mxState': 'YES'
            }
        return {
            'mxStatus': 'MX_NOT_FOUND',
            'mxProvider': 'No MX records found',
            'hasMxRecords': False,
            'mxState': 'NO'
        }
    except Exception:
        # D7: DNS lookup failure / timeouts are UNKNOWN, not a proof of "no MX".
        # Keep hasMxRecords None (unknown) so downstream scoring stays neutral.
        return {
            'mxStatus': 'MX_UNKNOWN',
            'mxProvider': 'DNS MX lookup failed or timed out',
            'hasMxRecords': None,
            'mxState': 'UNKNOWN',
            'dnsError': True
        }

def evaluate_person_email_match(person_name: str = '', email: str = '', domain: str = '') -> dict:
    # D6: Delegate to the single canonical person->email matcher so every caller
    # shares identical nickname/middle-name/initials/hyphen/domain logic.
    try:
        from app.services.email_validation_service import canonical_person_email_match
    except Exception:
        canonical_person_email_match = None

    if canonical_person_email_match is not None:
        res = canonical_person_email_match(person_name or '', email or '', domain or '')
        matched = bool(res.get('matched'))
        reason = res.get('reason') or ('Email reflects person name' if matched else 'Email does not correspond to person name')
        return {
            'match': matched,
            'personEmailMatch': res.get('personEmailMatch', 'true' if matched else 'false'),
            'reason': reason,
            'score': res.get('score', 0),
            'pattern': res.get('pattern', 'none'),
            'confidence': res.get('confidence', 'NONE'),
            'domainMatched': res.get('domainMatched', True)
        }

    # Fallback (never expected): identical legacy logic preserved for safety.
    if not email or '@' not in email:
        return {'match': False, 'personEmailMatch': 'unknown', 'reason': 'No email address available to compare'}

    clean_domain = re.sub(r'^https?://', '', domain or '')
    clean_domain = re.sub(r'^www\.', '', clean_domain).split('/')[0].lower()

    e_parts = email.split('@')
    local_part = e_parts[0].lower().strip()
    email_domain = e_parts[1].lower().strip() if len(e_parts) > 1 else ''

    if email_domain and clean_domain and (email_domain not in clean_domain and clean_domain not in email_domain):
        return {'match': False, 'personEmailMatch': 'false', 'reason': f"Email domain (@{email_domain}) does not match company domain (@{clean_domain})"}

    if not person_name:
        return {'match': False, 'personEmailMatch': 'unknown', 'reason': 'No person name provided'}

    normalized = re.sub(r'[^a-zA-Z\s]', '', person_name).strip().lower()
    parts = [p for p in normalized.split() if p]
    first = parts[0] if parts else ''
    last = parts[-1] if len(parts) > 1 else ''

    generic_prefixes = ['info', 'contact', 'support', 'sales', 'help', 'admin', 'desk', 'team', 'jobs', 'careers', 'hello', 'press', 'media', 'billing', 'partnerships', 'inquiries']
    if local_part in generic_prefixes:
        return {'match': False, 'personEmailMatch': 'false', 'reason': f"Generic corporate channel ({local_part}@) is not an individual person's mailbox"}

    # Dotted or separated
    separator = '.' if '.' in local_part else ('_' if '_' in local_part else ('-' if '-' in local_part else None))
    if separator:
        split_tokens = local_part.split(separator)
        local_first = split_tokens[0]
        local_last = separator.join(split_tokens[1:])

        is_first_match = (
            local_first == first or
            (first == 'tobias' and local_first == 'tobi') or
            (first == 'michael' and local_first == 'mike') or
            (first == 'robert' and local_first in ('bob', 'rob')) or
            (first == 'william' and local_first in ('will', 'bill')) or
            (first and local_first == first[0])
        )
        is_last_match = (local_last == last)

        if is_first_match and is_last_match:
            return {'match': True, 'personEmailMatch': 'true', 'reason': f"Email localpart ({local_part}) accurately reflects person name ({person_name})"}
        return {'match': False, 'personEmailMatch': 'false', 'reason': f"Email localpart ({local_part}) does not correspond to person name ({person_name})"}

    valid_single_patterns = {first, last, f"{first}{last}", f"{first[0]}{last}" if first else '', f"{first}{last[0]}" if first and last else ''}
    if first == 'tobias': valid_single_patterns.add('tobi')
    if first == 'michael': valid_single_patterns.add('mike')
    if first == 'robert': valid_single_patterns.update(['bob', 'rob'])
    if first == 'william': valid_single_patterns.update(['will', 'bill'])

    if local_part in valid_single_patterns:
        return {'match': True, 'personEmailMatch': 'true', 'reason': f"Email localpart ({local_part}) accurately reflects person name pattern for {person_name}"}

    return {'match': False, 'personEmailMatch': 'false', 'reason': f"Email localpart ({local_part}) does not correspond to person name ({person_name})"}

def calculate_explainable_confidence(data: dict) -> dict:
    is_generic = data.get('isGeneric', False)
    is_exact = data.get('isExactPublished', False)
    is_pattern = data.get('isPatternDerived', False)
    # D7: tri-state MX — do not silently default to "has MX" nor claim "no MX"
    # when the DNS state is unknown.
    has_mx = data.get('hasMxRecords', None)
    mx_state = data.get('mxState')
    if mx_state in ('YES', True, 'true'):
        has_mx = True
    elif mx_state in ('NO', False, 'false'):
        has_mx = False
    # Anything else (UNKNOWN / missing) leaves has_mx as None -> neutral. Note:
    # mxState strings like "UNKNOWN" must NOT be coerced to False.
    match = data.get('personEmailMatch', 'true')

    if is_generic:
        return {
            'confidenceScore': 85 if is_exact else 70,
            'confidenceLevel': 'medium',
            'confidenceReasoning': ['Official corporate inbound channel on company domain']
        }

    score = 0
    reasoning = []
    source_type = data.get('sourceType', 'official_team_page')

    if source_type in ('official_team_page', 'official_website'):
        score += 35
        reasoning.append('Official company leadership/team page (+35)')
    elif source_type in ('official_news', 'press_release'):
        score += 30
        reasoning.append('Authoritative public record / corporate press release (+30)')
    else:
        score += 20
        reasoning.append('Public web search and indexing evidence (+20)')

    if data.get('designationVerified') == 'true':
        score += 25
        reasoning.append('Confirmed C-Suite / Founder / Leadership designation (+25)')
    else:
        score += 15
        reasoning.append('General executive designation (+15)')

    if is_exact and match == 'true':
        score += 30
        reasoning.append('Exact professional email verified directly in source (+30)')
    elif is_pattern and has_mx is True:
        score += 15
        reasoning.append('Company employee email format with active DNS MX (+15)')
    else:
        reasoning.append('No direct personal mailbox published (+0)')

    if has_mx is True:
        score += 10
        reasoning.append('Active corporate DNS MX mail exchange verified (+10)')
    elif has_mx is None:
        reasoning.append('MX availability unknown / not verified (+0, neutral)')

    level = 'high' if score >= 85 else ('medium' if score >= 65 else 'low')
    return {
        'confidenceScore': min(score, 100),
        'confidenceLevel': level,
        'confidenceReasoning': reasoning
    }

def match_email_to_name_pattern(local_part: str = '', first_name: str = '', last_name: str = '') -> str:
    local = (local_part or '').lower().strip()
    f = re.sub(r'[^a-zA-Z]', '', first_name or '').lower()
    l = re.sub(r'[^a-zA-Z]', '', last_name or '').lower()

    if not local:
        return None

    if f and l:
        f_init = f[0]
        l_init = l[0]
        if local == f"{f}.{l}": return 'first.last'
        if local == f"{f}_{l}": return 'first_last'
        if local == f"{f}{l}": return 'firstlast'
        if local == f"{f_init}{l}": return 'flast'
        if local == f"{f_init}.{l}": return 'f.last'
        if local == f"{f}.{l_init}": return 'first.l'
        if local == f"{f}_{l_init}": return 'first_l'
        if local == f"{f}{l_init}": return 'firstl'
        if local == f"{l}.{f}": return 'last.first'
        if local == f"{l}_{f}": return 'last_first'
        if local == f"{l}{f}": return 'lastfirst'
        if local == f"{l}{f_init}": return 'lastf'
        if local == f"{l}.{f_init}": return 'last.f'
        if local == f"{f_init}{l_init}": return 'fl'
        if local == f"{f_init}.{l_init}": return 'f.l'
        if local == f: return 'first'
        if local == l: return 'last'
    elif f:
        if local == f: return 'first'

    if '.' in local:
        parts = local.split('.')
        if len(parts[0]) == 1: return 'f.last'
        if len(parts) > 1 and len(parts[1]) == 1: return 'first.l'
        return 'first.last'
    if '_' in local:
        parts = local.split('_')
        if len(parts[0]) == 1: return 'f_last'
        if len(parts) > 1 and len(parts[1]) == 1: return 'first_l'
        return 'first_last'

    return None

def generate_candidate_email(name: str, pattern: str, email_domain: str) -> str:
    if not name or not email_domain:
        return ''

    normalized = re.sub(r'[^a-zA-Z\s]', '', name).strip().lower()
    parts = [p for p in normalized.split() if p]
    if not parts:
        return ''

    first = parts[0]
    last = parts[-1] if len(parts) > 1 else ''
    f_init = first[0] if first else ''
    l_init = last[0] if last else ''
    clean_domain = re.sub(r'^https?://', '', email_domain)
    clean_domain = re.sub(r'^www\.', '', clean_domain).split('/')[0].lower()

    mapping = {
        'first.last': f"{first}.{last}" if last else first,
        'first_last': f"{first}_{last}" if last else first,
        'firstlast': f"{first}{last}" if last else first,
        'first': first,
        'flast': f"{f_init}{last}" if last else first,
        '{firstInitial}{lastName}': f"{f_init}{last}" if last else first,
        'firstInitial+last': f"{f_init}{last}" if last else first,
        'f.last': f"{f_init}.{last}" if last else first,
        '{firstInitial}.{lastName}': f"{f_init}.{last}" if last else first,
        'first.l': f"{first}.{l_init}" if last else first,
        '{firstName}.{lastInitial}': f"{first}.{l_init}" if last else first,
        'first_l': f"{first}_{l_init}" if last else first,
        'firstl': f"{first}{l_init}" if last else first,
        'last.first': f"{last}.{first}" if last else first,
        'last_first': f"{last}_{first}" if last else first,
        'lastfirst': f"{last}{first}" if last else first,
        'lastf': f"{last}{f_init}" if last else first,
        'last.f': f"{last}.{f_init}" if last else first,
        'last': last or first,
        'fl': f"{f_init}{l_init}" if last else f_init,
        'f.l': f"{f_init}.{l_init}" if last else f_init,
    }

    local_part = mapping.get(pattern, f"{first}.{last}" if last else first)
    return f"{local_part}@{clean_domain}"

async def discover_company_email_pattern(company_id, company_name: str, domain: str, direct_emails: list = None) -> dict:
    if direct_emails is None:
        direct_emails = []

    clean_domain = re.sub(r'^https?://', '', domain or '')
    clean_domain = re.sub(r'^www\.', '', clean_domain).split('/')[0].lower()
    valid_employee_emails = []
    pattern_sources = []

    generic_prefixes = ['info', 'contact', 'sales', 'support', 'help', 'admin', 'desk', 'inquiries', 'team', 'jobs', 'careers', 'hello', 'press', 'media', 'billing', 'partnerships']

    # 1. Existing DB contacts (EXACT / directly verified evidence ONLY - never include generated candidates)
    db = get_db()
    if db is not None and company_id:
        async for c in db.contacts.find({"companyId": to_object_id(company_id), "email": {"$ne": ""}}):
            # Guard: generated emails must NEVER become employee evidence
            if c.get("emailStatus") == "PATTERN_GENERATED" or c.get("email_status") == "PATTERN_GENERATED":
                continue
            if c.get("isExactPublished") is False or c.get("email_verification") == "PATTERN_INFERENCE":
                continue
            em = (c.get("email") or "").lower().strip()
            if '@' in em:
                local, em_dom = em.split('@')
                if local not in generic_prefixes and validate_company_match(em_dom.split('.')[0], company_name, clean_domain):
                    valid_employee_emails.append({
                        'name': c.get('name', ''),
                        'local': local, 'domain': em_dom, 'email': em,
                        'firstName': c.get('name', '').split()[0] if c.get('name') else '',
                        'lastName': c.get('name', '').split()[-1] if c.get('name') and len(c.get('name').split()) > 1 else '',
                        'personName': c.get('name', ''),
                        'sourceUrl': c.get('sourceUrl', '')
                    })

    # 2. Direct crawled page emails
    for de in direct_emails:
        if de and '@' in de:
            lower = de.lower().strip()
            local, em_dom = lower.split('@')
            if local not in generic_prefixes and validate_company_match(em_dom.split('.')[0], company_name, clean_domain):
                valid_employee_emails.append({
                    'name': '',
                    'local': local, 'domain': em_dom, 'email': lower,
                    'firstName': '', 'lastName': '', 'personName': '', 'sourceUrl': 'Official Website'
                })

    # 3. Public Web employee search
    if len(valid_employee_emails) < 3:
        try:
            pub_samples = await search_company_employee_emails(company_name, clean_domain)
            for ps in pub_samples:
                valid_employee_emails.append({
                    'name': ps.get('personName', ''),
                    'local': ps['email'].split('@')[0],
                    'domain': ps['domain'],
                    'email': ps['email'],
                    'firstName': ps.get('firstName', ''),
                    'lastName': ps.get('lastName', ''),
                    'personName': ps.get('personName', ''),
                    'sourceUrl': ps.get('sourceUrl', '')
                })
                pattern_sources.append(ps.get('sourceTitle', 'Public Search Result'))
        except Exception:
            pass

    if not valid_employee_emails:
        return {
            'pattern': None,
            'emailDomain': clean_domain,
            'confidence': 0,
            'patternConfidence': 'NONE',
            'examples': [],
            'verifiedAssociations': [],
            'sources': []
        }

    # Use Phase 2 generic pattern detector
    pattern_res = detect_generic_email_pattern(valid_employee_emails, clean_domain)
    sel_pattern = pattern_res.get('pattern')
    pattern_conf = pattern_res.get('pattern_confidence', 'NONE')
    evidence_list = pattern_res.get('pattern_evidence', [])

    return {
        'pattern': sel_pattern,
        'emailDomain': clean_domain,
        'confidence': 90 if pattern_conf == 'SUPPORTED' else (70 if pattern_conf in ('WEAK', 'INSUFFICIENT') else 0),
        'patternConfidence': pattern_conf,
        'patternsObserved': pattern_res.get('patterns_observed', []),
        'examples': [e['email'] for e in evidence_list][:5] or [e['email'] for e in valid_employee_emails][:5],
        'verifiedAssociations': [e for e in evidence_list if e.get('person')][:5],
        'sources': pattern_sources[:5]
    }

async def resolve_decision_maker_email(name: str = '', company_name: str = '', domain: str = '', direct_emails: list = None, company_id = None, pattern_info: dict = None) -> dict:
    if direct_emails is None:
        direct_emails = []
    if not name:
        return {
            'email': '', 'emailDomain': '', 'emailStatus': 'NOT_FOUND', 'status': 'not_found',
            'confidenceScore': 0, 'sourceType': 'None', 'patternUsed': 'none', 'patternConfidence': 'none',
            'patternExamples': [], 'patternSources': [], 'verifiedAssociations': [],
            'isExactPublished': False, 'verificationMethod': 'None',
            'emailVerificationState': 'NOT_FOUND'
        }

    clean_domain = re.sub(r'^https?://', '', domain or '')
    clean_domain = re.sub(r'^www\.', '', clean_domain).split('/')[0].lower()

    normalized = re.sub(r'[^a-zA-Z\s]', '', name).strip().lower()
    parts = [p for p in normalized.split() if p]
    first = parts[0] if parts else ''
    last = parts[-1] if len(parts) > 1 else ''

    # 1. Direct scraped match
    for e in direct_emails:
        local = e.split('@')[0].lower()
        if (first and first in local) or (last and last in local):
            return {
                'email': e.lower(),
                'emailDomain': e.split('@')[1] if '@' in e else clean_domain,
                'emailStatus': 'DIRECTLY_VERIFIED',
                'status': 'verified',
                'confidenceScore': 97,
                'sourceType': 'Published Leadership Page',
                'patternUsed': 'none',
                'patternConfidence': 'none',
                'patternExamples': [e.lower()],
                'patternSources': ['Official Leadership Page'],
                'verifiedAssociations': [{'email': e.lower(), 'personName': name}],
                'isExactPublished': True,
                'verificationMethod': 'DIRECT_SOURCE_MATCH',
                'emailVerificationState': 'EXACT_PUBLISHED'
            }

    # 2. Public Search for exact published email
    direct_search = await search_online_for_person_email(name, company_name, clean_domain)
    if direct_search and direct_search.get('email'):
        em = direct_search['email'].lower()
        return {
            'email': em,
            'emailDomain': em.split('@')[1] if '@' in em else clean_domain,
            'emailStatus': 'DIRECTLY_VERIFIED',
            'status': 'verified',
            'confidenceScore': direct_search.get('confidenceScore', 96),
            'sourceType': direct_search.get('source', 'Google Search Index'),
            'patternUsed': 'none',
            'patternConfidence': 'none',
            'patternExamples': [em],
            'patternSources': [direct_search.get('sourceUrl', '')],
            'verifiedAssociations': [{'email': em, 'personName': name}],
            'isExactPublished': True,
            'verificationMethod': 'DIRECT_SOURCE_MATCH',
            'emailVerificationState': 'EXACT_PUBLISHED',
            'searchIndexSighting': True
        }

    # 3. Discover company pattern and generate candidate
    if pattern_info is None:
        pattern_info = await discover_company_email_pattern(company_id, company_name, clean_domain, direct_emails)
    if pattern_info and pattern_info.get('pattern'):
        cand_email = generate_candidate_email(name, pattern_info['pattern'], pattern_info.get('emailDomain') or clean_domain)

        # Online verification of candidate email
        cand_verify = await search_online_for_generated_email(cand_email, name, company_name, clean_domain)
        if cand_verify.get('verified'):
            # D2: A search-index appearance of a PATTERN-GENERATED email is a
            # "sighting", NOT proof the address was explicitly published by an
            # authoritative source. It must never be promoted to DIRECT_SOURCE_MATCH
            # / isExactPublished=True, otherwise generated addresses would be
            # silently misrepresented as verified published mailboxes.
            #
            # Exception: when the sighting itself is hosted on the company's
            # official domain, the mailbox is genuinely published by the
            # company, so EXACT_PUBLISHED is accurate there.
            if cand_verify.get('onOfficialSource'):
                return {
                    'email': cand_email,
                    'emailDomain': pattern_info.get('emailDomain') or clean_domain,
                    'emailStatus': 'DIRECTLY_VERIFIED',
                    'status': 'verified',
                    'confidenceScore': cand_verify.get('confidenceScore', 96),
                    'sourceType': 'Official Company Domain (search-confirmed)',
                    'patternUsed': pattern_info['pattern'],
                    'patternConfidence': pattern_info.get('patternConfidence', 'medium'),
                    'patternExamples': pattern_info.get('examples', []),
                    'patternSources': pattern_info.get('sources', []),
                    'verifiedAssociations': pattern_info.get('verifiedAssociations', []),
                    'isExactPublished': True,
                    'verificationMethod': 'DIRECT_SOURCE_MATCH',
                    'emailVerificationState': 'EXACT_PUBLISHED',
                    'searchIndexSighting': True,
                    'searchSighting': cand_verify.get('source', ''),
                    'mailboxVerification': 'UNVERIFIED'
                }
            return {
                'email': cand_email,
                'emailDomain': pattern_info.get('emailDomain') or clean_domain,
                'emailStatus': 'PATTERN_GENERATED',
                'status': 'pattern_derived',
                'confidenceScore': pattern_info.get('confidence', 80),
                'sourceType': 'Company Email Pattern Inference',
                'patternUsed': pattern_info['pattern'],
                'patternConfidence': pattern_info.get('patternConfidence', 'medium'),
                'patternExamples': pattern_info.get('examples', []),
                'patternSources': pattern_info.get('sources', []),
                'verifiedAssociations': pattern_info.get('verifiedAssociations', []),
                'isExactPublished': False,
                'verificationMethod': 'PATTERN_INFERENCE',
                'emailVerificationState': 'PATTERN_GENERATED',
                'searchIndexSighting': True,
                'searchSighting': cand_verify.get('source', ''),
                'mailboxVerification': 'UNVERIFIED'
            }

        return {
            'email': cand_email,
            'emailDomain': pattern_info.get('emailDomain') or clean_domain,
            'emailStatus': 'PATTERN_BASED_UNVERIFIED',
            'status': 'pattern_derived',
            'confidenceScore': pattern_info.get('confidence', 80),
            'sourceType': 'Company Email Pattern Inference',
            'patternUsed': pattern_info['pattern'],
            'patternConfidence': pattern_info.get('patternConfidence', 'medium'),
            'patternExamples': pattern_info.get('examples', []),
            'patternSources': pattern_info.get('sources', []),
            'verifiedAssociations': pattern_info.get('verifiedAssociations', []),
            'isExactPublished': False,
            'verificationMethod': 'PATTERN_INFERENCE',
            'emailVerificationState': 'PATTERN_GENERATED',
            'mailboxVerification': 'UNVERIFIED'
        }

    return {
        'email': '',
        'emailDomain': clean_domain,
        'emailStatus': 'NOT_FOUND',
        'status': 'not_found',
        'confidenceScore': 0,
        'sourceType': 'None',
        'patternUsed': 'none',
        'patternConfidence': 'none',
        'patternExamples': [],
        'patternSources': [],
        'verifiedAssociations': [],
        'isExactPublished': False,
        'verificationMethod': 'None',
        'emailVerificationState': 'NOT_FOUND',
        'mailboxVerification': 'UNVERIFIED'
    }

def rank_decision_makers(candidates: list = None, company: dict = None, research: dict = None) -> list[dict]:
    if not candidates:
        return []
    if company is None: company = {}
    if research is None: research = {}

    ranked = []
    role_priority = {
        'ceo': 100, 'founder': 98, 'co_founder': 97, 'president': 95,
        'managing_director': 92, 'coo': 90, 'cto': 88, 'head_of_ai': 86,
        'cdo': 85, 'cio': 84, 'head_of_data': 82, 'head_of_technology': 80,
        'head_of_operations': 78, 'cfo': 75, 'head_of_product': 74,
        'head_of_sales': 72, 'vp': 70, 'director': 68, 'dept_head': 65,
        'lead': 55, 'manager': 50, 'other': 40, 'general': 10
    }

    for c in candidates:
        rc = c.get('roleCategory', 'other')
        base_score = role_priority.get(rc, 40)
        conf = c.get('confidenceScore', 80)
        overall = int((base_score * 0.6) + (conf * 0.4))

        item = dict(c)
        item['relevanceScore'] = base_score
        item['overallScore'] = overall
        ranked.append(item)

    ranked.sort(key=lambda x: -x.get('overallScore', 0))
    if ranked:
        ranked[0]['isPrimaryDecisionMaker'] = True
    return ranked

def extract_direct_signals(pages: list = None) -> dict:
    if not pages:
        return {'emails': [], 'phones': [], 'names': []}

    email_set = set()
    phone_set = set()
    email_regex = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', re.I)
    mailto_regex = re.compile(r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', re.I)
    phone_regex = re.compile(r'\+?[0-9]{1,3}[-.\s]?\(?[0-9]{2,4}\)?[-.\s]?[0-9]{3,4}[-.\s]?[0-9]{3,4}')

    for p in pages:
        content = (p.get('content') or '') + ' ' + (p.get('html') or '')
        for em in email_regex.findall(content):
            email_set.add(em.strip(".,;:()[]{}<>\"'").lower())
        for em in mailto_regex.findall(content):
            email_set.add(em.strip(".,;:()[]{}<>\"'").lower())
        # Cloudflare data-cfemail
        for code in re.findall(r'data-cfemail=["\']([a-fA-F0-9]+)["\']', content):
            dec = decode_cloudflare_email(code)
            if dec and '@' in dec:
                email_set.add(dec.strip(".,;:()[]{}<>\"'").lower())
        for code in re.findall(r'/cdn-cgi/l/email-protection#([a-fA-F0-9]+)', content):
            dec = decode_cloudflare_email(code)
            if dec and '@' in dec:
                email_set.add(dec.strip(".,;:()[]{}<>\"'").lower())
        for ph in phone_regex.findall(content):
            if len(ph.strip()) >= 7:
                phone_set.add(ph.strip())

    return {
        'emails': list(email_set),
        'phones': list(phone_set)
    }

async def extract_contacts_from_website(company_id: str, return_diagnostics: bool = False, enable_phase2: bool = False):
    db = get_db()
    cid = to_object_id(company_id)
    if not cid:
        raise HTTPException(status_code=400, detail="Invalid company ID")

    company = await db.companies.find_one({"_id": cid})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    company_name = company.get('companyName') or company.get('name') or ''
    raw_website = company.get('website') or company.get('officialDomain') or company.get('normalizedWebsite') or ''
    clean_domain = re.sub(r'^https?://', '', raw_website, flags=re.I)
    clean_domain = re.sub(r'^www\.', '', clean_domain, flags=re.I).split('/')[0].strip().lower()

    pages_cursor = db.crawledpages.find({"companyId": cid, "crawlStatus": "completed"}).sort([("pageType", 1), ("wordCount", -1)]).limit(50)
    pages = await pages_cursor.to_list(length=50)

    has_valid_content = any(len((p.get('html') or p.get('content') or '').strip()) > 50 for p in pages)
    if (not pages or not has_valid_content) and raw_website:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
        from urllib.parse import urljoin, urlparse
        from bs4 import BeautifulSoup
        seed_paths = [
            '/', '/about', '/about-us', '/team', '/our-team', '/leadership',
            '/leadership-team', '/management', '/board', '/board-of-directors',
            '/directors', '/executives', '/executive-team', '/people',
            '/contact', '/contact-us', '/investor', '/investors',
            '/corporate', '/governance', '/company/leadership-team',
            '/impressum', '/impressum/', '/de/impressum', '/de/impressum/',
            '/legal', '/legal-notice', '/imprint', '/company/team', '/about/team'
        ]
        discovered_urls = []
        fetched_urls = set()
        pages = []  # reset empty/corrupt pages with fresh fetch
        async with httpx.AsyncClient(verify=False, timeout=3.5) as client:
            for p in seed_paths:
                try:
                    u = urljoin(raw_website, p)
                    if u in fetched_urls:
                        continue
                    fetched_urls.add(u)
                    resp = await client.get(u, headers=headers, follow_redirects=True)
                    if resp.status_code == 200 and len(resp.text) > 200:
                        is_legal = any(k in str(resp.url).lower() for k in ['impressum', 'legal', 'imprint'])
                        pages.append({'url': str(resp.url), 'html': resp.text, 'content': resp.text, 'pageType': 'impressum' if is_legal else 'leadership'})
                        
                        # Extract internal leadership and footer links from page
                        soup = BeautifulSoup(resp.text, 'html.parser')
                        
                        # Search all links, giving special priority to footer elements
                        footer_links = []
                        for footer_el in soup.find_all(['footer', 'div', 'section'], class_=re.compile(r'footer', re.I)) + soup.find_all(['footer', 'div', 'section'], id=re.compile(r'footer', re.I)):
                            for a in footer_el.find_all('a', href=True):
                                footer_links.append(a)
                        
                        all_candidate_links = footer_links + soup.find_all('a', href=True)
                        for a in all_candidate_links:
                            href = a['href']
                            full_url = urljoin(str(resp.url), href)
                            if urlparse(full_url).netloc.lower().replace('www.', '') == clean_domain:
                                link_text = (a.get_text() or '').lower()
                                link_href = href.lower()
                                high_priority_keywords = ['impressum', 'imprint', 'legal', 'geschaeftsfuehrer', 'leadership', 'board', 'director', 'team', 'management', 'executive', 'governance', 'about-us', 'our-team', 'people', 'founder']
                                if any(k in link_href or k in link_text for k in high_priority_keywords):
                                    if full_url not in fetched_urls and full_url not in discovered_urls:
                                        if any(k in link_href or k in link_text for k in ['impressum', 'legal', 'leadership', 'board', 'director', 'management', 'team']):
                                            discovered_urls.insert(0, full_url)
                                        else:
                                            discovered_urls.append(full_url)
                except Exception:
                    pass

            # Fetch up to 8 dynamically discovered internal leadership/legal links
            for du in discovered_urls[:8]:
                if du in fetched_urls:
                    continue
                fetched_urls.add(du)
                try:
                    resp = await client.get(du, headers=headers, follow_redirects=True)
                    if resp.status_code == 200 and len(resp.text) > 200:
                        is_legal = any(k in str(resp.url).lower() for k in ['impressum', 'legal', 'imprint'])
                        pages.append({'url': str(resp.url), 'html': resp.text, 'content': resp.text, 'pageType': 'impressum' if is_legal else 'leadership'})
                except Exception:
                    pass

        # Persist valid crawled pages to MongoDB so future calls don't re-crawl
        for p in pages:
            try:
                await db.crawledpages.update_one(
                    {"companyId": cid, "url": p["url"]},
                    {"$set": {
                        "companyId": cid,
                        "url": p["url"],
                        "html": p["html"],
                        "content": p["content"],
                        "pageType": p["pageType"],
                        "crawlStatus": "completed",
                        "updatedAt": datetime.now(timezone.utc)
                    }},
                    upsert=True
                )
            except Exception:
                pass

    direct_signals = extract_direct_signals(pages)
    phase1_diagnostics = {
        "pages_crawled": len(pages),
        "leadership_pages_found": [p.get("url") for p in pages if p.get("url")],
        "candidates_extracted": 0,
        "candidates_validated": 0,
        "rejected_reasons": {
            "historical_role": 0,
            "organization_as_name": 0,
            "invalid_person_name": 0,
            "other_company_role": 0,
            "no_name_in_evidence": 0
        },
        "execution_time_ms": 0
    }

    # Concurrently start MX check and official website decision maker discovery (strictly NO DuckDuckGo, NO Wikipedia)
    mx_task = check_domain_mx(clean_domain)
    decision_engine_task = discover_official_website_decision_makers(
        company_name=company_name,
        website=raw_website,
        crawled_pages=pages,
        direct_emails=direct_signals.get('emails', []),
        max_decision_makers=6,
        diagnostics=phase1_diagnostics
    )

    engine_res, mx_res = await asyncio.gather(decision_engine_task, mx_task, return_exceptions=True)
    candidates = list(engine_res) if isinstance(engine_res, list) else []
    mx_check = mx_res if isinstance(mx_res, dict) else {'mxStatus': 'UNKNOWN', 'mxProvider': ''}
    mx_status = mx_check.get('mxStatus', 'UNKNOWN')

    # Phase 2 Email Discovery & Pattern Detection
    if enable_phase2:
        if not candidates:
            # Phase 1 found zero candidates on official crawled pages.
            # Perform external public web discovery to find decision makers:
            external_candidates = search_duckduckgo_multi_round(company_name, raw_website, [], target=6)
            deduped_ext = dedupe_candidates(external_candidates)
            valid_ext = validate_all_candidates(deduped_ext, company_name, raw_website)
            if valid_ext:
                ranked_ext = rank_candidates_with_ollama(valid_ext, company_name, 6)
                candidates = final_safety_filter(ranked_ext, company_name, raw_website, 6)

        if candidates:
            candidates = await discover_decision_maker_emails(
                candidates=candidates,
                company_name=company_name,
                website=raw_website,
                crawled_pages=pages,
                direct_emails=direct_signals.get('emails', []),
                mx_status=mx_status
            )

    research = await db.companyresearches.find_one({"companyId": cid}) or {}
    now = datetime.now(timezone.utc)
    discovered = []

    # Map candidate objects from decision_maker_engine to full Contact document schema
    for c in candidates:
        name = c.get('name', '').strip()
        if not name:
            continue
        role = c.get('role', 'Executive').strip()
        role_info = categorize_role(role)
        source_type = c.get('source_type', 'official_website')
        evidence_tier = 'tier1' if source_type == 'official_website' else 'tier2'
        source_url = c.get('source_url') or raw_website

        # Strict Final Email Status Priority Resolution
        # Case 1: Exact email exists -> EXACT_FOUND
        # Case 2: Generated email exists and exact does not -> PATTERN_GENERATED
        # Case 3: Neither exists -> NOT_FOUND, email = None

        exact_email = c.get('exact_email')
        if not exact_email and (c.get('email_status') == 'EXACT_FOUND' or c.get('emailStatus') == 'EXACT_FOUND' or c.get('isExactPublished')):
            exact_email = c.get('email')
        if exact_email and isinstance(exact_email, str) and is_valid_email_format(exact_email):
            exact_email = exact_email.strip()
        else:
            exact_email = None

        generated_email = None
        if not exact_email:
            if c.get('email_status') == 'PATTERN_GENERATED' or c.get('emailStatus') == 'PATTERN_GENERATED' or c.get('email_verification') == 'PATTERN_INFERENCE':
                cand_gen = c.get('email')
                if cand_gen and isinstance(cand_gen, str) and is_valid_email_format(cand_gen):
                    generated_email = cand_gen.strip()
                else:
                    generated_email = None

        if exact_email:
            # Phase 3 requirement: Store a source URL and supporting evidence for every email marked EXACT_FOUND.
            # If evidence is missing, do not mark it EXACT_FOUND.
            evidence_snippet = c.get('email_evidence') or c.get('evidence') or ''
            has_source_url = bool(source_url and str(source_url).strip() and str(source_url).strip() != 'about:blank')
            has_valid_evidence = bool(
                (isinstance(evidence_snippet, str) and len(evidence_snippet.strip()) >= 5) or
                (isinstance(evidence_snippet, dict) and bool(evidence_snippet))
            )

            if has_source_url and has_valid_evidence:
                final_email = exact_email
                email_status = 'EXACT_FOUND'
                status = 'verified'
                is_exact = True
                mailbox_verification = 'UNVERIFIED'
                verification_method = 'PUBLIC_EVIDENCE'
                conf_score = 96
                gen_pattern = 'none'
            else:
                final_email = exact_email
                email_status = 'NEEDS_REVIEW'
                status = 'needs_review'
                is_exact = False
                mailbox_verification = 'UNVERIFIED'
                verification_method = 'INSUFFICIENT_EVIDENCE'
                conf_score = 60
                gen_pattern = 'none'
                c['email_reason'] = 'Email found but lacks supporting source URL or evidence snippet'
        elif generated_email:
            final_email = generated_email
            email_status = 'PATTERN_GENERATED'
            status = 'pattern_derived'
            is_exact = False
            mailbox_verification = 'UNVERIFIED'
            verification_method = 'PATTERN_INFERENCE'
            conf_score = 80
            gen_pattern = c.get('generated_pattern') or c.get('generatedPattern') or c.get('email_pattern') or 'first.last'
        else:
            final_email = None
            cand_status = c.get('email_status') or c.get('emailStatus')
            if cand_status in ('SEARCH_TIMEOUT', 'SEARCH_UNAVAILABLE', 'DOMAIN_BLOCKED', 'NEEDS_REVIEW', 'PATTERN_INFERRED'):
                email_status = cand_status
            else:
                email_status = 'NOT_FOUND'
            status = 'not_found'
            is_exact = False
            mailbox_verification = 'UNVERIFIED'
            verification_method = 'NONE'
            conf_score = 0
            gen_pattern = 'none'

        pat_conf = c.get('pattern_confidence') or c.get('patternConfidence') or 'none'
        email_reason = c.get('email_reason') or c.get('emailReason') or (
            'Verified in public source' if email_status == 'EXACT_FOUND' else (
                'Inferred from verified company email pattern' if email_status in ('PATTERN_GENERATED', 'PATTERN_INFERRED') else (
                    'Search timed out within configured limit' if email_status == 'SEARCH_TIMEOUT' else (
                        'Public search service rate-limited or unavailable' if email_status == 'SEARCH_UNAVAILABLE' else (
                            'Target website blocked crawling' if email_status == 'DOMAIN_BLOCKED' else (
                                'Requires manual review' if email_status == 'NEEDS_REVIEW' else
                                'Discovery completed but no public email was found'
                            )
                        )
                    )
                )
            )
        )

        doc = {
            'companyId': cid,
            'name': name,
            'title': role,
            'designation': role,
            'cleanTitle': role_info.get('cleanTitle', role),
            'candidateEmployer': company_name,
            'roleCategory': role_info['roleCategory'],
            'seniority': role_info['seniority'],
            'department': 'Executive',
            'email': final_email,
            'emailDomain': c.get('email_domain') or clean_domain,
            'emailStatus': email_status,
            'email_status': email_status,
            'emailReason': email_reason,
            'email_reason': email_reason,
            'status': status,
            'mailboxVerification': mailbox_verification,
            'emailVerificationMethod': verification_method,
            'email_verification': verification_method,
            'isExactPublished': is_exact,
            'source': source_url if source_url != raw_website else 'Official Website',
            'sourceType': source_type,
            'evidenceTier': evidence_tier,
            'sourceUrl': source_url,
            'isCurrentRole': 'confirmed_current',
            'confidenceScore': conf_score,
            'evidence': {
                'personEvidence': c.get('evidence', ''),
                'roleEvidence': f"Role: {role}",
                'emailEvidence': c.get('email_evidence', ''),
                'snippet': c.get('evidence', '')
            },
            'patternUsed': gen_pattern,
            'generatedPattern': gen_pattern,
            'patternConfidence': pat_conf,
            'pattern_confidence': pat_conf,
            'patternEvidence': c.get('pattern_evidence', []),
            'patternsObserved': c.get('patterns_observed', []),
            'patternExamples': [e['email'] for e in c.get('pattern_evidence', []) if isinstance(e, dict) and e.get('email')] or ([final_email] if final_email else []),
            'patternSources': [e['source_url'] for e in c.get('pattern_evidence', []) if isinstance(e, dict) and e.get('source_url')] or ([c.get('email_evidence', '')] if c.get('email_evidence') else []),
            'mxStatus': c.get('mx_status') or mx_check.get('mxStatus', 'UNKNOWN'),
            'mxProvider': mx_check.get('mxProvider', ''),
            'emailPattern': gen_pattern,
            'searchStatus': c.get('search_status', 'COMPLETED'),
            'searchAttempts': c.get('search_attempts', 0),
            'sourcesChecked': c.get('sources_checked', []),
            'searchError': c.get('search_error'),
            'decisionMakerStatus': 'VERIFIED',
            'discoveredAt': now,
            'updatedAt': now
        }
        discovered.append(doc)

    # Fallback 1: Company imported contact name only if real identifiable person and zero discovered
    if not discovered and company.get('contactName'):
        imported_name = company.get('contactName').strip()
        if is_strict_person_name(imported_name, company_name):
            role_info = categorize_role('Executive Leadership')
            raw_imported_email = company.get('contactEmail')
            imported_email = raw_imported_email.strip() if (raw_imported_email and isinstance(raw_imported_email, str) and is_valid_email_format(raw_imported_email)) else None
            has_imported_email = bool(imported_email)
            discovered.append({
                'companyId': cid,
                'name': imported_name,
                'designation': 'Executive Leadership',
                'title': 'Executive Leadership',
                'cleanTitle': 'Executive Leadership',
                'candidateEmployer': company_name,
                'roleCategory': role_info['roleCategory'],
                'seniority': role_info['seniority'],
                'department': 'Executive',
                'email': imported_email,
                'emailDomain': clean_domain,
                'emailStatus': 'EXACT_FOUND' if has_imported_email else 'NOT_FOUND',
                'status': 'verified' if has_imported_email else 'not_found',
                'mailboxVerification': 'UNVERIFIED',
                'emailVerificationMethod': 'Direct Input' if has_imported_email else 'NONE',
                'isExactPublished': has_imported_email,
                'source': 'Imported Record',
                'sourceType': 'excel_import',
                'evidenceTier': 'tier1',
                'sourceUrl': raw_website,
                'isCurrentRole': 'confirmed_current',
                'confidenceScore': 90 if has_imported_email else 50,
                'evidence': {
                    'personEvidence': f"{imported_name} listed in company profile records",
                    'roleEvidence': 'Executive Leadership',
                    'emailEvidence': imported_email or '',
                    'snippet': imported_name
                },
                'patternUsed': 'none',
                'patternConfidence': 'none',
                'patternExamples': [imported_email] if imported_email else [],
                'patternSources': ['Imported Record'] if imported_email else [],
                'mxStatus': mx_check.get('mxStatus', 'UNKNOWN'),
                'mxProvider': mx_check.get('mxProvider', ''),
                'decisionMakerStatus': 'VERIFIED',
                'discoveredAt': now,
                'updatedAt': now
            })

    # Upsert discovered candidates into db.contacts
    saved_contacts = []
    for item in discovered:
        query = {"companyId": cid, "name": item['name']}
        update_doc = {"$set": item, "$setOnInsert": {"createdAt": now}}
        await db.contacts.update_one(query, update_doc, upsert=True)
        saved = await db.contacts.find_one(query)
        if saved:
            saved_contacts.append(saved)

    # Rank decision makers and set isPrimaryDecisionMaker on #1
    ranked = rank_decision_makers(saved_contacts, company, research)
    for rc in ranked:
        if rc.get('_id'):
            await db.contacts.update_one(
                {"_id": rc['_id']},
                {"$set": {
                    "isPrimaryDecisionMaker": rc.get('isPrimaryDecisionMaker', False),
                    "overallScore": rc.get('overallScore', 80),
                    "relevanceScore": rc.get('relevanceScore', 75)
                }}
            )

    # D8: Structured purge of fabricated/synthetic contacts (replaces the old
    # blanket regex delete_many). A contact is removed ONLY when BOTH:
    #   (a) it was NOT produced by this discovery run (real discovered
    #       executives are never swept up), AND
    #   (b) its name/evidence matches fabrication markers (placeholder initials,
    #       role-label-as-name, or LLM filler text "is verified as" / corporate
    #       channel boilerplate).
    saved_names = {c.get('name') for c in saved_contacts if c.get('name')}
    synthetic_name_pats = [
        re.compile(r"\s+[A-Z]$"),                          # single-initial placeholder, e.g. "John D"
        re.compile(r"Executive Officer$|Technology Officer$|Officer$", re.I),
        re.compile(r"Lead$|Leadership$|Management$", re.I),
        re.compile(r"Architect$", re.I),
        re.compile(r"^Global Managing Director$", re.I),
    ]
    synthetic_evidence_pat = re.compile(r"is verified as|Corporate leadership channel", re.I)

    existing_cursor = db.contacts.find({"companyId": cid})
    existing_contacts = await existing_cursor.to_list(length=250)
    purge_ids = []
    for ex in existing_contacts:
        ex_name = ex.get('name') or ''
        if ex_name in saved_names:
            continue
        is_synth = any(p.search(ex_name) for p in synthetic_name_pats)
        if not is_synth:
            ev = ex.get('evidence') or {}
            snippet = ev.get('snippet') or '' if isinstance(ev, dict) else ''
            person_ev = ev.get('personEvidence') or '' if isinstance(ev, dict) else ''
            is_synth = bool(synthetic_evidence_pat.search(snippet) or synthetic_evidence_pat.search(person_ev))
        if is_synth and ex.get('_id'):
            purge_ids.append(ex['_id'])
    if purge_ids:
        await db.contacts.delete_many({"_id": {"$in": purge_ids}})

    if db is not None:
        await db.companyresearches.update_one(
            {"companyId": cid},
            {"$set": {"phase1Diagnostics": phase1_diagnostics, "updatedAt": now}},
            upsert=True
        )

    all_contacts_cursor = db.contacts.find({"companyId": cid})
    all_contacts = await all_contacts_cursor.to_list(length=100)
    if return_diagnostics:
        return serialize_doc(all_contacts), phase1_diagnostics
    return serialize_doc(all_contacts)

async def get_company_contacts(company_id: str = None):
    db = get_db()
    query = {}
    cid = None
    if company_id:
        cid = to_object_id(company_id)
        if cid:
            query["companyId"] = cid
    cursor = db.contacts.find(query).sort("overallScore", -1)
    contacts = await cursor.to_list(length=100)

    # D4: GET /contacts is strictly read-only. Automatic extraction on read was
    # removed because any read-only view (reports, dashboards, polling) must not
    # trigger expensive crawls or mutate the collection. Use the explicit
    # POST /companies/{company_id}/contacts/discover endpoint instead.
    return serialize_doc(contacts)

async def create_contact(company_id: str, data: dict):
    db = get_db()
    cid = to_object_id(company_id)
    if not cid:
        raise HTTPException(status_code=400, detail="Invalid company ID")

    now = datetime.now(timezone.utc)
    doc = dict(data)
    doc['companyId'] = cid
    doc['createdAt'] = now
    doc['updatedAt'] = now

    role_info = categorize_role(doc.get('title', '') or doc.get('designation', ''))
    doc['roleCategory'] = doc.get('roleCategory') or role_info['roleCategory']
    doc['seniority'] = doc.get('seniority') or role_info['seniority']

    res = await db.contacts.insert_one(doc)
    doc['_id'] = res.inserted_id
    return serialize_doc(doc)

async def update_contact(contact_id: str, data: dict):
    db = get_db()
    cid = to_object_id(contact_id)
    if not cid:
        raise HTTPException(status_code=400, detail="Invalid contact ID")

    now = datetime.now(timezone.utc)
    update_fields = dict(data)
    update_fields['updatedAt'] = now

    if 'title' in update_fields or 'designation' in update_fields:
        t = update_fields.get('title') or update_fields.get('designation')
        role_info = categorize_role(t)
        update_fields['roleCategory'] = update_fields.get('roleCategory') or role_info['roleCategory']
        update_fields['seniority'] = update_fields.get('seniority') or role_info['seniority']

    await db.contacts.update_one({"_id": cid}, {"$set": update_fields})
    updated = await db.contacts.find_one({"_id": cid})
    if not updated:
        raise HTTPException(status_code=404, detail="Contact not found")
    return serialize_doc(updated)

async def delete_contact(contact_id: str):
    db = get_db()
    cid = to_object_id(contact_id)
    if not cid:
        raise HTTPException(status_code=400, detail="Invalid contact ID")

    res = await db.contacts.delete_one({"_id": cid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"message": "Contact deleted successfully"}

async def verify_contact_email(contact_id: str):
    db = get_db()
    cid = to_object_id(contact_id)
    if not cid:
        raise HTTPException(status_code=400, detail="Invalid contact ID")

    contact = await db.contacts.find_one({"_id": cid})
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    email = contact.get('email')
    if not email:
        raise HTTPException(status_code=400, detail="Contact has no email to verify")

    company = await db.companies.find_one({"_id": contact['companyId']})
    domain = (company.get('website') if company else '').split('/')[0]
    mx_check = await check_domain_mx(domain)

    now = datetime.now(timezone.utc)
    # Domain MX is separate from individual mailbox verification
    is_exact = contact.get('isExactPublished', False) or contact.get('emailStatus') == 'EXACT_FOUND' or contact.get('email_status') == 'EXACT_FOUND'
    if not email:
        email_status = 'NOT_FOUND'
    elif is_exact:
        email_status = 'EXACT_FOUND'
    else:
        email_status = 'PATTERN_GENERATED'

    await db.contacts.update_one(
        {"_id": cid},
        {"$set": {
            "emailStatus": email_status,
            "email_status": email_status,
            "status": "verified" if is_exact else "pattern_derived",
            "mailboxVerification": "UNVERIFIED",
            "mxStatus": mx_check.get('mxStatus', 'UNKNOWN'),
            "mxProvider": mx_check.get('mxProvider', ''),
            "lastVerifiedAt": now,
            "updatedAt": now
        }}
    )

    updated = await db.contacts.find_one({"_id": cid})
    return serialize_doc(updated)

async def get_company_email_pattern_info(company_id: str):
    db = get_db()
    cid = to_object_id(company_id)
    if not cid:
        raise HTTPException(status_code=400, detail="Invalid company ID")

    company = await db.companies.find_one({"_id": cid})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    clean_domain = re.sub(r'^https?://', '', company.get('website', ''))
    clean_domain = re.sub(r'^www\.', '', clean_domain).split('/')[0].lower()

    # Fast path: check if existing contacts already have resolved pattern info
    existing_contacts = await db.contacts.find({"companyId": cid}).to_list(length=50)
    for c in existing_contacts:
        pat = c.get("generatedPattern")
        if pat and pat != "none":
            pat_conf = c.get("patternConfidence", "INSUFFICIENT")
            return {
                'pattern': pat,
                'detectedPattern': pat,
                'confidence': 90 if pat_conf == "SUPPORTED" else 65,
                'patternConfidence': pat_conf,
                'evidence': [c.get("email")] if c.get("email") else [],
                'examples': [c.get("email")] if c.get("email") else [],
                'sources': ['Discovered Pattern'],
                'emailDomain': c.get('emailDomain') or clean_domain,
                'status': 'PATTERN_VERIFIED' if pat_conf == 'SUPPORTED' else 'LIKELY'
            }

    if existing_contacts and all((c.get("emailStatus") or c.get("email_status")) == "NOT_FOUND" for c in existing_contacts):
        return {
            'pattern': None,
            'detectedPattern': None,
            'confidence': 0,
            'patternConfidence': 'none',
            'evidence': [],
            'examples': [],
            'sources': [],
            'emailDomain': clean_domain or '',
            'status': 'NOT_FOUND'
        }

    direct_emails = []
    try:
        pages_cursor = db.crawledpages.find({"companyId": cid, "crawlStatus": "completed"})
        pages = await pages_cursor.to_list(length=10)
        signals = extract_direct_signals(pages)
        direct_emails = signals.get('emails', [])
    except Exception:
        pass

    pattern_info = await discover_company_email_pattern(cid, company.get('companyName'), clean_domain, direct_emails)
    if not pattern_info or not pattern_info.get('pattern'):
        return {
            'pattern': None,
            'detectedPattern': None,
            'confidence': 0,
            'patternConfidence': 'none',
            'evidence': [],
            'examples': [],
            'sources': [],
            'emailDomain': clean_domain or '',
            'status': 'NOT_FOUND'
        }

    return {
        'pattern': pattern_info['pattern'],
        'detectedPattern': pattern_info['pattern'],
        'confidence': pattern_info.get('confidence', 0),
        'patternConfidence': pattern_info.get('patternConfidence', 'medium'),
        'evidence': pattern_info.get('examples', []),
        'examples': pattern_info.get('examples', []),
        'sources': pattern_info.get('sources', []),
        'emailDomain': pattern_info.get('emailDomain') or clean_domain,
        'status': 'PATTERN_VERIFIED' if pattern_info.get('confidence', 0) >= 80 else 'LIKELY'
    }

async def apply_pattern_to_contacts(company_id: str, selected_pattern: str):
    db = get_db()
    cid = to_object_id(company_id)
    if not cid:
        raise HTTPException(status_code=400, detail="Invalid company ID")

    company = await db.companies.find_one({"_id": cid})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    clean_domain = re.sub(r'^https?://', '', company.get('website', ''))
    clean_domain = re.sub(r'^www\.', '', clean_domain).split('/')[0].lower()

    contacts_cursor = db.contacts.find({"companyId": cid})
    contacts = await contacts_cursor.to_list(length=100)
    updated_contacts = []
    now = datetime.now(timezone.utc)

    for c in contacts:
        if c.get('roleCategory') == 'general' or c.get('seniority') == 'general':
            continue
        if c.get('emailStatus') in ('DIRECTLY_VERIFIED', 'EXACT_SOURCE_VERIFIED'):
            continue

        generated = generate_candidate_email(c.get('name', ''), selected_pattern, clean_domain)
        if generated:
            await db.contacts.update_one(
                {"_id": c['_id']},
                {"$set": {
                    "email": generated,
                    "emailPattern": selected_pattern,
                    "patternUsed": selected_pattern,
                    "emailStatus": "PATTERN_BASED_UNVERIFIED",
                    "status": "pattern_derived",
                    "emailDomain": clean_domain,
                    "emailVerificationMethod": "Company Email Pattern Inference",
                    "updatedAt": now
                }}
            )
            c['email'] = generated
            updated_contacts.append(c)

    return {"success": True, "contacts": serialize_doc(updated_contacts)}
