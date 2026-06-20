import os


def search(*_args, **_kwargs):
    if not os.environ.get("PSA_API_KEY"):
        return {"provider": "psa", "available": False, "warning": "PSA_API_KEY not set.", "comps": []}
    return {"provider": "psa", "available": False, "warning": "PSA adapter scaffolded; pop-report API hookup pending.", "comps": []}
