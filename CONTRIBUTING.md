# Contributing

Thanks for helping improve GergVault.

## Local Checks

```bash
cd backend
python manage.py check
python manage.py test card_vault
```

## Data Safety

Do not commit real card scans, private collections, production database dumps,
API keys, private hostnames, or user-uploaded media. Use synthetic examples or
small intentionally redistributable fixtures.

## Provider Work

Provider integrations must be optional. Missing API keys should produce clear
status messages and must not crash pages.
