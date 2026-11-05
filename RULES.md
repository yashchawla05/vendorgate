# Rules and decision policy

Generated from `config/rules.yaml` (version 2026-11-01.1) and `config/policy.yaml` (version 2026-11-01.1) by `python scripts/export_rules.py`. The in-app **Rules & policy** page shows the same data.

## Decision policy (deterministic; an LLM never decides)

1. **REJECTED** if any of `SAN-001`, `FRD-001` fires, or there are 2+ CRITICAL findings, or more than 3 failed resubmissions.
2. **PENDING** if any finding blocks approval (all HIGH/CRITICAL plus the WARNs marked below) or the risk score is >= 30. Sub-status *awaiting vendor* when every blocker has resolver = vendor; otherwise *awaiting internal review*.
3. **APPROVED** otherwise (implies every document confidence >= 0.8, no possible sanctions match, risk < 30).

Risk score = min(100, sum of weights): INFO = 0, WARN = 5, HIGH = 20, CRITICAL = 40.

| Threshold | Value |
|---|---|
| `name_match` | 95 |
| `name_ambiguous` | 80 |
| `doc_confidence_min` | 0.8 |
| `bank_letter_max_age_days` | 90 |
| `sanctions_strong` | 92 |
| `sanctions_possible` | 85 |
| `duplicate_name_similarity` | 90 |
| `approve_max_risk` | 30 |

## Rule catalogue

Resolver: **vendor** = the vendor can fix it; **internal** = a person on our side must judge it.

### S2 Completeness

| ID | Rule | Severity | Resolver | Blocks approval | Rationale |
|---|---|---|---|---|---|
| `COMP-001` | Required field missing | HIGH | vendor | yes | We cannot verify or pay a vendor without the core identity, tax and bank fields for its country. |
| `COMP-002` | Required document missing | HIGH | vendor | yes | Each claim on the form must be backed by a document (tax registration, bank proof, incorporation). |
| `COMP-003` | Country not supported for automated checks | HIGH | internal | yes | Formats and documents are only defined for India, US and UK; other countries need manual review. |
| `COMP-004` | Declarations not accepted | HIGH | vendor | yes | The vendor must confirm accuracy and consent to verification before we process its data. |

### S3 Document understanding

| ID | Rule | Severity | Resolver | Blocks approval | Rationale |
|---|---|---|---|---|---|
| `DOC-001` | Wrong document type in slot | HIGH | vendor | yes | A document in the wrong slot leaves the requirement unmet and is a common cause of onboarding delay. |
| `DOC-002` | Document unreadable | HIGH | vendor | yes | If we cannot read a document we cannot verify it; never assume it is fine. |
| `DOC-003` | Low extraction confidence | WARN | vendor | yes | Approval requires every document's key fields to be read with confidence >= the policy threshold. |
| `DOC-004` | Document understanding degraded | HIGH | internal | yes | The extraction service failed (timeout, invalid output, refusal). The document is treated as unread. |
| `DOC-005` | Instruction-like text inside a document | WARN | internal | yes | Text addressed to an AI or reviewer inside a vendor document is a manipulation attempt; a person must look. |

### S4 Format & checksum

| ID | Rule | Severity | Resolver | Blocks approval | Rationale |
|---|---|---|---|---|---|
| `FMT-PAN` | PAN format invalid | HIGH | vendor | yes | PAN is 5 letters, 4 digits, 1 letter; the 4th letter must be a valid holder type. |
| `FMT-GSTIN` | GSTIN invalid | HIGH | vendor | yes | GSTIN = state code + PAN + entity number + 'Z' + mod-36 check character. A failed checksum is almost always a typo. |
| `FMT-IFSC` | IFSC invalid | HIGH | vendor | yes | IFSC is 4 letters, '0', 6 alphanumerics; a malformed IFSC means payments will bounce. |
| `FMT-IFSC-BANK` | IFSC bank code does not match bank name | WARN | vendor | yes | The first 4 IFSC letters identify the bank; a mismatch with the stated bank name means one of them is wrong. |
| `FMT-ACCT` | Bank account number invalid | HIGH | vendor | yes | India 9-18 digits, US 4-17 digits, UK 8 digits. |
| `FMT-ACCT-REVIEW` | Bank account number needs manual check | WARN | internal | yes | Some UK banks use 9-10 digit numbers converted by bank-specific rules we do not implement. |
| `FMT-EIN` | EIN invalid | HIGH | vendor | yes | EIN is 9 digits with an IRS-issued 2-digit prefix (no checksum exists). |
| `FMT-ABA` | ABA routing number invalid | HIGH | vendor | yes | Routing numbers carry a 3-7-1 checksum and a Federal Reserve prefix; a failure is almost always a typo. |
| `FMT-SORT` | UK sort code invalid | HIGH | vendor | yes | UK sort codes are 6 digits. |
| `FMT-CRN` | UK company number invalid | HIGH | vendor | yes | Companies House numbers are 8 characters (digits, or a 2-letter prefix plus 6 digits). |
| `FMT-VAT` | UK VAT number fails check | WARN | vendor | yes | The HMRC check-digit algorithm is unofficial, so a failure only warns. |
| `FMT-EMAIL` | Contact email invalid | HIGH | vendor | yes | Every follow-up goes to this address. |
| `FMT-CIN` | Company identity number unreadable or invalid | WARN | vendor | no | CIN/LLPIN is informational here (no registry lookup), so a bad value only warns. |

### S5 Consistency & simulated registry

| ID | Rule | Severity | Resolver | Blocks approval | Rationale |
|---|---|---|---|---|---|
| `CON-001` | Tax ID type does not match country | HIGH | vendor | yes | A US vendor supplying an Indian GSTIN (or vice versa) means the wrong entity or the wrong form. |
| `CON-002` | GSTIN embeds a different PAN | CRITICAL | internal | yes | Characters 3-12 of a GSTIN are the holder's PAN. A different PAN means the GSTIN belongs to another legal person. |
| `CON-003` | GSTIN state differs from address state | WARN | vendor | no | Usually a branch registration; worth a note, not a block. |
| `CON-004` | PAN holder type does not match entity type | HIGH | internal | yes | The 4th PAN letter encodes the holder type (C company, F firm/LLP, P individual). A company with an individual's PAN is a red flag. |
| `CON-005` | Legal name mismatch across sources | HIGH | internal | yes | Benign variants are normalised away first; what remains (score < 80) means different entities. |
| `CON-006` | Legal name ambiguous across sources | WARN | internal | yes | Score 80-95 and the adjudicator (LLM, or offline mode) could not confirm it is the same entity. |
| `CON-007` | Bank account holder differs from vendor name | HIGH | internal | yes | Paying an account held by someone else is the core payment-fraud risk. |
| `CON-008` | Bank letter too old or future-dated | WARN | vendor | yes | Bank proof must be recent (policy max age) so it reflects the account's current state. |
| `CON-009` | Document value differs from form | HIGH | vendor | yes | An ID or account number on a document must equal the one typed on the form. |
| `CON-010` | Bank country differs from vendor country | HIGH | vendor | yes | Cross-border payouts to a domestic vendor need a business reason and a different approval path. |
| `REG-001` | GSTIN not active (simulated registry) | HIGH | internal | yes | A cancelled or suspended GST registration cannot issue valid tax invoices. |
| `REG-002` | Registry legal name mismatch (simulated registry) | HIGH | internal | yes | The tax authority's record names a different entity. |
| `REG-003` | Bank account holder mismatch (simulated bank verification) | HIGH | internal | yes | The bank says the account belongs to someone else (penny-drop style check). |
| `REG-004` | Not found in simulated registry | WARN | internal | no | The simulated registry only knows synthetic demo entities; absence is noted, not punished. |

### S6 Duplicates & fraud patterns

| ID | Rule | Severity | Resolver | Blocks approval | Rationale |
|---|---|---|---|---|---|
| `FRD-001` | Identifier already used by a different vendor | CRITICAL | internal | yes | The same PAN, GSTIN, EIN or bank account under a different legal name is the ghost/duplicate vendor pattern. |
| `FRD-002` | Possible duplicate of an existing vendor | WARN | internal | yes | A near-identical name with different bank details may be a duplicate record or an impersonation. |
| `FRD-003` | Bank or tax details changed on resubmission | HIGH | internal | yes | Changing payment details that nobody asked to change is the classic bank-change fraud pattern. |
| `FRD-004` | Free email domain for a business | WARN | vendor | no | Registered businesses normally use a company domain; free mail is easy to create anonymously. |
| `FRD-005` | Email domain unrelated to website | WARN | vendor | no | A contact address on a different domain from the stated website weakens the link to the business. |
| `FRD-006` | Vendor already exists in master | WARN | internal | yes | Same identifiers and same name as an existing vendor, so approving would create a duplicate record. |
| `POL-001` | Too many failed resubmissions | HIGH | internal | yes | Repeated failed attempts suggest probing; the policy rejects after the configured limit. |

### S7 Sanctions

| ID | Rule | Severity | Resolver | Blocks approval | Rationale |
|---|---|---|---|---|---|
| `SAN-001` | Strong sanctions match (OFAC SDN) | CRITICAL | internal | yes | Paying an SDN-listed party is prohibited. Deterministic fuzzy score >= strong threshold. |
| `SAN-002` | Possible sanctions match | HIGH | internal | yes | Score between the possible and strong thresholds; a human must compare details (address, dates, program). |
| `SAN-003` | Match on non-SDN consolidated list | HIGH | internal | yes | Non-SDN lists (e.g. sectoral sanctions) restrict specific dealings rather than all dealings; needs compliance review. |

### System

| ID | Rule | Severity | Resolver | Blocks approval | Rationale |
|---|---|---|---|---|---|
| `SYS-001` | Pipeline stage failed | HIGH | internal | yes | If any check could not run, the outcome is unknown, and unknown never means approved. |

## Formats verified (sources checked 2026-11-01)

| Identifier | Rule implemented | Source |
|---|---|---|
| PAN | `^[A-Z]{3}[ABCFGHJLPT][A-Z][0-9]{4}[A-Z]$`; 4th letter = holder type (C company, F firm/LLP, P individual...) | Income Tax Department PAN FAQ |
| GSTIN | state code + PAN + entity no. + `Z` + Luhn mod-36 check char; state 25/28/96/99 rejected | GSTN state master; checksum verified on 27AAPFU0939F1ZV (the spec's 29AABCT1332L1ZS is invalid: check char should be A) |
| IFSC | `^[A-Z]{4}0[A-Z0-9]{6}$`; bank code vs bank name (20 major banks) | RBI format; Razorpay IFSC dataset |
| Indian account | 9-18 digits, kept as string | RBI guidance |
| EIN | 9 digits, IRS-issued 2-digit prefix (83 valid) | irs.gov valid EIN prefixes |
| ABA routing | 3-7-1 checksum + Federal Reserve prefix ranges | ABA / Federal Reserve |
| UK sort code / account | 6 digits / 8 digits (6-7 left-padded; 9-10 manual review) | Pay.UK |
| UK VAT | GB/XI + 9 or 12 digits, mod-97 remainder 0/42/55 (soft check) | HMRC (algorithm unofficial) |
| UK company number | 8 digits or 2-letter prefix + 6 digits | Companies House |
| Sanctions | OFAC SDN + consolidated, entity + individual names and aliases; composite fuzzy score | US Treasury OFAC SLS |
