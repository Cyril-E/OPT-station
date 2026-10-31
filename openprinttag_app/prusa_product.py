"""Read the selected Prusament product from the official shop's embedded JSON."""
from html.parser import HTMLParser
import json
import math
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from .domain import get_schema, validate_fields
from .prusament import NoRedirect, Page, PrusamentError

MAX_PAGE = 2 * 1024 * 1024
INVALID_PAGE = "La fiche produit Prusa reçue est illisible. Réessayez ou complétez la fiche manuellement."
PRODUCT_NOTICE = "Fiche produit uniquement : poids réel, tare, date de fabrication et consommation ne sont pas fournis. Lisez le tag NFC ou complétez ces valeurs si vous les connaissez."
COLOR_NOTICE = "La couleur provient du nuancier de la boutique; vérifiez-la avant enregistrement."


def product_url(text):
    """Canonicalize only the documented public product route, including bare QR URLs."""
    if not isinstance(text, str):
        return None
    value = text.strip()
    if re.search(r"[\x00-\x20\x7f]", value):
        return None
    if re.match(r"(?i)(?:www\.)?prusa3d\.com/", value):
        value = "https://" + value
    try:
        url = urlsplit(value)
        if (url.scheme.lower() not in {"http", "https"}
                or url.netloc.lower() not in {"prusa3d.com", "www.prusa3d.com"}
                or url.query or url.fragment or len(url.path) > 220):
            return None
        if re.fullmatch(r"/product/prusament-[a-z0-9]+(?:-[a-z0-9]+)*/?", url.path):
            return "https://www.prusa3d.com" + url.path.rstrip("/") + "/"
    except ValueError:
        pass
    return None


def fetch_page(url):
    assert product_url(url) == url
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        request = Request(url, headers={"User-Agent": "OPT-Station Prusa product QR", "Accept": "text/html"})
        with opener.open(request, timeout=8) as response:
            if response.headers.get_content_type() != "text/html":
                raise PrusamentError(INVALID_PAGE)
            content = response.read(MAX_PAGE + 1)
            if len(content) > MAX_PAGE:
                raise PrusamentError(INVALID_PAGE)
            return content.decode("utf-8")
    except HTTPError as exc:
        if exc.code == 404:
            raise PrusamentError("Ce produit est introuvable sur Prusa. Vérifiez le QR ou complétez la fiche manuellement.", 404) from None
        raise PrusamentError("La boutique Prusa est indisponible. Réessayez l’analyse ou utilisez une fiche de la bibliothèque.") from None
    except (URLError, OSError, TimeoutError):
        raise PrusamentError("La boutique Prusa est injoignable. Vérifiez la connexion Internet du Pi puis réessayez l’analyse.", 503) from None
    except UnicodeError:
        raise PrusamentError(INVALID_PAGE) from None


class ProductPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = None
        self.documents = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            attrs = dict(attrs)
            if attrs.get("id") == "__NEXT_DATA__" and attrs.get("type") == "application/json":
                self.active = []
                self.documents.append(self.active)

    def handle_endtag(self, tag):
        if tag == "script":
            self.active = None

    def handle_data(self, data):
        if self.active is not None:
            self.active.append(data)


def weight(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*([0-9]+(?:[.,][0-9]+)?)\s*(kg|g)\s*", value, re.I)
    if match:
        grams = float(match[1].replace(",", ".")) * (1000 if match[2].lower() == "kg" else 1)
        if math.isfinite(grams) and grams > 0:
            return grams
    return None


def parse_page(html, url):
    try:
        if not isinstance(html, str) or len(html.encode("utf-8")) > MAX_PAGE or product_url(url) != url:
            raise ValueError()
        page = ProductPage(); page.feed(html)
        if len(page.documents) != 1:
            raise ValueError()
        document = json.loads("".join(page.documents[0]))
        cache = document["props"]["pageProps"]["urqlState"]
        if not isinstance(cache, dict) or len(cache) > 256:
            raise ValueError()
        slug = urlsplit(url).path.lstrip("/")
        candidates = []
        for entry in cache.values():
            data = entry.get("data") if isinstance(entry, dict) else None
            if isinstance(data, str):
                data = json.loads(data)
            product = data.get("product") if isinstance(data, dict) else None
            if isinstance(product, dict) and product.get("slug") in {slug, slug.rstrip("/")}:
                candidates.append(product)
        if len(candidates) != 1:
            raise ValueError()
        product = candidates[0]
        if (product.get("detailTemplateType") != "FILAMENT" or product.get("brand", {}).get("name") != "Prusament"
                or not isinstance(product.get("name"), str) or not product["name"].startswith("Prusament ")):
            raise ValueError()
        main = {"material_class": "FFF", "brand_name": "Prusament", "material_name": product["name"]}
        options = next(field["options"] for field in get_schema()["main"] if field["name"] == "material_type")
        for material in sorted((option["value"] for option in options), key=len, reverse=True):
            if re.match(r"Prusament\s+" + re.escape(material) + r"(?:\b|[- ])", product["name"]):
                main["material_type"] = material
                break
        parameters = product.get("parameters", [])
        if not isinstance(parameters, list):
            raise ValueError()
        weights, colors = set(), set()
        named_weight = re.search(r"\b([0-9]+(?:[.,][0-9]+)?\s*(?:kg|g))\b", product["name"], re.I)
        if named_weight and (value := weight(named_weight[1])) is not None:
            weights.add(value)
        for parameter in parameters:
            if not isinstance(parameter, dict):
                raise ValueError()
            if parameter.get("name") == "Weight":
                for item in parameter.get("values", []):
                    value = weight(item.get("text")) if isinstance(item, dict) else None
                    if value is not None:
                        weights.add(value)
            if parameter.get("name") == "Filament color" and parameter.get("__typename") == "ColorParameter":
                color = parameter.get("rgbHex")
                if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                    colors.add(color.lower())
        if len(weights) > 1 or len(colors) > 1:
            raise ValueError()
        if weights:
            main["nominal_netto_full_weight"] = weights.pop()
        if colors:
            main["primary_color"] = colors.pop()
        description = product.get("description") or ""
        if not isinstance(description, str):
            raise ValueError()
        text_page = Page(); text_page.feed(description)
        text = " ".join(text_page.text)
        diameters = set(re.findall(r"\bFilament diameter\s+([0-9]+(?:[.,][0-9]+)?)\s*mm\b", text, re.I))
        if len(diameters) > 1:
            raise ValueError()
        if diameters:
            main["filament_diameter"] = float(diameters.pop().replace(",", "."))
        for label, prefix in (("Nozzle temperature", "print"), ("Heatbed temperature", "bed")):
            pattern = re.escape(label) + r"\s+([0-9]+(?:[.,][0-9]+)?)\s*(±|\+/-|[-–])\s*([0-9]+(?:[.,][0-9]+)?)\s*°?\s*C\b"
            ranges = set()
            for center, symbol, spread in re.findall(pattern, text, re.I):
                a, b = float(center.replace(",", ".")), float(spread.replace(",", "."))
                ranges.add((a, b) if symbol in {"-", "–"} else (a - b, a + b))
            if len(ranges) > 1:
                raise ValueError()
            if ranges:
                low, high = ranges.pop()
                if low <= 0 or high < low or not low.is_integer() or not high.is_integer():
                    raise ValueError()
                main[f"min_{prefix}_temperature"], main[f"max_{prefix}_temperature"] = int(low), int(high)
        main = validate_fields("main", main, partial=True)
        return {"kind": "prusa_product", "main": main, "aux": {}, "matches": [],
                "source_url": url, "source_scope": "product",
                "warnings": [PRODUCT_NOTICE] + ([COLOR_NOTICE] if "primary_color" in main else []),
                "message": "Fiche produit Prusa récupérée. Vérifiez les valeurs avant enregistrement."}
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError, OverflowError):
        raise PrusamentError(INVALID_PAGE) from None


def resolve_prusa_product(text, fetch=None):
    url = product_url(text)
    if url is None:
        return None
    return {**parse_page((fetch or fetch_page)(url), url), "raw": text}
