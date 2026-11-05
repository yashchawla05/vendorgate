# VendorGate

**Vendor onboarding verification with visible reasoning.** A vendor submits company, tax and bank details with
supporting documents. VendorGate runs a 10-stage verification pipeline and decides **APPROVED**, **PENDING**
(awaiting vendor / awaiting internal review) or **REJECTED**. It shows every rule that fired with its evidence, and
writes the vendor an email naming exactly what is needed. Built for the Zamp "AI Solutions Analyst" case study
(problem statement 2: vendor onboarding).

> All vendors, people, identifiers and documents in this repository are **synthetic**. No real companies, people or
> IDs are used. The GST registry and bank-account verification are **simulated** and labelled as such.

## What it does
- **Vendor portal:** a submission form with document uploads, programmatic JSON submissions, and a tokenised
  "fix your submission" link.
- **Reviewer console:** a dashboard; a live run view that shows each stage as it executes; submission detail
  (decision, reasoning, checks by category, field × source comparison, risk breakdown, emails, timeline); a review
  queue (approve / reject / request info with a mandatory reason); the vendor master; the outbox; rules and policy;
  an audit log with CSV export; assumptions; system health.
- **Five demo scenarios plus a stretch case**, each a folder of real input files run through the real pipeline:

| Scenario | What is wrong | Outcome |
|---|---|---|
| Happy path | Nothing ("Pvt. Ltd." vs "Private Limited" is a benign variant) | APPROVED |
| E1 Looks fine, isn't | GSTIN embeds a different PAN; PAN says individual, form says company | PENDING (internal review): CRITICAL + HIGH |
| E2 Wrong country / documents | US company gives a GSTIN, uploads a PAN card as its W-9, no bank letter | PENDING (awaiting vendor) with an itemised request |
| E3 Ghost vendor | Bank account belongs to an approved vendor; holder name differs; gmail contact | REJECTED, compliance escalation, neutral notice |
| E4 Pending → fixed → approved | Missing bank proof + IFSC typo, fixed through the emailed link | PENDING → APPROVED (variant: silent bank change → PENDING) |
| E5 Sanctions near-miss (stretch) | Name scores 87 against a real SDN entry | PENDING (human review) |

## Where AI is used
The LLM **reads documents**, **judges borderline name pairs** and **words emails**, behind a small provider
interface with two implementations: **Claude** (Anthropic SDK) or **Gemini** (Google Gen AI SDK; the free tier works).
Both get the same instructions and must answer in the same schemas. The LLM never decides: the decision engine is a
deterministic, unit-tested function of the findings and `config/policy.yaml`. Without an API key the app runs in an
honest **offline mode**: deterministic extraction from PDF text layers, while scans are reported unreadable.
See [ARCHITECTURE.md](ARCHITECTURE.md).

## Run locally
```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Windows (Linux/macOS: .venv/bin/python)
cp .env.example .env                                        # optional: add ANTHROPIC_API_KEY or GEMINI_API_KEY
.venv/Scripts/python -m streamlit run app.py                # http://localhost:8501
```
On first start the app creates `data/runtime/vendorgate.db`, seeds 12 vendors, and replays 16 history submissions
(about 10 s).

## Test
```bash
.venv/Scripts/python -m pytest -q                 # 167 tests: validators, decision engine, scenarios, form samples, providers, UI, theme
.venv/Scripts/python scripts/smoke_test.py        # every scenario headless on a fresh DB -> ALL GREEN
.venv/Scripts/python scripts/smoke_test.py --provider anthropic   # same, through Claude (needs a key)
.venv/Scripts/python scripts/smoke_test.py --provider gemini      # same, through Gemini (needs a key)
.venv/Scripts/python scripts/run_eval.py          # extraction accuracy -> EVAL.md (add --provider anthropic|gemini)
.venv/Scripts/python scripts/run_cli.py e1_looks_fine            # one scenario in the terminal
```

## Deploy (Streamlit Community Cloud, free)
Why this host: it is free, has enough memory (up to ~2.7 GB) for PDF parsing, deploys from GitHub, and gives a
stable `https://<name>.streamlit.app` URL. Render's free tier has only 512 MB, and Hugging Face now charges for
Docker/Streamlit Spaces. Caveats: the app **sleeps after 12 hours without visitors** (anyone can wake it with one
click; it takes about a minute), and the disk is ephemeral (the app re-seeds itself on every start).

**Steps:**
1. Push this repository to GitHub.
2. Go to <https://share.streamlit.io>, sign in with GitHub, choose **Create app → Deploy a public app from GitHub**.
   Pick the repository, branch `main`, main file `app.py`.
3. Open **Advanced settings**:
   - Python version: **3.12**
   - Secrets (TOML, keys at the root level so they also become environment variables). Either Claude:
     ```toml
     ANTHROPIC_API_KEY = "sk-ant-..."
     ```
     or Gemini (a free key from <https://aistudio.google.com/apikey>):
     ```toml
     GEMINI_API_KEY = "..."
     ```
     With neither, the app runs in offline mode.
4. Click **Deploy**. The first build takes a few minutes. Then open `/health` and click **Check now** under LLM
   reachability.

Fallback host: the `Dockerfile` runs anywhere that runs containers (Render: New → Web Service → Docker; set the same
environment variables).

## Configuration (environment variables, see `.env.example`)
| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | (none) | Enables Claude |
| `GEMINI_API_KEY` | (none) | Enables Gemini (used when there is no Anthropic key) |
| `LLM_PROVIDER` | `auto` | `auto` (Claude, else Gemini, else offline), `anthropic`, `gemini` or `offline` |
| `LLM_MODEL` | `claude-sonnet-5-5` | Claude model ID |
| `LLM_EFFORT` / `LLM_REFUSAL_FALLBACK` | `low` / `on` | Claude effort level; server-side refusal fallback |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini model ID (Flash-Lite has the most generous free tier) |
| `GEMINI_FALLBACK_MODELS` | `gemini-3.1-flash-lite,gemini-3.5-flash` | Backup models tried in order when the main one is busy (503), rate limited or retired; `none` = no backups |
| `GEMINI_RPM` / `GEMINI_THINKING_LEVEL` | `10` / `low` | Gemini requests per minute this app sends (0 = no pacing); thinking level |
| `LLM_MAX_PAGES_PER_DOC` / `LLM_MAX_DOCS_PER_SUBMISSION` | `4` / `8` | Cost guard |
| `APP_BASE_URL` | browser origin | Base of resubmission links in emails |
| `EMAIL_MODE` | `simulated` | `simulated`, `resend` (+`RESEND_API_KEY`) or `smtp` (+`SMTP_*`) |

## Project layout
```
app.py              navigation          core/         all logic (no Streamlit)
views/              one file per page   config/       rules.yaml, policy.yaml
ui/                 theme, charts       data/         scenarios, history, sanctions snapshot, registry, eval
scripts/            generate_data, smoke_test, run_eval, run_cli, refresh_sanctions, export_rules
tests/              pytest (unit, scenario, provider, UI)
```

## Documents
[ARCHITECTURE.md](ARCHITECTURE.md) · [RULES.md](RULES.md) · [ASSUMPTIONS.md](ASSUMPTIONS.md) ·
[LIMITATIONS.md](LIMITATIONS.md) · [EVAL.md](EVAL.md)

## Data sources
- OFAC Sanctions List Service (US Treasury), snapshot published 2026-10-28, public domain (17 U.S.C. §105). Refresh
  with `python scripts/refresh_sanctions.py`.
- GST state codes from the GSTN e-way bill master; IFSC bank codes from the Razorpay IFSC dataset; IRS valid EIN
  prefixes.
