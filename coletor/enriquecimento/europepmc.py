"""Europe PMC: referências (`/{source}/{id}/references`) e texto completo OA (`/{PMCID}/fullTextXML`) — seção 8.1."""

from __future__ import annotations

from lxml import etree

from ..http import ClienteHTTP
from ..modelo import Registro, espacos, normalizar_doi, unicos

RAIZ = "https://www.ebi.ac.uk/europepmc/webservices/rest/"
TAMANHO = 1000  # máximo aceito pelo endpoint de referências
MML = "{http://www.w3.org/1998/Math/MathML}math"
# elementos do <body> que não são texto corrido
FORA = ("fig", "table-wrap", "disp-formula", "inline-formula", "tex-math", "supplementary-material",
        "fn-group", "ref-list", "graphic", "media", "alternatives", "label", MML)
BLOCOS = {"p", "title"}


def referencia(ref: dict) -> str | None:
    doi = normalizar_doi(ref.get("doi"))
    if doi:
        return doi
    fonte, ident = ref.get("source"), ref.get("id")
    if not ident:
        return None
    if fonte == "MED":
        return f"pmid:{ident}"
    if fonte == "PMC" or str(ident).startswith("PMC"):
        return f"pmcid:{ident}"
    return f"{str(fonte).lower()}:{ident}" if fonte else str(ident)


async def referencias(reg: Registro, cliente: ClienteHTTP) -> None:
    fonte = (reg.raw or {}).get("source")
    if (reg.raw or {}).get("hasReferences") != "Y" or not fonte:
        return
    refs: list[str] = []
    total, pagina = None, 1
    while True:
        d = (await cliente.get(RAIZ + f"{fonte}/{reg.id_na_base}/references",
                               params={"format": "json", "pageSize": TAMANHO, "page": pagina})).json()
        total = d.get("hitCount", total)
        lista = (d.get("referenceList") or {}).get("reference") or []
        refs += [referencia(x) for x in lista]
        if not lista or total is None or pagina * TAMANHO >= total:
            break
        pagina += 1
    refs = unicos(refs)
    if refs:
        reg.referencias = refs
        reg.n_referencias = total if total is not None else len(refs)
        reg.fonte_referencias = "nativa"


def jats_para_texto(xml: str) -> str | None:
    """JATS → texto plano: títulos de seção e parágrafos do <body>, um por linha."""
    raiz = etree.fromstring(xml.encode("utf-8"), parser=etree.XMLParser(recover=True, resolve_entities=False))
    if raiz is None:
        return None
    corpo = raiz.find(".//body")
    if corpo is None:
        return None
    etree.strip_elements(corpo, *FORA, with_tail=False)
    linhas = []
    for el in corpo.iter():
        if not isinstance(el.tag, str) or etree.QName(el).localname not in BLOCOS:
            continue
        # parágrafo dentro de outro parágrafo (ex.: listas) já entra no texto do pai
        if any(etree.QName(a).localname == "p" for a in el.iterancestors() if isinstance(a.tag, str)):
            continue
        t = espacos("".join(el.itertext()))
        if t:
            linhas.append(t)
    return "\n".join(linhas) or None


async def texto_completo(reg: Registro, cliente: ClienteHTTP) -> None:
    raw = reg.raw or {}
    if not (reg.pmcid and raw.get("isOpenAccess") == "Y" and raw.get("inEPMC") == "Y"):
        return
    resp = await cliente.get(RAIZ + f"{reg.pmcid}/fullTextXML")
    texto = jats_para_texto(resp.texto)
    if texto:
        reg.texto_completo = texto
    else:
        reg.avisar("texto_completo_indisponivel")
