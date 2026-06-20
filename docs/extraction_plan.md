# Open-Source Extraction Plan

This repo is being carved out as a standalone, reusable Card Vault project. The extraction goal is to keep the useful product surface while removing private deployment assumptions.

## Stories

1. Audit and extraction plan
   - Identify app boundaries, copied files, production-specific strings, private media, credentials, and deployment assumptions.
2. Standalone repo scaffold
   - Add minimal Django settings, URL config, requirements, Docker Compose, CI, license, and security docs.
3. Reusable app and review UI
   - Preserve `card_vault` models, migrations, services, templates, API URLs, web URLs, and tests.
4. Scrub private data and naming
   - Remove private hostnames, user names, media files, hardcoded session ids, and local deployment links.
5. Provider architecture
   - Keep optional provider keys behind environment variables. No provider should be required for local UI review.
6. Tests, demo data, and CI
   - Keep tests runnable with SQLite and mocked providers.
7. Release prep
   - Add documentation for setup, provider configuration, contribution workflow, and security reporting.

## Extraction Principles

- Draft-first: AI and pricing output must remain reviewable and must not auto-approve cards.
- Provider-optional: missing API keys should show clear errors and never crash core pages.
- No scraping by default: use provider APIs and search-result metadata first.
- Privacy by default: no real media, keys, session ids, hostnames, or personal collection data in the public repo.
