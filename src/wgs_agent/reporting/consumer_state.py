"""Report-scoped state shared by chapters opting into the consumer presentation."""
from __future__ import annotations


def consumer(document):
    state = document.setdefault("consumer", {})
    state.setdefault("version", "consumer-v1")
    return state


def omit(document, chapter, item, reason_code, reason_cn):
    row = {"chapter": chapter, "item": item, "reason_code": reason_code, "reason_cn": reason_cn}
    rows = document.setdefault("consumer_omissions", [])
    if not any((r["chapter"], r["item"]) == (chapter, item) for r in rows):
        rows.append(row)
    return None


def table(headers, rows):
    """Consumer tables retain deliberately empty explanation cells."""
    from .document import text
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |",
                      *("| " + " | ".join(text(cell, missing="") for cell in row) + " |" for row in rows)])


class NameRegistry:
    """One registry per rendering; reset when rendering the same report again."""
    def __init__(self, document):
        self.state = consumer(document)
        self.seen = set()

    def name(self, row):
        from .taxon_labels import display_name
        from .reference import species_key
        key = species_key(row.get("species") or row.get("name") or row.get("label", ""))
        first = key not in self.seen
        self.seen.add(key)
        self.state["names_seen"] = sorted(self.seen)
        return display_name(row, first_mention=first)

    def mark(self, rows):
        for row in rows:
            self.name(row)
