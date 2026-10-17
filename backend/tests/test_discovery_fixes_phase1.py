import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from bson import ObjectId

from app.services.email_validation_service import is_valid_email_format, INVALID_EMAIL_PLACEHOLDERS
from app.services.decision_maker_engine import (
    is_strict_person_name,
    looks_like_organization_name,
    decode_redirect_url,
    ddg_search,
    search_ddg_exact_person_email,
    dedupe_candidates,
    LAST_DDG_SEARCH_FAILED,
)
from app.services.contact_service import extract_contacts_from_website
from app.services.search.public_web_search_provider import reset_circuit


@pytest.fixture(autouse=True)
def _reset_circuit_before_test():
    reset_circuit()
    yield
    reset_circuit()


def _build_mock_db(mock_company, saved_contacts=None):
    mock_db = MagicMock()
    mock_db.companies.find_one = AsyncMock(return_value=mock_company)
    mock_db.companyresearches.find_one = AsyncMock(return_value={})
    mock_db.companyresearches.update_one = AsyncMock()

    # crawledpages mock
    mock_pages_cursor = MagicMock()
    mock_pages_cursor.sort.return_value = mock_pages_cursor
    mock_pages_cursor.limit.return_value = mock_pages_cursor
    mock_pages_cursor.to_list = AsyncMock(return_value=[])
    mock_db.crawledpages.find.return_value = mock_pages_cursor

    # contacts mock
    saved_list = list(saved_contacts) if saved_contacts else []
    async def capture_update(query, doc, upsert=False):
        set_data = doc.get("$set", {})
        existing = next((c for c in saved_list if c.get("name") == query.get("name")), None)
        if existing:
            existing.update(set_data)
        else:
            saved_list.append(dict(set_data))
        return MagicMock()

    mock_db.contacts.update_one = AsyncMock(side_effect=capture_update)
    mock_db.contacts.find_one = AsyncMock(side_effect=lambda q: next((c for c in saved_list if c.get("name") == q.get("name")), None))
    mock_db.contacts.delete_many = AsyncMock()

    def make_contact_cursor(*args, **kwargs):
        c = MagicMock()
        c.sort.return_value = c
        c.to_list = AsyncMock(side_effect=lambda length=100: list(saved_list))
        return c

    mock_db.contacts.find = MagicMock(side_effect=make_contact_cursor)
    return mock_db, saved_list


# ============================================================
# Requirement 1 & 2: Phase 1 returns 0 candidates, Phase 2 gating
# ============================================================

@pytest.mark.asyncio
async def test_phase1_zero_candidates_triggers_phase2_when_enabled():
    """Requirement 1: Phase 1 returns zero candidates but Phase 2 still runs when enabled."""
    company_id = str(ObjectId())
    mock_company = {
        "_id": ObjectId(company_id),
        "name": "Acme Innovations Ltd",
        "website": "https://acmeinnovations.test",
        "contactName": None,
        "contactEmail": None
    }

    mock_db, _ = _build_mock_db(mock_company)

    fake_ext_candidates = [
        {
            "name": "Elena Rostova",
            "role": "Chief Executive Officer",
            "evidence": "Elena Rostova, CEO of Acme Innovations",
            "source_type": "duckduckgo",
            "source_url": "https://example.com/leadership"
        }
    ]

    with patch("app.services.contact_service.get_db", return_value=mock_db), \
         patch("app.services.contact_service.discover_official_website_decision_makers", new_callable=AsyncMock, return_value=[]), \
         patch("app.services.contact_service.check_domain_mx", new_callable=AsyncMock, return_value={"mxStatus": "VALID"}), \
         patch("app.services.contact_service.search_duckduckgo_multi_round", return_value=fake_ext_candidates) as mock_multi_search, \
         patch("app.services.contact_service.discover_decision_maker_emails", new_callable=AsyncMock) as mock_email_disc:
        
        mock_email_disc.return_value = [
            {
                **fake_ext_candidates[0],
                "email": "elena.rostova@acmeinnovations.test",
                "exact_email": "elena.rostova@acmeinnovations.test",
                "email_status": "EXACT_FOUND",
                "emailStatus": "EXACT_FOUND",
                "isExactPublished": True,
            }
        ]

        await extract_contacts_from_website(company_id=company_id, enable_phase2=True)

        # External search must have been called since Phase 1 returned zero candidates
        assert mock_multi_search.called, "Phase 2 external search should be triggered when Phase 1 finds 0 candidates"
        assert mock_email_disc.called, "discover_decision_maker_emails should be called when Phase 2 is enabled"


@pytest.mark.asyncio
async def test_phase2_does_not_run_when_disabled():
    """Requirement 2: Phase 2 does not run when disabled."""
    company_id = str(ObjectId())
    mock_company = {
        "_id": ObjectId(company_id),
        "name": "Acme Innovations Ltd",
        "website": "https://acmeinnovations.test",
    }

    mock_db, _ = _build_mock_db(mock_company)

    with patch("app.services.contact_service.get_db", return_value=mock_db), \
         patch("app.services.contact_service.discover_official_website_decision_makers", new_callable=AsyncMock, return_value=[]), \
         patch("app.services.contact_service.check_domain_mx", new_callable=AsyncMock, return_value={"mxStatus": "VALID"}), \
         patch("app.services.contact_service.search_duckduckgo_multi_round") as mock_multi_search, \
         patch("app.services.contact_service.discover_decision_maker_emails", new_callable=AsyncMock) as mock_email_disc:

        await extract_contacts_from_website(company_id=company_id, enable_phase2=False)

        assert not mock_multi_search.called, "Phase 2 external search should NOT run when enable_phase2=False"
        assert not mock_email_disc.called, "Phase 2 email discovery should NOT run when enable_phase2=False"


# ============================================================
# Requirement 3 & 4: Search error vs zero-results & timeout handling
# ============================================================

def test_successful_search_with_zero_results_vs_failure():
    """Requirement 3: A successful search returning zero results is different from a search failure."""
    from app.services import decision_maker_engine

    # Case A: DDG returns 200 OK with no results in HTML
    mock_html = "<html><body><div class='no-results'>No results found</div></body></html>"
    mock_response = MagicMock(status_code=200, text=mock_html)

    with patch("httpx.Client.get", return_value=mock_response):
        results = ddg_search("nonexistentquery123456789")
        assert results == []
        assert decision_maker_engine.LAST_DDG_SEARCH_FAILED is False, "200 OK with 0 results must NOT mark search as failed"
        assert decision_maker_engine.LAST_DDG_SEARCH_STATUS == "OK"

    # Case B: DDG returns 403 or network failure
    mock_fail_response = MagicMock(status_code=403, text="Forbidden")
    with patch("httpx.Client.get", return_value=mock_fail_response):
        results_fail = ddg_search("anyquery")
        assert results_fail is None
        assert decision_maker_engine.LAST_DDG_SEARCH_FAILED is True, "HTTP 403 must mark search as failed"
        assert decision_maker_engine.LAST_DDG_SEARCH_STATUS in ("SEARCH_UNAVAILABLE", "HTTP_ERROR")


def test_search_timeout_not_reported_as_not_found():
    """Requirement 4: Search timeout/error is not reported as NOT_FOUND."""
    import httpx

    with patch("httpx.Client.get", side_effect=httpx.TimeoutException("Search timed out")):
        res = search_ddg_exact_person_email("Marcus Aurelius", "Roman Empire", "rome.test")
        assert res["email"] is None
        assert res["status"] == "SEARCH_TIMEOUT", f"Expected SEARCH_TIMEOUT, got {res['status']}"
        assert res["search_status"] == "SEARCH_TIMEOUT"
        assert res["status"] != "NOT_FOUND", "Timeouts must never be reported as NOT_FOUND"


# ============================================================
# Requirement 5: Redirect URL decoding
# ============================================================

def test_redirect_urls_decoded_correctly():
    """Requirement 5: Redirect URLs are decoded correctly."""
    # DDG redirect with protocol-relative URL
    ddg_redirect = "//duckduckgo.com/l/?uddg=https%3A%2F%2Facme.com%2Fleadership%2Fceo&rut=xyz"
    decoded = decode_redirect_url(ddg_redirect)
    assert decoded == "https://acme.com/leadership/ceo"

    # DDG redirect with relative path
    rel_redirect = "/l/?uddg=https%3A%2F%2Fexample.org%2Fteam"
    assert decode_redirect_url(rel_redirect) == "https://example.org/team"

    # Regular direct URL remains intact
    direct = "https://acme.com/about-us"
    assert decode_redirect_url(direct) == "https://acme.com/about-us"

    # Blank or empty returns empty
    assert decode_redirect_url("") == ""


# ============================================================
# Requirement 6: Placeholder email strings rejected
# ============================================================

def test_placeholder_emails_rejected():
    """Requirement 6: Invalid placeholder email strings are never stored as valid email addresses."""
    # Format and placeholder checking
    placeholders = [
        "Not publicly available",
        "Not Publicly Available",
        "not publicly verified",
        "N/A",
        "None",
        "Unknown",
        "no email",
        "contact@company", # invalid domain format missing tld
    ]
    for ph in placeholders:
        assert is_valid_email_format(ph) is False, f"'{ph}' should be rejected as an invalid email format"

    # Valid email formats must pass
    assert is_valid_email_format("john.doe@company.com") is True
    assert is_valid_email_format("sarah_connor@tech.co.uk") is True


@pytest.mark.asyncio
async def test_imported_placeholder_email_not_marked_exact_found():
    """Requirement 6: Excel import with placeholder email never marked EXACT_FOUND."""
    company_id = str(ObjectId())
    mock_company = {
        "_id": ObjectId(company_id),
        "name": "Apex Global Solutions",
        "website": "https://apex.test",
        "contactName": "Vikram Sethi",
        "contactEmail": "Not publicly available"  # Placeholder string!
    }

    mock_db, _ = _build_mock_db(mock_company)

    with patch("app.services.contact_service.get_db", return_value=mock_db), \
         patch("app.services.contact_service.discover_official_website_decision_makers", new_callable=AsyncMock, return_value=[]), \
         patch("app.services.contact_service.check_domain_mx", new_callable=AsyncMock, return_value={"mxStatus": "VALID"}):

        contacts = await extract_contacts_from_website(company_id=company_id, enable_phase2=False)

        assert len(contacts) == 1
        contact = contacts[0]
        assert contact["name"] == "Vikram Sethi"
        assert contact["email"] is None, "Placeholder string must not be stored as an email"
        assert contact["emailStatus"] == "NOT_FOUND", "Placeholder email must NOT be marked EXACT_FOUND"
        assert contact["isExactPublished"] is False


# ============================================================
# Requirement 7: Non-person names rejected (locations & web labels)
# ============================================================

def test_non_person_names_rejected():
    """Requirement 7: Location names and generic webpage labels are rejected as people."""
    # Known false positive entities
    invalid_names = [
        "Altona North",
        "New Zealand",
        "Media Kit",
        "Fact Sheet",
        "Case Study",
        "Press Release",
        "Investor Relations",
        "United States",
        "South Africa",
        "Resource Center",
    ]
    for non_person in invalid_names:
        assert is_strict_person_name(non_person, "Acme Corp") is False, f"'{non_person}' should be rejected as a person"
        assert looks_like_organization_name(non_person, "Acme Corp") is True

    # Real human names must be accepted
    valid_names = [
        "David North",
        "Adam West",
        "Sarah Connor",
        "Michael Brown",
        "Elena Rostova",
        "Vikram Sethi",
    ]
    for person in valid_names:
        assert is_strict_person_name(person, "Acme Corp") is True, f"'{person}' should be accepted as a person"
        assert looks_like_organization_name(person, "Acme Corp") is False


# ============================================================
# Requirement 8: Truthful frontend feedback
# ============================================================

def test_frontend_does_not_display_false_success_on_empty_results():
    """Requirement 8: Empty frontend results do not display a false success message."""
    import re
    from pathlib import Path

    frontend_file = Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "pages" / "CompanyDetail.jsx"
    assert frontend_file.exists(), f"CompanyDetail.jsx not found at {frontend_file}"
    content = frontend_file.read_text(encoding="utf-8")

    # Verify that handleExtractContacts checks list.length before setting success message
    assert "if (Array.isArray(list) && list.length > 0)" in content
    assert "Discovered ${list.length} decision maker" in content
    assert "Search completed, but no public decision-maker profiles were found." in content
    # Verify the old blind success message is no longer present unconditionally
    assert "setSuccessMsg('Decision makers and corporate channels discovered successfully!');" not in content


# ============================================================
# Requirement 9: Deduplication and evidence tracking intact
# ============================================================

def test_deduplication_and_evidence_tracking_intact():
    """Requirement 9: Existing discovery behavior and deduplication remain intact."""
    candidates = [
        {
            "name": "Sarah Connor",
            "role": "Chief Executive Officer",
            "evidence": "Sarah Connor is the CEO of Acme Corp.",
            "source_type": "official_website",
            "source_url": "https://acme.test/leadership"
        },
        {
            "name": "Sarah Connor",
            "role": "CEO",
            "evidence": "Sarah Connor founded Acme Corp in 2020.",
            "source_type": "duckduckgo",
            "source_url": "https://news.test/article1"
        },
        {
            "name": "John Connor",
            "role": "CTO",
            "evidence": "John Connor, Chief Technology Officer.",
            "source_type": "official_website",
            "source_url": "https://acme.test/team"
        }
    ]

    deduped = dedupe_candidates(candidates)
    assert len(deduped) == 2, f"Expected 2 deduplicated candidates, got {len(deduped)}"

    sarah = next((c for c in deduped if c["name"] == "Sarah Connor"), None)
    assert sarah is not None
    assert "CEO" in sarah["role"] or "Chief Executive Officer" in sarah["role"]
    assert sarah.get("evidence") is not None
