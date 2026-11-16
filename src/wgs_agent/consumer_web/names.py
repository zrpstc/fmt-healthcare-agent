"""Chinese display names and the report-wide first-mention registry."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from wgs_agent.reporting.population_reference import species_key
from wgs_agent.reporting.taxon_labels import FALLBACK as GENUS_FALLBACK
from wgs_agent.reporting.functional_metrics import taxon_name

TAXON_CN: dict[str, str] = {
    # phyla
    "firmicutes": "厚壁菌门",
    "bacillota": "厚壁菌门",
    "bacteroidota": "拟杆菌门",
    "bacteroidetes": "拟杆菌门",
    "pseudomonadota": "变形菌门",
    "proteobacteria": "变形菌门",
    "fusobacteriota": "梭杆菌门",
    "fusobacteria": "梭杆菌门",
    "verrucomicrobiota": "疣微菌门",
    "verrucomicrobia": "疣微菌门",
    "actinomycetota": "放线菌门",
    "actinobacteria": "放线菌门",
    "ascomycota": "子囊菌门",
    "methanobacteriota": "甲烷杆菌门",
    "euryarchaeota": "广古菌门",
    # species / genera
    "veillonella rogosae": "罗氏韦荣球菌",
    "veillonella dispar": "差异韦荣球菌",
    "veillonella parvula": "微小韦荣球菌",
    "veillonella infantium": "婴儿韦荣球菌",
    "bacteroides fragilis": "脆弱拟杆菌",
    "faecalibacterium prausnitzii": "普拉梭菌",
    "escherichia coli": "大肠埃希菌",
    "prevotella corporis": "人体普雷沃菌",
    "fusobacterium animalis": "动物梭杆菌",
    "fusobacterium nucleatum": "具核梭杆菌",
    "limosilactobacillus fermentum": "发酵乳杆菌",
    "lactobacillus fermentum": "发酵乳杆菌",
    "roseburia hominis": "人类罗氏菌",
    "akkermansia muciniphila": "嗜黏蛋白阿克曼菌",
    "bifidobacterium adolescentis": "青春双歧杆菌",
    "clostridioides difficile": "艰难梭菌",
    "clostridium difficile": "艰难梭菌",
    "clostridium perfringens": "产气荚膜梭菌",
    "saccharomyces cerevisiae": "酿酒酵母",
    "candida albicans": "白色念珠菌",
    "methanobrevibacter smithii": "史密斯甲烷杆菌",
    "sphingomonas melonis": "甜瓜鞘氨醇单胞菌",
    "salmonella enterica": "肠道沙门菌",
    "klebsiella pneumoniae": "肺炎克雷伯菌",
    "enterobacter cloacae": "阴沟肠杆菌",
    "enterococcus faecalis": "粪肠球菌",
    "citrobacter freundii": "弗氏柠檬酸杆菌",
    "proteus mirabilis": "奇异变形杆菌",
    "mediterraneibacter gnavus": "活泼地中海杆菌",
    "ruminococcus gnavus": "活泼瘤胃球菌",
    "ruminococcus torques": "扭曲瘤胃球菌",
    "agathobacter rectalis": "直肠阿加托杆菌",
    "eubacterium rectale": "直肠真杆菌",
    "anaerostipes hadrus": "霍氏厌氧棍状菌",
    "eubacterium hallii": "霍尔真杆菌",
    "blautia wexlerae": "韦氏布劳特菌",
    "roseburia intestinalis": "肠道罗氏菌",
    "butyricicoccus pullicaecorum": "鸡盲肠丁酸球菌",
    # genera
    "veillonella": "韦荣球菌属",
    "bacteroides": "拟杆菌属",
    "faecalibacterium": "粪杆菌属",
    "escherichia": "埃希菌属",
    "prevotella": "普雷沃菌属",
    "fusobacterium": "梭杆菌属",
    "bifidobacterium": "双歧杆菌属",
    "lactobacillus": "乳杆菌属",
    "lacticaseibacillus": "乳酪杆菌属",
    "lactiplantibacillus": "植物乳杆菌属",
    "limosilactobacillus": "发酵乳杆菌属",
    "ligilactobacillus": "黏液乳杆菌属",
    "roseburia": "罗氏菌属",
    "akkermansia": "阿克曼菌属",
    "clostridioides": "梭菌属",
    "clostridium": "梭菌属",
    "klebsiella": "克雷伯菌属",
    "enterobacter": "肠杆菌属",
    "enterococcus": "肠球菌属",
    "citrobacter": "柠檬酸杆菌属",
    "proteus": "变形杆菌属",
    "bilophila": "嗜胆菌属",
    "desulfovibrio": "脱硫弧菌属",
    "methanobrevibacter": "甲烷杆菌属",
}

ALIASES: dict[str, str] = {
    "lactobacillus fermentum": "limosilactobacillus fermentum",
    "clostridium difficile": "clostridioides difficile",
    "eubacterium rectale": "agathobacter rectalis",
    "ruminococcus gnavus": "mediterraneibacter gnavus",
}


def canonical(name: str) -> str:
    key = species_key(name)
    key = ALIASES.get(key, key)
    return key


def _label_from_report(document: dict, key: str) -> str:
    for field in (
        "chapter_one_taxon_labels",
        "chapter_two_taxon_labels",
        "chapter_three_taxon_labels",
        "overview_taxon_labels",
    ):
        for lookup_key, item in document.get(field, {}).items():
            if species_key(lookup_key) == key:
                label = str(item.get("label") or "").strip()
                if label and label not in {"菌种", "未定种"} and re.search(r"[\u4e00-\u9fff]", label):
                    return label
    return ""


@dataclass
class NameRecord:
    name: str
    latin: str | None
    display: str
    first_mention: bool


@dataclass
class NameRegistry:
    document: dict
    seen: set[str] = field(default_factory=set)

    def _lookup(self, raw: str) -> tuple[str, str | None]:
        clean_raw = taxon_name(raw)
        if clean_raw == "未分类贡献" or not clean_raw:
            return "未分类贡献", None
        key = canonical(clean_raw)
        label = TAXON_CN.get(key) or _label_from_report(self.document, key) or GENUS_FALLBACK.get(key, "")
        latin = re.sub(r"\s+ex\s+.*$", "", str(clean_raw), flags=re.I).replace("_", " ").strip()
        if latin:
            parts = latin.split()
            if parts:
                parts[0] = parts[0][:1].upper() + parts[0][1:].lower()
            latin = " ".join(parts)
        if not label:
            genus = key.split(" ")[0] if key else ""
            genus_label = TAXON_CN.get(genus) or GENUS_FALLBACK.get(genus, "")
            if genus_label:
                label = f"未命名菌（{genus_label}相关）"
            else:
                label = f"未命名菌（{clean_raw.split()[0] if clean_raw.split() else '未知'}菌属相关）"
        return label, (latin if latin and latin.casefold() != label.casefold() else None)

    def taxon_card(self, raw: str) -> NameRecord:
        key = canonical(raw)
        label, latin = self._lookup(raw)
        first = key not in self.seen
        self.seen.add(key)
        return NameRecord(label, latin, label, first)

    def render(self, raw: str) -> str:
        """Return the first-mention form with Markdown italics, then only Chinese."""
        record = self.taxon_card(raw)
        if record.first_mention and record.latin:
            return f"{record.display}（*{record.latin}*）"
        return record.display

    def plain(self, raw: str) -> str:
        return self.taxon_card(raw).display

    def label_only(self, raw: str) -> str:
        return self._lookup(raw)[0]

    def mark_many(self, names: Iterable[str]) -> None:
        for name in names:
            self.taxon_card(name)
