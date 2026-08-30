"""Headless Instagram publisher used by GitHub Actions."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from urllib.parse import quote
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "state" / "manifest.json"
PUBLISHED = ROOT / "state" / "published.json"


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def api(method: str, url: str, token: str, **kwargs):
    params = kwargs.pop("params", {})
    params["access_token"] = token
    response = requests.request(method, url, params=params, timeout=180, **kwargs)
    data = response.json()
    if not response.ok or "error" in data:
        raise RuntimeError(f"Instagram API {response.status_code}: {data}")
    return data


def instagram_caption(raw: str) -> str:
    """Keep each cut's text while adding Instagram-only defaults once."""
    base = re.sub(r"#facebookreels\b", "", raw or "", flags=re.IGNORECASE).strip()
    present = {tag.casefold() for tag in re.findall(r"#[\wÀ-ÿ]+", base)}
    defaults = "#reels #instagramreels #viral #carrosel #novelas #novela"
    extra = [tag for tag in defaults.split() if tag.casefold() not in present]
    follow = "Siga @passaproladoofc para mais"
    return "\n\n".join(part for part in (base, " ".join(extra), follow) if part)


def main() -> int:
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    user_id = os.environ.get("IG_USER_ID", "").strip()
    version = os.environ.get("GRAPH_VERSION", "").strip() or "v26.0"
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    if not dry_run and (not token or not user_id):
        raise RuntimeError("Configure IG_ACCESS_TOKEN e IG_USER_ID nos Secrets do GitHub.")

    manifest = read_json(MANIFEST, [])
    if isinstance(manifest, dict):
        manifest = manifest.get("videos", [])
    state = read_json(PUBLISHED, {"published": []})
    done = {str(item) for item in state.get("published", [])}
    pending = [item for item in manifest if str(item.get("id")) not in done]
    if not pending:
        print("Fila concluida: nenhum video pendente.")
        return 0

    item = pending[0]
    item_id = str(item["id"])
    caption = instagram_caption(str(item.get("caption", "")).strip())
    video_url = str(item.get("video_url", "")).strip()
    if not video_url:
        base_url = os.environ.get("VIDEO_BASE_URL", "").strip().rstrip("/")
        video_path = str(item.get("video_path", "")).strip()
        if not video_path:
            raise RuntimeError("O item da fila nao possui video_path.")
        if not base_url and not dry_run:
            raise RuntimeError("Configure VIDEO_BASE_URL e video_path no manifest.")
        video_url = f"{base_url}/{quote(video_path)}" if base_url else f"(VIDEO_BASE_URL)/{video_path}"
    print(f"Proximo video: {item_id}")
    print(f"URL: {video_url}")
    if dry_run:
        print("DRY_RUN=true: nada sera publicado.")
        return 0

    base = f"https://graph.facebook.com/{version}"
    container = api("POST", f"{base}/{user_id}/media", token,
                    data={"media_type": "REELS", "video_url": video_url,
                          "caption": caption, "share_to_feed": "true"})
    creation_id = container["id"]
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        status = api("GET", f"{base}/{creation_id}", token,
                     params={"fields": "status_code,status"})
        code = status.get("status_code")
        if code == "FINISHED":
            break
        if code in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Container falhou: {status}")
        time.sleep(10)
    else:
        raise RuntimeError("Timeout aguardando processamento do Reel.")

    published = api("POST", f"{base}/{user_id}/media_publish", token,
                    data={"creation_id": creation_id})
    state.setdefault("published", []).append(item_id)
    state["published"] = list(dict.fromkeys(state["published"]))
    PUBLISHED.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Publicado {item_id}: {published.get('id')}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise
