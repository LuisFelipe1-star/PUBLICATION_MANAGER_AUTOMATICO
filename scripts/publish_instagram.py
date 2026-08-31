"""Headless Instagram publisher used by GitHub Actions."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "state" / "manifest.json"
PUBLISHED = ROOT / "state" / "published.json"
PUBLICATION_SLOTS = {"1245", "1930"}
BAHIA_TIME = timezone(timedelta(hours=-3))


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def publication_slot_key(slot: str, now: datetime | None = None) -> str | None:
    slot = slot.strip()
    if slot not in PUBLICATION_SLOTS:
        return None
    current = now or datetime.now(timezone.utc)
    local_day = current.astimezone(BAHIA_TIME).date().isoformat()
    return f"{local_day}:{slot}"


def mark_slot_completed(state: dict, slot_key: str) -> None:
    completed = [str(item) for item in state.get("completed_slots", [])]
    if slot_key not in completed:
        completed.append(slot_key)
    state["completed_slots"] = completed[-120:]


def write_state(state: dict) -> None:
    PUBLISHED.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def api(method: str, url: str, token: str, **kwargs):
    params = kwargs.pop("params", {})
    params["access_token"] = token
    response = requests.request(method, url, params=params, timeout=180, **kwargs)
    data = response.json()
    if not response.ok or "error" in data:
        raise RuntimeError(f"Instagram API {response.status_code}: {data}")
    return data


def instagram_caption(raw: str) -> str:
    """Convert the cutter's structured text into a clean Instagram caption."""
    text = (raw or "").replace("\r\n", "\n").strip()
    title_match = re.search(
        r"(?ims)^\s*t[ií]tulo:\s*(.+?)(?=^\s*(?:parte\s+\d+|siga\s+@|descri[cç][aã]o:|hashtags:)|\Z)",
        text,
    )
    description_match = re.search(
        r"(?ims)^\s*descri[cç][aã]o:\s*(.+?)(?=^\s*hashtags:|\Z)",
        text,
    )

    title = title_match.group(1).strip() if title_match else ""
    description = description_match.group(1).strip() if description_match else ""
    description = re.sub(r"\s*#[\wÀ-ÿ]+", "", description).strip()

    hashtags = []
    seen = set()
    blocked = {"#facebookreels", "#viral", "#novelas", "#novela", "#carrosel"}
    for tag in re.findall(r"#[\wÀ-ÿ]+", text):
        key = tag.casefold()
        if key in blocked or key in seen:
            continue
        seen.add(key)
        hashtags.append(tag)
    if "#reels" not in seen:
        hashtags.append("#Reels")

    if not title and not description:
        clean = re.sub(
            r"(?im)^\s*(?:t[ií]tulo:|descri[cç][aã]o:|hashtags:|parte\s+\d+|siga\s+@\S+.*)$",
            "",
            text,
        )
        clean = re.sub(r"#[\wÀ-ÿ]+", "", clean)
        description = re.sub(r"\n{3,}", "\n\n", clean).strip()

    follow = "Siga @passaproladoofc para acompanhar os próximos cortes."
    return "\n\n".join(
        part for part in (title, description, follow, " ".join(hashtags[:10])) if part
    )


def main() -> int:
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    user_id = os.environ.get("IG_USER_ID", "").strip()
    version = os.environ.get("GRAPH_VERSION", "").strip() or "v26.0"
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    publishing_enabled = os.environ.get("PUBLISHING_ENABLED", "").lower() == "true"
    slot_key = publication_slot_key(os.environ.get("PUBLISH_SLOT", ""))
    if not dry_run and not publishing_enabled:
        raise RuntimeError(
            "Publicacao pausada. Defina PUBLISHING_ENABLED=true nas Variables do GitHub."
        )
    if not token or not user_id:
        raise RuntimeError("Configure IG_ACCESS_TOKEN e IG_USER_ID nos Secrets do GitHub.")

    manifest = read_json(MANIFEST, [])
    if isinstance(manifest, dict):
        manifest = manifest.get("videos", [])
    state = read_json(PUBLISHED, {"published": []})
    if slot_key and slot_key in {str(item) for item in state.get("completed_slots", [])}:
        print(f"Horario {slot_key} ja concluido; nenhuma publicacao sera repetida.")
        return 0
    done = {str(item) for item in state.get("published", [])}
    pending = [item for item in manifest if str(item.get("id")) not in done]
    if not pending:
        print("Fila concluida: nenhum video pendente.")
        if slot_key and not dry_run:
            mark_slot_completed(state, slot_key)
            write_state(state)
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
    base = f"https://graph.facebook.com/{version}"
    if dry_run:
        account = api(
            "GET",
            f"{base}/{user_id}",
            token,
            params={"fields": "id,username"},
        )
        print(
            "Credenciais validas para "
            f"@{account.get('username', 'conta-sem-username')} ({account.get('id')})."
        )
        print("DRY_RUN=true: credenciais validadas; nada sera publicado.")
        return 0

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
    if slot_key:
        mark_slot_completed(state, slot_key)
    write_state(state)
    print(f"Publicado {item_id}: {published.get('id')}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise
