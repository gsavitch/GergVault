import os


def search(*_args, **_kwargs):
    if not (os.environ.get("EBAY_CLIENT_ID") and os.environ.get("EBAY_CLIENT_SECRET")):
        return {"provider": "ebay_browse", "available": False, "warning": "EBAY_CLIENT_ID/EBAY_CLIENT_SECRET not set.", "comps": []}
    return {"provider": "ebay_browse", "available": False, "warning": "eBay Browse adapter scaffolded; API hookup pending.", "comps": []}
