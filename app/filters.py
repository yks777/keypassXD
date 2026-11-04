"""Filtro puro de busca (sem Qt, sem dependências): usado pela tela cheia
do gerenciador. Testável sem PySide6/PyKeePass."""
from __future__ import annotations


def filter_records(records: list[dict], query: str, group: str | None = None) -> list[dict]:
    """Filtra credenciais pelo termo (título/usuário/URL) e, opcionalmente,
    por pasta. `group=None` busca em todas as pastas."""
    term = query.casefold().strip()
    items = records if group is None else [r for r in records if r["group"] == group]
    if not term:
        return list(items)
    return [r for r in items
            if term in (r["title"] + " " + r["username"] + " " + r["url"]).casefold()]
