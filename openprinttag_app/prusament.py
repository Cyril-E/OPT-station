"""Read data embedded in official Prusament spool pages, without executing JS."""
from datetime import datetime
from html.parser import HTMLParser
import json
import math
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .domain import get_schema, validate_fields

MAX_PAGE = 512 * 1024


class PrusamentError(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


def spool_url(text):
    try:
        url = urlsplit(text.strip())
        if (url.scheme.lower() not in {"http", "https"}
                or url.netloc.lower() not in {"prusament.com", "www.prusament.com"}
                or url.query or url.fragment):
            return None
        match = re.fullmatch(r"/spool/([1-9][0-9]{0,8})/([0-9a-fA-F]{10})/?", url.path)
        if match:
            return f"https://prusament.com/spool/{match[1]}/{match[2].lower()}/"
    except (ValueError, AttributeError):
        pass
    return None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_page(url):
    # Only the canonical URL constructed above is ever requested. No page assets.
    assert spool_url(url) == url
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        request = Request(url, headers={"User-Agent": "OPT-Station Prusament QR", "Accept": "text/html"})
        with opener.open(request, timeout=8) as response:
            if response.headers.get_content_type() != "text/html":
                raise PrusamentError("La fiche Prusament reçue est illisible. Réessayez ou complétez la fiche manuellement.")
            body = response.read(MAX_PAGE + 1)
            if len(body) > MAX_PAGE:
                raise PrusamentError("La fiche Prusament reçue est illisible. Réessayez ou complétez la fiche manuellement.")
            return body.decode("utf-8")
    except HTTPError as exc:
        if exc.code == 404:
            raise PrusamentError("Cette bobine est introuvable sur Prusament. Vérifiez le QR ou complétez la fiche manuellement.", 404) from None
        raise PrusamentError("Prusament est indisponible. Réessayez l’analyse ou utilisez une fiche de la bibliothèque.") from None
    except (URLError, OSError, TimeoutError):
        raise PrusamentError("Prusament est injoignable. Vérifiez la connexion Internet du Pi puis réessayez l’analyse.", 503) from None
    except UnicodeError:
        raise PrusamentError("La fiche Prusament reçue est illisible. Réessayez ou complétez la fiche manuellement.") from None


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.script = False
        self.style = False
        self.scripts, self.text = [], []

    def handle_starttag(self, tag, attrs):
        if tag == "script": self.script = True
        if tag == "style": self.style = True

    def handle_endtag(self, tag):
        if tag == "script": self.script = False
        if tag == "style": self.style = False

    def handle_data(self, value):
        if self.script: self.scripts.append(value)
        elif not self.style: self.text.append(value)


def parse_page(html, url):
    try:
        if not isinstance(html, str) or len(html.encode("utf-8")) > MAX_PAGE:
            raise ValueError()
        page = Page(); page.feed(html)
        scripts = "\n".join(page.scripts)
        if re.search(r"\bspoolFound\s*=\s*false\b", scripts):
            raise ValueError()
        literals = re.findall(r"\b(?:var|let|const)\s+spoolData\s*=\s*'((?:\\.|[^'\\])*)'\s*;", scripts)
        if len(literals) != 1:
            raise ValueError()
        # JSON data in a single-quoted JS literal; never eval or run page code.
        data = json.loads(literals[0].replace("\\'", "'"))
        product, identifier = url.rstrip("/").split("/")[-2:]
        if not isinstance(data, dict) or str(data.get("ff_goods_id")) != product:
            raise ValueError()
        filament = data.get("filament")
        if not isinstance(filament, dict) or not isinstance(filament.get("name"), str) or not filament["name"].strip():
            raise ValueError()
        main = {"material_class": "FFF", "brand_name": "Prusament",
                "material_name": filament["name"], "brand_specific_instance_id": identifier}

        def number(source, key, target, scale=1):
            value = source.get(key)
            if type(value) in {int, float} and math.isfinite(value) and value > 0:
                main[target] = value * scale

        material = filament.get("material", "")
        if isinstance(material, str):
            options = next(f["options"] for f in get_schema()["main"] if f["name"] == "material_type")
            for option in sorted((o["value"] for o in options), key=len, reverse=True):
                if re.fullmatch(re.escape(option) + r"(?:[ -].*)?", material):
                    main["material_type"] = option; break
        if isinstance(filament.get("color_rgb"), str) and re.fullmatch(r"#[0-9a-fA-F]{6}", filament["color_rgb"]):
            main["primary_color"] = filament["color_rgb"]
        nominal = re.search(r"\b([0-9]+(?:[.,][0-9]+)?)\s*(kg|g)\b", filament["name"], re.I)
        if nominal:
            main["nominal_netto_full_weight"] = float(nominal[1].replace(",", ".")) * (1000 if nominal[2].lower() == "kg" else 1)
        number(data, "weight", "actual_netto_full_weight")
        number(data, "spool_weight", "empty_container_weight")  # Zero means not supplied, not a zero-gram container.
        number(data, "length", "actual_full_length", 1000)  # Page: metres; OpenPrintTag: millimetres.
        for key, target in (("he_min", "min_print_temperature"), ("he_max", "max_print_temperature"),
                            ("hb_min", "min_bed_temperature"), ("hb_max", "max_bed_temperature")):
            number(filament, key, target)
        diameter = re.search(r"\bDiameter\s+([0-9]+(?:[.,][0-9]+)?)\s*mm\b", " ".join(page.text))
        if diameter:
            main["filament_diameter"] = float(diameter[1].replace(",", "."))
        country = data.get("country")
        if isinstance(country, str) and re.fullmatch(r"[A-Z]{2}", country):
            main["country_of_origin"] = country
        try:
            date = datetime.fromisoformat(data["manufacture_date"])
            if date.tzinfo is not None and date.timestamp() >= 0:
                main["manufactured_date"] = int(date.timestamp())
        except (KeyError, ValueError, TypeError, OverflowError):
            pass
        main = validate_fields("main", main, partial=True)
        warnings = []
        if "empty_container_weight" not in main:
            warnings.append("Le poids du contenant vide n’est pas renseigné par Prusament. Complétez-le si vous le connaissez.")
        return {"kind": "prusament", "main": main, "aux": {}, "matches": [], "warnings": warnings,
                "source_url": url, "message": "Fiche Prusament récupérée. Vérifiez les valeurs; les informations absentes restent à compléter."}
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        raise PrusamentError("La fiche Prusament reçue est illisible. Réessayez ou complétez la fiche manuellement.") from None


def resolve_prusament(text, fetch=None):
    url = spool_url(text)
    if url is None:
        return None
    return {**parse_page((fetch or fetch_page)(url), url), "raw": text}
