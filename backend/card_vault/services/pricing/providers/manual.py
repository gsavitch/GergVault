from card_vault.services.pricing.normalization import research_links


def search(card, *_args, **_kwargs):
    return {
        "provider": "manual",
        "available": True,
        "warning": "",
        "research_links": research_links(card),
        "comps": [],
    }
