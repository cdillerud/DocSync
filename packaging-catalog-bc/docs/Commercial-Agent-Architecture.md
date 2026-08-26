# GPI Packaging Catalog Commercial Agent Architecture

## Purpose

Extend the Packaging Catalog replacement POC into a reusable commercial intelligence platform for AI-assisted detection, investigation, prioritization, recommendation, controlled action, and audit.

The initial agent set is:

1. Low Margin Warning
2. Cost Change
3. Incorrect Item Detection

Lucid architecture diagram: https://lucid.app/lucidchart/cc24b761-c006-4ceb-9829-86602c83f066/edit

## Architectural rule

AI participates throughout the workflow, but Business Central remains authoritative for deterministic financial and transactional facts.

AI responsibilities include anomaly detection, pattern comparison, context gathering, investigation, commercial prioritization, risk and confidence scoring, recommendations, and explanation.

Business Central responsibilities include authoritative cost, sell price, landed cost, gross margin, special pricing, pricing guardrails, hard thresholds, and controlled transactional writes.

## Shared flow

Business Central + Spiro
-> Commercial Context Layer
-> Deterministic BC Services + AI Reasoning Layer
-> Commercial Exception Framework
-> Controlled Action / Notification / Feedback

## 0.45 Commercial Agent Foundation

### 0.45A Commercial Exception model

A durable shared record for agent findings, including source identity, customer/item/document context, severity, risk, confidence, AI findings, recommendation, assignment, review disposition, and audit metadata.

### 0.45B Commercial Evidence model

Child evidence records preserve the deterministic facts and comparisons that support an AI conclusion. Evidence is explicit rather than hidden inside a model response.

### 0.45C Agent Evaluation Queue

A reusable unattended evaluation queue provides idempotent submission, processing status, retry tracking, correlation, and linkage from queue work to durable exceptions.

### 0.45D Commercial Agent Management service

Shared AL procedures provide queue submission, exception creation, evidence capture, completion/failure handling, and human review feedback.

## Planned context services

### 0.45E Customer / Item History Context

Answers:
- What does this customer normally buy?
- How frequently?
- At what quantity and price?
- What margin pattern is normal?
- Is the current item new or unusual for this customer?

### 0.45F Margin Context

Answers:
- What is the authoritative current GP?
- What is the customer/item historical GP range?
- What changed in cost, freight, quantity, or sell price?
- Is the exception material relative to historical behavior?

### 0.45G Cost Change Context

Answers:
- What changed in supplier or landed cost?
- Which active customers and open orders are exposed?
- Which sell prices have not moved with cost?
- Which cases are commercially material?

### 0.45H Item Similarity Context

Builds a deterministic similarity vector from product family, dimensions, material, capacity, closure, color, packout, vendor, and other Packaging Catalog attributes. AI reasons over that vector together with customer history and Spiro context.

### 0.45I AI Evaluation Contract

The AI-facing contract should include:
- agent type
- trigger identity
- authoritative source facts
- normalized context
- evidence array
- risk score
- confidence score
- finding
- recommended action
- model/version metadata
- correlation ID

### 0.45J Review / Feedback Loop

Every finding must eventually support a disposition such as Confirmed Issue, Valid Exception, Intentional, False Positive, Corrected, or No Action Needed. Feedback becomes durable context for future evaluations.

## Agent implementation sequence

### 0.46 Low Margin Agent

Deterministic BC prefilter -> AI investigation -> historical/customer/item comparison -> materiality ranking -> leadership exception output.

### 0.47 Cost Change Agent

Cost change trigger -> deterministic impact calculations -> customer/open-order exposure -> AI commercial prioritization -> rep notification and review.

### 0.48 Incorrect Item Agent

New order-line trigger -> customer purchase history -> deterministic product similarity -> Spiro quote/opportunity context -> AI anomaly scoring -> controlled review alert.

## Safety principles

- No production writes during UAT development.
- Quote 67 remains protected and must not be used for write testing.
- AI never invents authoritative GP, landed cost, pricing, or approval facts.
- Controlled writes remain behind explicit gates and existing Prepare/Execute protections.
- Every agent finding must retain evidence and provenance sufficient for human review.
- False-positive feedback must be preserved and reusable.
