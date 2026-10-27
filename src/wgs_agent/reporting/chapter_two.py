"""Data-backed diversity, observed functional contributors and unlinked stage evidence."""
from __future__ import annotations
import re
from PIL import Image, ImageDraw
from .inputs import finite
from .functional_metrics import category, contributor_summary, taxon_name
from .taxon_labels import translate_overview_taxa
from .reference import species_key

VERSION="chapter-two-data-bound-v1"
METRICS=[("richness","检出丰富度"),("shannon","Shannon 指数"),("simpson","Simpson 指数（1−D）"),("evenness","Pielou 均匀度")]
CATEGORIES=["丁酸合成","乳酸利用","复杂多糖降解"]


def qc_failed(document):
    return str(document.get("metadata",{}).get("qc_status","")).lower() in {"failed","fail","未通过","不通过"}


def diversity_rows(document):
    if qc_failed(document):return []
    evidence=list(document.get("evidence",{}).values());rows=[]
    for key,label in METRICS:
        ref=next((r for r in evidence if r.get("kind")=="healthy_diversity" and r.get("metric")==key),None)
        primary=next((r for r in evidence if r.get("kind")=="div_"+key),None)
        if ref is None:
            ref=next((r for r in evidence if r.get("kind")=="div_reference" and r.get("metric")==key),None)
        row=ref or primary
        if not row or finite(row.get("value")) is None or finite(row.get("value"))<0:continue
        rows.append({**row,"metric":key,"label":label,"primary_value":finite(primary.get("value")) if primary else None,
                     "profile_label":"MHNO 独立谱" if ref and ref.get("kind")=="healthy_diversity" else "本次样本"})
    return rows


def filter_diversity_table(document,rows):
    covered={row["metric"] for row in diversity_rows(document)}
    def metric(label):
        text=str(label).lower().replace(" ","")
        if "丰富度估计" in text:return None
        if "shannon" in text:return "shannon"
        if "simpson" in text:return "simpson"
        if "均匀度" in text:return "evenness"
        if "观测物种数" in text or "检出丰富度" in text:return "richness"
        return None
    return [row for row in rows if metric(row[0]) not in covered]


def pathway_rows(document):
    if qc_failed(document):return []
    return [r for r in document.get("evidence",{}).values() if r.get("kind") in {"pathway","function"}
            and r.get("measurement_type")!="unverified" and finite(r.get("value",r.get("abundance"))) is not None
            and finite(r.get("value",r.get("abundance")))>0]


def redundancy_rows(document):
    paths=pathway_rows(document);result=[]
    for label in CATEGORIES:
        candidates=[r for r in paths if category(r.get("name",r.get("label","")))==label]
        candidates.sort(key=lambda r:(contributor_summary(r)["status"]!="available",-(finite(r.get("value",r.get("abundance"))) or 0)))
        row=candidates[0] if candidates else None
        summary=contributor_summary(row) if row else {"status":"missing","reason":"未提供对应通路记录","members":[],"named_count":0,"top_named_share":None,"unknown_share":None,"complete":False}
        result.append({"label":label,"pathway":row,"summary":summary,"candidate_count":len(candidates)})
    return result


def display_name(document,value):
    plain=taxon_name(value)
    if plain=="未分类贡献":return plain
    genus_only=bool(re.search(r"\bsp\b",plain,re.I))
    lookup=plain.split()[0] if genus_only else plain
    labels=document.get("chapter_two_taxon_labels",{})
    row=labels.get(species_key(lookup)) or document.get("chapter_one_taxon_labels",{}).get(species_key(lookup)) or document.get("overview_taxon_labels",{}).get(species_key(lookup))
    label=row["label"] if row else plain
    return label+"未定种" if genus_only else label


def _major(document,row):
    summary=contributor_summary(row)
    members=[r for r in summary["members"] if r["name"]!="未分类贡献"][:3]
    return "；".join(display_name(document,r["taxon"]) for r in members) or ("仅有未分类分层" if summary["members"] else "未提供分层贡献")


def cooperation_data(document):
    if qc_failed(document):return {"stages":[],"connections":[],"source":"qc_failed"}
    module=document.get("template_inputs",{}).get("metabolic_cooperation") or {}
    explicit=module.get("stages",[]) if isinstance(module,dict) else []
    if explicit:
        stages=[]
        for item in explicit[:3]:
            if not isinstance(item,dict):continue
            contributors=item.get("contributors",item.get("taxon","未提供"))
            if isinstance(contributors,list):contributors="；".join(map(str,contributors))
            stages.append({"stage":str(item.get("stage","功能环节")),"contributors":str(contributors),
                           "function":str(item.get("function",item.get("product","未提供"))),
                           "link_evidence":str(item.get("link_evidence",item.get("evidence","未提供连接证据"))),
                           "pathway":None})
        links=[r for r in module.get("connections",[]) if isinstance(r,dict) and r.get("supported") is True and r.get("evidence")]
        return {"stages":stages,"connections":links,"source":"provided_stage_records"}
    paths=pathway_rows(document)
    natural=[r for r in paths if "engineered" not in str(r.get("label","")).lower()]
    groups=[("底物初级降解",[r for r in natural if category(r.get("label",""))=="复杂多糖降解"],"多糖初级降解"),
            ("中间产物周转",[r for r in natural if "glycolysis" in str(r.get("label","")).lower() or "糖酵解" in str(r.get("label",""))],"糖酵解相关功能"),
            ("终产物生成",[r for r in natural if category(r.get("label",""))=="丁酸合成"],"丁酸生成相关功能")]
    stages=[]
    for stage,candidates,function in groups:
        preferred={"底物初级降解":"PWY-6731","中间产物周转":"ANAGLYCOLYSIS-PWY","终产物生成":"PWY-5676"}
        candidates.sort(key=lambda r:(contributor_summary(r)["status"]!="available",r.get("id")!=preferred[stage],-(finite(r.get("value",r.get("abundance"))) or 0)))
        row=candidates[0] if candidates else None
        if row:
            ident=str(row.get("id",""));value=finite(row.get("value",row.get("abundance")))
            text=f"{function}（{ident}）；通路丰度 {value:.5g} {row.get('unit','')}"
            stages.append({"stage":stage,"contributors":_major(document,row),"function":text,
                           "link_evidence":"通路与分层注释；未提供菌间交换连接证据","pathway":row})
        else:
            stages.append({"stage":stage,"contributors":"未提供对应分层记录","function":"未提供对应通路记录",
                           "link_evidence":"未提供连接证据","pathway":None})
    return {"stages":stages,"connections":[],"source":"independent_pathway_stage_annotations"}


def prepare_chapter_two(document,config,*,post=None,fallback_config=None):
    members=[]
    for record in redundancy_rows(document):members.extend(record["summary"]["members"])
    for stage in cooperation_data(document)["stages"]:
        if stage.get("pathway"):members.extend(contributor_summary(stage["pathway"])["members"])
    rows=[]
    for member in members:
        plain=member["name"]
        if plain=="未分类贡献":continue
        if re.search(r"\bsp\b",plain,re.I):plain=plain.split()[0]
        rows.append({"kind":"species","species":plain,"label":plain})
    translate_overview_taxa(document,config,post=post,fallback_config=fallback_config,rows=rows,
                           label_field="chapter_two_taxon_labels",audit_field="chapter_two_taxon_translation")
    document["chapter_two_results"]={"version":VERSION,"diversity":diversity_rows(document),
        "redundancy":redundancy_rows(document),"cooperation":cooperation_data(document)}


def redundancy_table(document):
    rows=[]
    for item in redundancy_rows(document):
        path=item["pathway"];summary=item["summary"]
        label=item["label"]+(f"（{path['id']}）" if path and path.get("id") else "")
        if summary["status"]!="available":
            rows.append([label,"未提供可用分层贡献",summary["reason"],"未建立功能参考分布"]);continue
        count=f"{summary['named_count']} 个已注释分类单元"
        if summary["unknown_share"]:count+="；另有未分类贡献"
        share=(f"{summary['top_named_share']:.4g}%（已记录分层内）" if summary["top_named_share"] is not None else "贡献均未分类，无法确定首位物种")
        rows.append([label,count,share,"未建立功能参考分布"])
    return rows


def cooperation_table(document):
    return [[r["stage"],r["contributors"],r["function"],r["link_evidence"]] for r in cooperation_data(document)["stages"]]


def paragraph_override(document,text):
    if text.startswith("图 2-4"):
        return "图 2-4  已记录的功能阶段（菌间连接未验证）"
    if text.startswith("功能冗余"):
        return "功能冗余  "+"；".join(f"{r[0]}：{r[1]}" for r in redundancy_table(document))
    if text.startswith("贡献集中度"):
        partial=any(r["summary"]["status"]=="available" and not r["summary"]["complete"] for r in redundancy_rows(document))
        return "贡献集中度  占比以每条通路的已记录分层贡献总和为分母，包含未分类贡献；不使用群落通路总丰度作分母。"+("分层完整性未确认的项目，完整分层贡献比例暂不计算，图中仅展示已有记录内比例。" if partial else "")
    if text.startswith("结果解读"):
        data=cooperation_data(document)
        if data["source"]=="provided_stage_records":return "结果解读  按已有阶段记录展示功能与贡献菌，连接仅在明确提供支持记录时绘制。"
        found=[r["stage"] for r in data["stages"] if r.get("pathway")]
        return "结果解读  "+("已记录"+"、".join(found)+"的独立通路功能潜能；尚无菌间交换连接证据，图中不绘制传递箭头。" if found else "本次未提供对应通路或阶段记录，暂无法描述潜在分工。")
    return None


def chart_payload(document,spec):
    from .word_figures import _dataset,_series
    if spec["id"]=="2.1.1":
        rows=diversity_rows(document)
        result=_dataset([("MHNO · " if r["profile_label"]=="MHNO 独立谱" else "")+r["label"] for r in rows],[_series("本次结果",[r["value"] for r in rows]),_series("参考中位数",[finite(r.get("reference_median")) for r in rows])],"各指标原单位")
        return {**result,"chapter_two_mode":"diversity","rows":rows}
    rows=redundancy_rows(document)
    available=any(row["summary"]["status"]=="available" for row in rows)
    return {"labels":CATEGORIES,"series":[],"unit":"已记录分层贡献内占比（%）","status":"available" if available else "missing",
            "chapter_two_mode":"redundancy","rows":rows,
            "taxon_labels":{**document.get("overview_taxon_labels",{}),**document.get("chapter_one_taxon_labels",{}),**document.get("chapter_two_taxon_labels",{})}}


def cooperation_payload(document):
    data=cooperation_data(document)
    return {**data,"labels":[[r["stage"],r["contributors"],r["function"]] for r in data["stages"]]+[[],[]]}


def _text(draw,xy,text,size=27,**kwargs):
    from .chapter_one import _label
    _label(draw,xy,text,size,**kwargs)


def draw_chart(spec,payload,width):
    names={"chapter_two_taxon_labels":payload.get("taxon_labels",{})}
    return draw_diversity(payload,width) if payload["chapter_two_mode"]=="diversity" else draw_redundancy(names,payload,width)


def draw_diversity(payload,width):
    rows=payload["rows"];height=max(240,105+235*len(rows));image=Image.new("RGB",(width,height),"white");draw=ImageDraw.Draw(image)
    _text(draw,(40,25),"橙色：本次结果　蓝色：参考 P5–P95　深蓝标记：参考中位数",27)
    _text(draw,(width-40,38),"各指标独立线性刻度",24,anchor="rm")
    if not rows:_text(draw,(40,105),"未提供可展示的多样性结果");return image
    for i,row in enumerate(rows):
        y=80+235*i;draw.rounded_rectangle((20,y,width-20,y+220),radius=12,fill="#F2F6FA")
        _text(draw,(40,y+20),row["label"],31,width=460,max_lines=2)
        _text(draw,(40,y+104),row["profile_label"],25)
        primary=row.get("primary_value");unit=row.get("unit","")
        if primary is not None:_text(draw,(40,y+158),f"主分析：{primary:.5g} {unit}",24)
        value=finite(row.get("value"));p5=finite(row.get("p5"));p95=finite(row.get("p95"));median=finite(row.get("reference_median"))
        valid=all(v is not None and v>=0 for v in [p5,p95,median]) and p5<=median<=p95
        left,right=550,width-385;span=right-left;maximum=max(value or 0,p95 or 0,median or 0,1e-20)
        pos=lambda amount:left+span*amount/maximum
        draw.rounded_rectangle((left,y+28,right,y+58),radius=4,fill="#E0E7EF")
        if value and value>0:draw.rectangle((left,y+28,pos(value),y+58),fill="#E66B24")
        _text(draw,(right+20,y+43),f"本次 {value:.5g} {unit}",27,anchor="lm")
        if valid:
            draw.rounded_rectangle((left,y+87,right,y+117),radius=4,fill="#E0E7EF")
            if p95>p5:draw.rectangle((pos(p5),y+87,pos(p95),y+117),fill="#2675B8")
            mx=pos(median);draw.line((mx,y+81,mx,y+123),fill="#143F69",width=5);draw.ellipse((mx-7,y+95,mx+7,y+109),fill="#143F69")
            _text(draw,(right+20,y+102),f"中位数 {median:.5g}",27,anchor="lm")
            _text(draw,(550,y+143),f"参考 P5–P95：{p5:.5g}–{p95:.5g} {unit}",26)
            pct=finite(row.get("percentile"));n=row.get("n_subjects",row.get("n_reference"))
            status={"above":"高于参考区间","below":"低于参考区间","within":"位于参考区间"}.get(row.get("comparison"),"暂不判定高低")
            detail=(f"经验百分位 {pct:.1f}" if pct is not None else "经验百分位未提供")+f"；参考 n={n if n is not None else '未提供'}；{status}"
            _text(draw,(550,y+183),detail,25,width=width-600,max_lines=1)
        else:_text(draw,(550,y+112),"未建立可用参考比较",27)
    return image


def draw_redundancy(document,payload,width):
    height=895;image=Image.new("RGB",(width,height),"white");draw=ImageDraw.Draw(image)
    colors=["#246A73","#4A86A4","#8AB8C2","#B5D2CD","#D0D6DD"]
    for i,item in enumerate(payload["rows"]):
        y=20+i*270;draw.rounded_rectangle((20,y,width-20,y+252),radius=12,fill="#F2F6FA")
        _text(draw,(40,y+18),item["label"],31)
        path=item["pathway"];summary=item["summary"]
        if path:_text(draw,(40,y+83),str(path.get("id","")),23,width=335)
        if summary["status"]!="available":
            _text(draw,(440,y+66),summary["reason"],28,width=width-490)
            if item["label"]=="乳酸利用":_text(draw,(440,y+125),"乳酸生成通路未替代为乳酸利用。",25)
            continue
        _text(draw,(40,y+140),f"已注释 {summary['named_count']} 个分类单元",24,width=340)
        _text(draw,(40,y+185),"完整输出" if summary["complete"] else "按已有分层记录统计",23,width=340)
        members=summary["members"];named=[m for m in members if m["name"]!="未分类贡献"]
        selected=[{"label":display_name(document,m["taxon"]),"share":m["share"]} for m in named[:3]]
        remainder=sum(m["share"] for m in named[3:])
        if remainder>0:selected.append({"label":"其余已注释贡献","share":remainder})
        if summary["unknown_share"]:selected.append({"label":"未分类贡献","share":summary["unknown_share"]})
        left,right=440,width-55;position=left
        for j,member in enumerate(selected):
            span=(right-left)*member["share"]/100;color=colors[j%len(colors)]
            draw.rectangle((position,y+26,position+span,y+68),fill=color)
            if span>140:_text(draw,(position+span/2,y+47),f"{member['share']:.1f}%",25,fill="white" if j<2 else "#22313E",anchor="mm")
            position+=span
            x=440+(j%3)*435;ly=y+98+(j//3)*74
            draw.rectangle((x,ly+7,x+22,ly+29),fill=color)
            _text(draw,(x+34,ly),member["label"],24,width=390,max_lines=1)
            _text(draw,(x+34,ly+35),f"{member['share']:.2f}%",23)
    _text(draw,(35,850),"占比分母：各通路已记录分层贡献总和（含未分类）；不等同于群落通路总丰度。",24,width=width-70,max_lines=1)
    return image


def draw_cooperation(payload,width):
    height=625;image=Image.new("RGB",(width,height),"white");draw=ImageDraw.Draw(image)
    stages=payload["stages"]
    if not stages:_text(draw,(40,70),"未提供可用阶段记录");return image
    part=(width-130)/3
    for i,stage in enumerate(stages[:3]):
        x=25+i*(part+40)
        draw.rounded_rectangle((x,35,x+part,530),radius=14,fill="#EAF1F5",outline="#B8CDD2",width=2)
        _text(draw,(x+22,60),stage["stage"],32,width=part-44,max_lines=2)
        _text(draw,(x+22,143),"贡献菌：",26)
        _text(draw,(x+22,190),stage["contributors"],27,width=part-44,max_lines=3)
        path=stage.get("pathway")
        if path:
            _text(draw,(x+22,330),str(path.get("id","")),24)
            _text(draw,(x+22,378),stage["function"].split("（",1)[0],27,width=part-44,max_lines=2)
            value=finite(path.get("value",path.get("abundance")))
            _text(draw,(x+22,457),f"通路丰度 {value:.5g}",25)
        else:_text(draw,(x+22,330),stage["function"],25,width=part-44,max_lines=3)
    links=payload.get("connections",[])
    if links:
        stage_names=[r["stage"] for r in stages[:3]]
        for link in links:
            if link.get("source") not in stage_names or link.get("target") not in stage_names:continue
            source=stage_names.index(link["source"]);target=stage_names.index(link["target"])
            if target!=source+1:continue
            start=25+source*(part+40)+part+3;end=25+target*(part+40)-3;y=280
            draw.line((start,y,end,y),fill="#246A73",width=3)
            draw.polygon([(end,y),(end-9,y-6),(end-9,y+6)],fill="#246A73")
        _text(draw,(35,565),"按已提供的阶段与连接证据展示；详细连接记录见下表。",25)
    else:_text(draw,(35,565),"以上为独立功能阶段的注释记录；未提供菌间交换连接证据，未绘制传递箭头。",25,width=width-70,max_lines=2)
    return image
