"""HUMAnN stratified-output validation and descriptive contribution summaries."""
from __future__ import annotations
import math
import re
from .inputs import finite


def category(name):
    text=str(name).lower().replace("lactic acid","lactate")
    # MetaCyc PWY-5022 ends in butanoate; other GABA degradation routes do not.
    if text.strip() == "4-aminobutanoate degradation v":
        return "丁酸合成"
    if re.search(r"\b(?:butyrate|butanoate)\b|丁酸",text):
        if not re.search(r"aminobutanoate|(?:butanoate|butyrate) (?:degradation|utilization|oxidation|consumption)|丁酸(?:降解|利用|氧化)",text):
            return "丁酸合成"
    if (re.search(r"\blactate\s+(?:degradation|utilization|oxidation|consumption|fermentation to)",text)
            or "乳酸利用" in text or "乳酸降解" in text):
        return "乳酸利用"
    if any(w in text for w in ["lipopolysaccharide","lipid a","peptidoglycan","脂多糖","肽聚糖"]):
        return None
    substrate=any(w in text for w in ["starch","pectin","xylan","polysaccharide","cellulose","多糖","淀粉","木聚糖","果胶","纤维素"])
    degradation=any(w in text for w in ["degradation","utilization","hydrolysis","降解","利用"])
    return "复杂多糖降解" if substrate and degradation else None


def taxon_name(value):
    value=str(value or "").strip()
    if value.lower() in {"","unclassified","unassigned","unknown"}:
        return "未分类贡献"
    parts=re.split(r"(?:\.|\|)s__",value)
    if len(parts)>1:
        value=parts[-1]
    else:
        value=re.sub(r"^[sg]__","",value)
    value=value.replace("_"," ")
    return "未分类贡献" if value.lower() in {"unclassified","unassigned","unknown"} else value


def contributor_summary(row):
    def canonical_unit(value):
        text=str(value or "").strip().lower()
        return {"相对丰度":"relative_abundance","relative abundance":"relative_abundance","percent":"%","percentage":"%","未提供":"","单位未提供":""}.get(text,text)
    members=row.get("contributors")
    result={"status":"missing","reason":"未提供分层贡献记录","members":[],"named_count":0,
            "top_named_share":None,"top_named_taxon":None,"unknown_share":None,
            "complete":row.get("contributors_complete") is True,"denominator":None,
            "scope":"已记录分层贡献内占比"}
    if not isinstance(members,list) or not members:
        return result
    parsed=[];seen=set();units=set()
    for member in members:
        if not isinstance(member,dict):
            return {**result,"reason":"分层记录格式无效"}
        value=finite(member.get("abundance",member.get("value")))
        raw=member.get("taxon") or member.get("species") or member.get("name")
        unit=member.get("unit",row.get("unit"))
        if value is None or value<0 or not raw or not unit:
            return {**result,"reason":"分层记录数值或单位缺失"}
        key=str(raw).casefold()
        if key in seen:
            return {**result,"reason":"分层分类单元重复，暂不计算占比"}
        seen.add(key);units.add(canonical_unit(unit))
        if value>0:parsed.append({"taxon":str(raw),"name":taxon_name(raw),"value":value})
    if len(units)!=1 or "" in units or (canonical_unit(row.get("unit")) and canonical_unit(row["unit"]) not in units):
        return {**result,"reason":"分层贡献单位不一致"}
    total=math.fsum(member["value"] for member in parsed)
    if total<=0:
        return {**result,"reason":"分层贡献总和为0，未计算占比"}
    parsed.sort(key=lambda r:-r["value"])
    for member in parsed:member["share"]=100*member["value"]/total
    named=[member for member in parsed if member["name"]!="未分类贡献"]
    return {**result,"status":"available","reason":"","members":parsed,"denominator":total,
            "named_count":len(named),"top_named_share":named[0]["share"] if named else None,
            "top_named_taxon":named[0]["name"] if named else None,
            "unknown_share":sum(member["share"] for member in parsed if member["name"]=="未分类贡献"),
            "scope":"完整输出分层内占比" if result["complete"] else "已记录分层贡献内占比（完整性未确认）"}


def read_humann_pathways(path):
    communities={};strata={};special={};issues=set()
    with path.open(encoding="utf-8-sig") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):continue
            fields=line.rstrip("\r\n").split("\t")
            value=finite(fields[1]) if len(fields)==2 else None
            if value is None or value<0:
                issues.add("invalid_numeric_or_column_count");continue
            base,_,taxon=fields[0].partition("|")
            if base in {"UNMAPPED","UNINTEGRATED"}:
                if not taxon:special[base]=value
                continue
            if taxon:
                values=strata.setdefault(base,{})
                if taxon in values:issues.add("duplicate_stratified_row")
                else:values[taxon]=value
            elif base in communities:issues.add("duplicate_community_row")
            else:communities[base]=value
    if set(strata)-set(communities):issues.add("orphan_stratified_rows")
    if not communities:issues.add("empty_community_output")
    rows=[]
    for base,value in communities.items():
        ident,sep,label=base.partition(":")
        members=[{"taxon":taxon,"abundance":amount,"unit":"relative_abundance"}
                 for taxon,amount in strata.get(base,{}).items()]
        rows.append({"id":ident,"name":label.strip() if sep else base,"abundance":value,
                     "unit":"relative_abundance","data_type":"functional_potential","source_file":str(path),
                     "contributors":members,"contributors_complete":bool(members) and not issues,
                     "stratification_validation":"complete_output_read" if members and not issues else "no_strata" if not members else "invalid_output",
                     "contribution_denominator":"sum_of_recorded_strata_including_unclassified"})
    return {"pathways":sorted(rows,key=lambda r:-r["abundance"]),"special_rows":special,
            "unit":"relative_abundance","is_complete":not issues,"method":"HUMAnN pathway profiling",
            "source_file":str(path),"n_total_pathways":len(rows),
            "stratification_source":"canonical_humann_output_v1","validation_issues":sorted(issues)}


CATEGORY_PATHWAYS = {
    "丁酸合成": frozenset({"CENTFERM-PWY", "PWY-5676", "P162-PWY", "P163-PWY", "PWY-5022"}),
    "乳酸利用": frozenset({"PWY-8086"}),
}
ENZYME_MARKERS = {"丁酸合成": frozenset({"2.8.3.8", "2.7.2.7"})}


def pathway_category(row):
    """Prefer curated pathway identities over ambiguous substrate substrings."""
    ident = str(row.get("id", "")).split(":", 1)[0]
    for name, identifiers in CATEGORY_PATHWAYS.items():
        if ident in identifiers:
            return name
    name = str(row.get("name") or row.get("label") or "")
    if name.strip().casefold() == "4-aminobutanoate degradation v":
        return "丁酸合成"
    return category(name)


def _category_pathways(document):
    rows = []
    seen = set()
    for row in document.get("evidence", {}).values():
        if row.get("kind") not in {"pathway", "function"} or row.get("measurement_type") == "unverified":
            continue
        ident = str(row.get("id") or row.get("name") or row.get("label"))
        if ident in seen:
            continue
        amount = finite(row.get("value", row.get("abundance")))
        if amount is not None and amount > 0:
            rows.append(row)
            seen.add(ident)
    return rows


def _enzyme_contributors(document, category_name):
    markers = ENZYME_MARKERS.get(category_name, ())
    inputs = document.get("template_inputs", {})
    module = inputs.get("functional_modules") or {}
    candidates = list(module.get("results", [])) if module.get("status") == "completed" else []
    marker_module = document.get("consumer", {}).get("enzyme_markers") or {}
    if marker_module.get("status") == "available":
        candidates += marker_module.get("results", [])
    candidates += [r for r in document.get("evidence", {}).values() if r.get("ec_number") or str(r.get("id", "")).startswith("EC:")]
    found = {}
    for row in candidates:
        ec = str(row.get("ec_number") or row.get("id", "")).removeprefix("EC:")
        if ec not in markers or row.get("measurement_type") == "unverified":
            continue
        summary = contributor_summary(row)
        if summary["status"] != "available":
            continue
        for member in summary["members"]:
            if member["name"] == "未分类贡献":
                continue
            key = member["name"].casefold()
            item = found.setdefault(key, {"taxon": member["taxon"], "name": member["name"], "value": None,
                                          "share": None, "evidence": [], "enzyme_markers": []})
            if ec not in item["enzyme_markers"]:
                item["enzyme_markers"].append(ec)
                item["evidence"].append({"type": "enzyme_marker", "ec_number": ec,
                                          "abundance": member["value"], "unit": row.get("unit")})
    return found


def aggregate_category(document, category_name):
    """Aggregate every observed HUMAnN pathway in one functional category (G11).

    Returns category, status, pathways, per_pathway (original records plus validated
    summaries), contributors (deduplicated named taxa and unknown contribution),
    named_count, top_named_share, unknown_share, denominator, unit, complete and
    unit_consistent. Shares are percentages of ALL recorded stratified values,
    including unclassified values, across all usable same-unit pathways. They are
    not organism abundance, pathway abundance, or a measure of activity.

    Mixed or missing units never produce a pooled denominator or shares. Their
    per_pathway summaries remain available for separate display. Enzyme-marker
    contributors are merged by taxon identity, with evidence.type= enzyme_marker;
    their enzyme quantities are NEVER added to pathway quantities or share
    denominators. Missing stratification remains explicit in per_pathway and
    complete=False. The input's raw evidence is never altered.
    """
    paths = [row for row in _category_pathways(document) if pathway_category(row) == category_name]
    details = [{"pathway": row, "summary": contributor_summary(row)} for row in paths]
    usable = [r for r in details if r["summary"]["status"] == "available"]
    aliases = {"相对丰度": "relative_abundance", "relative abundance": "relative_abundance",
               "percent": "%", "percentage": "%"}
    units = {aliases.get(str(r["pathway"].get("unit", "")).strip().lower(),
                         str(r["pathway"].get("unit", "")).strip().lower()) for r in details}
    unit_consistent = len(units) <= 1 and "" not in units
    members = {}
    for item in usable:
        for member in item["summary"]["members"]:
            key = member["name"].casefold()
            target = members.setdefault(key, {"taxon": member["taxon"], "name": member["name"],
                                             "values": [], "evidence": [], "pathway_ids": []})
            target["values"].append(member["value"])
            target["pathway_ids"].append(item["pathway"].get("id"))
            target["evidence"].append({"type": "pathway", "pathway_id": item["pathway"].get("id")})
    denominator = math.fsum(math.fsum(r["values"]) for r in members.values()) if unit_consistent else None
    result_members = []
    for item in members.values():
        values = item.pop("values")
        value = math.fsum(values) if unit_consistent else None
        result_members.append({**item, "value": value,
                               "share": 100 * value / denominator if denominator else None})
    lookup = {r["name"].casefold(): r for r in result_members}
    for key, marker in _enzyme_contributors(document, category_name).items():
        if key in lookup:
            lookup[key]["evidence"].extend(marker["evidence"])
            lookup[key]["enzyme_markers"] = marker["enzyme_markers"]
        else:
            result_members.append(marker)
    result_members.sort(key=lambda r: (r["share"] is None, -(r["share"] or 0), r["name"]))
    named = [r for r in result_members if r["name"] != "未分类贡献"]
    unknown = next((r["share"] for r in result_members if r["name"] == "未分类贡献"), 0.0 if denominator else None)
    return {"category": category_name, "status": "available" if named else "missing",
            "pathways": paths, "per_pathway": details, "contributors": result_members,
            "named_count": len(named), "top_named_share": named[0]["share"] if named else None,
            "unknown_share": unknown, "denominator": denominator,
            "unit": next(iter(units)) if unit_consistent and units else None,
            "unit_consistent": unit_consistent,
            "complete": bool(paths) and all(r["summary"]["status"] == "available" and r["summary"]["complete"] for r in details),
            "reason": "mixed_or_missing_units" if not unit_consistent else "incomplete_pathway_stratification" if len(usable) != len(paths) else "",
            "share_scope": "sum_of_recorded_category_strata_including_unclassified"}


def record_function_consistency(document, category_name, aggregate, glossary_entries):
    """Record coverage gaps for abundant tagged taxa without inventing gene evidence.

    glossary_entries is supplied by the shared G4 service as resolved taxon entries
    (latin_name/name/species and tags). Existing gaps for this category are replaced
    deterministically; other categories and raw inputs are preserved.
    """
    from .reference import species_key
    tag = {"丁酸合成": "butyrate_producer", "乳酸利用": "lactate_utilizer",
           "复杂多糖降解": "polysaccharide_degrader"}.get(category_name)
    tagged = {species_key(r.get("latin_name") or r.get("latin") or r.get("species") or r.get("name"))
              for r in glossary_entries if tag in r.get("tags", [])}
    contributors = {species_key(r["name"]) for r in aggregate["contributors"]}
    taxonomy = document.get("template_inputs", {}).get("taxonomy", {})
    gaps = []
    for row in taxonomy.get("ranks", {}).get("species", []):
        name = row.get("name") or row.get("species") or row.get("taxon")
        if species_key(name) in tagged and (finite(row.get("abundance")) or 0) >= 1 and species_key(name) not in contributors:
            gaps.append({"type": "coverage_gap", "category": category_name, "species": str(name),
                         "abundance": finite(row.get("abundance")), "unit": "%", "reason": "tagged_taxon_not_in_gene_contributors"})
    consumer = document.setdefault("consumer", {})
    records = consumer.setdefault("function_consistency", [])
    records[:] = [r for r in records if r.get("category") != category_name] + gaps
    return gaps
