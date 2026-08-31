"""Validate queue state and produce a caption review report."""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

SUSPICIOUS = {
    r"\bluna nova\b": "possível transcrição de 'aluna nova'",
    r"\bprecente\b": "possível erro de 'presente'",
    r"\bcyril\b": "nome possivelmente grafado como Cirilo",
    r"\bcyrilo\b": "nome possivelmente grafado como Cirilo",
    r"\bfirmena\b": "nome possivelmente grafado como Firmino",
    r"-scenes": "prefixo técnico indevido",
    r"publicaã": "texto com codificação corrompida",
}


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def caption_fields(caption: str) -> tuple[str, str]:
    title = re.search(
        r"(?ims)^\s*t[ií]tulo:\s*(.+?)(?=^\s*parte\s+\d+)", caption
    )
    description = re.search(
        r"(?ims)^\s*descri[cç][aã]o:\s*(.+?)(?=^\s*hashtags:)", caption
    )
    return (
        title.group(1).strip() if title else "",
        description.group(1).strip() if description else "",
    )


def validate(manifest, state) -> tuple[list[str], list[str], list[dict]]:
    videos = manifest.get("videos", []) if isinstance(manifest, dict) else manifest
    errors = []
    warnings = []
    review = []
    if not isinstance(videos, list) or not videos:
        return ["O manifesto não possui vídeos."], warnings, review
    ids = []
    paths = []
    normalized_titles = defaultdict(list)
    normalized_descriptions = defaultdict(list)
    for index, item in enumerate(videos, start=1):
        item_id = str(item.get("id", "")).strip()
        path = str(item.get("video_path", "")).strip()
        caption = str(item.get("caption", "")).strip()
        if not item_id or not path or not caption:
            errors.append(f"Item {index} não possui id, video_path ou caption.")
            continue
        ids.append(item_id)
        paths.append(path.casefold())
        number = re.search(r"(\d+)$", item_id)
        if not number:
            errors.append(f"ID inválido: {item_id}")
        elif not re.search(rf"(?im)^\s*PARTE\s+{int(number.group(1))}\s*$", caption):
            errors.append(f"{item_id}: número da legenda não corresponde ao ID.")
        title, description = caption_fields(caption)
        if not title or not description:
            errors.append(f"{item_id}: título ou descrição estruturada ausente.")
        normalized_titles[re.sub(r"\W+", " ", title.casefold()).strip()].append(item_id)
        normalized_descriptions[
            re.sub(r"\W+", " ", description.casefold()).strip()
        ].append(item_id)
        item_warnings = []
        lower = caption.casefold()
        for pattern, explanation in SUSPICIOUS.items():
            if re.search(pattern, lower):
                item_warnings.append(explanation)
        if "cena do capítulo" in lower:
            item_warnings.append("texto genérico; revisar com o vídeo")
        for warning in item_warnings:
            warnings.append(f"{item_id}: {warning}")
        review.append(
            {
                "id": item_id,
                "title": title,
                "description": description,
                "warnings": item_warnings,
            }
        )
    if len(ids) != len(set(ids)):
        errors.append("Há IDs duplicados no manifesto.")
    if len(paths) != len(set(paths)):
        errors.append("Há video_path duplicados no manifesto.")
    for values in normalized_titles.values():
        if len(values) > 1:
            warnings.append(f"Título duplicado: {', '.join(values)}")
    for values in normalized_descriptions.values():
        if len(values) > 1:
            warnings.append(f"Descrição duplicada: {', '.join(values)}")
    known = set(ids)
    for item_id in state.get("published", []):
        if str(item_id) not in known:
            errors.append(f"Estado publicado fora do manifesto: {item_id}")
    inflight = state.get("inflight")
    if inflight and str(inflight.get("item_id")) not in known:
        errors.append("A reserva atual aponta para um item fora do manifesto.")
    if inflight and inflight.get("status", "reserved") not in {"reserved", "published"}:
        errors.append(f"Status de reserva inválido: {inflight.get('status')}")
    for slot in state.get("completed_slots", []):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}:(1245|1930)", str(slot)):
            errors.append(f"Slot concluído inválido: {slot}")
    return errors, warnings, review


def write_report(path: Path, review: list[dict]) -> None:
    lines = ["# Revisão de legendas", "", "Gerado por `scripts/validate_manifest.py`.", ""]
    for item in review:
        status = "revisar" if item["warnings"] else "estrutura válida"
        lines.append(f"- `{item['id']}`: {status} - {item['title']}")
        for warning in item["warnings"]:
            lines.append(f"  - {warning}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("state/manifest.json"))
    parser.add_argument("--state", type=Path, default=Path("state/published.json"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--strict-content", action="store_true")
    args = parser.parse_args()
    errors, warnings, review = validate(
        read_json(args.manifest, []), read_json(args.state, {"published": []})
    )
    if args.report:
        write_report(args.report, review)
    for error in errors:
        print(f"ERRO: {error}")
    for warning in warnings:
        print(f"AVISO: {warning}")
    print(f"Manifesto: {len(review)} itens, {len(errors)} erros, {len(warnings)} avisos.")
    return 1 if errors or (args.strict_content and warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
