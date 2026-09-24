"""End-to-end API tests for Seclock.

Run with:  pytest -v
Each test starts from a freshly reset state, so tests can run in any order
and be re-run individually with `pytest -k <name>`.
"""
import pytest
from fastapi.testclient import TestClient

from main import app, state

client = TestClient(app)

SETUP_PAYLOAD = {
    "owner_name": "K. V. Ramachandran Nair",
    "owner_phone": "+91 98470 12345",
    "owner_email": "ramachandran.kv@gmail.com",
    "preferred_channels": ["App", "SMS", "IVR"],
    "check_in_interval_days": 30,
    "nominees": [
        {"name": "Priya Ramachandran", "phone": "+91 98471 99881", "relation": "Daughter"},
        {"name": "Anil Nair", "phone": "+91 94472 44332", "relation": "Son"},
        {"name": "Dr. Radhika Nair", "phone": "+91 98950 11223", "relation": "Sister"},
        {"name": "Adv. Suresh Kumar", "phone": "+91 98460 77889", "relation": "Legal Counsel"},
        {"name": "Vijayalakshmi Amma", "phone": "+91 94461 55667", "relation": "Spouse"},
    ],
    "tier1_assets": [{"bank": "State Bank of India", "acc": "30489102934", "balance": "INR 6,50,000"}],
    "tier2_assets": [{"credentials": "ramachandran.kv@gmail.com"}],
    "tier3_assets": [{"note": "Family ancestral land details"}],
}

LIFE_CERT_TEXT = """
GOVERNMENT OF INDIA
JEEVAN PRAMAAN — DIGITAL LIFE CERTIFICATE
Pramaan ID: JP-98471029348
Account Owner / Pensioner: K. V. RAMACHANDRAN NAIR
Aadhaar Biometric Verification: AADHAAR_IRIS_FINGERPRINT_VERIFIED
Issuing Authority: JEEVAN PRAMAAN ONLINE PORTAL / UIDAI
Status: ACTIVE — PERSON CONFIRMED ALIVE
"""

DEATH_CERT_TEXT = """
GOVERNMENT OF KERALA - DEPARTMENT OF ECONOMICS AND STATISTICS
FORM NO. 6 — DEATH CERTIFICATE
Registration Number: KL-D-2025-098412
Date of Death: 14/05/2025
Name of Deceased: K. V. RAMACHANDRAN NAIR
Nominee / Informant Name: PRIYA RAMACHANDRAN
Issuing Authority: SUB-REGISTRAR / TAHSILDAR OFFICE
"""

NOMINEE_NAMES = ["Priya Ramachandran", "Anil Nair", "Dr. Radhika Nair"]


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def clean_state():
    """Reset global app state before every test."""
    state.reset()
    yield


@pytest.fixture
def vault():
    """A freshly set-up vault. Returns the setup response JSON."""
    res = client.post("/api/vault/setup", json=SETUP_PAYLOAD)
    assert res.status_code == 200
    return res.json()


@pytest.fixture
def expired_vault(vault):
    """A set-up vault whose liveness has expired (ready for claims)."""
    res = client.post("/api/liveness/simulate-miss")
    assert res.status_code == 200
    return vault


@pytest.fixture
def claim_ready_vault(expired_vault):
    """Expired vault with a verified death certificate, the precondition for claims."""
    res = client.post(
        "/api/ocr/verify-document", json={"document_text": DEATH_CERT_TEXT}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "VERIFIED"
    return expired_vault


def submit_share(nominee_name, share):
    return client.post(
        "/api/claim/submit-share",
        json={
            "nominee_name": nominee_name,
            "share_index": share["share_index"],
            "share_hex": share["share_hex"],
        },
    )


# --------------------------------------------------------------------------
# 1. Initial state
# --------------------------------------------------------------------------
def test_initial_state():
    res = client.get("/api/state")
    assert res.status_code == 200
    assert res.json()["is_vault_setup"] is False


# --------------------------------------------------------------------------
# 2. Vault setup & Shamir 3-of-5 key splitting
# --------------------------------------------------------------------------
def test_vault_setup_generates_five_shares(vault):
    assert vault["status"] == "SUCCESS"
    assert len(vault["shares"]) == 5
    assert state.threshold_k == 3


# --------------------------------------------------------------------------
# 3. Multi-channel liveness check-ins
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "channel, code",
    [
        ("App", "APP_BIOMETRIC"),
        ("SMS", "YES 4829"),
        ("IVR", "DTMF_KEY_1"),
    ],
)
def test_liveness_check_in_channels(vault, channel, code):
    res = client.post(
        "/api/liveness/check-in", json={"channel": channel, "response_code": code}
    )
    assert res.status_code == 200


def test_app_check_in_marks_owner_active(vault):
    res = client.post(
        "/api/liveness/check-in",
        json={"channel": "App", "response_code": "APP_BIOMETRIC"},
    )
    assert res.status_code == 200
    assert res.json()["liveness_status"] == "ACTIVE"


# --------------------------------------------------------------------------
# 4. Liveness miss / expiry
# --------------------------------------------------------------------------
def test_liveness_miss_expires(vault):
    res = client.post("/api/liveness/simulate-miss")
    assert res.status_code == 200
    assert res.json()["status"] == "EXPIRED"


# --------------------------------------------------------------------------
# 4b. Life certificate (Jeevan Pramaan) restores liveness
# --------------------------------------------------------------------------
def test_life_certificate_restores_liveness(expired_vault):
    res = client.post(
        "/api/liveness/upload-life-certificate",
        json={"document_text": LIFE_CERT_TEXT},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "VERIFIED_ALIVE"
    assert client.get("/api/state").json()["liveness_status"] == "ACTIVE"


# --------------------------------------------------------------------------
# 5. Legal document OCR verification
# --------------------------------------------------------------------------
def test_death_certificate_ocr_verification(expired_vault):
    res = client.post(
        "/api/ocr/verify-document", json={"document_text": DEATH_CERT_TEXT}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "VERIFIED"
    assert body["confidence_score"] >= 70


# --------------------------------------------------------------------------
# 6. Nominee share submission (3-of-5 threshold)
# --------------------------------------------------------------------------
def test_partial_shares_held_pending(claim_ready_vault):
    shares = claim_ready_vault["shares"]
    for name, share in zip(NOMINEE_NAMES[:2], shares[:2]):
        res = submit_share(name, share)
        assert res.status_code == 200
        assert res.json()["is_reconstructed"] is False


def test_threshold_reconstructs_and_decrypts_vault(claim_ready_vault):
    shares = claim_ready_vault["shares"]
    results = [
        submit_share(name, share).json()
        for name, share in zip(NOMINEE_NAMES, shares[:3])
    ]

    # First two shares are held pending, the third meets the threshold.
    assert results[0]["is_reconstructed"] is False, results[0]
    assert results[1]["is_reconstructed"] is False, results[1]
    assert results[2]["is_reconstructed"] is True, results[2]

    decrypted = results[2]["decrypted_vault"]
    assert decrypted is not None
    assert decrypted["tier1_financial"][0]["bank"] == "State Bank of India"


# --------------------------------------------------------------------------
# 7. Audit ledger integrity
# --------------------------------------------------------------------------
def test_audit_ledger_integrity(expired_vault):
    res = client.get("/api/audit/ledger")
    assert res.status_code == 200
    body = res.json()
    assert body["integrity"]["is_valid"] is True
    assert body["compliance_report"]["total_audit_events"] > 0


# --------------------------------------------------------------------------
# 8. Tamper detection
# --------------------------------------------------------------------------
def test_tamper_detection(expired_vault):
    res = client.post("/api/audit/simulate-tamper?block_index=1")
    assert res.status_code == 200
    assert res.json()["new_integrity"]["is_valid"] is False


# --------------------------------------------------------------------------
# 9. Emergency owner veto
# --------------------------------------------------------------------------
def test_owner_veto(expired_vault):
    res = client.post("/api/owner/veto")
    assert res.status_code == 200
    assert res.json()["status"] == "VETO_EXECUTED"