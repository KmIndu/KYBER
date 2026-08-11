"""Realistic data provider — country-aware + domain-aware value generation.

Generates realistic values for each SemanticType, aware of the target
country/locale and business domain (banking, insurance, healthcare, retail).
"""

from __future__ import annotations

import random
import re
import string
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from faker import Faker

from app.generators.semantic_types import SemanticType

# ── Country → Faker locale mapping ─────────────────────────────

_COUNTRY_LOCALES: dict[str, str] = {
    "india": "en_IN",
    "in": "en_IN",
    "usa": "en_US",
    "us": "en_US",
    "united states": "en_US",
    "uk": "en_GB",
    "united kingdom": "en_GB",
    "canada": "en_CA",
    "ca": "en_CA",
    "australia": "en_AU",
    "au": "en_AU",
    "germany": "de_DE",
    "de": "de_DE",
    "france": "fr_FR",
    "fr": "fr_FR",
    "japan": "ja_JP",
    "jp": "ja_JP",
    "china": "zh_CN",
    "cn": "zh_CN",
    "brazil": "pt_BR",
    "br": "pt_BR",
    "singapore": "en_SG",
    "sg": "en_SG",
    "hong kong": "en_HK",
    "hk": "en_HK",
    "philippines": "en_PH",
    "ph": "en_PH",
}

# ── Country-specific phone formats ─────────────────────────────

_PHONE_FORMATS: dict[str, str] = {
    "en_IN": "+91 #####-#####",
    "en_US": "+1 (###) ###-####",
    "en_GB": "+44 #### ######",
    "en_CA": "+1 (###) ###-####",
    "en_AU": "+61 4## ### ###",
    "de_DE": "+49 ### #######",
    "fr_FR": "+33 # ## ## ## ##",
    "ja_JP": "+81 ##-####-####",
    "zh_CN": "+86 ### #### ####",
    "pt_BR": "+55 ## #####-####",
    "en_SG": "+65 ####-####",
    "en_HK": "+852 #### ####",
    "en_PH": "+63 ### ### ####",
}

# ── Country-specific postal code formats ────────────────────────

_POSTAL_FORMATS: dict[str, str] = {
    "en_IN": "######",
    "en_US": "#####",
    "en_GB": "??# #??",  # simplified
    "en_CA": "?#? #?#",
    "en_AU": "####",
    "de_DE": "#####",
    "fr_FR": "#####",
    "ja_JP": "###-####",
    "zh_CN": "######",
    "pt_BR": "#####-###",
}

# ── Insurance-specific templates ────────────────────────────────

_POLICY_PREFIXES = ["POL", "INS", "LIF", "HLT", "AUT", "HOM", "TRV"]
_ICD_CODES = [
    "E11.9", "I10", "J06.9", "M54.5", "K21.0", "J45.0", "E78.5",
    "N39.0", "R10.9", "F32.9", "G43.9", "J18.9", "M79.3", "L30.9",
]
_MEDICATIONS = [
    "Metformin 500mg", "Amlodipine 5mg", "Atorvastatin 10mg",
    "Omeprazole 20mg", "Amoxicillin 500mg", "Salbutamol 100mcg",
    "Paracetamol 650mg", "Ibuprofen 400mg", "Losartan 50mg",
    "Ciprofloxacin 500mg", "Azithromycin 250mg", "Pantoprazole 40mg",
    "Cetirizine 10mg", "Montelukast 10mg", "Insulin Glargine 100U/mL",
]
_DOSAGES = [
    "1 tablet daily", "2 tablets twice daily", "5ml three times daily",
    "1 capsule at bedtime", "10mg once daily", "500mg every 8 hours",
    "Apply twice daily", "2 puffs as needed", "1 injection daily",
]


class RealisticProvider:
    """Country-aware and domain-aware realistic data provider."""

    def __init__(
        self,
        country: str = "us",
        domain: str = "unknown",
    ) -> None:
        self._country = country.lower().strip()
        self._domain = domain.lower().strip()
        self._locale = _COUNTRY_LOCALES.get(self._country, "en_US")
        self._faker = Faker(self._locale)
        # Fallback english faker for consistent formatting
        self._faker_en = Faker("en_US") if self._locale != "en_US" else self._faker

    @property
    def locale(self) -> str:
        return self._locale

    @property
    def domain(self) -> str:
        return self._domain

    def generate(self, sem_type: SemanticType) -> Any:
        """Generate a realistic value for the given semantic type."""
        handler = _GENERATORS.get(sem_type)
        if handler:
            return handler(self)
        return self._faker.word()

    # ── Person generators ──────────────────────────────────────

    def _gen_first_name(self) -> str:
        return self._faker.first_name()

    def _gen_last_name(self) -> str:
        return self._faker.last_name()

    def _gen_full_name(self) -> str:
        return self._faker.name()

    def _gen_gender(self) -> str:
        return random.choice(["Male", "Female", "Non-binary"])

    def _gen_date_of_birth(self) -> str:
        start = date(1950, 1, 1)
        end = date(2005, 12, 31)
        days = (end - start).days
        dob = start + timedelta(days=random.randint(0, days))
        return dob.isoformat()

    def _gen_age(self) -> int:
        return random.randint(18, 85)

    # ── Contact generators ─────────────────────────────────────

    def _gen_email(self) -> str:
        first = self._faker.first_name().lower()
        last = self._faker.last_name().lower()
        # Clean non-ascii for email safety
        first = re.sub(r"[^a-z]", "", first)
        last = re.sub(r"[^a-z]", "", last)
        domains = ["gmail.com", "outlook.com", "yahoo.com", "company.com", "mail.com"]
        sep = random.choice([".", "_", ""])
        num = random.choice(["", str(random.randint(1, 99))])
        return f"{first}{sep}{last}{num}@{random.choice(domains)}"

    def _gen_phone(self) -> str:
        fmt = _PHONE_FORMATS.get(self._locale, "+1 (###) ###-####")
        return self._format_pattern(fmt)

    def _gen_mobile(self) -> str:
        return self._gen_phone()

    # ── Address generators ─────────────────────────────────────

    def _gen_street_address(self) -> str:
        return self._faker.street_address()

    def _gen_city(self) -> str:
        return self._faker.city()

    def _gen_state(self) -> str:
        try:
            return self._faker.state()
        except AttributeError:
            return self._faker.city()

    def _gen_country(self) -> str:
        return self._faker.country()

    def _gen_postal_code(self) -> str:
        fmt = _POSTAL_FORMATS.get(self._locale)
        if fmt:
            return self._format_pattern(fmt)
        return self._faker.postcode()

    def _gen_full_address(self) -> str:
        return self._faker.address().replace("\n", ", ")

    # ── Financial generators ───────────────────────────────────

    def _gen_account_number(self) -> str:
        if self._locale == "en_IN":
            # Indian bank account: 11-16 digits
            length = random.randint(11, 16)
            return "".join(random.choices(string.digits, k=length))
        elif self._locale in ("en_US", "en_CA"):
            # US/CA: 10-12 digits
            length = random.randint(10, 12)
            return "".join(random.choices(string.digits, k=length))
        elif self._locale == "en_GB":
            # UK: 8 digits
            return "".join(random.choices(string.digits, k=8))
        else:
            length = random.randint(10, 16)
            return "".join(random.choices(string.digits, k=length))

    def _gen_iban(self) -> str:
        return self._faker_en.iban()

    def _gen_swift_code(self) -> str:
        # SWIFT/BIC: 8 or 11 chars (4 bank + 2 country + 2 location + 3 branch)
        bank = "".join(random.choices(string.ascii_uppercase, k=4))
        country = "".join(random.choices(string.ascii_uppercase, k=2))
        location = "".join(random.choices(string.ascii_uppercase + string.digits, k=2))
        branch = "".join(random.choices(string.ascii_uppercase + string.digits, k=3))
        return f"{bank}{country}{location}{branch}"

    def _gen_routing_number(self) -> str:
        # US ABA routing number: 9 digits
        return "".join(random.choices(string.digits, k=9))

    def _gen_amount(self) -> float:
        if self._domain == "insurance":
            return round(random.uniform(100.00, 500000.00), 2)
        elif self._domain == "healthcare":
            return round(random.uniform(50.00, 50000.00), 2)
        elif self._domain == "retail":
            return round(random.uniform(0.99, 9999.99), 2)
        else:
            return round(random.uniform(10.00, 100000.00), 2)

    def _gen_currency(self) -> str:
        locale_currencies = {
            "en_IN": "INR",
            "en_US": "USD",
            "en_GB": "GBP",
            "en_CA": "CAD",
            "en_AU": "AUD",
            "de_DE": "EUR",
            "fr_FR": "EUR",
            "ja_JP": "JPY",
            "zh_CN": "CNY",
            "pt_BR": "BRL",
            "en_SG": "SGD",
            "en_HK": "HKD",
        }
        return locale_currencies.get(self._locale, "USD")

    def _gen_credit_card(self) -> str:
        return self._faker_en.credit_card_number()

    # ── Insurance generators ───────────────────────────────────

    def _gen_policy_id(self) -> str:
        prefix = random.choice(_POLICY_PREFIXES)
        year = random.randint(2020, 2026)
        seq = random.randint(100000, 999999)
        return f"{prefix}-{year}-{seq}"

    def _gen_claim_number(self) -> str:
        prefix = "CLM"
        year = random.randint(2020, 2026)
        seq = random.randint(10000, 99999)
        return f"{prefix}{year}{seq}"

    def _gen_premium_amount(self) -> float:
        return round(random.uniform(500.00, 50000.00), 2)

    def _gen_coverage_amount(self) -> float:
        return round(random.uniform(50000.00, 5000000.00), 2)

    # ── Healthcare generators ──────────────────────────────────

    def _gen_patient_id(self) -> str:
        prefix = "PAT"
        seq = random.randint(100000, 999999)
        return f"{prefix}-{seq}"

    def _gen_diagnosis_code(self) -> str:
        return random.choice(_ICD_CODES)

    def _gen_medication_name(self) -> str:
        return random.choice(_MEDICATIONS)

    def _gen_dosage(self) -> str:
        return random.choice(_DOSAGES)

    # ── Retail generators ──────────────────────────────────────

    def _gen_sku(self) -> str:
        prefix = "".join(random.choices(string.ascii_uppercase, k=3))
        num = "".join(random.choices(string.digits, k=6))
        return f"{prefix}-{num}"

    def _gen_barcode(self) -> str:
        # EAN-13
        digits = [random.randint(0, 9) for _ in range(12)]
        # Calculate check digit
        odd_sum = sum(digits[i] for i in range(0, 12, 2))
        even_sum = sum(digits[i] for i in range(1, 12, 2))
        check = (10 - (odd_sum + even_sum * 3) % 10) % 10
        digits.append(check)
        return "".join(str(d) for d in digits)

    def _gen_product_name(self) -> str:
        adjectives = ["Premium", "Organic", "Classic", "Ultra", "Pro", "Essential", "Natural"]
        nouns = ["Widget", "Gadget", "Device", "Solution", "Kit", "Pack", "Bundle", "Set"]
        return f"{random.choice(adjectives)} {random.choice(nouns)}"

    # ── Identity generators ────────────────────────────────────

    def _gen_pan(self) -> str:
        """Generate Indian PAN number: AAAPL1234C format.

        5 uppercase letters + 4 digits + 1 uppercase letter.
        4th char indicates entity type (P=Person, C=Company, etc.).
        """
        first_three = "".join(random.choices(string.ascii_uppercase, k=3))
        entity = random.choice(["P", "C", "H", "F", "A", "T", "B", "L", "J", "G"])
        fifth = random.choice(string.ascii_uppercase)
        digits = "".join(random.choices(string.digits, k=4))
        last = random.choice(string.ascii_uppercase)
        return f"{first_three}{entity}{fifth}{digits}{last}"

    def _gen_ssn(self) -> str:
        if self._locale == "en_US":
            area = random.randint(100, 899)
            group = random.randint(1, 99)
            serial = random.randint(1, 9999)
            return f"{area:03d}-{group:02d}-{serial:04d}"
        return self._faker_en.ssn()

    def _gen_passport(self) -> str:
        if self._locale == "en_IN":
            letter = random.choice(string.ascii_uppercase)
            digits = "".join(random.choices(string.digits, k=7))
            return f"{letter}{digits}"
        elif self._locale in ("en_US", "en_CA"):
            digits = "".join(random.choices(string.digits, k=9))
            return digits
        else:
            letters = "".join(random.choices(string.ascii_uppercase, k=2))
            digits = "".join(random.choices(string.digits, k=7))
            return f"{letters}{digits}"

    def _gen_national_id(self) -> str:
        if self._locale == "en_IN":
            # Aadhaar: 12 digits
            return "".join(random.choices(string.digits, k=12))
        return "".join(random.choices(string.digits, k=10))

    # ── Timestamp generators ───────────────────────────────────

    def _gen_timestamp(self) -> str:
        start = datetime(2020, 1, 1)
        end = datetime(2026, 12, 31)
        delta = int((end - start).total_seconds())
        dt = start + timedelta(seconds=random.randint(0, delta))
        return dt.isoformat()

    def _gen_date(self) -> str:
        start = date(2020, 1, 1)
        end = date(2026, 12, 31)
        delta = (end - start).days
        d = start + timedelta(days=random.randint(0, delta))
        return d.isoformat()

    def _gen_time(self) -> str:
        h = random.randint(0, 23)
        m = random.randint(0, 59)
        s = random.randint(0, 59)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _gen_created_at(self) -> str:
        return self._gen_timestamp()

    def _gen_updated_at(self) -> str:
        return self._gen_timestamp()

    # ── General generators ─────────────────────────────────────

    def _gen_uuid(self) -> str:
        return str(uuid.uuid4())

    def _gen_url(self) -> str:
        return self._faker_en.url()

    def _gen_ip_address(self) -> str:
        return self._faker_en.ipv4()

    def _gen_company(self) -> str:
        return self._faker.company()

    def _gen_description(self) -> str:
        return self._faker.sentence(nb_words=8)

    # ── DevOps / Software generators ──────────────────────────

    def _gen_status(self) -> str:
        if self._domain == "insurance":
            return random.choice(["pending", "approved", "rejected", "under_review", "cancelled", "expired"])
        elif self._domain == "healthcare":
            return random.choice(["admitted", "discharged", "in_treatment", "scheduled", "cancelled", "completed"])
        elif self._domain == "retail":
            return random.choice(["pending", "processing", "shipped", "delivered", "returned", "cancelled"])
        else:
            return random.choice([
                "pending", "running", "completed", "failed", "cancelled",
                "in_progress", "queued", "success", "error", "skipped",
            ])

    def _gen_username(self) -> str:
        first = self._faker.first_name().lower()
        last = self._faker.last_name().lower()
        fmt = random.choice(["dot", "initial", "underscore", "short"])
        if fmt == "dot":
            return f"{first}.{last}"
        elif fmt == "initial":
            return f"{first[0]}{last}"
        elif fmt == "underscore":
            return f"{first}_{last}"
        else:
            return f"{first[0]}.{last}"

    def _gen_git_branch(self) -> str:
        prefixes = ["feature", "bugfix", "hotfix", "release", "develop", "main", "master"]
        topics = [
            "user-auth", "api-refactor", "db-migration", "ci-pipeline",
            "security-patch", "dependency-update", "logging-enhancement",
            "performance-fix", "config-update", "test-coverage",
            "error-handling", "retry-logic", "rate-limiting",
            "caching-layer", "monitoring-setup", "data-validation",
        ]
        kind = random.choice(["prefixed", "plain", "versioned"])
        if kind == "prefixed":
            return f"{random.choice(prefixes)}/{random.choice(topics)}"
        elif kind == "versioned":
            return f"release/{random.randint(1, 5)}.{random.randint(0, 9)}.{random.randint(0, 20)}"
        else:
            return random.choice(["main", "master", "develop", "staging"])

    def _gen_git_repo_url(self) -> str:
        orgs = ["acme-corp", "sunlife", "fintech-labs", "cloudops", "data-platform", "security-team"]
        repos = [
            "api-gateway", "auth-service", "payment-engine", "config-server",
            "metrics-collector", "scan-orchestrator", "remediation-agent",
            "vulnerability-db", "ci-pipeline", "deployment-manager",
            "notification-service", "audit-logger", "data-pipeline",
        ]
        host = random.choice(["github.com", "bitbucket.org", "gitlab.com", "bitbucket.sunlifecorp.com"])
        return f"https://{host}/{random.choice(orgs)}/{random.choice(repos)}"

    def _gen_hostname(self) -> str:
        prefixes = ["app", "web", "api", "db", "cache", "worker", "scan", "agent"]
        envs = ["prod", "staging", "dev", "uat", "perf"]
        num = random.randint(1, 20)
        return f"{random.choice(prefixes)}-{random.choice(envs)}-{num:02d}.internal.corp"

    def _gen_version(self) -> str:
        major = random.randint(1, 5)
        minor = random.randint(0, 15)
        patch = random.randint(0, 30)
        fmt = random.choice(["semver", "prefixed"])
        if fmt == "prefixed":
            return f"v{major}.{minor}.{patch}"
        return f"{major}.{minor}.{patch}"

    def _gen_error_message(self) -> str:
        messages = [
            "Connection timed out after 30000ms",
            "NullPointerException at line 42",
            "Authentication failed: invalid credentials",
            "Rate limit exceeded: retry after 60s",
            "Resource not found: /api/v2/scan/results",
            "Database connection pool exhausted",
            "SSL handshake failed: certificate expired",
            "Memory allocation failed: out of heap space",
            "File not found: /opt/config/application.yml",
            "Permission denied: insufficient privileges",
            "JSON parse error at position 156",
            "Dependency resolution failed: circular reference detected",
            "HTTP 503: Service temporarily unavailable",
            "Timeout waiting for lock acquisition",
            "Invalid state transition: COMPLETED -> RUNNING",
        ]
        return random.choice(messages)

    def _gen_error_code(self) -> str:
        codes = [
            "ERR_TIMEOUT", "ERR_AUTH_FAILED", "ERR_NOT_FOUND", "ERR_RATE_LIMIT",
            "ERR_CONNECTION", "ERR_PARSE", "ERR_PERMISSION", "ERR_MEMORY",
            "ERR_CONFIG", "ERR_VALIDATION", "ERR_STATE", "ERR_DEPENDENCY",
            "SCAN_001", "SCAN_002", "AGENT_001", "AGENT_002", "AGENT_003",
            "CVE_RESOLVE_FAIL", "BUILD_FAIL", "TEST_FAIL", "DEPLOY_FAIL",
        ]
        return random.choice(codes)

    def _gen_service_name(self) -> str:
        """Generate a realistic service/agent/component name."""
        prefixes = [
            "Vulnerability Scanner", "Code Analyzer", "Dependency Resolver",
            "Security Remediator", "Build Orchestrator", "Test Runner",
            "Deploy Agent", "Config Manager", "Metrics Collector",
            "Log Aggregator", "Alert Monitor", "Compliance Checker",
            "PR Reviewer", "License Scanner", "Secret Detector",
            "Container Scanner", "SAST Analyzer", "DAST Scanner",
            "SCA Agent", "IaC Validator", "API Tester", "Load Runner",
            "Chaos Agent", "Backup Manager", "Data Migrator",
        ]
        return random.choice(prefixes)

    # ── SharePoint / OData / Metadata generators ──────────────

    def _gen_boolean(self) -> bool:
        return random.choice([True, False])

    def _gen_month(self) -> str:
        return random.choice([
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ])

    def _gen_title(self) -> str:
        """Generate a realistic item/case title."""
        prefixes = [
            "Q1 Review", "Q2 Planning", "Q3 Assessment", "Q4 Closeout",
            "Annual Compliance", "Risk Assessment", "Audit Finding",
            "Policy Update", "Process Improvement", "Strategic Initiative",
            "Budget Review", "Performance Report", "Stakeholder Request",
            "System Migration", "Data Quality", "Access Control Review",
            "Incident Response", "Change Request", "Service Enhancement",
            "Regulatory Update", "Vendor Assessment", "Training Program",
        ]
        suffixes = [
            f"- {random.randint(2023, 2026)}", f"#{random.randint(100, 9999)}",
            f"({random.choice(['High Priority', 'Medium', 'Low', 'Critical'])})",
            "", "",
        ]
        return f"{random.choice(prefixes)} {random.choice(suffixes)}".strip()

    def _gen_integer_id(self) -> int:
        return random.randint(1, 99999)

    def _gen_integer_count(self) -> int:
        return random.randint(0, 50)

    def _gen_integer_size(self) -> int:
        return random.randint(1024, 10_000_000)

    def _gen_file_type(self) -> str:
        return random.choice(["", "docx", "xlsx", "pdf", "pptx", "txt", "msg", "csv", "png", "jpg"])

    def _gen_file_path(self) -> str:
        sites = ["sites/ProjectTracking", "sites/Compliance", "sites/TeamDocs", "sites/Operations"]
        folders = ["Shared Documents", "Reports", "Archives", "Templates", "Active Cases"]
        names = ["Report", "Summary", "Notes", "Findings", "Action_Items", "Review", "Assessment"]
        ext = random.choice(["docx", "xlsx", "pdf", "pptx"])
        year = random.randint(2022, 2026)
        return f"/{random.choice(sites)}/{random.choice(folders)}/{random.choice(names)}_{year}.{ext}"

    def _gen_hex_color(self) -> str:
        colors = ["#FF0000", "#FFA500", "#008000", "#0000FF", "#FFD700", "#808080", "#FFFFFF", "#000000"]
        return random.choice(colors)

    def _gen_color_name(self) -> str:
        # Weighted towards RAG (Red/Amber/Green) since most use cases are status-oriented
        return random.choice(["Red", "Amber", "Green", "Green", "Green", "Amber", "Red"])

    def _gen_content_type_id(self) -> str:
        """Generate a realistic SharePoint content type ID."""
        base = "0x0100"
        suffix = "".join(random.choices("0123456789ABCDEF", k=32))
        return f"{base}{suffix}"

    def _gen_moderation_status(self) -> str:
        return random.choice(["Approved", "Pending", "Rejected", "Draft"])

    def _gen_order_number(self) -> int:
        return random.randint(1, 1000)

    # ── Utilities ──────────────────────────────────────────────

    def _format_pattern(self, fmt: str) -> str:
        """Replace # with random digit, ? with random uppercase letter."""
        result = []
        for ch in fmt:
            if ch == "#":
                result.append(random.choice(string.digits))
            elif ch == "?":
                result.append(random.choice(string.ascii_uppercase))
            else:
                result.append(ch)
        return "".join(result)


# ── Generator dispatch table ───────────────────────────────────
# Maps SemanticType → method

_GENERATORS: dict[SemanticType, Any] = {
    SemanticType.FIRST_NAME: RealisticProvider._gen_first_name,
    SemanticType.LAST_NAME: RealisticProvider._gen_last_name,
    SemanticType.FULL_NAME: RealisticProvider._gen_full_name,
    SemanticType.GENDER: RealisticProvider._gen_gender,
    SemanticType.DATE_OF_BIRTH: RealisticProvider._gen_date_of_birth,
    SemanticType.AGE: RealisticProvider._gen_age,
    SemanticType.EMAIL: RealisticProvider._gen_email,
    SemanticType.PHONE: RealisticProvider._gen_phone,
    SemanticType.MOBILE: RealisticProvider._gen_mobile,
    SemanticType.STREET_ADDRESS: RealisticProvider._gen_street_address,
    SemanticType.CITY: RealisticProvider._gen_city,
    SemanticType.STATE: RealisticProvider._gen_state,
    SemanticType.COUNTRY: RealisticProvider._gen_country,
    SemanticType.POSTAL_CODE: RealisticProvider._gen_postal_code,
    SemanticType.FULL_ADDRESS: RealisticProvider._gen_full_address,
    SemanticType.ACCOUNT_NUMBER: RealisticProvider._gen_account_number,
    SemanticType.IBAN: RealisticProvider._gen_iban,
    SemanticType.SWIFT_CODE: RealisticProvider._gen_swift_code,
    SemanticType.ROUTING_NUMBER: RealisticProvider._gen_routing_number,
    SemanticType.AMOUNT: RealisticProvider._gen_amount,
    SemanticType.CURRENCY: RealisticProvider._gen_currency,
    SemanticType.CREDIT_CARD: RealisticProvider._gen_credit_card,
    SemanticType.POLICY_ID: RealisticProvider._gen_policy_id,
    SemanticType.CLAIM_NUMBER: RealisticProvider._gen_claim_number,
    SemanticType.PREMIUM_AMOUNT: RealisticProvider._gen_premium_amount,
    SemanticType.COVERAGE_AMOUNT: RealisticProvider._gen_coverage_amount,
    SemanticType.PATIENT_ID: RealisticProvider._gen_patient_id,
    SemanticType.DIAGNOSIS_CODE: RealisticProvider._gen_diagnosis_code,
    SemanticType.MEDICATION_NAME: RealisticProvider._gen_medication_name,
    SemanticType.DOSAGE: RealisticProvider._gen_dosage,
    SemanticType.SKU: RealisticProvider._gen_sku,
    SemanticType.BARCODE: RealisticProvider._gen_barcode,
    SemanticType.PRODUCT_NAME: RealisticProvider._gen_product_name,
    SemanticType.PAN: RealisticProvider._gen_pan,
    SemanticType.SSN: RealisticProvider._gen_ssn,
    SemanticType.PASSPORT: RealisticProvider._gen_passport,
    SemanticType.NATIONAL_ID: RealisticProvider._gen_national_id,
    SemanticType.TIMESTAMP: RealisticProvider._gen_timestamp,
    SemanticType.DATE: RealisticProvider._gen_date,
    SemanticType.TIME: RealisticProvider._gen_time,
    SemanticType.CREATED_AT: RealisticProvider._gen_created_at,
    SemanticType.UPDATED_AT: RealisticProvider._gen_updated_at,
    SemanticType.UUID: RealisticProvider._gen_uuid,
    SemanticType.URL: RealisticProvider._gen_url,
    SemanticType.IP_ADDRESS: RealisticProvider._gen_ip_address,
    SemanticType.COMPANY: RealisticProvider._gen_company,
    SemanticType.DESCRIPTION: RealisticProvider._gen_description,
    SemanticType.STATUS: RealisticProvider._gen_status,
    SemanticType.USERNAME: RealisticProvider._gen_username,
    SemanticType.GIT_BRANCH: RealisticProvider._gen_git_branch,
    SemanticType.GIT_REPO_URL: RealisticProvider._gen_git_repo_url,
    SemanticType.HOSTNAME: RealisticProvider._gen_hostname,
    SemanticType.VERSION: RealisticProvider._gen_version,
    SemanticType.ERROR_MESSAGE: RealisticProvider._gen_error_message,
    SemanticType.ERROR_CODE: RealisticProvider._gen_error_code,
    SemanticType.SERVICE_NAME: RealisticProvider._gen_service_name,
    SemanticType.BOOLEAN: RealisticProvider._gen_boolean,
    SemanticType.MONTH: RealisticProvider._gen_month,
    SemanticType.TITLE: RealisticProvider._gen_title,
    SemanticType.INTEGER_ID: RealisticProvider._gen_integer_id,
    SemanticType.INTEGER_COUNT: RealisticProvider._gen_integer_count,
    SemanticType.INTEGER_SIZE: RealisticProvider._gen_integer_size,
    SemanticType.FILE_TYPE: RealisticProvider._gen_file_type,
    SemanticType.FILE_PATH: RealisticProvider._gen_file_path,
    SemanticType.HEX_COLOR: RealisticProvider._gen_hex_color,
    SemanticType.COLOR_NAME: RealisticProvider._gen_color_name,
    SemanticType.CONTENT_TYPE_ID: RealisticProvider._gen_content_type_id,
    SemanticType.MODERATION_STATUS: RealisticProvider._gen_moderation_status,
    SemanticType.ORDER_NUMBER: RealisticProvider._gen_order_number,
}
