# GergVault Hosted Strategy

GergVault has two connected products:

1. **Open-source GergVault**
   - Self-hostable Django app.
   - Batch card intake, review, card detail, AI/pricing provider hooks, and collection workflows.
   - Intended for collectors, developers, and contributors who want to run or extend the system themselves.

2. **Hosted GergVault**
   - Public hosted service at `gergvault.halobridge.ai`.
   - Built from the same core codebase.
   - Adds multi-tenant account isolation and managed operational features.
   - Free while early, with donations first and paid tiers later.

## Product Rule

The hosted version should feel like the polished version of the open-source product, not a disconnected fork.

Shared core features should include:

- card models and intake sessions
- front/back batch upload
- review UI and card detail pages
- image/crop records
- AI extraction interfaces
- pricing provider interfaces
- import/export primitives
- tests and management commands

Hosted-only features can include:

- tenant/workspace isolation
- hosted media storage and backups
- managed OpenAI/Brave/eBay/price-guide provider configuration
- usage limits, quotas, and billing
- collaboration and sharing
- support/admin tooling
- premium automation and bulk workflows

## Free-to-Paid Path

Early hosted service:

- free account creation
- basic card intake
- manual review
- limited provider-powered enrichment as capacity allows
- donations/support links

Future paid tiers:

- larger collection limits
- more AI extraction runs
- managed pricing-provider credits
- advanced valuation history
- exports and reports
- team/collaboration features
- priority support

## Multi-Tenant Requirements

Before charging users, hosted GergVault needs explicit tenant boundaries:

- every user-visible collection object belongs to a tenant/workspace
- cards, sessions, images, valuations, locations, and provider runs are tenant-scoped
- queries filter by tenant by default
- media paths avoid leaking tenant data
- admin/support tools clearly show tenant ownership
- tests prove cross-tenant data cannot be accessed

## Implementation Notes

Do not bolt billing onto single-user assumptions. Add tenancy first, then usage tracking, then paid plans.

Preferred sequence:

1. Add `CardVaultTenant` or workspace model.
2. Attach users to tenants with roles.
3. Scope all Card Vault models to tenant.
4. Add query helpers/managers for tenant filtering.
5. Add cross-tenant isolation tests.
6. Add hosted usage counters.
7. Add donation links.
8. Add billing/payments only after isolation and usage accounting are stable.
