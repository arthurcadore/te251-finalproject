"""Registro das bases: adicionar uma base = criar o adaptador e incluí-lo em BASES."""

from __future__ import annotations

from .arxiv import ArXiv
from .base import Adaptador
from .core import Core
from .crossref import Crossref
from .doaj import DOAJ
from .europepmc import EuropePMC
from .openalex import OpenAlex
from .pubmed import PubMed
from .scielo import SciELO
from .semantic_scholar import SemanticScholar

BASES: dict[str, type[Adaptador]] = {
    "openalex": OpenAlex,
    "semantic_scholar": SemanticScholar,
    "crossref": Crossref,
    "arxiv": ArXiv,
    "pubmed": PubMed,
    "europepmc": EuropePMC,
    "core": Core,
    "doaj": DOAJ,
    "scielo": SciELO,
}

# Credenciais por base (seção 4): (obrigatória, opcionais)
CREDENCIAIS: dict[str, tuple[str | None, tuple[str, ...]]] = {
    "openalex": ("OPENALEX_API_KEY", ()),
    "semantic_scholar": (None, ("S2_API_KEY",)),
    "crossref": (None, ("CONTACT_EMAIL",)),
    "arxiv": (None, ()),
    "pubmed": (None, ("NCBI_API_KEY", "CONTACT_EMAIL")),
    "europepmc": (None, ()),
    "core": (None, ("CORE_API_KEY",)),
    "doaj": (None, ()),
    "scielo": (None, ()),
    "opencitations": (None, ("OPENCITATIONS_TOKEN",)),
}
