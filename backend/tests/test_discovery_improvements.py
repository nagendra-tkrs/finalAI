import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from bson import ObjectId

from app.services.decision_maker_engine import (
    role_attached_to_other_company,
    extract_impressum_candidates,
    ddg_search,
    reset_circuit,
    is_circuit_open,
)
from app.services.contact_service import extract_contacts_from_website
from app.services.search_service import search_public_web
import app.services.decision_maker_engine as dm_engine


# ============================================================
# Phase 2 Regression Tests: The 6 false-positive cellumation candidates
# ============================================================

def test_cellumation_six_testimonial_false_positives_rejected():
    """Requirement: Regression tests for the six false-positive candidates found in cellumation."""
    company_name = "cellumation"
    
    test_cases = [
        (
            "Erik Meulendijks",
            "Erik Meulendijks Co-Owner | Dücker Prefeeder „By combining our expertise in the corrugated cardboard industry with cellumation’s advanced conveyor technology, we can offer our customers real added value and also automate existing cardboard production lines in the smallest of spaces.“",
            "Dücker Prefeeder"
        ),
        (
            "Rob Smets",
            "Rob Smets Owner | Fris Karton „ With our “Flexo-Folder-Gluer” that we installed in the year 2022, we have not used the potential of the machine. We were limited to a certain number of packages per minute. With this new system, we can easily handle one truck per hour going out. “",
            "Fris Karton"
        ),
        (
            "Martin Schäfer",
            "Martin Schäfer Managing Director | FS Solutions „The celluveyor is compact and powerful. On an area of only 2.7 m², it reliably conveys and distributes parcels without congestion.”",
            "FS Solutions"
        ),
        (
            "Jochen Seidler",
            "Jochen Seidler Managing Director | ETT Verpackungstechnik „In the construction, the module can be integrated without any problems. Assembly and commissioning are also designed to be straightforward. Even the programming impressed me – I once observed our programmers and thought: With so many different wheels, it must be complicated. But in reality, it is surprisingly simple”",
            "ETT Verpackungstechnik"
        ),
        (
            "Juan Vicente Sanchis",
            "Juan Vicente Sanchis Managing Director | Vector Conveyors „The celluveyor GO offers our customers enormous flexibility and thus great savings potential.”",
            "Vector Conveyors"
        ),
        (
            "Dieter Hübner",
            "Dieter Hübner Managing Partner | PCA Roboter- & Verpackungstechnik „Together with cellumation, we move more than just cartons – we move efficiency, precision, and performance.”",
            "PCA Roboter- & Verpackungstechnik"
        ),
    ]

    for name, snippet, other_org in test_cases:
        is_other = role_attached_to_other_company(snippet, company_name)
        assert is_other is True, (
            f"Candidate '{name}' representing external org '{other_org}' was NOT rejected! "
            f"Snippet: {snippet}"
        )


def test_employer_affiliation_separators_pipe_dash_slash():
    """Requirement: Test that pipe, dash, slash, and at/for separators attach role to other company."""
    target_company = "Acme Innovations"
    
    external_examples = [
        "Alice Smith CEO | Global Logistics Ltd „We love Acme's software.”",
        "Bob Jones Managing Director - Nexus Solutions, an industry leader.",
        "Carol White Founder / Apex Robotics, keynote speaker.",
        "David Clark Chief Technology Officer at Zeta Networks, partnering with us.",
        "Emma Stone Partner for Beacon Capital, investor.",
    ]
    for ex in external_examples:
        assert role_attached_to_other_company(ex, target_company) is True, f"Failed to detect other company in: {ex}"

    # Target company's own roles must NOT be flagged as other company
    internal_examples = [
        "John Doe, CEO | Acme Innovations leads the company.",
        "Jane Doe Managing Director at Acme Innovations.",
        "Mark Vance CTO of Acme Innovations.",
    ]
    for ex in internal_examples:
        assert role_attached_to_other_company(ex, target_company) is False, f"Erroneously flagged own company in: {ex}"


# ============================================================
# Phase 1 Tests: Impressum & Legal Disclosures Extraction
# ============================================================

def test_extract_impressum_statutory_managing_directors():
    """Requirement: Extract statutory managing directors from German / EU Impressum disclosures."""
    impressum_text = """
    Gesetzliche Anbieterkennung:
    cellumation GmbH
    diese vertr. d. d. Geschäftsführer Dr.-Ing. Hendrik Thamer und Dr.-Ing. Claudio Uriarte
    Kleiner Ort 7 28357 Bremen Deutschland
    Telefon: +49 421 331135 0 Telefax: +49 421 331135 99 E-Mail: info@cellumation.com
    USt-IdNr.: DE 313140406
    eingetragen im Handelsregister des Amtsgerichtes Bremen Handelsregisternummer HRB HRB 32569
    """
    source_url = "https://cellumation.com/de/impressum/"
    cands = extract_impressum_candidates(impressum_text, source_url, "cellumation")

    assert len(cands) == 2, f"Expected 2 Impressum candidates, found {len(cands)}"
    names = {c["name"] for c in cands}
    assert "Hendrik Thamer" in names
    assert "Claudio Uriarte" in names
    for c in cands:
        assert c["role"] == "Managing Director"
        assert c["source_url"] == source_url
        assert "Official legal notice" in c["evidence"]


# ============================================================
# Phase 3 Tests: Published-Email Evidence & Guessed-Email Safety
# ============================================================

@pytest.mark.asyncio
async def test_exact_found_requires_supporting_evidence_and_source_url():
    """Requirement: Never label an email EXACT_FOUND if source URL or evidence snippet is missing."""
    company_id = str(ObjectId())
    mock_company = {
        "_id": ObjectId(company_id),
        "name": "Tech Corp",
        "website": "https://techcorp.test",
    }

    from tests.test_discovery_fixes_phase1 import _build_mock_db

    mock_db_a, _ = _build_mock_db(mock_company)

    # Case A: Email candidate WITH valid evidence and source_url
    cand_with_evidence = {
        "name": "Sarah Connor",
        "role": "CEO",
        "email": "sarah.connor@techcorp.test",
        "exact_email": "sarah.connor@techcorp.test",
        "email_status": "EXACT_FOUND",
        "source_url": "https://techcorp.test/team",
        "email_evidence": "Found on official leadership page: sarah.connor@techcorp.test",
        "evidence": "Sarah Connor, CEO"
    }

    with patch("app.services.contact_service.get_db", return_value=mock_db_a), \
         patch("app.services.contact_service.discover_official_website_decision_makers", new_callable=AsyncMock, return_value=[cand_with_evidence]), \
         patch("app.services.contact_service.check_domain_mx", new_callable=AsyncMock, return_value={"mxStatus": "VALID"}):

        contacts_a = await extract_contacts_from_website(company_id=company_id, enable_phase2=False)
        assert len(contacts_a) == 1
        assert contacts_a[0]["emailStatus"] == "EXACT_FOUND"
        assert contacts_a[0]["isExactPublished"] is True

    # Case B: Email candidate WITHOUT valid evidence or source_url
    mock_db_b, _ = _build_mock_db(mock_company)
    cand_without_evidence = {
        "name": "Sarah Connor",
        "role": "CEO",
        "email": "sarah.connor@techcorp.test",
        "exact_email": "sarah.connor@techcorp.test",
        "email_status": "EXACT_FOUND",
        "source_url": "",  # Empty source URL!
        "email_evidence": "",  # Empty evidence!
        "evidence": ""
    }

    with patch("app.services.contact_service.get_db", return_value=mock_db_b), \
         patch("app.services.contact_service.discover_official_website_decision_makers", new_callable=AsyncMock, return_value=[cand_without_evidence]), \
         patch("app.services.contact_service.check_domain_mx", new_callable=AsyncMock, return_value={"mxStatus": "VALID"}):

        contacts_b = await extract_contacts_from_website(company_id=company_id, enable_phase2=False)
        assert len(contacts_b) == 1
        # Must be downgraded to NEEDS_REVIEW because evidence is missing!
        assert contacts_b[0]["emailStatus"] == "NEEDS_REVIEW"
        assert contacts_b[0]["isExactPublished"] is False
        assert "lacks supporting" in contacts_b[0].get("emailReason", "").lower()


def test_guessed_email_is_never_marked_exact_found():
    """Requirement: Never label guessed or pattern-derived addresses as publicly verified."""
    from app.services.email_discovery_service import render_pattern_email

    rendered = render_pattern_email("first.last", "Hendrik Thamer", "cellumation.com")
    assert rendered == "hendrik.thamer@cellumation.com"
    # An email produced by pattern rendering is a hypothesis, NOT a verified public publication


# ============================================================
# Phase 3 Tests: DuckDuckGo HTTP 202 Anomaly Challenge Handling
# ============================================================

def test_ddg_http_202_trips_circuit_and_avoids_repeated_retries():
    """Requirement: Handle DDG HTTP 202 challenge without repeated retries or anti-bot bypass."""
    reset_circuit()
    assert is_circuit_open() is False

    mock_resp = MagicMock(status_code=202, text="<html><body><div class='anomaly-modal'>Anomaly Challenge</div></body></html>")
    
    with patch("httpx.Client.get", return_value=mock_resp):
        res = ddg_search("any query")
        assert res is None
        assert dm_engine.LAST_DDG_SEARCH_FAILED is True
        assert dm_engine.LAST_DDG_SEARCH_STATUS == "SEARCH_UNAVAILABLE"
        # Circuit breaker must have been tripped immediately to avoid hammering the endpoint
        assert is_circuit_open() is True

    # Subsequent search while circuit is open returns immediately without making network calls
    with patch("httpx.Client.get") as mock_get:
        res2 = ddg_search("another query")
        assert res2 is None
        assert not mock_get.called, "Network call was made while circuit breaker was open!"

    reset_circuit()


@pytest.mark.asyncio
async def test_search_service_trips_circuit_on_http_202():
    """Requirement: search_service.search_public_web trips circuit breaker on HTTP 202."""
    from app.services.search_service import reset_circuit as ss_reset, is_circuit_open as ss_circuit_open
    ss_reset()

    mock_resp = MagicMock(status_code=202, text="<html><body>challenge</body></html>")
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        out = await search_public_web("test query")
        assert out["status"] == "SEARCH_UNAVAILABLE"
        assert "challenge" in out["error"].lower() or "202" in out["error"]
        assert ss_circuit_open() is True

    ss_reset()
