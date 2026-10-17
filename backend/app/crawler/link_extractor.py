import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from app.crawler.url_utils import extract_domain, resolve_url, filter_same_domain_links, is_same_domain

LEADERSHIP_KEYWORDS = [
    'leadership', 'management', 'team', 'our team', 'about us', 'about',
    'company', 'board', 'board of directors', 'directors', 'director', 'management team',
    'executive team', 'executives', 'executive', 'key management', 'key people',
    'leadership team', 'senior management', 'founders', 'founding team',
    'our people', 'who we are', 'governance', 'corporate governance',
    'investor relations', 'investors', 'investor', 'annual report', 'management discussion',
    'corporate profile', 'corporate', 'contact', 'contact-us', 'contact us',
    'careers', 'press', 'media', 'news', 'people', 'our-team', 'management-team',
    'leadership-team', 'nodal', 'compliance', 'secretary', 'kmp',
    'impressum', 'imprint', 'legal', 'legal-notice', 'gesetzliche-angaben'
]

AVOID_PATTERNS = [
    re.compile(p, re.I) for p in [
        r'/(login|signin|signup|auth|register|account|user|profile/edit|my-account)',
        r'/(cart|checkout|basket|shop|store|order|billing|pay)',
        r'/(search|query|find)',
        r'/(tag|author|wp-json|xmlrpc|feed)',
        r'/(careers/apply|jobs/apply|vacancies/apply|job-openings)',
    ]
]

KNOWN_LEADERSHIP_PATHS = [
    '/about', '/about-us', '/leadership', '/leadership-team',
    '/management', '/management-team', '/our-team', '/team',
    '/board', '/board-of-directors', '/directors', '/key-management',
    '/our-people', '/people', '/governance', '/corporate-governance',
    '/executives', '/executive-team', '/corporate', '/investor',
    '/investors', '/contact', '/contact-us', '/investor/contacts',
    '/investors/contact', '/investor-relations', '/company',
    '/company/team', '/company/leadership-team',
    '/impressum', '/impressum/', '/de/impressum', '/de/impressum/',
    '/legal', '/legal-notice', '/imprint'
]

def is_avoided_url(url: str) -> bool:
    if not url:
        return True
    lower = url.lower()
    if any(p.search(lower) for p in AVOID_PATTERNS):
        return True
    blocked_exts = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico',
                    '.mp4', '.mp3', '.zip', '.rar', '.xlsx', '.xls', '.doc',
                    '.docx', '.ppt', '.pptx', '.pdf', '.css', '.js')
    clean_path = lower.split('?')[0].split('#')[0]
    return clean_path.endswith(blocked_exts)

def extract_links_with_metadata(html: str, base_url: str) -> list[dict]:
    if not html:
        return []
    base_domain = extract_domain(base_url)
    results = []
    seen = set()
    soup = BeautifulSoup(html, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if (not href or
            href.startswith("#") or
            href.startswith("javascript:") or
            href.startswith("mailto:") or
            href.startswith("tel:")):
            continue

        absolute = resolve_url(base_url, href)
        if not absolute or not is_same_domain(absolute, base_domain):
            continue

        clean_url = absolute.split('#')[0].rstrip('/')
        if not clean_url or clean_url in seen or is_avoided_url(clean_url):
            continue

        seen.add(clean_url)
        anchor_text = a.get_text(" ", strip=True)
        title_attr = a.get("title", "")
        aria_label = a.get("aria-label", "")

        combined_text = f"{anchor_text} {title_attr} {aria_label} {urlparse(clean_url).path}".lower()
        is_leadership = any(kw in combined_text for kw in LEADERSHIP_KEYWORDS)

        priority = 30
        if is_leadership:
            if any(k in combined_text for k in ['leadership', 'board', 'director', 'directors', 'management', 'executive', 'executives', 'founder', 'founders', 'kmp']):
                priority = 100
            elif any(k in combined_text for k in ['investor', 'investors', 'governance', 'team', 'our-team', 'people', 'contact', 'secretary', 'nodal']):
                priority = 85
            elif any(k in combined_text for k in ['about', 'corporate', 'company', 'annual-report', 'media', 'press', 'news']):
                priority = 75
            else:
                priority = 60

        results.append({
            "url": clean_url,
            "anchor_text": anchor_text,
            "title": title_attr,
            "aria_label": aria_label,
            "is_leadership": is_leadership,
            "priority": priority
        })

    return results

def extract_links(html: str, base_url: str) -> list[str]:
    links_with_meta = extract_links_with_metadata(html, base_url)
    # Sort by priority descending
    links_with_meta.sort(key=lambda x: -x["priority"])
    return [item["url"] for item in links_with_meta]
