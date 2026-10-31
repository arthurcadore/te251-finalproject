"""Utilitários de normalização: HTML/JATS → texto, códigos de idioma, datas parciais."""

from __future__ import annotations

import html
import re

# ISO 639-1 → ISO 639-2/B (códigos usados por MEDLINE/PubMed e Europe PMC: `por[la]`, `LANG:"por"`)
ISO1_PARA_ISO2B = {
    "af": "afr", "ar": "ara", "bg": "bul", "bn": "ben", "ca": "cat", "cs": "cze", "cy": "wel", "da": "dan",
    "de": "ger", "el": "gre", "en": "eng", "es": "spa", "et": "est", "eu": "baq", "fa": "per", "fi": "fin",
    "fr": "fre", "ga": "gle", "gl": "glg", "he": "heb", "hi": "hin", "hr": "hrv", "hu": "hun", "hy": "arm",
    "id": "ind", "is": "ice", "it": "ita", "ja": "jpn", "ka": "geo", "ko": "kor", "lt": "lit", "lv": "lav",
    "mk": "mac", "ms": "may", "nl": "dut", "no": "nor", "pl": "pol", "pt": "por", "ro": "rum", "ru": "rus",
    "sk": "slo", "sl": "slv", "sq": "alb", "sr": "srp", "sv": "swe", "ta": "tam", "th": "tha", "tr": "tur",
    "uk": "ukr", "ur": "urd", "vi": "vie", "zh": "chi",
}
# 3 letras → ISO 639-1 (inclui as variantes ISO 639-2/T: fra, deu, zho, …)
_T = {"fra": "fr", "deu": "de", "zho": "zh", "nld": "nl", "ces": "cs", "ell": "el", "fas": "fa", "ron": "ro",
      "slk": "sk", "isl": "is", "cym": "cy", "sqi": "sq", "mkd": "mk", "kat": "ka", "hye": "hy", "msa": "ms",
      "eus": "eu"}
ISO3_PARA_ISO1 = {**{v: k for k, v in ISO1_PARA_ISO2B.items()}, **_T}

MESES = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
MESES.update({"january": 1, "february": 2, "march": 3, "april": 4, "june": 6, "july": 7, "august": 8,
              "september": 9, "october": 10, "november": 11, "december": 12})

_BLOCO = re.compile(r"</?(?:p|div|br|h[1-6]|li|sec|title|jats:p|jats:title|jats:sec)\b[^>]*>", re.I)
_TAG = re.compile(r"<[^>]+>")


def idioma_iso1(codigo: str | None) -> str | None:
    """'eng' → 'en'; 'EN' → 'en'; código desconhecido é devolvido em minúsculas."""
    if not codigo:
        return None
    c = codigo.strip().lower()
    if len(c) == 2:
        return c
    return ISO3_PARA_ISO1.get(c, c)


def html_para_texto(s: str | None) -> str | None:
    """Remove tags HTML/JATS, decodifica entidades; blocos (<p>, <br>, <h4>…) viram parágrafos (`\\n`)."""
    if not s:
        return None
    s = _BLOCO.sub("\n", s)
    s = html.unescape(_TAG.sub("", s))
    paragrafos = [" ".join(p.split()) for p in s.split("\n")]
    t = "\n".join(p for p in paragrafos if p)
    return t or None


def mes(valor) -> int | None:
    if valor is None:
        return None
    v = str(valor).strip().lower()
    if v.isdigit():
        n = int(v)
        return n if 1 <= n <= 12 else None
    return MESES.get(v[:3]) if v[:3] in MESES else MESES.get(v)


def data_iso(ano, mes_=None, dia=None) -> str | None:
    """Data ISO com a precisão disponível: AAAA-MM-DD, AAAA-MM ou AAAA."""
    try:
        a = int(ano)
    except (TypeError, ValueError):
        return None
    m = mes(mes_)
    if m is None:
        return f"{a:04d}"
    try:
        d = int(dia) if dia is not None else None
    except ValueError:
        d = None
    return f"{a:04d}-{m:02d}-{d:02d}" if d else f"{a:04d}-{m:02d}"


def ano_de(texto: str | None) -> int | None:
    m = re.search(r"\b(1[5-9]\d\d|2\d\d\d)\b", texto or "")
    return int(m.group(1)) if m else None


def orcid(valor: str | None) -> str:
    """'https://orcid.org/0000-…' → '0000-…'; vazio quando não houver."""
    if not valor:
        return ""
    return valor.strip().rstrip("/").rsplit("/", 1)[-1]
