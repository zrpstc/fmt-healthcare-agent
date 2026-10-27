"""HUMAnN stratified-output validation and descriptive contribution summaries."""
from __future__ import annotations
import math
import re
from .inputs import finite


def category(name):
    text=str(name).lower().replace("lactic acid","lactate")
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
