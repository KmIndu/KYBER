"""Domain detection engine.

Analyzes schema metadata, OpenAPI endpoints, and BDD feature files
to detect the business domain (banking, insurance, healthcare, retail)
using keyword matching against field names, table/schema names,
endpoint names, and BDD keywords.

Returns the detected domain with a confidence score (0.0–1.0).
"""

from __future__ import annotations

import re
from typing import Any

from app.models.bdd import BDDMetadata
from app.models.domain import DomainResult, DomainSignal
from app.models.openapi import OpenAPIMetadata
from app.models.schema import SchemaMetadata

# ── Domain keyword dictionaries ───────────────────────────────
# Each keyword has an implicit weight of 1.0 unless overridden.
# Higher-weight terms are strong indicators exclusive to that domain.

_BANKING_KEYWORDS: dict[str, float] = {
    "account": 1.0,
    "balance": 1.5,
    "transaction": 1.5,
    "transfer": 2.0,
    "deposit": 2.0,
    "withdrawal": 2.0,
    "ledger": 2.0,
    "loan": 1.5,
    "mortgage": 2.0,
    "interest_rate": 2.0,
    "credit": 1.0,
    "debit": 1.5,
    "atm": 2.0,
    "branch": 1.0,
    "swift": 2.0,
    "iban": 2.0,
    "routing_number": 2.0,
    "overdraft": 2.0,
    "savings": 1.5,
    "checking": 2.0,
    "bank": 2.0,
    "currency": 1.0,
    "exchange_rate": 1.5,
    "wire_transfer": 2.0,
    "statement": 1.0,
    "apr": 1.5,
    "kyc": 2.0,
    "aml": 2.0,
    "beneficiary": 1.5,
}

_INSURANCE_KEYWORDS: dict[str, float] = {
    "policy": 2.0,
    "premium": 2.0,
    "claim": 2.0,
    "coverage": 2.0,
    "underwriting": 2.0,
    "beneficiary": 1.5,
    "insured": 2.0,
    "policyholder": 2.0,
    "deductible": 2.0,
    "rider": 1.5,
    "endorsement": 1.5,
    "actuary": 2.0,
    "risk": 1.0,
    "liability": 1.5,
    "annuity": 2.0,
    "reinsurance": 2.0,
    "claim_amount": 2.0,
    "sum_assured": 2.0,
    "maturity": 1.5,
    "surrender": 1.5,
    "nominee": 2.0,
    "insurance": 2.0,
    "indemnity": 2.0,
    "peril": 1.5,
    "exclusion": 1.5,
    "copay": 1.5,
    "coinsurance": 2.0,
    "group_life": 2.0,
    "term_life": 2.0,
}

_HEALTHCARE_KEYWORDS: dict[str, float] = {
    "patient": 2.0,
    "diagnosis": 2.0,
    "prescription": 2.0,
    "medication": 2.0,
    "doctor": 1.5,
    "physician": 2.0,
    "hospital": 2.0,
    "clinic": 1.5,
    "appointment": 1.5,
    "medical_record": 2.0,
    "icd": 2.0,
    "cpt": 2.0,
    "ehr": 2.0,
    "emr": 2.0,
    "lab_result": 2.0,
    "vital_signs": 2.0,
    "blood_pressure": 2.0,
    "allergy": 1.5,
    "immunization": 2.0,
    "surgery": 1.5,
    "ward": 1.5,
    "nurse": 1.5,
    "radiology": 2.0,
    "pharmacy": 1.5,
    "dosage": 2.0,
    "symptom": 1.5,
    "treatment": 1.5,
    "healthcare": 2.0,
    "hipaa": 2.0,
    "discharge": 1.5,
}

_RETAIL_KEYWORDS: dict[str, float] = {
    "product": 1.5,
    "cart": 2.0,
    "order": 1.5,
    "inventory": 2.0,
    "sku": 2.0,
    "catalog": 2.0,
    "price": 1.0,
    "discount": 1.5,
    "coupon": 2.0,
    "customer": 1.0,
    "shipment": 1.5,
    "shipping": 1.5,
    "warehouse": 2.0,
    "store": 1.0,
    "checkout": 2.0,
    "wishlist": 2.0,
    "refund": 1.5,
    "return": 1.0,
    "supplier": 1.5,
    "vendor": 1.5,
    "purchase_order": 2.0,
    "pos": 2.0,
    "barcode": 2.0,
    "upc": 2.0,
    "retail": 2.0,
    "ecommerce": 2.0,
    "shopping": 2.0,
    "merchandise": 2.0,
    "category": 1.0,
    "brand": 1.0,
}

_DOMAIN_KEYWORDS: dict[str, dict[str, float]] = {
    "banking": _BANKING_KEYWORDS,
    "insurance": _INSURANCE_KEYWORDS,
    "healthcare": _HEALTHCARE_KEYWORDS,
    "retail": _RETAIL_KEYWORDS,
}

# Pre-compile patterns for each domain's keywords
_DOMAIN_PATTERNS: dict[str, list[tuple[re.Pattern, str, float]]] = {}
for _domain, _kw_dict in _DOMAIN_KEYWORDS.items():
    _patterns = []
    for _kw, _weight in _kw_dict.items():
        # Match as whole word, case-insensitive
        _patterns.append((re.compile(rf"\b{re.escape(_kw)}\b", re.I), _kw, _weight))
    _DOMAIN_PATTERNS[_domain] = _patterns


class DomainDetectionEngine:
    """Detect business domain from schema, OpenAPI, and BDD metadata."""

    def __init__(
        self,
        schema: SchemaMetadata | None = None,
        openapi: OpenAPIMetadata | None = None,
        bdd: BDDMetadata | None = None,
    ) -> None:
        self._schema = schema
        self._openapi = openapi
        self._bdd = bdd

    def detect(self) -> DomainResult:
        """Run domain detection and return result with confidence."""
        signals: list[DomainSignal] = []

        # Extract signals from all sources
        signals.extend(self._scan_schema())
        signals.extend(self._scan_openapi())
        signals.extend(self._scan_bdd())

        # Aggregate scores per domain
        scores: dict[str, float] = {d: 0.0 for d in _DOMAIN_KEYWORDS}
        for sig in signals:
            scores[sig.domain] += sig.weight

        total_weight = sum(scores.values())
        if total_weight == 0:
            return DomainResult(
                domain="unknown",
                confidence=0.0,
                signals=[],
                all_scores={d: 0.0 for d in _DOMAIN_KEYWORDS},
            )

        # Normalize to get confidence (winner's share of total)
        best_domain = max(scores, key=lambda d: scores[d])
        confidence = round(scores[best_domain] / total_weight, 2)

        # Normalize all scores to 0-1
        all_scores = {d: round(s / total_weight, 2) for d, s in scores.items()}

        return DomainResult(
            domain=best_domain,
            confidence=confidence,
            signals=signals,
            all_scores=all_scores,
        )

    # ── Schema scanning ────────────────────────────────────────

    def _scan_schema(self) -> list[DomainSignal]:
        if not self._schema:
            return []
        signals: list[DomainSignal] = []
        for table in self._schema.tables:
            # Scan table name
            signals.extend(self._match_text(table.name, "table_name"))
            # Scan column names
            for col in table.columns:
                signals.extend(self._match_text(col.name, "field_name"))
            # Scan check constraints
            for chk in table.check_constraints:
                signals.extend(self._match_text(chk, "field_name"))
        return signals

    # ── OpenAPI scanning ───────────────────────────────────────

    def _scan_openapi(self) -> list[DomainSignal]:
        if not self._openapi:
            return []
        signals: list[DomainSignal] = []
        # Scan title
        if self._openapi.title:
            signals.extend(self._match_text(self._openapi.title, "endpoint_name"))
        # Scan schema definitions
        for schema_def in self._openapi.schemas:
            signals.extend(self._match_text(schema_def.name, "table_name"))
            for field in schema_def.fields:
                signals.extend(self._match_text(field.name, "field_name"))
        return signals

    # ── BDD scanning ───────────────────────────────────────────

    def _scan_bdd(self) -> list[DomainSignal]:
        if not self._bdd:
            return []
        signals: list[DomainSignal] = []
        # Scan feature name
        if self._bdd.feature:
            signals.extend(self._match_text(self._bdd.feature, "bdd_keyword"))
        # Scan scenarios
        for scenario in self._bdd.scenarios:
            signals.extend(self._match_text(scenario.name, "bdd_keyword"))
            # Scan raw steps
            for step_text in scenario.raw_steps:
                signals.extend(self._match_text(step_text, "bdd_keyword"))
        return signals
        return signals

    # ── Pattern matching ───────────────────────────────────────

    def _match_text(self, text: str, source: str) -> list[DomainSignal]:
        """Match text against all domain keyword patterns."""
        if not text:
            return []
        # Normalize: replace separators with spaces for matching
        normalized = text.replace("_", " ").replace("-", " ").replace("/", " ")
        signals: list[DomainSignal] = []
        seen: set[tuple[str, str]] = set()  # (domain, keyword) dedup per call
        for domain, patterns in _DOMAIN_PATTERNS.items():
            for pattern, keyword, weight in patterns:
                if pattern.search(normalized) or pattern.search(text):
                    key = (domain, keyword)
                    if key not in seen:
                        seen.add(key)
                        signals.append(DomainSignal(
                            source=source,
                            value=keyword,
                            domain=domain,
                            weight=weight,
                        ))
        return signals
