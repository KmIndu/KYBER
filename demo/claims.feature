Feature: Insurance Claim Processing Rules
  As a claims adjudicator
  I want the system to enforce business rules
  So that claims are processed accurately and fairly

  # ── Age & Eligibility ──────────────────────────────────

  Scenario: Minor cannot hold a life insurance policy
    Given customer age is below 18
    Then policy issuance should fail

  Scenario: Senior citizen requires enhanced review
    Given customer age is above 65
    Then the claim requires approval

  Scenario: Standard adult policyholder
    Given customer age is above 18
    And customer age is below 65
    Then policy issuance should succeed

  # ── Claim Amount Thresholds ────────────────────────────

  Scenario: Small claim — auto-approved
    Given claim amount is below 5000
    And policy status is active
    Then the claim should succeed

  Scenario: Medium claim — standard review
    Given claim amount is above 5000
    And claim amount is below 50000
    Then the claim requires approval

  Scenario: Large claim — manager escalation required
    Given claim amount is above 50000
    Then the claim requires approval

  Scenario: Claim exceeds coverage limit
    Given claim amount is above 1000000
    Then the claim should fail

  # ── Policy Status Checks ───────────────────────────────

  Scenario: Claim on lapsed policy is denied
    Given policy status is inactive
    Then the claim should fail

  Scenario: Claim on active policy proceeds
    Given policy status is active
    Then the claim should succeed

  # ── Premium Payment Rules ──────────────────────────────

  Scenario: Payment below minimum premium
    Given premium amount is below 10
    Then payment processing should fail

  Scenario: Payment above maximum premium
    Given premium amount is above 50000
    Then payment processing should fail

  Scenario: Valid premium range
    Given premium amount is above 10
    And premium amount is below 50000
    Then payment processing should succeed

  # ── Identity & Fraud ───────────────────────────────────

  Scenario: Missing email blocks registration
    Given email is null
    Then registration should fail

  Scenario: Duplicate email is rejected
    Given email is duplicate
    Then registration should fail

  Scenario: Invalid email format is rejected
    Given email is invalid
    Then registration should fail

  Scenario: Valid email allows registration
    Given email is valid
    Then registration should succeed

  # ── Beneficiary Allocation ─────────────────────────────

  Scenario: Beneficiary allocation must not exceed 100%
    Given allocation percentage is above 100
    Then beneficiary assignment should fail

  Scenario: Beneficiary allocation cannot be zero
    Given allocation percentage is below 1
    Then beneficiary assignment should fail

  Scenario: Valid beneficiary allocation
    Given allocation percentage is above 1
    And allocation percentage is below 100
    Then beneficiary assignment should succeed

  # ── Coverage Constraints ───────────────────────────────

  Scenario: Coverage amount below product minimum
    Given coverage amount is below 1000
    Then policy issuance should fail

  Scenario: Coverage amount exceeds product maximum
    Given coverage amount is above 10000000
    Then policy issuance should fail
