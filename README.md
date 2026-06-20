# GergVault

GergVault is a Django app for cataloging trading cards from front/back group photos. The first supported workflow is a 10-card batch intake: upload one front group image and one back group image, create draft card records, review metadata, optionally run AI extraction, and keep every card in review until a human approves it.

This repository is the standalone open-source extraction of the Card Vault module. It intentionally excludes private deployment config, production media, credentials, and local data.

## Features

- Django app/module: `card_vault`
- Batch intake session type: `batch_front_back`
- API endpoint: `POST /api/card-vault/intake/batch/`
- Web dashboard: `/card-vault/`
- Review page: `/card-vault/intake/<session_id>/review/`
- Card detail page: `/card-vault/cards/<card_id>/`
- Draft-first metadata review flow
- Front/back crop slots and crop regeneration hooks
- OpenAI Vision extraction service, optional via `OPENAI_API_KEY`
- Pricing intelligence with Brave Search fallback, optional via `BRAVE_SEARCH_API_KEY`
- Provider-ready pricing architecture for eBay, PriceCharting/SportsCardsPro, PSA, and manual comps

## Quick Start

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Then open:

```text
http://127.0.0.1:8000/card-vault/
```

## Environment

Copy `.env.example` to `.env` if your runtime loads env files, or export values directly.

Required for basic local UI:

- `SECRET_KEY`
- `DEBUG`

Optional provider keys:

- `OPENAI_API_KEY`
- `OPENAI_CARD_VAULT_MODEL`
- `BRAVE_SEARCH_API_KEY`
- `EBAY_CLIENT_ID`
- `EBAY_CLIENT_SECRET`
- `PRICECHARTING_API_KEY`
- `SPORTSCARDSPRO_API_KEY`
- `PSA_API_KEY`

## Management Commands

```bash
python backend/manage.py card_vault_extract_session <session_id>
python backend/manage.py card_vault_update_values <session_id>
python backend/manage.py card_vault_recrop_session <session_id>
python backend/manage.py card_vault_pricing_provider_status
```

Use `--dry-run` where supported to inspect work before writing changes.

## Verification

```bash
python backend/manage.py check
python -m compileall backend/card_vault
python backend/manage.py makemigrations card_vault --check --dry-run
python backend/manage.py test card_vault
```

## Data and Privacy

Do not commit real card scans, production media, user uploads, API keys, or valuation results tied to a private collection. Use synthetic examples under `examples/` for demos and tests.
