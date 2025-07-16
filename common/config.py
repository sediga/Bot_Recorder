import json
import os
from pathlib import Path

_config_path = Path(__file__).parent.parent / "agent_config.json"
_api_base = "http://localhost:5000"
_auth_type = "jwt"
_api_key = "u42Q7gXgVx8fN1rLk9eJ0cGm5wYzA2dR"

if _config_path.exists():
    with open(_config_path) as f:
        conf = json.load(f)
        _api_base = conf.get("apiBaseUrl", _api_base)
        _auth_type = conf.get("authType", _auth_type)
        _api_key = conf.get("apiKey")

API_BASE_URL = os.getenv("BOTFLOWS_API_URL", _api_base)
AUTH_TYPE = _auth_type
API_KEY = _api_key

def get_api_url(path: str) -> str:
    return f"{API_BASE_URL.rstrip('/')}/{path.lstrip('/')}"