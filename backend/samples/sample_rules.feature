Feature: Insurance Registration Validation

  Scenario: Underage user registration
    Given user age is below 18
    Then registration should fail

  Scenario: Senior citizen policy
    Given user age is above 65
    Then registration should succeed

  Scenario: Null email registration
    Given user email is null
    Then registration should fail

  Scenario: Duplicate email registration
    Given user email already exists
    Then registration should fail

  Scenario: Invalid email format
    Given user email is invalid
    Then registration should fail

  Scenario: Valid email format
    Given user email is valid
    Then registration should succeed

  Scenario: High claim amount requires approval
    Given claim amount is greater than 50000
    Then requires manager approval

  Scenario: Premium within valid range
    Given premium is between 100 and 99999
    Then policy creation should succeed

  Scenario: Null phone allowed
    Given user phone is empty
    Then registration should succeed

  Scenario: Short password rejected
    Given password length is less than 8
    Then registration should fail

  Scenario: Long password rejected
    Given password length is greater than 128
    Then registration should fail

  Scenario: Exact age boundary
    Given user age is equal to 18
    Then registration should succeed

  Scenario: Not null check
    Given user name is not null
    And user email is not empty
    Then registration should succeed
