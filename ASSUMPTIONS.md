# Assumptions

Where the brief was ambiguous, we made a decision and recorded it here. Numbers live in
`config/policy.yaml`, so each one can be changed without touching code.

## Scope and submission format
- **Countries:** India, United States and United Kingdom are supported. Any other country is accepted but goes to
  PENDING (internal review) with rule `COMP-003`, because we have no verified formats or document lists for it.
- **Submission format:** the `SubmissionForm` model (`core/models.py`). The same JSON is accepted programmatically;
  example: `data/scenarios/happy/initial/submission.json`.
- **Entity types:** company, LLP/partnership, proprietorship, other. A **proprietorship** is not a separate legal
  person, so its *legal name* is the owner's name, the business name is the *trade name*, its PAN is the owner's
  personal PAN (4th letter `P`), and its bank account may be in the trade name.
- **GST:** registration is optional below the turnover threshold. Such a vendor ticks "not registered" and uploads a
  signed non-registration declaration instead of a GST certificate (there is no statutory form for this).
- **Required documents:**

  | Country | Always | Companies | LLPs |
  |---|---|---|---|
  | India | PAN card; cancelled cheque **or** bank letter; GST certificate **or** non-registration declaration | Certificate of incorporation | Certificate of incorporation |
  | US | Form W-9; bank confirmation letter | | |
  | UK | Bank confirmation letter | Companies House certificate | |

- **Bank letter freshness:** the letter must be at most 90 days old *at the time of submission* (not "today"), so
  replaying an old submission gives the same answer.
- **Expired certificates:** none of the supported documents (PAN, GST REG-06, incorporation certificates, W-9)
  carries an expiry date, so no expiry rule exists. GST *cancellation* is covered by the registry check (`REG-001`).

## Decision policy
- REJECTED / PENDING / APPROVED logic and the risk score are exactly as in the brief (see RULES.md). Choices
  the brief left open:
  - Every HIGH and CRITICAL finding blocks approval. Some WARNs also block (ambiguous name, low document confidence,
    stale bank letter, possible duplicate, instruction-like text), because the brief says "anything ... ambiguous"
    is PENDING. Non-blocking WARNs (GSTIN state differs from address state, free email domain, email/website domain
    mismatch, not found in registry) only add risk points.
  - **Sub-status:** "awaiting vendor" when *every* blocking finding is something the vendor can fix; otherwise
    "awaiting internal review". E1 is internal review even though the email asks the vendor to confirm details,
    because a person must judge a PAN/GSTIN conflict.
  - **Failed resubmissions:** attempts in the same chain that did not end APPROVED. More than 3 means REJECTED.
- **A reviewer can override** any PENDING outcome (approve, reject or request information) with a mandatory reason.
  The system's own decision is kept (`system_status`) and shown next to the human one.

## Where AI is used (and where it is not)
- **Provider:** Claude if `ANTHROPIC_API_KEY` is set, else Gemini if `GEMINI_API_KEY` is set, else offline
  (`LLM_PROVIDER` forces one). Both LLM providers get the same instructions (`core/llm/prompts.py`) and must answer in
  the same schemas, so swapping them changes how facts are read, never a rule.
- **Claude:** `LLM_MODEL` (default `claude-sonnet-5-5`), effort `low`, structured outputs via `messages.parse`, timeout
  60 s, 2 SDK retries with exponential backoff, server-side refusal fallback on (`LLM_REFUSAL_FALLBACK=off` to disable).
- **Gemini:** `GEMINI_MODEL` (default `gemini-3.5-flash-lite`: stable, vision and structured output, and the most
  generous free tier at about 10 requests/minute and 500/day; the Flash models allow only about 20 requests/day free,
  less than three demo runs). `generate_content` with `response_schema`, thinking level `low`, timeout 60 s, 2 SDK
  retries for timeouts and 5xx. Rate limits (429) are handled by the provider: it waits the delay Google asks for
  (capped at 60 s, at most twice), fails fast when the daily quota is used up, and paces itself to `GEMINI_RPM`
  (default 10) requests per minute so multi-document runs wait instead of failing. On the free tier Google may use
  the inputs to improve its products; that is acceptable here only because every document is synthetic.
- **S3 document understanding:** classification plus field extraction with confidence and a verbatim evidence snippet.
  Text-layer PDFs are sent as text; scans and photos are sent as images (vision). The model is **not** told which slot
  the file was uploaded into, and does not see the filename, so the vendor's claim cannot anchor the classification.
- **S5 name adjudication:** only for pairs scoring 80-95 after normalisation. "yes" counts as a match, "no" as a
  mismatch, "unsure" as WARN `CON-006`.
- **S9 email wording:** only for PENDING outcomes, and only from the list of requested items. A draft that drops an
  item or the link, mentions internal checks, or implies approval is discarded in favour of the template. Rejection
  notices are always a fixed neutral template.
- **Dates:** providers copy dates exactly as printed and S3 converts them to ISO in deterministic code
  (`core/documents/dates.py`). NN/NN/NNNN is month-first on US documents (a routing number, an EIN or a W-9 says
  so) and day-first otherwise; the declared country only decides for documents with no such identifiers. The first
  live Gemini eval showed why: the model read "10/02/2026" on two US bank letters as 10 February. A date that
  cannot be parsed gets confidence 0, so a key date such as the bank letter's becomes `DOC-003` instead of skipping
  the freshness check.
- **Never:** format checks, consistency, duplicates, sanctions, risk score or the decision.
- **Offline mode (no API key):** a deterministic provider reads PDF text layers with keyword classification and
  label-anchored regular expressions, answers "unsure" for borderline names, and uses templates for emails. Scans are
  reported as unreadable, so the submission goes PENDING. This is the brief's "degraded" behaviour, not a simulation.
  Tests and the smoke test use this mode so they are free and deterministic.
- **LLM failure:** timeout, invalid schema or refusal marks S3 "degraded" with `DOC-004` (HIGH, internal review).
  It is never treated as a pass.

## Sanctions
- US Treasury OFAC lists only: the SDN list plus the consolidated non-SDN lists, from a committed snapshot
  (publication date shown in the app). There are no UN, EU, UK HMT or Indian lists. The UI says so.
- Screened names: legal name, trade name and bank account holder. Entity and individual entries and their aliases are
  used; vessels and aircraft are excluded. "Weak" aliases embedded in remarks are excluded, as OFAC itself advises.
- Scoring: legal-form words (LTD, PVT, LLC...) are stripped; score = max(token-sort ratio, space-insensitive ratio);
  very short names need an exact match; candidates sharing no distinctive word are capped below review. At least 92
  on SDN gives `SAN-001` (CRITICAL, reject); 85-92 gives `SAN-002` (HIGH, human review). Any hit on a non-SDN list
  gives `SAN-003` (review, never auto-reject). WRatio and token-set scorers were rejected: on the real list they scored
  32 of 34 benign company names at 85 or above.

## Simulated components (labelled "SIMULATED" in the UI)
- **GST registry lookup** and **bank account-holder verification** (penny drop) use `data/registry/simulated_registry.json`
  through the `RegistryClient` interface. Real providers need paid or credentialed access.
- **Email sending:** `EMAIL_MODE=simulated` by default, which writes to the Outbox only. Resend or SMTP can be
  switched on with environment variables.

## Duplicates and fraud patterns
- **Identifier reuse (`FRD-001`):** an exact PAN, GSTIN, EIN, company number, or (bank code + account number) match with
  an approved vendor whose name does not match. The same identifiers *and* the same name give `FRD-006`
  (already a vendor).
- **Possible duplicate (`FRD-002`):** a name similarity of 90 or more with an approved vendor that has different bank
  details.
- **Bank-change pattern (`FRD-003`):** on resubmission, a change to bank or tax fields that we did *not* ask the vendor
  to fix. Fixing a field we flagged (for example the IFSC typo in E4) is expected and not flagged.
- **Free email (`FRD-004`):** only for companies and LLPs. Proprietors commonly use personal email.

## Resubmission
- The emailed link carries a 32-byte random token. Only its SHA-256 hash is stored; it expires after 14 days and works
  once. Documents the vendor does not re-upload are carried over from the previous attempt. A carried-over document is
  not re-sent to the LLM (to save tokens) if the same provider already read it.

## Dashboard
- **Seeded history:** on a fresh database, 16 older synthetic submissions are replayed **through the real pipeline**
  (offline provider, back-dated timestamps, marked "seeded"). Free hosts wipe the disk on restart, and without this the
  dashboard would be empty after every cold start. A toggle excludes them.
- **Time to decision** is the measured duration of the pipeline run.
- **Manual review time saved** assumes 45 minutes of manual checking for every submission the system decided, or sent
  back to the vendor with an itemised request, without a person (`manual_review_minutes_per_submission`).

## Live run view
- An optional "demo pacing" toggle adds a 0.4 s pause *between* stages so an audience can follow. The durations
  shown are always the real measured execution times. It is off by default.

## Synthetic data
- Every vendor, person, ID and document is fictional. PANs use a "ZZ" series, websites and emails use the reserved
  `.example` domain, Indian phone numbers start with 00000, and UK numbers use Ofcom's drama range. Every document is
  stamped "SYNTHETIC TEST DOCUMENT". Every synthetic vendor name is screened against the sanctions list at generation
  time. E5 is deliberately close to a list entry.
- Document dates are relative to the day `scripts/generate_data.py` ran. More than about 60 days later, it should be
  re-run (with the smoke test) so bank letters are not stale.

## Where we departed from the brief (after verification)
- The brief's checksum test value `29AABCT1332L1ZS` is **not** a valid GSTIN: the algorithm in the brief is correct and
  gives check character `A`. Tests assert that `...ZS` fails and `...ZA` passes.
- Hugging Face Spaces now requires a paid plan for Docker or Streamlit apps, and Render's free tier has 512 MB RAM, so
  the target is Streamlit Community Cloud (a Dockerfile is provided as a fallback).
- PyMuPDF is AGPL-licensed, so we use pdfplumber (text) and pypdfium2 (rasterising).
- The E4 bank-change variant uses its own vendor. Otherwise E4's approval would make the variant a legitimate
  "already a vendor" duplicate (`FRD-006`), which would muddy the scenario.
