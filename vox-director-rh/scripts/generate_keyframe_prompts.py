#!/usr/bin/env python3
"""Generate keyframe prompts for a validated Vox Director MVP project.

Offline-only: this script reads/writes local beats.json and never submits a
RunningHub task. Run it after the storyboard content is finalized and strict
validation passes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from new_project import validate_doc

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

# RunningHub reference image-models.md maps “Nano Banana 2” to this endpoint.
DEFAULT_IMAGE_ENDPOINT = "rhart-image-n-g31-flash-lite/text-to-image"
# RunningHub reference image-models.md maps “Nano Banana Pro” to this endpoint.
PRO_IMAGE_ENDPOINT = "rhart-image-n-pro/text-to-image"

THEMES = {
    "newsprint-editorial": {
        "description": (
            "vintage mid-century newspaper front-page editorial collage: broadsheet newsprint layers, "
            "archival photographic cut-outs, magazine illustrations, charcoal-black headlines, deep red "
            "and mustard-yellow accent blocks, heavy halftone dots, slight ink misregistration and paper grain"
        ),
    },
    "swiss-modern": {
        "description": (
            "Swiss/International Typographic paper collage: strict modular grid, geometric cut paper blocks, "
            "clean infographic hierarchy, generous negative space, white/light gray and black with one highly "
            "saturated accent color, strong Akzidenz-Grotesk/Helvetica-like typographic confidence"
        ),
    },
    "chinese-ink": {
        "description": (
            "contemporary Chinese rice-paper collage: xuan paper fibers, ink-wash and woodblock printed cut-outs, "
            "old Chinese newspaper and receipt scraps, bold calligraphic Chinese headline, vermilion seal stamp, "
            "ink black and rice-paper cream with small mineral blue or ochre accents; restrained museum-handbook mood"
        ),
    },
    "american-retro": {
        "description": (
            "mid-century American retro editorial collage: bold retro primaries (red, mustard, teal, cream), "
            "1950s-60s magazine and catalog cut-outs, ben-day halftone, screen-print texture, confident sans-serif banners"
        ),
    },
    "punk-zine": {
        "description": (
            "raw punk zine photomontage: high-contrast black and white photocopied cut-outs, torn tape, rough gouges, "
            "one fluorescent spot color, stencil and ransom-note type energy, gritty DIY grain"
        ),
    },
    "soviet-constructivist": {
        "description": (
            "Soviet Constructivist photomontage: bold diagonal geometry, red/black/cream blocks, strong industrial "
            "composition, hard-edged type, dynamic upward thrust, limited palette, agitprop poster mood"
        ),
    },
    "wpa-propaganda": {
        "description": (
            "1930s WPA / vintage travel silkscreen-poster collage: flat heroic shapes, warm earthy palette, "
            "clean simplified forms, generous solid color blocks, optimistic and dignified civic-poster feeling"
        ),
    },
    "70s-groovy": {
        "description": (
            "1970s groovy print collage: mustard, rust, avocado and cream, wavy organic shapes, retro flower-power "
            "patterns, rounded bubbly display type, warm faded newsprint and risograph texture"
        ),
    },
    "atomic-age": {
        "description": (
            "1950s atomic-age retro-futurism collage: teal, orange and cream, starbursts and boomerang shapes, "
            "chrome-and-bakelite optimism, blueprint diagrams and space-age motifs as flat paper cut-outs"
        ),
    },
    "gilded-deco": {
        "description": (
            "Art Deco gilded editorial collage: aged cream, champagne gold, charcoal black and muted deep gold, "
            "symmetric geometric frames, fan and sunburst motifs, luxurious metallic-paper cut-outs, elegant"
        ),
    },
}

COMMON_STYLE = (
    "Mixed-media hand-cut PAPER COLLAGE in a modern editorial zine style, flat 2D paper collage. "
    "The image must be built from clearly separated torn and scissor-cut paper layers with rough deckled edges, "
    "tape corners, real paper drop shadows, halftone print dots, newspaper clippings, paper-stencil shapes and print grain. "
    "People and objects are printed-image or illustrated paper cut-outs with crisp edges and separated layers. "
    "NOT 3D, NOT CGI, NOT photorealistic, no glossy e-commerce rendering."
)

TECH_SUFFIX = (
    "16:9 horizontal editorial poster composition, straight-on scanned-flat camera, one strong focal point, clear hierarchy, high contrast and consistent paper grain. "
    "Keep every element flat 2D with readable foreground, middle-ground and background layers for subtle parallax animation later."
)


SHOT_SIZE_GUIDE = {
    "WIDE": "a WIDE establishing composition: the subject sits clearly within its full environment with context around it",
    "MEDIUM": "a MEDIUM composition: one main subject centered and dominant, supporting props kept minimal",
    "CLOSE": "a TIGHT CLOSE composition: one key object, gesture or detail fills most of the frame as the focal point",
    "DETAIL": "an extreme DETAIL macro composition: a single texture, number, symbol or small object, bold and graphic",
}


def title_block(shot: dict) -> str:
    if shot.get("title_on_image"):
        headline = str(shot.get("headline", "")).strip()
        return (
            f"Add one torn-paper banner containing one large bold Chinese headline with the exact text “{headline}”. "
            "Render only these exact Chinese characters: keep them sharp, accurate and legible; no wrong characters, no extra letters, no garbled text. "
            "A small sticker, arrow or vermilion seal is allowed, but it must not cover the main subject."
        )
    return "Do not include a headline or readable text in this shot; use only a small sticker, arrow, abstract mark or seal as a graphic accent."


def english_visual_field(shot: dict, field: str, fallback_field: str) -> str:
    """Return the English image-prompt field; Chinese storyboard text must not be rendered."""
    value = str(shot.get(field, "")).strip()
    if value:
        return value
    raise SystemExit(
        f"{shot.get('id')} 缺少英文画面字段 `{field}`。中文 `{fallback_field}` 只用于旁白/分镜，"
        "不能直接进入图片提示词，否则模型可能把它渲染成画面文字。"
    )


def compose_prompt(doc: dict, shot: dict) -> str:
    theme = THEMES[doc["theme"]]
    scene = english_visual_field(shot, "scene_en", "scene")
    palette = english_visual_field(shot, "palette_en", "palette_note")
    element_motion = english_visual_field(shot, "element_motion_en", "element_motion")

    parts = [
        COMMON_STYLE,
        f"Visual theme: {theme['description']}.",
        f"Framing: {SHOT_SIZE_GUIDE.get(str(shot.get('shot_size', 'WIDE')), SHOT_SIZE_GUIDE['WIDE'])}.",
        f"Scene as layered paper cut-out pieces: {scene}",
        f"Background and palette: use bold but restrained flat color and paper tones: {palette}.",
        title_block(shot),
        (
            "Strict text rule: apart from the exact Chinese headline above, do not render any readable words, letters, numbers, newspaper headlines, labels, signs, shop names or timelines. "
            "Turn any documentary or newspaper scraps into abstract unreadable ink marks and texture only."
        ),
        (
            "Layering note: foreground, middle-ground and background must be clearly separated; the subject, props, banner and decorative scraps need independent edges and shadows. "
            f"Planned future motion clue, for composition only: {element_motion}"
        ),
        TECH_SUFFIX,
    ]
    return "\n".join(parts)


def update_project(project_dir: Path, force: bool, set_endpoint: bool, only: set[str] | None = None) -> tuple[int, int]:
    beats_path = project_dir / "beats.json"
    if not beats_path.exists():
        raise SystemExit(f"beats.json not found: {beats_path}")

    doc = json.loads(beats_path.read_text(encoding="utf-8"))
    errors = validate_doc(doc, strict=True, project_dir=project_dir)
    if errors:
        print("Strict validation failed; keyframe prompts were not generated:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    generated = 0
    skipped = 0
    for shot in doc["shots"]:
        if only and shot.get("id") not in only:
            skipped += 1
            continue
        if shot.get("keyframe_prompt") and not force:
            skipped += 1
            continue
        shot["keyframe_prompt"] = compose_prompt(doc, shot)
        generated += 1

    if set_endpoint and not doc.get("image_endpoint"):
        doc["image_endpoint"] = DEFAULT_IMAGE_ENDPOINT
    # Nano Banana 2 low-cost channel exposes prompt + aspectRatio only; do not send resolution.
    doc.pop("image_resolution", None)

    beats_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return generated, skipped


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate offline keyframe prompts in beats.json")
    parser.add_argument("project_dir", help="Project directory containing beats.json")
    parser.add_argument("--only", help="Comma-separated shot IDs, e.g. s3,s4")
    parser.add_argument("--force", action="store_true", help="Overwrite existing keyframe_prompt values")
    parser.add_argument("--set-default-endpoint", action="store_true",
                        help=f"Set image_endpoint to Nano Banana 2 ({DEFAULT_IMAGE_ENDPOINT}) when empty")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    project_dir = Path(args.project_dir).resolve()
    only = {item.strip() for item in args.only.split(",") if item.strip()} if args.only else None
    generated, skipped = update_project(project_dir, args.force, args.set_default_endpoint, only)
    print(f"Keyframe prompts written: {project_dir / 'beats.json'}")
    print(f"Generated: {generated}; skipped existing: {skipped}")
    if skipped and not args.force:
        print("Use --force to overwrite existing keyframe_prompt values.")
    print(f"Default image endpoint (Nano Banana 2): {DEFAULT_IMAGE_ENDPOINT}")
    print(f"Higher-quality alternative (Nano Banana Pro): {PRO_IMAGE_ENDPOINT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
