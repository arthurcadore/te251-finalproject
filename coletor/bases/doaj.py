"""DOAJ — GET https://doaj.org/api/search/articles/{consulta} (mapeamento a partir de tests/fixtures/doaj/).

A API não entrega além de 1.000 resultados por busca (HTTP 400 — confirmado no teste prático).
"""

from __future__ import annotations

from typing import AsyncIterator
from urllib.parse import quote

from ..config import Enriquecimento, Filtros
from ..consulta import No, para_doaj
from ..enriquecimento import opencitations
from ..filtros import LOCAL, NATIVO, TODOS, PlanoFiltros, planejar
from ..modelo import Registro, espacos, normalizar_doi, unicos
from ..segredos import Credenciais
from ..texto import data_iso, idioma_iso1, orcid
from .base import Adaptador, Pagina

RAIZ = "https://doaj.org/api/search/articles/"
LIMITE_API = 1000


class DOAJ(Adaptador):
    chave = "doaj"
    nome = "DOAJ"
    colunas_extras = ["x_doaj_pais_periodico", "x_doaj_assunto_lcc"]

    @classmethod
    def limites_padrao(cls, cred: Credenciais) -> tuple[float, int]:
        return 2, 1

    def suporta(self, filtros: Filtros) -> PlanoFiltros:
        return planejar(filtros, nome_base=self.nome, periodo=NATIVO, idiomas=LOCAL, somente_oa=TODOS,
                        tipos_unicos=frozenset({"artigo"}),
                        campos_nativos=frozenset({"tudo", "titulo", "titulo_resumo"}))

    def traduzir(self, arvore: No, plano: PlanoFiltros) -> str:
        f = self.ctx.config.filtros
        q = para_doaj(arvore, f.campo_busca if plano.nativo("campo_busca") else "tudo")
        if plano.nativo("periodo"):
            de = f.ano_de if f.ano_de is not None else "*"
            ate = f.ano_ate if f.ano_ate is not None else "*"
            q = f"({q}) AND bibjson.year:[{de} TO {ate}]"
        return q

    def idiomas_do_registro(self, reg: Registro) -> list[str]:
        """O DOAJ informa os idiomas do periódico, não do artigo: basta um coincidir."""
        langs = ((reg.raw or {}).get("bibjson") or {}).get("journal", {}).get("language") or []
        return unicos(idioma_iso1(x) for x in langs)

    async def paginas(self, arvore: No, plano: PlanoFiltros, tamanho: int) -> AsyncIterator[Pagina]:
        url = RAIZ + quote(self.traduzir(arvore, plano), safe="")
        pagina = 1
        while True:
            resp = await self.ctx.cliente.get(url, params={"page": pagina, "pageSize": tamanho})
            d = resp.json()
            res = d.get("results") or []
            total = d.get("total")
            vistos = pagina * tamanho
            no_limite = vistos >= LIMITE_API
            ultima = not res or (total is not None and vistos >= total) or no_limite
            if no_limite and total and total > LIMITE_API:
                aviso = f"DOAJ não entrega mais de {LIMITE_API} resultados por busca (total informado: {total})"
                if aviso not in self.ctx.estat.avisos:
                    self.ctx.estat.avisos.append(aviso)
            yield Pagina([self.normalizar(a) for a in res], total, ultima=ultima)
            if ultima:
                return
            pagina += 1

    async def enriquecer(self, registros: list[Registro], opcoes: Enriquecimento) -> list[Registro]:
        """Referências e contagem de citações pelo OpenCitations, a partir do DOI (seção 8.1)."""
        if opcoes.referencias:
            await opencitations.enriquecer(registros, self.ctx.opencitations, self.log)
        return registros

    def normalizar(self, a: dict) -> Registro:
        b = a.get("bibjson") or {}
        j = b.get("journal") or {}
        autores = b.get("author") or []
        doi = next((i.get("id") for i in b.get("identifier") or [] if (i.get("type") or "").lower() == "doi"), None)
        links = b.get("link") or []
        pdf = next((lk.get("url") for lk in links if (lk.get("content_type") or "").lower() in ("pdf", "application/pdf")), None)
        pagina = next((lk.get("url") for lk in links if lk.get("type") == "fulltext"), None)
        ini, fim = b.get("start_page"), b.get("end_page")
        langs = [idioma_iso1(x) for x in j.get("language") or []]
        reg = Registro(
            base=self.chave,
            id_na_base=a.get("id") or "",
            doi=normalizar_doi(doi),
            url_pagina=pagina or (f"https://doaj.org/article/{a['id']}" if a.get("id") else None),
            titulo=espacos(b.get("title")),
            autores=[espacos(x.get("name")) or "" for x in autores],
            autores_orcid=[orcid(x.get("orcid_id")) for x in autores],
            afiliacoes=unicos(espacos(x.get("affiliation")) for x in autores),
            ano=int(b["year"]) if str(b.get("year", "")).isdigit() else None,
            data_publicacao=data_iso(b.get("year"), b.get("month")),
            tipo="artigo",
            idioma=langs[0] if len(langs) == 1 else None,  # vários idiomas do periódico: não dá para escolher
            veiculo=espacos(j.get("title")),
            issn=unicos(j.get("issns") or []),
            editora=espacos(j.get("publisher")),
            volume=j.get("volume"),
            numero=j.get("number"),
            paginas="-".join(x for x in (ini, fim) if x) or None,
            resumo=espacos(b.get("abstract")),
            palavras_chave=unicos(b.get("keywords") or []),
            assuntos=unicos(s.get("term") for s in b.get("subject") or []),
            acesso_aberto=True,
            url_pdf=pdf,
            raw=a,
        )
        reg.extras = {
            "x_doaj_pais_periodico": j.get("country"),
            "x_doaj_assunto_lcc": unicos(s.get("code") for s in b.get("subject") or [] if s.get("scheme") == "LCC"),
        }
        return reg
