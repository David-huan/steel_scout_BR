from dataclasses import dataclass, field


COUNTRY_ALIASES = {
    "br": "BR",
    "brazil": "BR",
    "brasil": "BR",
    "巴西": "BR",
}


@dataclass
class Brief:
    product: str
    country: str
    category: str
    ncm: list[str] = field(default_factory=list)
    grades: list[str] = field(default_factory=list)
    forms: list[str] = field(default_factory=list)
    search_hints: list[str] = field(default_factory=list)
    negative_keywords: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    target_count: int = 15
    needs_review: bool = False
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "product": self.product,
            "country": self.country,
            "category": self.category,
            "ncm": self.ncm,
            "grades": self.grades,
            "forms": self.forms,
            "search_hints": self.search_hints,
            "negative_keywords": self.negative_keywords,
            "regions": self.regions,
            "target_count": self.target_count,
            "needs_review": self.needs_review,
            "confidence": self.confidence,
        }


def _contains_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def build_brief(product: str, country: str, target_count: int = 15) -> Brief:
    if not product or not product.strip():
        raise ValueError("product is required")
    if not country or not country.strip():
        raise ValueError("country is required")

    country_key = country.strip().lower()
    country_code = COUNTRY_ALIASES.get(country_key)
    if not country_code:
        raise ValueError(f"UNSUPPORTED_COUNTRY:{country}")

    product_norm = product.strip().lower()
    stainless = _contains_any(
        product_norm,
        ["stainless", "inox", "inoxidável", "inoxidavel", "不锈"],
    )
    flat_profile = _contains_any(
        product_norm,
        ["flat", "sheet", "plate", "coil", "strip", "profile", "bar", "板", "卷", "型材", "棒"],
    )
    tubes_only = _contains_any(product_norm, ["tube", "tubo", "pipe"]) and not flat_profile

    if stainless and flat_profile and not tubes_only:
        category = "stainless_steel_flat_profiles"
        confidence = 0.96
        needs_review = False
    elif stainless and tubes_only:
        category = "stainless_steel_tubes"
        confidence = 0.7
        needs_review = True
    else:
        category = "other"
        confidence = 0.35
        needs_review = True

    return Brief(
        product=product.strip(),
        country=country_code,
        category=category,
        ncm=["7219", "7220", "7222"] if category == "stainless_steel_flat_profiles" else [],
        grades=["201", "304", "304L", "316", "316L", "430", "439", "441"],
        forms=["chapas", "bobinas", "tiras", "blanks", "barras", "perfis", "cantoneiras"],
        search_hints=[
            "distribuidor de aço inoxidável",
            "importador de aço inox",
            "chapas de aço inox",
            "bobinas inox 304",
            "barras e perfis de inox",
            "centro de serviço inox",
            "estoque de inox",
        ],
        negative_keywords=[
            "sucata",
            "reciclagem",
            "ferro-velho",
            "usina siderúrgica",
            "produção de aço",
        ],
        regions=["SP", "PR", "SC", "MG", "RS", "DF"],
        target_count=max(1, min(int(target_count or 15), 200)),
        needs_review=needs_review,
        confidence=confidence,
    )
