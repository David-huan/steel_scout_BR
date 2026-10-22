import hashlib
import re
import unicodedata

from .brief import Brief


ROLES = [
    ("distribuidor", "importer_distributor"),
    ("importador", "importer_distributor"),
    ("centro de serviço", "service_center"),
    ("atacadista", "importer_distributor"),
    ("representante", "trader"),
    ("comércio de metais", "importer_distributor"),
]

FORMS = ["chapas", "bobinas", "tiras", "barras", "perfis", "cantoneiras"]
REGIONS = ["São Paulo", "Curitiba", "Belo Horizonte", "Joinville", "Porto Alegre", "Recife"]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


def query_hash(text: str, lang: str = "pt-BR") -> str:
    return hashlib.sha1(f"{lang}|{normalize(text)}".encode("utf-8")).hexdigest()


def generate_queries(brief: Brief, max_queries: int = 40) -> list[dict]:
    raw: list[dict] = []
    seen: set[str] = set()

    def add(text: str, source: str, dimensions: dict, expected: list[str], priority: int) -> None:
        h = query_hash(text)
        if h in seen:
            return
        seen.add(h)
        raw.append(
            {
                "text": text,
                "lang": "pt-BR",
                "source": source,
                "dimensions": dimensions,
                "expected_types": expected,
                "priority": priority,
                "query_hash": h,
            }
        )

    for role, expected in ROLES:
        for region in REGIONS[:5]:
            add(
                f"{role} de aço inoxidável {region}",
                "template",
                {"role": role, "region": region},
                [expected],
                90 if role in {"importador", "distribuidor"} else 75,
            )
        add(
            f"{role} de aço inox no Brasil",
            "template",
            {"role": role, "region": "BR"},
            [expected],
            80,
        )

    for form in FORMS:
        for region in ["São Paulo", "Paraná", "Santa Catarina", "Minas Gerais"]:
            add(
                f"{form} de aço inoxidável {region}",
                "template",
                {"form": form, "region": region},
                ["importer_distributor", "service_center"],
                78,
            )
        add(
            f"estoque de {form} inox 304",
            "template",
            {"form": form, "signal": "estoque"},
            ["importer_distributor"],
            70,
        )

    for text in [
        "importador de aço inoxidável Brasil",
        "importação de chapas de aço inox",
        "importação de bobinas inox 304",
        "distribuidor de aço inox com estoque",
        "centro de serviço de aço inoxidável",
        "inox para indústria alimentícia",
        "inox para petroquímica",
        "inox para papel e celulose",
        "inox para construção naval",
        "site:abinox.org.br associado inox",
        "site:quemfornece.com aço inox importador",
        "stainless steel distributor Brazil",
    ]:
        add(
            text,
            "template",
            {"signal": text.split()[0]},
            ["importer_distributor", "service_center"],
            60,
        )

    raw.sort(key=lambda q: q["priority"], reverse=True)
    if len(raw) > max_queries:
        head = raw[: max_queries - len(REGIONS)]
        tail = []
        for region in REGIONS:
            for q in raw[max_queries - len(REGIONS) :]:
                if q["dimensions"].get("region") == region and q not in tail:
                    tail.append(q)
                    break
        raw = head + tail
    return raw[:max_queries]
