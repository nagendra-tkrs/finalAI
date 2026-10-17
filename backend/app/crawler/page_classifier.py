import re

RULES = [
    {
        'patterns': [
            re.compile(p, re.I) for p in [
                r'/team', r'/our-team', r'/leadership', r'/management', r'/board',
                r'/people', r'/executives', r'/founders', r'/advisors', r'/staff',
                r'/who-we-are/leadership', r'/company/team', r'/about/team',
                r'/about-us/leadership', r'/meet-the-team', r'/bio/', r'/profile/',
                r'/impressum', r'/imprint', r'/legal-notice', r'/gesetzliche-angaben'
            ]
        ],
        'type': 'leadership'
    },
    {
        'patterns': [
            re.compile(p, re.I) for p in [
                r'/about', r'/company', r'/our-story', r'/who-we-are', r'/overview', r'/history'
            ]
        ],
        'type': 'about'
    },
    {
        'patterns': [
            re.compile(p, re.I) for p in [
                r'/contact', r'/get-in-touch', r'/reach-us', r'/connect', r'/locations', r'/office'
            ]
        ],
        'type': 'contact'
    },
    {
        'patterns': [
            re.compile(p, re.I) for p in [
                r'/service', r'/what-we-do', r'/solutions', r'/offerings', r'/capabilities'
            ]
        ],
        'type': 'services'
    },
    {
        'patterns': [
            re.compile(p, re.I) for p in [
                r'/product', r'/platform', r'/catalog', r'/features', r'/technology'
            ]
        ],
        'type': 'products'
    },
    {
        'patterns': [re.compile(p, re.I) for p in [r'/industr', r'/sector', r'/verticals']],
        'type': 'industries'
    },
    {
        'patterns': [re.compile(p, re.I) for p in [r'/customer', r'/client', r'/partner', r'/ecosystem']],
        'type': 'customers'
    },
    {
        'patterns': [re.compile(p, re.I) for p in [r'/case-stud', r'/success-stor', r'/portfolio', r'/work/', r'/projects']],
        'type': 'case-study'
    },
    {
        'patterns': [re.compile(p, re.I) for p in [r'/pricing', r'/plan', r'/cost', r'/quote']],
        'type': 'pricing'
    },
    {
        'patterns': [re.compile(p, re.I) for p in [r'/career', r'/job', r'/hiring', r'/recruit', r'/join-us']],
        'type': 'careers'
    },
    {
        'patterns': [re.compile(p, re.I) for p in [r'/blog', r'/news', r'/article', r'/post', r'/press', r'/media']],
        'type': 'blog'
    },
    {
        'patterns': [re.compile(p, re.I) for p in [r'/resource', r'/guide', r'/whitepaper', r'/ebook', r'/webinar']],
        'type': 'resources'
    },
    {
        'patterns': [re.compile(p, re.I) for p in [r'/faq', r'/help', r'/support', r'/knowledge-base']],
        'type': 'support'
    },
    {
        'patterns': [re.compile(p, re.I) for p in [r'/privacy', r'/terms', r'/legal', r'/policy', r'/cookie', r'/disclaimer']],
        'type': 'legal'
    }
]

def classify_page(url: str, title: str = '', content: str = '') -> str:
    url_lower = (url or '').lower()
    title_lower = (title or '').lower()

    for rule in RULES:
        if any(p.search(url_lower) for p in rule['patterns']):
            return rule['type']

    if ('team' in title_lower or 'leadership' in title_lower or 'founder' in title_lower or
        'executive' in title_lower or 'board of director' in title_lower):
        return 'leadership'
    if 'about' in title_lower or 'who we are' in title_lower or 'our story' in title_lower:
        return 'about'
    if 'contact' in title_lower or 'get in touch' in title_lower or 'reach out' in title_lower:
        return 'contact'
    if 'service' in title_lower or 'solution' in title_lower or 'what we do' in title_lower:
        return 'services'
    if 'product' in title_lower or 'platform' in title_lower:
        return 'products'

    return 'other'

def get_page_priority(url: str, text: str = '') -> int:
    url_lower = (url or '').lower()
    text_lower = (text or '').lower()
    combined = f"{url_lower} {text_lower}"

    if re.search(r'/(login|signin|signup|auth|register|account|cart|checkout|basket|shop|career/apply|job)', url_lower):
        return 0
    if re.search(r'(leadership|team|founder|management|board|director|executive|people|staff|who-we-are|key-management|senior-management)', combined):
        return 100
    if re.search(r'(about|about-us|company|governance|investor|corporate-profile|our-story)', combined):
        return 85
    if re.search(r'(contact|connect|office|location)', combined):
        return 70
    if re.search(r'(service|product|solution|platform|pricing)', combined):
        return 40
    if re.search(r'(case-stud|customer|portfolio|client)', combined):
        return 20
    if re.search(r'(blog|news|article|privacy|terms|legal|career|job)', combined):
        return 5
    return 30
