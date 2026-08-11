"""Semantic data-type detection.

Maps column names (and optionally domain context) to semantic types
like "person_name", "email", "phone", "address", "policy_id", "pan", etc.
This allows the synthetic generator to produce realistic, domain-aware values.
"""

from __future__ import annotations

import re
from enum import Enum


class SemanticType(str, Enum):
    """Semantic categories for realistic data generation."""

    # Person
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    FULL_NAME = "full_name"
    GENDER = "gender"
    DATE_OF_BIRTH = "date_of_birth"
    AGE = "age"

    # Contact
    EMAIL = "email"
    PHONE = "phone"
    MOBILE = "mobile"

    # Address
    STREET_ADDRESS = "street_address"
    CITY = "city"
    STATE = "state"
    COUNTRY = "country"
    POSTAL_CODE = "postal_code"
    FULL_ADDRESS = "full_address"

    # Financial / Banking
    ACCOUNT_NUMBER = "account_number"
    IBAN = "iban"
    SWIFT_CODE = "swift_code"
    ROUTING_NUMBER = "routing_number"
    AMOUNT = "amount"
    CURRENCY = "currency"
    CREDIT_CARD = "credit_card"

    # Insurance
    POLICY_ID = "policy_id"
    CLAIM_NUMBER = "claim_number"
    PREMIUM_AMOUNT = "premium_amount"
    COVERAGE_AMOUNT = "coverage_amount"

    # Healthcare
    PATIENT_ID = "patient_id"
    DIAGNOSIS_CODE = "diagnosis_code"
    MEDICATION_NAME = "medication_name"
    DOSAGE = "dosage"

    # Retail
    SKU = "sku"
    BARCODE = "barcode"
    PRODUCT_NAME = "product_name"

    # Identity
    PAN = "pan"
    SSN = "ssn"
    PASSPORT = "passport"
    NATIONAL_ID = "national_id"

    # Timestamps
    TIMESTAMP = "timestamp"
    DATE = "date"
    TIME = "time"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"

    # General
    UUID = "uuid"
    URL = "url"
    IP_ADDRESS = "ip_address"
    COMPANY = "company"
    DESCRIPTION = "description"

    # DevOps / Software
    STATUS = "status"
    USERNAME = "username"
    GIT_BRANCH = "git_branch"
    GIT_REPO_URL = "git_repo_url"
    HOSTNAME = "hostname"
    VERSION = "version"
    ERROR_MESSAGE = "error_message"
    ERROR_CODE = "error_code"
    SERVICE_NAME = "service_name"

    # SharePoint / OData / General metadata
    BOOLEAN = "boolean"
    MONTH = "month"
    TITLE = "title"
    INTEGER_ID = "integer_id"
    INTEGER_COUNT = "integer_count"
    INTEGER_SIZE = "integer_size"
    FILE_TYPE = "file_type"
    FILE_PATH = "file_path"
    HEX_COLOR = "hex_color"
    COLOR_NAME = "color_name"
    CONTENT_TYPE_ID = "content_type_id"
    MODERATION_STATUS = "moderation_status"
    ORDER_NUMBER = "order_number"

    # Fallback
    UNKNOWN = "unknown"


# ── Pattern → SemanticType mapping ─────────────────────────────
# Order matters: more specific patterns first.

_SEMANTIC_PATTERNS: list[tuple[re.Pattern[str], SemanticType]] = [
    # ── Boolean patterns (must be FIRST to prevent false positives) ──
    (re.compile(r"^Is[A-Z]|^Has[A-Z]|^Can[A-Z]|^Should[A-Z]|^Allow|^Enable|^Disable|^Restricted$|^Attachments$|^NoExecute$|^OData_Has", re.I), SemanticType.BOOLEAN),

    # Identity documents
    (re.compile(r"pan[_\s]?(number|no|num|id)?$", re.I), SemanticType.PAN),
    (re.compile(r"ssn|social.?security", re.I), SemanticType.SSN),
    (re.compile(r"passport[_\s]?(number|no|num|id)?$", re.I), SemanticType.PASSPORT),
    (re.compile(r"national[_\s]?id|aadhaar|aadhar|nin", re.I), SemanticType.NATIONAL_ID),

    # Person names
    (re.compile(r"first[_\s]?name|given[_\s]?name|fname", re.I), SemanticType.FIRST_NAME),
    (re.compile(r"last[_\s]?name|surname|family[_\s]?name|lname", re.I), SemanticType.LAST_NAME),
    (re.compile(r"full[_\s]?name|^name$|customer[_\s]?name|patient[_\s]?name|policyholder[_\s]?name|employee[_\s]?name|insured[_\s]?name|payee[_\s]?name|beneficiary[_\s]?name|claimant[_\s]?name|provider[_\s]?name|advisor[_\s]?name|adjuster[_\s]?name|applicant[_\s]?name|recipient[_\s]?name", re.I), SemanticType.FULL_NAME),
    (re.compile(r"gender|sex", re.I), SemanticType.GENDER),
    (re.compile(r"dob|date[_\s]?of[_\s]?birth|birth[_\s]?date", re.I), SemanticType.DATE_OF_BIRTH),
    (re.compile(r"^age$", re.I), SemanticType.AGE),

    # Contact
    (re.compile(r"email|e[_\s]?mail", re.I), SemanticType.EMAIL),
    (re.compile(r"mobile[_\s]?(number|no|phone)?$", re.I), SemanticType.MOBILE),
    (re.compile(r"phone|telephone|contact[_\s]?number|tel", re.I), SemanticType.PHONE),

    # Address
    (re.compile(r"street|address[_\s]?line|addr[_\s]?1|addr[_\s]?2", re.I), SemanticType.STREET_ADDRESS),
    (re.compile(r"^city$|city[_\s]?name", re.I), SemanticType.CITY),
    (re.compile(r"^state$|province|region", re.I), SemanticType.STATE),
    (re.compile(r"^country$|country[_\s]?name|country[_\s]?code", re.I), SemanticType.COUNTRY),
    (re.compile(r"zip[_\s]?code|postal[_\s]?code|pincode|pin[_\s]?code", re.I), SemanticType.POSTAL_CODE),
    (re.compile(r"full[_\s]?address|mailing[_\s]?address|address$", re.I), SemanticType.FULL_ADDRESS),

    # Financial
    (re.compile(r"account[_\s]?(number|no|num|id)", re.I), SemanticType.ACCOUNT_NUMBER),
    (re.compile(r"^iban$", re.I), SemanticType.IBAN),
    (re.compile(r"swift[_\s]?code|bic", re.I), SemanticType.SWIFT_CODE),
    (re.compile(r"routing[_\s]?(number|no|num)", re.I), SemanticType.ROUTING_NUMBER),
    (re.compile(r"currency[_\s]?(code)?$", re.I), SemanticType.CURRENCY),
    (re.compile(r"credit[_\s]?card|card[_\s]?number|cc[_\s]?num", re.I), SemanticType.CREDIT_CARD),

    # Insurance (before generic amount so premium_amount matches here)
    (re.compile(r"policy[_\s]?(id|number|no|num)", re.I), SemanticType.POLICY_ID),
    (re.compile(r"claim[_\s]?(id|number|no|num)", re.I), SemanticType.CLAIM_NUMBER),
    (re.compile(r"premium[_\s]?(amount)?$", re.I), SemanticType.PREMIUM_AMOUNT),
    (re.compile(r"coverage[_\s]?(amount)?$", re.I), SemanticType.COVERAGE_AMOUNT),

    # Healthcare
    (re.compile(r"patient[_\s]?(id|number|no)", re.I), SemanticType.PATIENT_ID),
    (re.compile(r"diagnosis[_\s]?code|icd[_\s]?code|icd", re.I), SemanticType.DIAGNOSIS_CODE),
    (re.compile(r"medication[_\s]?(name)?$|drug[_\s]?(name)?$", re.I), SemanticType.MEDICATION_NAME),
    (re.compile(r"dosage|dose", re.I), SemanticType.DOSAGE),

    # Retail
    (re.compile(r"^sku$|sku[_\s]?(code|id|number)", re.I), SemanticType.SKU),
    (re.compile(r"barcode|upc|ean", re.I), SemanticType.BARCODE),
    (re.compile(r"product[_\s]?name|item[_\s]?name", re.I), SemanticType.PRODUCT_NAME),

    # SharePoint / OData metadata (before generic patterns)
    (re.compile(r"ContentTypeId", re.I), SemanticType.CONTENT_TYPE_ID),
    (re.compile(r"ModerationStatus|VirusStatus", re.I), SemanticType.MODERATION_STATUS),
    (re.compile(r"Color.?Hex|_ColorHex", re.I), SemanticType.HEX_COLOR),
    (re.compile(r"Color.?Tag|_ColorTag", re.I), SemanticType.COLOR_NAME),
    (re.compile(r"File.*Type$|FileType", re.I), SemanticType.FILE_TYPE),
    (re.compile(r"File.?Ref|Dir.?Ref|FileLeafRef", re.I), SemanticType.FILE_PATH),
    (re.compile(r"FSObjType|SortBehavior", re.I), SemanticType.INTEGER_COUNT),
    (re.compile(r"Case[_\s]?ID|Case[_\s]?Id|CaseId", re.I), SemanticType.CLAIM_NUMBER),
    (re.compile(r"RAG[_\s]?Status|RAG$|ForcastedRAG|ForecastedRAG", re.I), SemanticType.COLOR_NAME),
    (re.compile(r"Comments$|ModerationComments", re.I), SemanticType.DESCRIPTION),
    (re.compile(r"CommentFlags", re.I), SemanticType.INTEGER_COUNT),
    (re.compile(r"Plan_to_Return|ReturnPlan|ActionPlan", re.I), SemanticType.DESCRIPTION),
    (re.compile(r"Emoji$|_Emoji$", re.I), SemanticType.DESCRIPTION),
    (re.compile(r"ComplianceAssetId|AssetId", re.I), SemanticType.UUID),
    (re.compile(r"OKR[_\s]?ID|OKRID", re.I), SemanticType.CLAIM_NUMBER),

    # Dates/Times (must be before generic amount to not match date words)
    (re.compile(r"^Created$|^Created_Date$|^Created_x0020_Date$|creation[_\s]?(date|time)", re.I), SemanticType.CREATED_AT),
    (re.compile(r"^Modified$|^Last_Modified$|^Last_x0020_Modified$|updated[_\s]?(at|on|date|time)|modified[_\s]?(at|on|date|time)", re.I), SemanticType.UPDATED_AT),
    (re.compile(r"created[_\s]?(at|on|date|time)", re.I), SemanticType.CREATED_AT),
    (re.compile(r"Date_|_Date$|_date$|^date$|When.*Date|Date.*When", re.I), SemanticType.DATE),
    (re.compile(r"^Month$", re.I), SemanticType.MONTH),
    (re.compile(r"^timestamp$|^datetime$|_timestamp$|_datetime$", re.I), SemanticType.TIMESTAMP),
    (re.compile(r"^time$|time[_\s]?of", re.I), SemanticType.TIME),

    # Generic financial (after domain-specific patterns)
    (re.compile(r"amount|balance|price|cost|fee", re.I), SemanticType.AMOUNT),

    # Count / Size / Order (integer-valued)
    (re.compile(r"Count$|_Count$|ChildCount$|FileCount$", re.I), SemanticType.INTEGER_COUNT),
    (re.compile(r"Size$|_Size$|StreamSize$", re.I), SemanticType.INTEGER_SIZE),
    (re.compile(r"^Order$|^sort.?order|^sequence$|^seq$", re.I), SemanticType.ORDER_NUMBER),
    (re.compile(r"^ID$|^id$", re.I), SemanticType.INTEGER_ID),
    (re.compile(r"^Title$", re.I), SemanticType.TITLE),

    # General identifiers
    (re.compile(r"UniqueId|ParentUniqueId|uuid|guid|^GUID$", re.I), SemanticType.UUID),
    (re.compile(r"(scm[_\s]?)?repo[_\s]?(url|link|uri)", re.I), SemanticType.GIT_REPO_URL),
    (re.compile(r"url|website|link|href", re.I), SemanticType.URL),
    (re.compile(r"ip[_\s]?address|ip$", re.I), SemanticType.IP_ADDRESS),
    (re.compile(r"company|org[_\s]?name|organization", re.I), SemanticType.COMPANY),
    (re.compile(r"^description$|^note$|^remark$|^bio$", re.I), SemanticType.DESCRIPTION),

    # DevOps / Software patterns
    (re.compile(r"(scm[_\s]?)?branch|git[_\s]?branch", re.I), SemanticType.GIT_BRANCH),
    (re.compile(r"host[_\s]?name|hostname|server[_\s]?name", re.I), SemanticType.HOSTNAME),
    (re.compile(r"(agent[_\s]?)?version|app[_\s]?version|api[_\s]?version|^version$|Version$", re.I), SemanticType.VERSION),
    (re.compile(r"error[_\s]?message|err[_\s]?msg|exception[_\s]?message", re.I), SemanticType.ERROR_MESSAGE),
    (re.compile(r"error[_\s]?(code|type)|err[_\s]?(code|type)", re.I), SemanticType.ERROR_CODE),
    (re.compile(r"^status$|_status$", re.I), SemanticType.STATUS),
    (re.compile(r"(created|updated|modified|last_updated|executed|requested|approved|reviewed|assigned|processed|handled|verified|adjudicated)[_\s]?by$", re.I), SemanticType.USERNAME),
    (re.compile(r"user[_\s]?name|username|login[_\s]?name|^author$|^editor$|^owner$|Updated_By", re.I), SemanticType.USERNAME),

    # Descriptive name fields (agent_name, display_name, project_name, etc.)
    # Must be AFTER person name patterns (first_name, last_name, full_name)
    (re.compile(r"(agent|service|module|component|app|application|project|pipeline|job|task|scan|tool|display)[_\s]?name", re.I), SemanticType.SERVICE_NAME),
]


def detect_semantic_type(column_name: str, domain: str = "unknown") -> SemanticType:
    """Detect the semantic type of a column from its name and optional domain context.

    Args:
        column_name: The column/field name to analyze.
        domain: Detected business domain (banking, insurance, healthcare, retail).

    Returns:
        The most specific SemanticType that matches.
    """
    normalized = column_name.strip()

    for pattern, sem_type in _SEMANTIC_PATTERNS:
        if pattern.search(normalized):
            return sem_type

    # Domain-aware fallbacks: column names that are ambiguous without domain context
    if domain == "banking":
        if re.search(r"^account$", normalized, re.I):
            return SemanticType.ACCOUNT_NUMBER
    elif domain == "insurance":
        if re.search(r"^policy$", normalized, re.I):
            return SemanticType.POLICY_ID
        if re.search(r"^claim$", normalized, re.I):
            return SemanticType.CLAIM_NUMBER
    elif domain == "healthcare":
        if re.search(r"^patient$", normalized, re.I):
            return SemanticType.PATIENT_ID

    return SemanticType.UNKNOWN
