"""Public chapter numbering; original Word/evidence identifiers stay stable."""
import re

REMOVED_CHAPTER = 11
OUTLINE_VERSION = "report-outline-13-chapters-v1"


def display_number(source_number):
    return source_number - (source_number > REMOVED_CHAPTER)


def visible_chapters(chapters):
    return tuple((display_number(n), *rest) for n, *rest in chapters if n != REMOVED_CHAPTER)


def display_references(value):
    """Change explicit chapter/caption references, never bare measurement values."""
    value = str(value)
    value = re.sub(r"(?m)^(#{2,3}\s+)(1[234])(?=[.\s])",
                   lambda m: m[1] + str(display_number(int(m[2]))), value)
    value = re.sub(r"(!\[)(1[234])(?=\.\d+\s)",
                   lambda m: m[1] + str(display_number(int(m[2]))), value)
    value = re.sub(r"(第\s*)(1[234])(?=(?:\.\d+)?\s*[章节])",
                   lambda m: m[1] + str(display_number(int(m[2]))), value)
    return re.sub(r"([图表]\s*)(1[234])(?=[-－.])",
                  lambda m: m[1] + str(display_number(int(m[2]))), value)
