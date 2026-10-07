"""Turn a card (character / scene / prop) into a full image prompt."""

KINDS = ("character", "scene", "prop")

DEFAULT_TEMPLATES = {
    "character": (
        "{style}\n"
        "Character design reference of {title}: {description}. "
        "Full body, front view, standing in a neutral pose, plain light grey studio background, "
        "soft even lighting, highly detailed, consistent design."
    ),
    "scene": (
        "{style}\n"
        "Location concept art, {title}: {description}. "
        "Wide establishing shot, no people, cinematic composition, clear sense of space and depth."
    ),
    "prop": (
        "{style}\n"
        "Prop design of {title}: {description}. "
        "Single object, centered, isolated on a plain light grey background, product photography lighting, "
        "highly detailed."
    ),
}

# ~1.5 MP buckets, multiples of 32 (Qwen Image 2.1 is used at 1024x1536 on the PC).
ASPECTS = {
    "1:1": (1248, 1248),
    "16:9": (1664, 928),
    "9:16": (928, 1664),
    "4:3": (1440, 1088),
    "3:4": (1088, 1440),
    "3:2": (1536, 1024),
    "2:3": (1024, 1536),
}

DEFAULT_NEGATIVE = (
    "text, letters, watermark, signature, cartoon, illustration, painting, 3d render, oversaturated, "
    "deformed hands, extra fingers"
)

# Added to the project negative so plates stay clean for use as video references.
KIND_NEGATIVE = {
    "character": "multiple people, crowd, busy background",
    "scene": "people, person, figure, crowd, horse",
    "prop": "people, person, hands, cluttered background",
}

DEFAULT_ASPECT = {"character": "2:3", "scene": "16:9", "prop": "1:1"}


def compose_negative(kind: str, negative: str) -> str:
    parts = [negative.strip().strip(","), KIND_NEGATIVE.get(kind, "")]
    return ", ".join(p for p in parts if p)


def compose(kind: str, title: str, description: str, style: str, templates: dict | None = None) -> str:
    template = (templates or {}).get(kind) or DEFAULT_TEMPLATES.get(kind, "{style}\n{title}: {description}")
    # Plain replace, not str.format: user text may contain braces.
    text = (
        template.replace("{style}", style.strip())
        .replace("{title}", title.strip() or kind)
        .replace("{description}", description.strip().rstrip("."))
    )
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)
