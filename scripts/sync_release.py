"""Build the publication manifest and optionally synchronize a GitHub Release."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def compose_caption(title: str, part: int, description: str, hashtags: list[str]) -> str:
    tags = " ".join(dict.fromkeys(str(tag).strip() for tag in hashtags if str(tag).strip()))
    return (
        f"Título:\n{title.strip()}\n\n"
        f"PARTE {part}\nSiga @passaproladoofc para mais\n\n"
        f"Descrição:\n{description.strip()}\n\n"
        f"Hashtags:\n{tags}"
    )


def build_entries(
    metadata_path: Path,
    existing_manifest: dict | list | None = None,
    overrides: dict | None = None,
    start_order: int = 1,
    end_order: int | None = None,
    refresh_captions: bool = False,
) -> tuple[list[dict], dict[str, Path]]:
    metadata_path = metadata_path.resolve()
    metadata = read_json(metadata_path, {})
    parts = metadata.get("parts", [])
    if not isinstance(parts, list) or not parts:
        raise ValueError("metadata.json não possui parts válidas.")
    if isinstance(existing_manifest, dict):
        existing_manifest = existing_manifest.get("videos", [])
    existing = {
        str(item.get("id")): item
        for item in (existing_manifest or [])
        if isinstance(item, dict)
    }
    overrides = overrides or {}
    entries = []
    assets = {}
    seen_orders = set()
    for part in sorted(parts, key=lambda item: int(item.get("order", 0))):
        order = int(part.get("order", 0))
        if order < start_order or (end_order is not None and order > end_order):
            continue
        if order <= 0 or order in seen_orders:
            raise ValueError(f"Ordem global inválida ou duplicada: {order}")
        seen_orders.add(order)
        source_ref = str(part.get("video_file", "")).strip()
        if not source_ref:
            raise ValueError(f"Parte {order} não possui video_file.")
        source = (metadata_path.parent / source_ref).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        item_id = f"parte_{order:02d}"
        caption = str(part.get("post_text", "")).strip()
        if not refresh_captions and item_id in existing:
            caption = str(existing[item_id].get("caption", caption)).strip()
        override = overrides.get(item_id)
        if isinstance(override, str):
            caption = override.strip()
        elif isinstance(override, dict):
            caption = compose_caption(
                str(override.get("title", part.get("title", ""))),
                order,
                str(override.get("description", part.get("description", ""))),
                list(override.get("hashtags", part.get("hashtags", []))),
            )
        if not caption:
            raise ValueError(f"Parte {order} não possui legenda.")
        asset_name = f"parte_{order:02d}.mp4"
        entries.append(
            {
                "id": item_id,
                "video_path": asset_name,
                "caption": caption,
                "size": source.stat().st_size,
            }
        )
        assets[asset_name] = source
    if not entries:
        raise ValueError("Nenhuma parte foi selecionada.")
    return entries, assets


def prepare_assets(assets: dict[str, Path], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared = []
    for name, source in assets.items():
        destination = output_dir / name
        if destination.exists() and destination.stat().st_size == source.stat().st_size:
            prepared.append(destination)
            continue
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        if temporary.exists():
            temporary.unlink()
        try:
            os.link(source, temporary)
        except OSError:
            shutil.copy2(source, temporary)
        os.replace(temporary, destination)
        prepared.append(destination)
    return prepared


def gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True, encoding="utf-8"
    )


def synchronize_release(repo: str, tag: str, assets: list[Path]) -> None:
    try:
        result = gh(["release", "view", tag, "--repo", repo, "--json", "assets"])
        remote = {
            item["name"]: int(item.get("size", 0))
            for item in json.loads(result.stdout).get("assets", [])
        }
    except subprocess.CalledProcessError:
        gh(
            [
                "release",
                "create",
                tag,
                "--repo",
                repo,
                "--title",
                tag,
                "--notes",
                "Assets gerados automaticamente a partir do metadata.json.",
            ]
        )
        remote = {}
    for asset in assets:
        if remote.get(asset.name) == asset.stat().st_size:
            print(f"Release: {asset.name} já está atualizado.")
            continue
        gh(["release", "upload", tag, str(asset), "--repo", repo, "--clobber"])
        print(f"Release: {asset.name} enviado.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--overrides", type=Path)
    parser.add_argument("--asset-dir", type=Path)
    parser.add_argument("--start-order", type=int, default=1)
    parser.add_argument("--end-order", type=int)
    parser.add_argument("--refresh-captions", action="store_true")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--repo")
    parser.add_argument("--tag", default="videos-v1")
    args = parser.parse_args()

    existing = read_json(args.manifest, {"videos": []})
    overrides = read_json(args.overrides, {}) if args.overrides else {}
    entries, sources = build_entries(
        args.metadata,
        existing,
        overrides,
        args.start_order,
        args.end_order,
        args.refresh_captions,
    )
    write_json(args.manifest, {"videos": entries})
    print(f"Manifesto atualizado: {len(entries)} vídeos em {args.manifest}")

    prepared = []
    if args.asset_dir:
        prepared = prepare_assets(sources, args.asset_dir.resolve())
        print(f"Assets preparados: {len(prepared)} em {args.asset_dir.resolve()}")
    if args.upload:
        if not args.repo or not args.asset_dir:
            parser.error("--upload exige --repo e --asset-dir")
        synchronize_release(args.repo, args.tag, prepared)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
