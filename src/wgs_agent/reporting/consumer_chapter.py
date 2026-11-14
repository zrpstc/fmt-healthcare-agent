"""Consumer chapter one; original assays and Word contracts are immutable."""
from __future__ import annotations
import copy
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from .consumer_copy import CHAPTERS, EMPTY_SECTION
from .consumer_format import pct, count, percentile_phrase, tier
from .consumer_state import consumer, omit, NameRegistry
from .inputs import finite


def _rows(document, kind, limit=100000):
    from .chapter_one import _rows as rows, name, scientific
    return [{**r, "display_label": name(document,r), "scientific_label": scientific(r)} for r in rows(document,kind,limit)]


def comparison_rows(document):
    from .chapter_one import reference_rows, name, scientific
    rows=[]
    for r in reference_rows(document):
        p=finite(r.get("percentile"))
        if (p is None or not 0<=p<=100 or r.get("unit")!="%" or finite(r.get("value")) is None
                or r.get("comparison") not in {"above","below","within"} and not r.get("borderline")):
            continue
        rows.append({**r,"display_label":name(document,r),"scientific_label":scientific(r),
                     "tier_label":tier(p,r.get("borderline",False))})
    rank={"明显偏高":0,"明显偏低":0,"略高":1,"略低":1,"常见":2}
    return sorted(rows,key=lambda r:(rank[r["tier_label"]],-r["value"],r["display_label"]))[:8]


def prepare(document, *, config=None):
    from .glossary import Glossary, citation_numbers
    from .reference import species_key
    from .consumer_reference import concentration
    state=consumer(document)
    glossary=Glossary(document,config=config)
    for term in ["relative_abundance","taxonomic_ranks","reference_population","enterotype"]:
        glossary.get(term,kind="concept")
    phyla=_rows(document,"tax_phylum")
    species=_rows(document,"species",5)
    aliases={"firmicutes":"bacillota","bacteroidetes":"bacteroidota","proteobacteria":"pseudomonadota",
             "actinobacteria":"actinomycetota","verrucomicrobia":"verrucomicrobiota","fusobacteria":"fusobacteriota"}
    for kind,rows in [("phylum",phyla),("taxon",species)]:
        for row in rows:
            raw=species_key(row.get("species") or row.get("name") or row.get("label",""))
            term=aliases.get(raw,raw)
            entry=glossary.get(term,kind=kind,display_name=row["display_label"],latin=row["scientific_label"])
            if entry:
                row.update(explanation=entry["one_liner"],glossary_term=term)
    for term in ["relative_abundance", "taxonomic_ranks"]:
        entry = state.get("glossary", {}).get(term)
        if entry:
            citation_numbers(document, entry)
    for row in phyla[:5]:
        entry = state.get("glossary", {}).get(row.get("glossary_term"))
        if entry:
            row["explanation"] += citation_numbers(document, entry)
    for entry in state.get("glossary", {}).values():
        citation_numbers(document, entry)
    core=document.get("template_inputs",{}).get("core_microbiome") or {}
    if not core.get("definition"):
        omit(document,1,"核心菌群","core_definition_missing","缺少可核对的参考核心菌群定义")
    else:
        from .word_figures import chart_data
        if chart_data(document, {"id":"1.2.2", "kind":"doughnutChart"})["status"] != "available":
            omit(document,1,"核心菌群检出图表","core_members_unverifiable","核心成员清单或检出记录不足以核对")
    omit(document,1,"1.3 肠型","reference_genus_profile_missing","参考资产只有物种谱，没有经校验的属级参考谱")
    if not concentration(document):
        omit(document,1,"集中度参考位置","concentration_reference_unavailable","缺少与报告完全一致且通过校验的集中度参考")
    previous = state.get("raw_chapter_one", {}).get("source_word_figures")
    if previous is None:
        previous = {k: copy.deepcopy(v) for k,v in document.get("word_figures", {}).items() if k.startswith("1.")}
    state["raw_chapter_one"]={key:copy.deepcopy(_rows(document,kind)) for key,kind in [("phylum","tax_phylum"),("genus","tax_genus"),("species","species")]}
    state["raw_chapter_one"]["source_word_figures"] = previous
    data={"phyla":phyla,"genera":_rows(document,"tax_genus",5),"species":species,
          "reference_rows":comparison_rows(document),"enterotype":{"strategy":"B","reason":"reference_genus_profile_missing"}}
    state.setdefault("chapters",{})["1"]=data
    return data


def _data(document):
    return document.get("consumer",{}).get("chapters",{}).get("1") or prepare(document)


def chart_payload(document,spec):
    from .word_figures import _dataset,_series
    data=_data(document);ident=spec["id"]
    if ident=="1.1.1":
        source=data["phyla"];total=math.fsum(r["value"] for r in source)
        if not source or total>100.000001:
            omit(document,1,"门水平组成图","invalid_or_missing_phylum_profile","门水平数据缺失或合计超过百分之百")
            return _dataset(chapter_one_mode="phylum",rows=[],reason="")
        rows=[dict(r) for r in source[:5]]
        remaining=math.fsum(r["value"] for r in source[5:])
        if remaining>0:
            rows.append({"display_label":"其他已归类","scientific_label":"","value":remaining,"explanation":"已分到其他大类的微生物。"})
        missing=max(0.,100-total)
        if missing>.000001:
            rows.append({"display_label":"未能归类","scientific_label":"","value":missing,"explanation":"当前分类结果未能归入上述大类的部分。"})
        return _dataset(["您的样本"],[_series(r["display_label"],[r["value"]]) for r in rows],"%",
                        chapter_one_mode="phylum",rows=rows,recorded_total=total,total=math.fsum(r["value"] for r in rows))
    if ident=="1.2.1":
        source=data["species"];total=math.fsum(r["value"] for r in source)
        if not source or total>100.000001:
            return _dataset(chapter_one_mode="concentration",rows=[],reason="")
        values=[source[0]["value"],math.fsum(r["value"] for r in source[1:]),max(0.,100-total)]
        rows=[{"display_label":label,"value":v} for label,v in zip(["第1名","第2–5名","其余"],values)]
        return _dataset(["集中程度"],[_series(r["display_label"],[r["value"]]) for r in rows],"%",chapter_one_mode="concentration",rows=rows,total=math.fsum(values))
    rows=data["reference_rows"] if ident=="1.4.1" else data["genera"] if ident=="1.1.2" else data["species"]
    result=_dataset([r["display_label"] for r in rows],[_series("相对丰度",[r["value"] for r in rows])],"%",
                    chapter_one_mode="reference" if ident=="1.4.1" else "bars",rows=rows)
    if ident=="1.4.1":
        result["series"].append(_series("参考人群中位数",[finite(r.get("reference_median")) for r in rows]))
    return result


def _text(draw,xy,text,size=28,**kwargs):
    from .word_figures import _font,_text as label
    label(draw,xy,text,_font(size),**kwargs)


def _latin(draw,xy,text,size,width):
    if not text:return
    for path in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Italic.ttf"]:
        if Path(path).is_file():
            from .word_figures import _wrap
            font=ImageFont.truetype(path,size)
            for i,line in enumerate(_wrap(draw,text,font,width,2)):
                draw.text((xy[0],xy[1]+i*size*1.2),line,font=font,fill="#657279")
            return
    _text(draw,xy,text,size,width=width,max_lines=2)


def draw_chart(payload,width):
    from .word_figures import draw_tier_scale
    rows=payload["rows"];mode=payload["chapter_one_mode"]
    if mode=="reference":return draw_tier_scale(rows,width)
    height=125+math.ceil(len(rows)/2)*110 if mode=="phylum" else 180 if mode=="concentration" else 55+len(rows)*112
    image=Image.new("RGB",(width,max(160,height)),"white");draw=ImageDraw.Draw(image)
    colors=["#246A73","#4A86A4","#8AB8C2","#B5D2CD","#C6B694","#C9D3D6","#E7E9EC"]
    if mode in {"phylum","concentration"}:
        x=35
        for i,row in enumerate(rows):
            span=(width-70)*row["value"]/100
            draw.rectangle((x,20,x+span,70),fill=colors[i]);x+=span
            if mode=="concentration":
                _text(draw,(35+i*(width-70)/3,97),row["display_label"]+"  "+pct(row["value"]),29)
            else:
                px=35+i%2*(width/2);py=108+i//2*110
                draw.rectangle((px,py+5,px+22,py+27),fill=colors[i])
                _text(draw,(px+35,py),row["display_label"]+"  "+pct(row["value"]),28,width=width/2-65,max_lines=1)
                _latin(draw,(px+35,py+36),row.get("scientific_label",""),19,width/2-65)
                _text(draw,(px+35,py+66),row.get("explanation",""),21,width=width/2-65,max_lines=1)
        return image
    left,right=width*.5,width-130;maximum=max([r["value"] for r in rows] or [1]) or 1
    for i,row in enumerate(rows):
        y=18+i*112
        _text(draw,(18,y),row["display_label"],26,width=left-30,max_lines=1)
        _latin(draw,(18,y+40),row.get("scientific_label",""),19,left-35)
        draw.rounded_rectangle((left,y+18,right,y+43),radius=4,fill="#EDF2F6")
        end=left+(right-left)*row["value"]/maximum
        if row["value"]>0:draw.rectangle((left,y+18,end,y+43),fill=colors[0])
        _text(draw,(right+12,y+12),pct(row["value"]),25)
    return image


def fallback(document,sub):
    data=_data(document)
    if sub==1:
        phyla,species=data["phyla"],data["species"];sentences=[]
        if phyla:
            text=f"您的菌群以{phyla[0]['display_label']}为主（约{pct(phyla[0]['value'])}）"
            if len(phyla)>1:text+=f"，其次是{phyla[1]['display_label']}"
            sentences.append(text+"。")
        if species:sentences.append(f"占比最高的菌是{species[0]['display_label']}，约占{pct(species[0]['value'])}。")
        if not sentences and data["genera"]:
            sentences.append("您的菌群中占比较高的菌属包括"+"、".join(r["display_label"] for r in data["genera"][:3])+"。")
        return "".join(sentences) or EMPTY_SECTION
    if sub==2 and data["species"]:
        return f"占比最高的五种菌合计约{pct(math.fsum(r['value'] for r in data['species']))}。"
    if sub==4 and data["reference_rows"]:
        high=[r["display_label"] for r in data["reference_rows"] if r["tier_label"]=="明显偏高"][:3]
        low=[r["display_label"] for r in data["reference_rows"] if r["tier_label"]=="明显偏低"][:max(0,3-len(high))]
        parts=(["、".join(high)+"明显偏高"] if high else [])+(["、".join(low)+"明显偏低"] if low else [])
        return "与健康人相比，"+"；".join(parts)+"。这只说明较少见，具体意义请结合第三章阅读。" if parts else "没有菌明显偏离常见范围。具体意义请结合第三章阅读。"
    return EMPTY_SECTION


def displayed_values(document,sub):
    data=_data(document)
    if sub==1:
        phyla = chart_payload(document, {"id":"1.1.1"})["rows"]
        return [pct(r["value"]) for r in phyla+data["genera"]+data["species"]]
    if sub==2:
        values=[pct(r["value"]) for r in data["species"][:1]]
        if data["species"]:values.append(pct(math.fsum(r["value"] for r in data["species"])))
        ref=document["consumer"].get("concentration_reference")
        if ref:
            for k in ["top1", "top5"]:
                values.extend([pct(ref[k]["value"]), percentile_phrase(ref[k]["percentile"])])
        return values
    return [value for r in data["reference_rows"] for value in [pct(r["value"]), percentile_phrase(r["percentile"])]]


def interpretation(document,sub):
    topic=next((t for s in document.get("word_sections",[]) for t in s["topics"] if t["id"]==f"word.1.{sub}"),{})
    value=topic.get("interpretation","")
    if value:
        from .narrative import consumer_text_error
        if consumer_text_error(value,displayed_values(document,sub)) is None:return value
    return fallback(document,sub)


def render(document):
    from .consumer_state import table
    from .glossary import citation_numbers
    from .word_figures import chart_data
    data=_data(document);state=consumer(document);names=NameRegistry(document)
    output=["## 1 "+CHAPTERS[1]["title"],CHAPTERS[1]["intro"]]
    for term in ["relative_abundance","taxonomic_ranks"]:
        entry=state.get("glossary",{}).get(term)
        if entry and entry["review_status"]=="approved":
            output.append("> "+entry["display_name"]+"："+entry["one_liner"]+citation_numbers(document,entry))
    figures=document.get("word_figures",{})
    def figure(key,caption,rows):
        item=figures.get(key)
        if item:
            output.extend([caption,f"![{caption}]({item['filename']})"]);names.mark(rows);return True
        return False
    output.append("### 1.1 "+CHAPTERS[1]["subsections"][1])
    phylum=chart_payload(document,{"id":"1.1.1"})
    if phylum["status"]=="available" and not figure("1.1.1","图1-1 门水平组成",data["phyla"]):
        output.append(table(["主要大类","占比"],[[names.name(r),pct(r["value"])] for r in phylum["rows"]]))
    if data["genera"] or data["species"]:
        shown = figure("1.1.2+1.1.3","图1-2 菌属与菌种前五",data["genera"]+data["species"])
        if not shown and data["genera"]:
            output.append(table(["主要菌属", "占比"], [[names.name(r), pct(r["value"])] for r in data["genera"]]))
    if data["species"]:
        output.append("**菌种小档案**");rows=[]
        for row in data["species"]:
            entry=state.get("glossary",{}).get(row.get("glossary_term"));explanation=row.get("explanation","")
            if explanation and entry:explanation+=citation_numbers(document,entry)
            rows.append([names.name(row),pct(row["value"]),explanation])
        output.append(table(["菌名","占比","它是做什么的"],rows))
    output.append(interpretation(document,1))
    if data["genera"]:output.append("丰度较高的菌属依次为"+"、".join(names.name(r) for r in data["genera"][:3])+"。")
    output.append("### 1.2 "+CHAPTERS[1]["subsections"][2])
    if data["species"]:
        first=data["species"][0]
        output.append(table(["组成指标","您的结果"],[["占比最高的菌",names.name(first)],["第一名占比",pct(first["value"])],["前五种合计占比",pct(math.fsum(r["value"] for r in data["species"]))]]))
        figure("1.2.1+1.2.2","集中度：第一名、第二至五名与其余成员",[])
        reference=state.get("concentration_reference")
        if reference:
            output.extend(["用于人群比较的集中程度：",table(["指标","同口径占比","参考位置"],[[label,pct(reference[key]["value"]),tier(reference[key]["percentile"],reference[key].get("borderline",False))+"；"+percentile_phrase(reference[key]["percentile"])] for label,key in [("第一名","top1"),("前五种合计","top5")]])])
        core=document.get("template_inputs",{}).get("core_microbiome") or {}
        if core.get("definition"):
            ring=chart_data(document,{"id":"1.2.2","kind":"doughnutChart"})
            if ring["status"]=="available":
                detected,absent=ring["series"][0]["values"]
                output.extend(["表1-1 核心菌群检出",table(["组成指标","您的结果"],[["核心成员检出数 / 参考成员数",count(detected)+" / "+count(detected+absent)]])])
                from .word_template import Data
                from .reference import species_key
                core_rows = []
                observed = {species_key(r.get("species") or r.get("label", "")): r for r in _rows(document, "species")}
                for member in Data(document).raw("core_microbiome", "members"):
                    ident = species_key(member.get("species") or member.get("name", ""))
                    measured = observed.get(ident, {})
                    value = finite(member.get("value", member.get("abundance", measured.get("value"))))
                    unit = member.get("unit", core.get("unit", measured.get("unit")))
                    if value is not None:
                        core_rows.append([names.name(member), "检出" if value > 0 else "未检出", pct(value) if unit == "%" else ""])
                if core_rows:
                    output.append(table(["核心成员", "检出情况", "占比"], core_rows))
        output.append(interpretation(document,2))
    else:output.append(EMPTY_SECTION)
    output.append("### 1.4 "+CHAPTERS[1]["subsections"][4])
    audit=(document.get("template_inputs",{}).get("healthy_comparison") or {}).get("audit",{})
    if data["reference_rows"]:
        n=audit.get("n_subjects") or data["reference_rows"][0].get("n_subjects") or data["reference_rows"][0].get("n_reference")
        if n:
            matching="已按登记的人口学条件筛选" if audit.get("stratify_by") else "未按年龄、性别、地区匹配"
            output.append(f"对照人群：{count(n)}名来自公开研究的健康成人（{matching}）。方法见附录A1。")
        entry=state.get("glossary",{}).get("reference_population")
        if entry:output.append(entry["one_liner"]+citation_numbers(document,entry))
        high=[r["display_label"] for r in data["reference_rows"] if r["tier_label"]=="明显偏高"]
        low=[r["display_label"] for r in data["reference_rows"] if r["tier_label"]=="明显偏低"]
        output.append("主要差异："+("；".join((["明显偏高："+"、".join(high)] if high else [])+(["明显偏低："+"、".join(low)] if low else [])) or "没有菌明显偏离常见范围")+"。")
        if not figure("1.4.1","图1-5 您的菌种与参考人群比较",data["reference_rows"]):
            output.append(table(["菌名","占比","参考位置"],[[names.name(r),pct(r["value"]),r["tier_label"]+"；"+percentile_phrase(r["percentile"])] for r in data["reference_rows"]]))
        output.append("> 为与对照人群同口径比较，此处丰度经重新计算，与 1.1 数值可能略有差异。")
        output.append(interpretation(document,4))
    else:
        omit(document,1,"1.4 人群比较","reference_comparison_unavailable","没有可发布的人群比较结果");output.append(EMPTY_SECTION)
    from .word_template import Data
    from .consumer_format import number
    absolute = [r for r in Data(document).raw("absolute_abundance", "measurements")
                if r.get("unit") and r.get("method") and finite(r.get("value")) is not None
                and (r.get("data_type") == "measured" or r.get("validated_quantification") is True)]
    if absolute:
        from .consumer_copy import FORBIDDEN
        rows = []
        for row in absolute:
            label = row.get("name") or names.name(row)
            method = str(row["method"])
            if any(token in str(label)+method+str(row["unit"]) for token in FORBIDDEN):
                omit(document, 1, "绝对丰度正文", "technical_quantification_text", "定量说明含专业细节，完整记录保留在结构化报告")
                continue
            rows.append([label, number(row["value"])+" "+str(row["unit"]), method])
        if rows:
            output.extend(["**绝对丰度补充结果**", table(["定量项目", "您的结果", "测量依据"], rows)])
    else:
        omit(document, 1, "绝对丰度补充结果", "validated_quantification_missing", "没有经验证的绝对数量测量")
    state["chapters"]["1"]["body_markdown"]="\n\n".join(output)
    return output
