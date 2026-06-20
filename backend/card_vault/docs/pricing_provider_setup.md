# Card Vault Pricing Provider Setup

Card Vault Pricing Intelligence is an estimate engine, not a market-value authority. It stores source links, confidence, and warnings so every value can be reviewed.

## Current Fallback Behavior

When only Brave Search is configured, Card Vault can create a low-confidence rough range only if Brave result titles or snippets contain at least two parseable card-price hints after filtering unrelated results. These are labeled `Rough search-based estimate`.

If no verified sold comps or price-guide data are available, the UI explains that clearly. If fewer than two weak price hints are found, the card remains blank and shows `Needs stronger pricing source`.

## Required Environment Variables

- `BRAVE_SEARCH_API_KEY`: search-result discovery and rough fallback hints.
- `EBAY_CLIENT_ID`: future eBay Browse API integration.
- `EBAY_CLIENT_SECRET`: future eBay Browse API integration.
- `PRICECHARTING_API_KEY`: future guide-price provider.
- `SPORTSCARDSPRO_API_KEY`: future guide-price provider.
- `PSA_API_KEY`: future population-report provider.

## eBay Browse API

1. Create or use an eBay Developer account.
2. Create an application in the eBay developer portal.
3. Enable Browse API access for production.
4. Add the app credentials to the GergVault environment:
   - `EBAY_CLIENT_ID`
   - `EBAY_CLIENT_SECRET`
5. Restart the web container so the environment is loaded.
6. Rerun valuation:

```bash
python manage.py card_vault_update_values --session-id <session_id> --force
```

## PriceCharting and SportsCardsPro

These are provider hooks for future guide-price integrations. Add the API key when available:

```bash
PRICECHARTING_API_KEY=...
SPORTSCARDSPRO_API_KEY=...
```

Then restart web and rerun valuation:

```bash
python manage.py card_vault_update_values --session-id <session_id> --force
```

## PSA Pop Report

`PSA_API_KEY` is a placeholder for future population-report integration. PSA data should influence scarcity/grading context, not raw value by itself.

## Provider Status

Check provider readiness without printing secrets:

```bash
python manage.py card_vault_pricing_provider_status
```

## Rerun an Intake

For a 10-card batch:

```bash
python manage.py card_vault_update_values --session-id <session_id> --force
```
