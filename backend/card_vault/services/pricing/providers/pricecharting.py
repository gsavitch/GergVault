import os


def search(*_args, **_kwargs):
    if not os.environ.get("PRICECHARTING_API_KEY"):
        return {"provider": "pricecharting", "available": False, "warning": "PRICECHARTING_API_KEY not set.", "comps": []}
    return {"provider": "pricecharting", "available": False, "warning": "PriceCharting adapter scaffolded; API/export hookup pending.", "comps": []}
