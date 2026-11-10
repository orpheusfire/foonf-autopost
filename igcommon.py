"""Shared helpers: .env loading/writing, token-safe HTTP, redaction. Stdlib only."""
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(HERE, ".env")
GRAPH = "https://graph.instagram.com"
API_VERSION = "v23.0"

_secrets = set()


def load_env(path=ENV_PATH):
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            val = val.strip().strip('"').strip("'")
            env[key.strip()] = val
    token = env.get("IG_ACCESS_TOKEN")
    if token:
        _secrets.add(token)
    return env


def set_env_value(key, value, path=ENV_PATH):
    """Replace (or append) KEY=value in .env atomically, keeping other lines and mode 600."""
    _secrets.add(value)
    with open(path) as f:
        lines = f.readlines()
    out, found = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == key:
            out.append(f"{key}={value}\n")
            found = True
        else:
            out.append(line if line.endswith("\n") else line + "\n")
    if not found:
        out.append(f"{key}={value}\n")
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".env.")
    try:
        with os.fdopen(fd, "w") as f:
            f.writelines(out)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def redact(text):
    text = str(text)
    for s in _secrets:
        if s:
            text = text.replace(s, "<IG_ACCESS_TOKEN>")
    return text


class GraphError(RuntimeError):
    pass


def graph(method, path, params, token, base=GRAPH, versioned=True):
    """Call graph.instagram.com. Token goes in the POST body or query string, never in output."""
    url = f"{base}/{API_VERSION}/{path}" if versioned else f"{base}/{path}"
    params = dict(params, access_token=token)
    data = None
    if method == "GET":
        url += "?" + urllib.parse.urlencode(params)
    else:
        data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            err = json.loads(body).get("error", {})
            msg = f"{err.get('type')} {err.get('code')}: {err.get('message')}"
        except ValueError:
            msg = body[:500]
        raise GraphError(redact(f"{method} /{path} -> HTTP {e.code}: {msg}")) from None
    except urllib.error.URLError as e:
        raise GraphError(redact(f"{method} /{path} -> {e.reason}")) from None
