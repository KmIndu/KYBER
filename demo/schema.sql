-- ============================================================
-- Sun Life Insurance — Core Database Schema
-- Demo asset for AI-Powered Synthetic Test Data Generator
-- ============================================================

-- Customers / policyholders
CREATE TABLE customers (
    customer_id       INT PRIMARY KEY,
    first_name        VARCHAR(100) NOT NULL,
    last_name         VARCHAR(100) NOT NULL,
    email             VARCHAR(255) UNIQUE NOT NULL,
    phone             VARCHAR(20),
    date_of_birth     DATE NOT NULL,
    gender            VARCHAR(10) CHECK (gender IN ('Male', 'Female', 'Other')),
    address           VARCHAR(500),
    city              VARCHAR(100),
    province          VARCHAR(50),
    postal_code       VARCHAR(10),
    country           VARCHAR(50) DEFAULT 'Canada',
    risk_score        INT CHECK (risk_score BETWEEN 1 AND 100),
    status            VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'suspended')),
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insurance agents / advisors
CREATE TABLE agents (
    agent_id          INT PRIMARY KEY,
    first_name        VARCHAR(100) NOT NULL,
    last_name         VARCHAR(100) NOT NULL,
    email             VARCHAR(255) UNIQUE NOT NULL,
    license_number    VARCHAR(50) UNIQUE NOT NULL,
    branch            VARCHAR(100),
    hire_date         DATE NOT NULL,
    commission_rate   DECIMAL(5, 4) CHECK (commission_rate BETWEEN 0.0 AND 0.15),
    status            VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'terminated'))
);

-- Insurance products / plan types
CREATE TABLE products (
    product_id        INT PRIMARY KEY,
    product_name      VARCHAR(200) NOT NULL,
    product_type      VARCHAR(50) NOT NULL CHECK (product_type IN ('life', 'health', 'dental', 'disability', 'critical_illness', 'travel')),
    min_premium       DECIMAL(12, 2) NOT NULL CHECK (min_premium > 0),
    max_premium       DECIMAL(12, 2) NOT NULL CHECK (max_premium > 0),
    min_coverage      DECIMAL(14, 2) NOT NULL CHECK (min_coverage > 0),
    max_coverage      DECIMAL(14, 2) NOT NULL CHECK (max_coverage > 0),
    waiting_period_days INT DEFAULT 30,
    is_active         BOOLEAN DEFAULT TRUE
);

-- Policies (links customer → product, via agent)
CREATE TABLE policies (
    policy_id         INT PRIMARY KEY,
    policy_number     VARCHAR(50) UNIQUE NOT NULL,
    customer_id       INT NOT NULL,
    product_id        INT NOT NULL,
    agent_id          INT NOT NULL,
    start_date        DATE NOT NULL,
    end_date          DATE,
    premium_amount    DECIMAL(12, 2) NOT NULL CHECK (premium_amount > 0),
    coverage_amount   DECIMAL(14, 2) NOT NULL CHECK (coverage_amount > 0),
    payment_frequency VARCHAR(20) DEFAULT 'monthly' CHECK (payment_frequency IN ('monthly', 'quarterly', 'semi_annual', 'annual')),
    status            VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'lapsed', 'cancelled', 'expired', 'pending')),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

-- Beneficiaries on a policy
CREATE TABLE beneficiaries (
    beneficiary_id    INT PRIMARY KEY,
    policy_id         INT NOT NULL,
    full_name         VARCHAR(200) NOT NULL,
    relationship      VARCHAR(50) NOT NULL CHECK (relationship IN ('spouse', 'child', 'parent', 'sibling', 'other')),
    allocation_pct    DECIMAL(5, 2) NOT NULL CHECK (allocation_pct BETWEEN 0.01 AND 100.00),
    FOREIGN KEY (policy_id) REFERENCES policies(policy_id)
);

-- Claims filed against policies
CREATE TABLE claims (
    claim_id          INT PRIMARY KEY,
    claim_number      VARCHAR(50) UNIQUE NOT NULL,
    policy_id         INT NOT NULL,
    claim_date        DATE NOT NULL,
    incident_date     DATE NOT NULL,
    claim_amount      DECIMAL(14, 2) NOT NULL CHECK (claim_amount > 0),
    approved_amount   DECIMAL(14, 2) CHECK (approved_amount >= 0),
    claim_type        VARCHAR(50) NOT NULL CHECK (claim_type IN ('medical', 'dental', 'disability', 'death', 'critical_illness', 'travel')),
    status            VARCHAR(20) DEFAULT 'submitted' CHECK (status IN ('submitted', 'under_review', 'approved', 'denied', 'paid', 'appealed')),
    denial_reason     VARCHAR(500),
    reviewer_notes    TEXT,
    FOREIGN KEY (policy_id) REFERENCES policies(policy_id)
);

-- Premium payments
CREATE TABLE payments (
    payment_id        INT PRIMARY KEY,
    policy_id         INT NOT NULL,
    payment_date      DATE NOT NULL,
    amount            DECIMAL(12, 2) NOT NULL CHECK (amount > 0),
    payment_method    VARCHAR(30) CHECK (payment_method IN ('credit_card', 'debit', 'bank_transfer', 'cheque', 'payroll_deduction')),
    transaction_ref   VARCHAR(100) UNIQUE,
    status            VARCHAR(20) DEFAULT 'completed' CHECK (status IN ('completed', 'pending', 'failed', 'refunded')),
    FOREIGN KEY (policy_id) REFERENCES policies(policy_id)
);
