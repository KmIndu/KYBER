"""Context-aware column value inference.

Resolves column meaning by considering the FULL context:
- table name (e.g., "vuln_scan_result" implies security scanning domain)
- column name (e.g., "pr_url" = pull request URL)
- neighboring columns (e.g., "vulns_critical_before" implies a count)
- common jargon/abbreviations in software engineering

This module provides a pool of realistic values for each inferred context,
which the generator uses BEFORE falling back to generic Faker/random.
"""

from __future__ import annotations

import random
import string
import uuid
from typing import Any, Callable


# ── Jargon resolution table ──────────────────────────────────
# Maps abbreviations/jargon to their full meaning for value generation

_JARGON: dict[str, str] = {
    "pr": "pull_request",
    "scm": "source_control",
    "repo": "repository",
    "vuln": "vulnerability",
    "vulns": "vulnerabilities",
    "org": "organization",
    "env": "environment",
    "ms": "milliseconds",
    "seq": "sequence",
    "ref": "reference",
    "ext": "extension",
    "exec": "execution",
    "err": "error",
    "cfg": "config",
    "num": "number",
    "amt": "amount",
    "dur": "duration",
    "ts": "timestamp",
    "idx": "index",
    "cnt": "count",
    "qty": "quantity",
    "desc": "description",
    "msg": "message",
    "param": "parameter",
    "params": "parameters",
    "iter": "iteration",
    "fp": "false_positive",
    "cx": "checkmarx",
    "sast": "static_analysis",
    "dast": "dynamic_analysis",
    "sca": "software_composition_analysis",
    "iac": "infrastructure_as_code",
    "ci": "continuous_integration",
    "cd": "continuous_deployment",
    "cve": "vulnerability_id",
}


# ── Context value pools ──────────────────────────────────────
# Each pool is a callable(n) -> list[Any] that generates n values

def _pool_ai_models(n: int) -> list[str]:
    models = [
        "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo", "claude-3-opus",
        "claude-3-sonnet", "claude-3-haiku", "gemini-1.5-pro",
        "gemini-1.5-flash", "llama-3-70b", "mixtral-8x7b",
        "codellama-34b", "deepseek-coder-33b", "claude-opus-4",
    ]
    return [random.choice(models) for _ in range(n)]


def _pool_scan_tools(n: int) -> list[str]:
    tools = [
        "Checkmarx", "Snyk", "SonarQube", "Veracode", "Fortify",
        "Trivy", "Grype", "OWASP ZAP", "Semgrep", "CodeQL",
        "Bandit", "Dependabot", "BlackDuck", "WhiteSource", "Prisma Cloud",
    ]
    return [random.choice(tools) for _ in range(n)]


def _pool_step_types(n: int) -> list[str]:
    types = [
        "clone_repo", "install_dependencies", "run_scan", "parse_results",
        "generate_fix", "apply_patch", "run_tests", "validate_build",
        "create_branch", "commit_changes", "create_pr", "notify",
        "analyze_cve", "resolve_dependency", "update_config",
        "rollback", "retry", "cleanup", "upload_report",
    ]
    return [random.choice(types) for _ in range(n)]


def _pool_parameter_names(n: int) -> list[str]:
    names = [
        "target_branch", "source_branch", "repo_url", "scan_type",
        "severity_threshold", "max_retries", "timeout_seconds",
        "output_format", "include_devDependencies", "fix_mode",
        "pr_title_prefix", "commit_message_template", "api_key",
        "project_id", "organization_id", "scan_policy",
        "ignore_patterns", "file_extensions", "language",
        "framework_version", "build_command", "test_command",
    ]
    return [random.choice(names) for _ in range(n)]


def _pool_parameter_values(n: int) -> list[str]:
    values = [
        "main", "true", "false", "high", "critical", "json",
        "3", "30", "60", "120", "yaml", "sarif",
        "/src/**/*.java", "npm test", "mvn clean verify",
        "fix:", "chore(deps):", "auto", "manual",
        "https://api.snyk.io/v1", "all", "production",
        "2.4.1", "3.0.0", "latest", "^2.0.0",
    ]
    return [random.choice(values) for _ in range(n)]


def _pool_subject_refs(n: int) -> list[str]:
    refs = []
    for _ in range(n):
        kind = random.choice(["cve", "file", "dep", "package"])
        if kind == "cve":
            refs.append(f"CVE-{random.randint(2020, 2026)}-{random.randint(1000, 99999)}")
        elif kind == "file":
            paths = [
                "src/main/java/com/app/SecurityConfig.java",
                "pom.xml", "package.json", "build.gradle",
                "Dockerfile", "requirements.txt", "go.mod",
                "src/utils/auth.ts", "lib/http_client.rb",
                ".github/workflows/ci.yml",
            ]
            refs.append(random.choice(paths))
        elif kind == "dep":
            deps = [
                "org.apache.logging.log4j:log4j-core",
                "com.fasterxml.jackson.core:jackson-databind",
                "org.springframework:spring-web",
                "lodash@4.17.20", "express@4.18.2",
                "axios@1.4.0", "django==4.2.1",
                "numpy==1.24.0", "requests==2.31.0",
            ]
            refs.append(random.choice(deps))
        else:
            refs.append(f"pkg:npm/{random.choice(['lodash', 'express', 'axios', 'webpack', 'react'])}@{random.randint(1,5)}.{random.randint(0,20)}.{random.randint(0,10)}")
    return refs


def _pool_notes(n: int) -> list[str]:
    notes = [
        "Successfully cloned repository and checked out target branch",
        "Scan completed with 0 new critical findings",
        "Applied automated fix for CVE — all tests passing",
        "Dependency version bumped from 2.3.1 to 2.4.0",
        "Build validation passed — no regressions detected",
        "PR created and assigned to security team for review",
        "Retry attempt 2/3 after transient network error",
        "Skipped — vulnerability already marked as false positive",
        "Fix conflicts detected — manual review required",
        "Rollback triggered due to failing integration tests",
        "Configuration updated for new scan policy",
        "Report uploaded to compliance dashboard",
        "Waiting for approval from security lead",
        "Resolved 3 of 5 critical vulnerabilities automatically",
        "Test coverage increased from 72% to 78% after fix",
    ]
    return [random.choice(notes) for _ in range(n)]


def _pool_pr_urls(n: int) -> list[str]:
    orgs = ["acme-corp", "sunlife", "fintech-labs", "cloudops", "security-team"]
    repos = ["api-gateway", "auth-service", "payment-engine", "scan-orchestrator",
             "remediation-agent", "config-server", "data-pipeline"]
    hosts = ["github.com", "bitbucket.org", "gitlab.com", "bitbucket.sunlifecorp.com"]
    urls = []
    for _ in range(n):
        host = random.choice(hosts)
        org = random.choice(orgs)
        repo = random.choice(repos)
        pr_num = random.randint(100, 9999)
        if "bitbucket" in host:
            urls.append(f"https://{host}/{org}/{repo}/pull-requests/{pr_num}")
        elif "gitlab" in host:
            urls.append(f"https://{host}/{org}/{repo}/-/merge_requests/{pr_num}")
        else:
            urls.append(f"https://{host}/{org}/{repo}/pull/{pr_num}")
    return urls


# ── Correlated data tables ────────────────────────────────────
# Maps related columns together so they produce coherent row-level data.

_CORRELATED_ORGS: dict[str, str] = {
    "SLF": "Sun Life Financial",
    "SLE": "Sun Life Engineering",
    "PLATSEC": "Platform Security",
    "CLOUDOPS": "Cloud Operations",
    "DEVSECOPS": "DevSecOps Team",
    "APPMOD": "Application Modernization",
    "COREBANK": "Core Banking",
    "DIGIPAY": "Digital Payments",
    "RISKCOMP": "Risk & Compliance",
    "DATAENG": "Data Engineering",
    "INFRA": "Infrastructure",
    "SRE": "SRE Team",
    "QA": "Quality Assurance",
    "FINTECH": "FinTech Labs",
    "IDSVC": "Identity Services",
}


def _pool_org_ids(n: int) -> list[str]:
    """Generate org IDs that are short abbreviations (NOT random UUIDs)."""
    # These are correlated with org_names via _CORRELATED_ORGS
    orgs = list(_CORRELATED_ORGS.keys())
    return [random.choice(orgs) for _ in range(n)]


def _pool_org_names(n: int) -> list[str]:
    names = list(_CORRELATED_ORGS.values())
    return [random.choice(names) for _ in range(n)]


def _pool_project_names(n: int) -> list[str]:
    names = [
        "api-gateway", "auth-service", "payment-engine", "scan-orchestrator",
        "remediation-agent", "config-server", "data-pipeline", "user-portal",
        "notification-service", "audit-logger", "identity-provider",
        "risk-engine", "fraud-detection", "claims-processor", "policy-manager",
        "document-service", "event-bus", "workflow-engine", "report-generator",
        "compliance-checker", "metrics-aggregator", "cache-layer",
    ]
    return [random.choice(names) for _ in range(n)]


def _pool_project_ids(n: int) -> list[str]:
    return [str(uuid.uuid4()) for _ in range(n)]


def _pool_scan_ids(n: int) -> list[str]:
    return [str(uuid.uuid4()) for _ in range(n)]


def _pool_scan_types(n: int) -> list[str]:
    types_pool = [
        "SAST", "SCA", "SAST,SCA", "DAST", "IaC", "Secrets",
        "SAST,SCA,Secrets", "Container", "License", "SAST,IaC",
    ]
    return [random.choice(types_pool) for _ in range(n)]


def _pool_agent_codes(n: int) -> list[str]:
    codes = [
        "VULN_SCANNER", "CODE_ANALYZER", "DEP_RESOLVER", "SEC_REMEDIATOR",
        "BUILD_AGENT", "TEST_RUNNER", "DEPLOY_AGENT", "CONFIG_MGR",
        "METRICS_AGENT", "LOG_COLLECTOR", "ALERT_MONITOR", "COMPLIANCE_CHK",
        "PR_REVIEWER", "LICENSE_SCAN", "SECRET_DETECT", "CONTAINER_SCAN",
        "SAST_AGENT", "DAST_AGENT", "SCA_AGENT", "IAC_VALIDATOR",
    ]
    return [random.choice(codes) for _ in range(n)]


def _pool_vuln_counts(n: int) -> list[int]:
    """Vulnerability counts — skewed toward low numbers (most scans find few)."""
    return [_skewed_vuln_count() for _ in range(n)]


def _skewed_vuln_count() -> int:
    r = random.random()
    if r < 0.4:
        return 0
    elif r < 0.7:
        return random.randint(1, 5)
    elif r < 0.9:
        return random.randint(5, 20)
    else:
        return random.randint(20, 100)


def _pool_duration_ms(n: int) -> list[int]:
    """Execution durations — range from quick ops to long scans."""
    return [random.choice([
        random.randint(50, 500),       # quick
        random.randint(500, 5000),     # medium
        random.randint(5000, 30000),   # long
        random.randint(30000, 300000), # very long
    ]) for _ in range(n)]


def _pool_sequence(n: int) -> list[int]:
    """Pipeline stage sequence numbers — typically 1-10."""
    return [random.randint(1, 10) for _ in range(n)]


def _pool_small_count(n: int) -> list[int]:
    """Small counts (iterations, skipped, false positives) — typically 0-20."""
    r = random.random
    return [int(r() * 15) for _ in range(n)]


def _pool_premium_requests(n: int) -> list[int]:
    """AI premium request consumption — 1-50 per execution."""
    return [random.randint(1, 50) for _ in range(n)]


# ── General-purpose pools (non-DevOps) ───────────────────────

_OFFICE_BRANCHES = [
    "Toronto Downtown", "Montreal", "Vancouver", "Calgary", "Ottawa",
    "Waterloo", "Halifax", "Winnipeg", "Edmonton", "Victoria",
    "Mississauga", "Brampton", "Hamilton", "London", "Quebec City",
    "New York", "Boston", "Chicago", "San Francisco", "Dallas",
    "Philadelphia", "Atlanta", "Denver", "Seattle", "Miami",
]

_LICENSE_PREFIXES = ["LIC", "AG", "INS", "BRK", "FIN", "REG", "CRT"]


def _pool_office_branches(n: int) -> list[str]:
    return [random.choice(_OFFICE_BRANCHES) for _ in range(n)]


def _pool_license_numbers(n: int) -> list[str]:
    """Professional license numbers like LIC-2024-12345."""
    results = []
    for _ in range(n):
        prefix = random.choice(_LICENSE_PREFIXES)
        year = random.randint(2018, 2026)
        num = random.randint(10000, 99999)
        results.append(f"{prefix}-{year}-{num}")
    return results


def _pool_commission_rates(n: int) -> list[float]:
    """Commission rates as decimal percentages (0.02 - 0.15)."""
    return [round(random.uniform(0.02, 0.15), 4) for _ in range(n)]


def _pool_claim_numbers(n: int) -> list[str]:
    """Insurance claim numbers like CLM-2024-00123."""
    results = []
    for i in range(n):
        year = random.randint(2022, 2026)
        seq = random.randint(10000, 99999)
        results.append(f"CLM-{year}-{seq:05d}")
    return results


def _pool_policy_numbers(n: int) -> list[str]:
    """Insurance policy numbers like POL-2023-A12345."""
    prefixes = ["POL", "PLY", "INS"]
    results = []
    for _ in range(n):
        prefix = random.choice(prefixes)
        year = random.randint(2020, 2026)
        letter = random.choice("ABCDEFGH")
        num = random.randint(10000, 99999)
        results.append(f"{prefix}-{year}-{letter}{num}")
    return results


def _pool_reference_numbers(n: int) -> list[str]:
    """Payment/transaction reference numbers."""
    results = []
    for _ in range(n):
        kind = random.choice(["REF", "TXN", "PAY", "EFT", "CHQ"])
        num = random.randint(100000000, 999999999)
        results.append(f"{kind}-{num}")
    return results


def _pool_denial_reasons(n: int) -> list[str]:
    """Insurance claim denial reasons."""
    reasons = [
        "Pre-existing condition not covered",
        "Policy lapsed due to non-payment",
        "Claim filed after deadline",
        "Insufficient supporting documentation",
        "Service not covered under current plan",
        "Duplicate claim submission",
        "Maximum benefit limit exceeded",
        "Waiting period not yet satisfied",
        "Incident occurred outside coverage period",
        "Exclusion clause applies",
        "Fraudulent claim detected",
        "Non-disclosure of material facts",
        "Claim amount exceeds policy limit",
        "Treatment not medically necessary",
        "Provider not in network",
    ]
    return [random.choice(reasons) for _ in range(n)]


# ── Domain-aware notes/comments pools ─────────────────────────

_INSURANCE_NOTES = [
    "Awaiting additional documentation from policyholder",
    "Medical records received and under review",
    "Approved after manager escalation",
    "Claim amount verified against policy limits",
    "Beneficiary verification completed",
    "Adjuster site visit scheduled",
    "Payment processed and sent to claimant",
    "Pending third-party liability assessment",
    "Policy coverage confirmed for incident type",
    "Claimant contacted for clarification",
    "Subrogation process initiated",
    "Final settlement offer accepted by claimant",
    "Reinsurance notification sent",
    "Compliance review passed",
    "Escalated to senior claims adjuster",
    "Waiting for police report",
    "Independent medical examination requested",
    "Repair estimate received from vendor",
    "Deductible applied to settlement amount",
    "Fraud investigation cleared — no concerns",
]

_BANKING_NOTES = [
    "KYC verification completed successfully",
    "Transaction flagged for manual review",
    "Account holder identity confirmed",
    "Pending compliance officer approval",
    "Wire transfer processed — confirmation sent",
    "Insufficient funds — transaction declined",
    "Interest rate adjustment applied",
    "Loan disbursement approved by credit committee",
    "Collateral valuation report received",
    "Payment scheduled for next business day",
    "Overdraft fee waived per customer request",
    "Account frozen pending investigation",
    "Direct deposit configuration updated",
    "Credit limit increase approved",
    "Dispute resolution in progress",
    "Statement discrepancy resolved",
    "Mortgage prepayment penalty calculated",
    "Account closure request — pending final settlement",
    "Tax withholding documentation received",
    "Regulatory reporting filed for large transaction",
]

_GENERAL_NOTES = [
    "Reviewed and approved",
    "Pending further information from requester",
    "Escalated to supervisor for review",
    "Completed — no further action required",
    "On hold — awaiting third-party response",
    "Reassigned to department lead",
    "Verified against source documentation",
    "Follow-up scheduled for next week",
    "Processed within SLA",
    "Exception granted per management approval",
    "Returned for corrections",
    "Batch processing completed without errors",
    "Manual override applied with justification",
    "Quality check passed",
    "Flagged for audit trail",
]


def _pool_insurance_notes(n: int) -> list[str]:
    return [random.choice(_INSURANCE_NOTES) for _ in range(n)]


def _pool_banking_notes(n: int) -> list[str]:
    return [random.choice(_BANKING_NOTES) for _ in range(n)]


def _pool_general_notes(n: int) -> list[str]:
    return [random.choice(_GENERAL_NOTES) for _ in range(n)]


# ── Domain inference for context-aware notes ──────────────────
# Instead of hardcoding table names per domain, we detect the domain
# from table name keywords dynamically.

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "insurance": [
        "claim", "policy", "beneficiar", "underwrit", "premium", "coverage",
        "insured", "adjuster", "deductible", "endorsement", "rider",
        "actuar", "reinsur", "disbursement", "settlement", "adjudicat",
    ],
    "banking": [
        "transaction", "account", "transfer", "ledger", "deposit", "withdraw",
        "loan", "mortgage", "credit", "debit", "balance", "interest",
        "wire", "cheque", "check", "remittance", "forex",
    ],
    "healthcare": [
        "patient", "diagnosis", "prescription", "appointment", "doctor",
        "hospital", "medical", "clinical", "treatment", "referral",
        "lab_result", "discharge", "admission", "nurse", "pharmacy",
    ],
    "hr": [
        "employee", "payroll", "leave", "attendance", "performance",
        "recruitment", "onboarding", "appraisal", "training", "grievance",
        "termination", "promotion", "department", "salary", "benefit",
    ],
    "ecommerce": [
        "order", "cart", "product", "shipping", "inventory", "catalog",
        "customer", "return", "refund", "wishlist", "coupon", "discount",
        "fulfillment", "warehouse", "supplier",
    ],
    "devops": [
        "execution", "scan", "pipeline", "deploy", "build", "release",
        "agent_execution", "agent_error", "vuln", "remediation",
        "ci_cd", "container", "kubernetes", "terraform",
    ],
}

_DOMAIN_NOTES: dict[str, list[str]] = {
    "insurance": _INSURANCE_NOTES,
    "banking": _BANKING_NOTES,
    "healthcare": [
        "Patient vitals within normal range",
        "Lab results pending — follow-up in 48 hours",
        "Prescription renewed for 90 days",
        "Referred to specialist for further evaluation",
        "Insurance pre-authorization obtained",
        "Treatment plan discussed with patient",
        "Discharge instructions provided to family",
        "Awaiting radiology report",
        "Second opinion requested by patient",
        "Follow-up appointment scheduled in 2 weeks",
        "Medication adjustment based on lab values",
        "Patient non-compliant with prescribed treatment",
        "Emergency admission — stabilized",
        "Post-operative recovery progressing well",
        "Allergy information updated in system",
    ],
    "hr": [
        "Probation period completed successfully",
        "Performance review submitted — meets expectations",
        "Leave request approved by manager",
        "Training certification completed",
        "Salary revision effective next pay cycle",
        "Disciplinary warning issued — documented",
        "Background check cleared",
        "Onboarding checklist completed",
        "Exit interview scheduled",
        "Transfer request approved — effective next month",
        "Benefits enrollment confirmed",
        "Overtime hours approved for project deadline",
        "Grievance filed — under HR investigation",
        "Promotion recommendation submitted to committee",
        "Work-from-home arrangement approved",
    ],
    "ecommerce": [
        "Order confirmed — awaiting fulfillment",
        "Shipped via express — tracking number sent",
        "Return request approved — label generated",
        "Refund processed to original payment method",
        "Item back in stock — customer notified",
        "Delivery attempted — customer not available",
        "Payment verification pending",
        "Gift wrapping applied per customer request",
        "Coupon applied — discount reflected",
        "Inventory reserved for 24 hours",
        "Partial shipment — remaining items backordered",
        "Customer dispute opened with payment provider",
        "Delivery confirmed — signature obtained",
        "Exchange processed — new item shipping",
        "Subscription renewal processed",
    ],
    "devops": _INSURANCE_NOTES,  # placeholder, overwritten below
}
_DOMAIN_NOTES["devops"] = [
    "Successfully cloned repository and checked out target branch",
    "Scan completed with 0 new critical findings",
    "Applied automated fix for CVE — all tests passing",
    "Dependency version bumped from 2.3.1 to 2.4.0",
    "Build validation passed — no regressions detected",
    "PR created and assigned to security team for review",
    "Retry attempt 2/3 after transient network error",
    "Skipped — vulnerability already marked as false positive",
    "Fix conflicts detected — manual review required",
    "Rollback triggered due to failing integration tests",
    "Configuration updated for new scan policy",
    "Report uploaded to compliance dashboard",
    "Waiting for approval from security lead",
    "Resolved 3 of 5 critical vulnerabilities automatically",
    "Test coverage increased from 72% to 78% after fix",
]


def _infer_domain(table_name: str) -> str:
    """Infer the business domain from the table name.

    Returns the domain key (insurance, banking, healthcare, hr, ecommerce, devops)
    or 'general' if no domain matches.
    """
    tbl = table_name.lower()
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw in tbl:
                return domain
    return "general"


def _pool_contextual_notes(n: int, table_name: str = "") -> list[str]:
    """Generate notes appropriate to the table's business domain."""
    domain = _infer_domain(table_name)
    notes = _DOMAIN_NOTES.get(domain, _GENERAL_NOTES)
    return [random.choice(notes) for _ in range(n)]


# ── Context resolution rules ─────────────────────────────────
# Rules: (table_pattern, column_pattern) → pool_function
# Patterns are checked with `in` for table and column substring matching.
# More specific rules first.

_CONTEXT_RULES: list[tuple[str | None, str, Callable[[int], list[Any]]]] = [
    # Pull request URLs
    (None, "pr_url", _pool_pr_urls),
    (None, "pr_link", _pool_pr_urls),
    (None, "pull_request_url", _pool_pr_urls),

    # AI model names
    (None, "ai_model", _pool_ai_models),
    (None, "model_name", _pool_ai_models),
    (None, "llm_model", _pool_ai_models),

    # Scan tools
    (None, "scan_tool", _pool_scan_tools),
    (None, "scanner_name", _pool_scan_tools),

    # Step types
    (None, "step_type", _pool_step_types),
    (None, "action_type", _pool_step_types),

    # Parameter names
    ("parameter_name", "parameter_name", _pool_parameter_names),
    (None, "param_name", _pool_parameter_names),

    # Parameter values
    (None, "parameter_value", _pool_parameter_values),
    (None, "param_value", _pool_parameter_values),

    # Subject references (CVEs, files, dependencies)
    (None, "subject_ref", _pool_subject_refs),

    # Payment/transaction reference numbers
    (None, "reference_number", _pool_reference_numbers),
    (None, "reference_no", _pool_reference_numbers),
    (None, "ref_number", _pool_reference_numbers),
    (None, "transaction_ref", _pool_reference_numbers),

    # Denial/rejection reasons (insurance)
    (None, "denial_reason", _pool_denial_reasons),
    (None, "reject_reason", _pool_denial_reasons),
    (None, "rejection_reason", _pool_denial_reasons),
    (None, "decline_reason", _pool_denial_reasons),

    # Claim numbers
    (None, "claim_number", _pool_claim_numbers),
    (None, "claim_no", _pool_claim_numbers),
    (None, "claim_ref", _pool_claim_numbers),

    # Policy numbers
    (None, "policy_number", _pool_policy_numbers),
    (None, "policy_no", _pool_policy_numbers),
    (None, "policy_ref", _pool_policy_numbers),

    # Organization
    (None, "org_id", _pool_org_ids),
    (None, "org_name", _pool_org_names),
    (None, "organization_name", _pool_org_names),

    # Project / scan IDs (UUID-style)
    (None, "project_name", _pool_project_names),
    (None, "repo_name", _pool_project_names),
    (None, "repository_name", _pool_project_names),
    (None, "project_id", _pool_project_ids),
    (None, "scan_id", _pool_scan_ids),
    ("checkmarx", "scan_types", _pool_scan_types),
    (None, "scan_types", _pool_scan_types),
    (None, "scan_type", _pool_scan_types),

    # Agent/service codes
    ("agent_type", "code", _pool_agent_codes),
    (None, "agent_code", _pool_agent_codes),
    (None, "type_code", _pool_agent_codes),

    # Vulnerability counts (columns with "vulns_" prefix)
    (None, "vulns_", _pool_vuln_counts),

    # Duration in ms
    (None, "duration_ms", _pool_duration_ms),
    (None, "execution_duration", _pool_duration_ms),
    (None, "elapsed_ms", _pool_duration_ms),

    # Sequence / stage numbers
    (None, "sequence", _pool_sequence),
    (None, "step_number", _pool_sequence),
    (None, "stage_number", _pool_sequence),

    # Small integer counts
    (None, "fix_iterations", _pool_small_count),
    (None, "false_positives", _pool_small_count),
    (None, "vulns_skipped", _pool_small_count),
    (None, "retry_count", _pool_small_count),

    # Premium/token consumption
    (None, "premium_requests", _pool_premium_requests),
    (None, "tokens_consumed", _pool_premium_requests),
    (None, "requests_consumed", _pool_premium_requests),

    # ── General / non-DevOps patterns ──

    # License numbers (insurance, financial, regulatory)
    (None, "license_number", _pool_license_numbers),
    (None, "license_no", _pool_license_numbers),
    (None, "licence_number", _pool_license_numbers),

    # Commission rates (financial/insurance)
    (None, "commission_rate", _pool_commission_rates),
    (None, "commission_pct", _pool_commission_rates),

    # Office branch (only when table context is NOT DevOps/git)
    # These trigger for agent/employee/advisor/broker tables
    ("agent", "branch", _pool_office_branches),
    ("employee", "branch", _pool_office_branches),
    ("advisor", "branch", _pool_office_branches),
    ("broker", "branch", _pool_office_branches),
    ("staff", "branch", _pool_office_branches),
    ("office", "branch", _pool_office_branches),
    ("rep", "branch", _pool_office_branches),
]


# ── Public API ────────────────────────────────────────────────


def resolve_contextual_values(
    table_name: str,
    column_name: str,
    n: int,
) -> list[Any] | None:
    """Resolve realistic values based on table + column context.

    Returns a list of n values if a contextual rule matches,
    or None if no context match is found (fall through to semantic types).
    """
    col_lower = column_name.lower()
    tbl_lower = table_name.lower()

    # ── Notes/comments: domain-inferred (not hardcoded) ──
    # Only match explicit notes/comment columns, not generic "description" or "reason"
    _NOTE_COL_PATTERNS = ("notes", "comment", "remarks", "observation")
    # Columns with these suffixes are numeric/metadata, not text content
    _NOTE_COL_SKIP = ("count", "flag", "id", "size", "num")
    for pattern in _NOTE_COL_PATTERNS:
        if pattern in col_lower:
            # Skip if column name indicates numeric/metadata field
            if any(skip in col_lower for skip in _NOTE_COL_SKIP):
                break
            return _pool_contextual_notes(n, table_name)

    # ── Static context rules ──
    for tbl_pattern, col_pattern, pool_fn in _CONTEXT_RULES:
        # Check column match
        if col_pattern not in col_lower:
            continue
        # Check table match (if specified)
        if tbl_pattern is not None and tbl_pattern not in tbl_lower:
            continue
        return pool_fn(n)

    return None


# ── Correlated column groups ──────────────────────────────────
# Defines groups of columns that must be generated together (row-level coherence).
# Each entry: (table_pattern | None, {col_pattern: field_key}, generator_fn)
# generator_fn(n) returns list[dict[field_key, value]]

_CORRELATED_PROJECTS: list[dict[str, str]] = [
    {"id": "PRJ-001", "name": "api-gateway"},
    {"id": "PRJ-002", "name": "auth-service"},
    {"id": "PRJ-003", "name": "payment-engine"},
    {"id": "PRJ-004", "name": "scan-orchestrator"},
    {"id": "PRJ-005", "name": "remediation-agent"},
    {"id": "PRJ-006", "name": "config-server"},
    {"id": "PRJ-007", "name": "data-pipeline"},
    {"id": "PRJ-008", "name": "user-portal"},
    {"id": "PRJ-009", "name": "notification-service"},
    {"id": "PRJ-010", "name": "identity-provider"},
    {"id": "PRJ-011", "name": "risk-engine"},
    {"id": "PRJ-012", "name": "fraud-detection"},
    {"id": "PRJ-013", "name": "claims-processor"},
    {"id": "PRJ-014", "name": "policy-manager"},
    {"id": "PRJ-015", "name": "compliance-checker"},
]


def _gen_correlated_orgs(n: int) -> list[dict[str, str]]:
    """Generate n rows with correlated org_id + org_name."""
    items = list(_CORRELATED_ORGS.items())
    return [
        {"org_id": pair[0], "org_name": pair[1]}
        for pair in random.choices(items, k=n)
    ]


def _gen_correlated_projects(n: int) -> list[dict[str, str]]:
    """Generate n rows with correlated project_id + project_name."""
    return random.choices(_CORRELATED_PROJECTS, k=n)


# ── Person name + email correlation ──────────────────────────

_FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael",
    "Linda", "David", "Elizabeth", "William", "Barbara", "Richard", "Susan",
    "Joseph", "Jessica", "Thomas", "Sarah", "Christopher", "Karen",
    "Daniel", "Lisa", "Matthew", "Nancy", "Anthony", "Betty", "Mark",
    "Margaret", "Donald", "Sandra", "Steven", "Ashley", "Paul", "Dorothy",
    "Andrew", "Kimberly", "Joshua", "Emily", "Kenneth", "Donna",
    "Kevin", "Michelle", "Brian", "Carol", "George", "Amanda", "Timothy",
    "Melissa", "Ronald", "Deborah", "Jason", "Stephanie", "Jeffrey",
    "Rebecca", "Ryan", "Sharon", "Jacob", "Laura", "Gary", "Cynthia",
    "Nicholas", "Kathleen", "Eric", "Amy", "Jonathan", "Angela",
    "Stephen", "Shirley", "Larry", "Brenda", "Justin", "Emma",
    "Scott", "Anna", "Brandon", "Pamela", "Benjamin", "Nicole",
    "Samuel", "Helen", "Raymond", "Samantha", "Gregory", "Katherine",
]

_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz",
    "Parker", "Cruz", "Edwards", "Collins", "Reyes", "Stewart", "Morris",
    "Morales", "Murphy", "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan",
]

_EMAIL_DOMAINS = [
    "gmail.com", "yahoo.com", "outlook.com", "company.com",
    "mail.com", "protonmail.com", "icloud.com", "hotmail.com",
]


def _gen_correlated_persons(n: int) -> list[dict[str, str]]:
    """Generate n rows with correlated first_name + last_name + email."""
    persons = []
    for _ in range(n):
        first = random.choice(_FIRST_NAMES)
        last = random.choice(_LAST_NAMES)
        domain = random.choice(_EMAIL_DOMAINS)
        # Email pattern varies: first.last, f.last, firstlast, first_last
        pattern = random.choice(["dot", "initial", "concat", "underscore"])
        if pattern == "dot":
            local = f"{first.lower()}.{last.lower()}"
        elif pattern == "initial":
            local = f"{first[0].lower()}.{last.lower()}"
        elif pattern == "concat":
            local = f"{first.lower()}{last.lower()}"
        else:
            local = f"{first.lower()}_{last.lower()}"
        # Add small number suffix occasionally to simulate duplicates
        if random.random() < 0.3:
            local += str(random.randint(1, 99))
        persons.append({
            "first_name": first,
            "last_name": last,
            "email": f"{local}@{domain}",
            "full_name": f"{first} {last}",
        })
    return persons


# ── Status + notes/reason correlation ─────────────────────────
# When a table has both a status column and a notes/comments/reason column,
# they should tell a coherent story together.

_STATUS_NOTES_MAP: dict[str, dict[str, list[str]]] = {
    "insurance": {
        "approved": [
            "All documentation verified — claim approved",
            "Approved after policy coverage confirmation",
            "Manager sign-off obtained — processing payment",
            "Claim within policy limits — auto-approved",
            "Medical necessity confirmed by reviewer",
        ],
        "denied": [
            "Pre-existing condition exclusion applies",
            "Claim filed past the submission deadline",
            "Policy lapsed — coverage not active at time of incident",
            "Insufficient supporting documentation provided",
            "Exceeds maximum coverage limit",
        ],
        "under_review": [
            "Awaiting additional documentation from claimant",
            "Sent to senior adjuster for complex case review",
            "Pending third-party liability determination",
            "Medical records requested from provider",
            "Subrogation assessment in progress",
        ],
        "pending": [
            "Claim received — assigned to adjuster",
            "Initial assessment scheduled",
            "Waiting for police report",
            "Beneficiary verification in progress",
            "Coverage determination pending",
        ],
        "closed": [
            "Settlement accepted — case closed",
            "Payment disbursed — no further action",
            "Claim withdrawn by policyholder",
            "Statute of limitations reached — archived",
            "Final resolution documented",
        ],
    },
    "banking": {
        "approved": [
            "Identity verified — transaction cleared",
            "Credit check passed — loan disbursed",
            "Funds transferred successfully",
            "Compliance review passed",
            "Manager override authorized",
        ],
        "rejected": [
            "Insufficient funds in source account",
            "Failed AML compliance check",
            "Credit score below minimum threshold",
            "Suspicious activity detected — blocked",
            "Daily transaction limit exceeded",
        ],
        "pending": [
            "Awaiting compliance officer review",
            "Transaction queued for next business day",
            "Additional verification required from account holder",
            "Pending manager approval for large amount",
            "Wire transfer in processing queue",
        ],
        "completed": [
            "Transaction settled — confirmation sent",
            "Direct deposit processed successfully",
            "Statement generated — available for download",
            "Reconciliation completed — no discrepancies",
            "Payment cleared through ACH network",
        ],
    },
    "healthcare": {
        "active": [
            "Patient responding well to current treatment plan",
            "Medication regimen adjusted — monitoring",
            "Follow-up appointment scheduled",
            "Lab results within expected range",
            "Treatment progressing as planned",
        ],
        "discharged": [
            "Recovery milestones met — patient released",
            "Discharge instructions provided to family",
            "Outpatient follow-up scheduled in 2 weeks",
            "All post-operative checks cleared",
            "Home care services arranged",
        ],
        "cancelled": [
            "Patient requested cancellation",
            "Insurance pre-authorization denied",
            "Scheduling conflict — needs rescheduling",
            "Provider unavailable — patient notified",
            "Duplicate appointment — removed",
        ],
    },
    "devops": {
        "success": [
            "All tests passed — deployment successful",
            "Build completed with 0 warnings",
            "Scan completed — no new vulnerabilities found",
            "PR merged after successful code review",
            "Pipeline completed in under 5 minutes",
        ],
        "failed": [
            "Build failed — compilation error in module",
            "Integration tests failing — timeout on DB connection",
            "Deployment rolled back due to health check failure",
            "Security scan blocked — critical CVE detected",
            "Docker image build failed — dependency conflict",
        ],
        "in_progress": [
            "Currently running security scan",
            "Deploying to staging environment",
            "Waiting for dependent pipeline to complete",
            "Running integration test suite",
            "Container image being pushed to registry",
        ],
        "skipped": [
            "No changes detected in related files",
            "Manually skipped per team request",
            "Vulnerability already marked as false positive",
            "Duplicate of existing parallel execution",
            "Excluded by pipeline filter rules",
        ],
    },
    "general": {
        "active": [
            "In progress — awaiting next step",
            "Assigned and being worked on",
            "Processing within normal SLA",
            "Currently under review",
            "Progressing as expected",
        ],
        "completed": [
            "Completed — no further action required",
            "All steps finalized successfully",
            "Verified and closed",
            "Processed and archived",
            "Resolution confirmed by requestor",
        ],
        "pending": [
            "Awaiting input from stakeholder",
            "On hold — pending external response",
            "Queued for next batch processing",
            "Waiting for manager approval",
            "Paused — dependency not yet resolved",
        ],
        "rejected": [
            "Does not meet requirements — returned",
            "Insufficient information provided",
            "Out of scope for this process",
            "Returned for corrections",
            "Non-compliant with policy",
        ],
        "cancelled": [
            "Cancelled at requestor's instruction",
            "Superseded by newer request",
            "No longer needed — withdrawn",
            "Duplicate entry removed",
            "Project deprioritized",
        ],
    },
}


def _gen_correlated_status_notes(
    n: int, table_name: str = "", allowed_statuses: list[str] | None = None,
) -> list[dict[str, str]]:
    """Generate correlated status + notes pairs appropriate to the domain.

    If allowed_statuses is provided (from CHECK constraint), only those
    status values are used, and notes are matched to the closest known status.
    """
    domain = _infer_domain(table_name)
    status_map = _STATUS_NOTES_MAP.get(domain, _STATUS_NOTES_MAP["general"])

    if allowed_statuses:
        # Map each allowed status to the closest known status key for notes
        effective_map: dict[str, list[str]] = {}
        known_keys = list(status_map.keys())
        for status in allowed_statuses:
            s = status.lower().replace(" ", "_").replace("-", "_")
            # Try exact match first
            if s in status_map:
                effective_map[status] = status_map[s]
            else:
                # Fuzzy match: find key that's a substring or shares prefix
                matched = False
                for key in known_keys:
                    if key in s or s in key:
                        effective_map[status] = status_map[key]
                        matched = True
                        break
                if not matched:
                    # Generate generic notes for this status
                    effective_map[status] = [
                        f"Status set to {status}",
                        f"Updated to {status} — see details",
                        f"Moved to {status} state",
                        f"Transitioned to {status}",
                        f"Changed to {status} per review",
                    ]
        statuses = list(effective_map.keys())
        rows = []
        for _ in range(n):
            status = random.choice(statuses)
            note = random.choice(effective_map[status])
            rows.append({"status": status, "notes": note})
        return rows

    # No CHECK constraint — use domain-inferred statuses
    statuses = list(status_map.keys())
    rows = []
    for _ in range(n):
        status = random.choice(statuses)
        note = random.choice(status_map[status])
        rows.append({"status": status, "notes": note})
    return rows


# Column group definitions:
# (table_pattern, column_patterns_dict, generator_fn)
# column_patterns_dict maps col_pattern (substring match) → field_key in generated dict
_CORRELATED_GROUPS: list[tuple[
    str | None,
    dict[str, str],  # {col_substring: dict_key}
    Callable[[int], list[dict[str, Any]]],
]] = [
    # Person: first_name + last_name + email (generalized — any table)
    (None, {"first_name": "first_name", "last_name": "last_name", "email": "email"}, _gen_correlated_persons),
    # org_id + org_name correlation
    (None, {"org_id": "org_id", "org_name": "org_name"}, _gen_correlated_orgs),
    # project_id + project_name correlation
    (None, {"project_id": "id", "project_name": "name"}, _gen_correlated_projects),
]


def resolve_correlated_columns(
    table_name: str,
    column_names: list[str],
    n: int,
    check_constraints: dict[str, str] | None = None,
) -> dict[str, list[Any]] | None:
    """Check if any columns in this table form a correlated group.

    Returns a dict mapping column_name → list[values] for ALL columns
    that are part of a correlated group, or None if no correlation found.
    Multiple groups may match (e.g., org pair + project pair).
    """
    tbl_lower = table_name.lower()
    col_lowers = {c: c.lower() for c in column_names}
    result: dict[str, list[Any]] = {}
    checks = check_constraints or {}

    # ── Status + notes/comments correlation (domain-inferred) ──
    _status_patterns = ("status", "state")
    # Skip columns that are RAG/color indicators (not workflow statuses)
    _status_skip_patterns = ("rag", "color", "moderation", "virus")
    # Ordered by priority: prefer explicit notes/comment columns over reason
    _notes_patterns_primary = ("notes", "comment", "remarks", "observation")
    _notes_patterns_secondary = ("reason",)
    status_col = None
    notes_col = None
    for actual_col, actual_lower in col_lowers.items():
        if not status_col:
            # Skip RAG/color columns — they are not workflow statuses
            if any(skip in actual_lower for skip in _status_skip_patterns):
                continue
            for sp in _status_patterns:
                if sp in actual_lower and "timestamp" not in actual_lower:
                    status_col = actual_col
                    break
        if not notes_col:
            for np in _notes_patterns_primary:
                if np in actual_lower:
                    notes_col = actual_col
                    break
    # Only fallback to "reason" if no primary notes column found
    if not notes_col:
        for actual_col, actual_lower in col_lowers.items():
            for np in _notes_patterns_secondary:
                if np in actual_lower:
                    notes_col = actual_col
                    break
            if notes_col:
                break
    if status_col and notes_col:
        # If the notes column has its own CHECK constraint enum, don't correlate it
        # — let the normal generation path enforce its allowed values
        from app.utils.sql_types import extract_enum_from_check
        notes_enum = extract_enum_from_check(checks.get(notes_col))
        if notes_enum:
            notes_col = None  # drop from correlation; will be generated normally

    if status_col and notes_col:
        # If the status column has a CHECK constraint, use those exact values
        from app.utils.sql_types import extract_enum_from_check
        enum_values = extract_enum_from_check(checks.get(status_col))
        rows = _gen_correlated_status_notes(n, table_name, enum_values)
        result[status_col] = [row["status"] for row in rows]
        result[notes_col] = [row["notes"] for row in rows]

    # ── Standard correlated groups ──
    for tbl_pattern, col_patterns, gen_fn in _CORRELATED_GROUPS:
        # Check table pattern
        if tbl_pattern is not None and tbl_pattern not in tbl_lower:
            continue

        # Find which actual columns match this group's patterns
        matched: dict[str, str] = {}  # actual_col_name → dict_key
        for actual_col, actual_lower in col_lowers.items():
            # Skip columns already handled by status+notes
            if actual_col in result:
                continue
            for col_pattern, dict_key in col_patterns.items():
                if col_pattern in actual_lower:
                    matched[actual_col] = dict_key
                    break

        # Only activate if at least 2 DIFFERENT dict_keys are matched
        # (e.g., org_id + org_name, not project_id_before + project_id_after)
        distinct_keys = set(matched.values())
        if len(distinct_keys) >= 2:
            rows = gen_fn(n)
            for actual_col, dict_key in matched.items():
                result[actual_col] = [row[dict_key] for row in rows]

    return result if result else None
