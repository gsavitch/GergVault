import os


def search(*_args, **_kwargs):
    if not os.environ.get("SPORTSCARDSPRO_API_KEY"):
        return {"provider": "sportscardspro", "available": False, "warning": "SPORTSCARDSPRO_API_KEY not set.", "comps": []}
    return {"provider": "sportscardspro", "available": False, "warning": "SportsCardsPro adapter scaffolded; API/export hookup pending.", "comps": []}
