"""按正文模板生成共享的 Markdown 与 PDF 健康报告。"""

from __future__ import annotations

import os
import re
from datetime import datetime as _dt
from typing import Any

# ── 物种健康解读（复用 report_sections.py 的逻辑） ──


def _species_comment(r: dict[str, Any]) -> str:
    """对异常物种给出健康解读"""
    sp = r.get("species", "")
    if r.get("status") == "high":
        if "Faecalibacterium" in sp or "prausnitzii" in sp:
            return "通常有益（产丁酸、抗炎），但过高可能提示肠道生态改变"
        elif "Bifidobacterium" in sp:
            return "通常有益（益生菌、免疫支持），但极端高水平需关注"
        elif "Bacteroides" in sp or "Phocaeicola" in sp:
            return "偏高可能提示肠道生态改变，与某些炎症状态相关"
        elif "Escherichia" in sp or "Klebsiella" in sp or "Enterobacter" in sp:
            return "肠杆菌扩增是肠道菌群失调的标志，可能促炎"
        elif "Fusobacterium" in sp:
            return "高水平与结直肠癌风险相关，建议关注"
        elif "Streptococcus" in sp:
            return "部分链球菌种可能是条件致病菌，建议关注"
        else:
            return "偏离健康参考范围，建议关注"
    else:
        if "Faecalibacterium" in sp or "Roseburia" in sp or "Eubacterium" in sp or "Anaerostipes" in sp:
            return "产丁酸菌，对肠道屏障功能重要，偏低可能影响 SCFA 产生"
        elif "Akkermansia" in sp:
            return "对黏膜完整性重要，低水平与肥胖、2 型糖尿病相关"
        elif "Bifidobacterium" in sp:
            return "益生菌群减少可能降低定植抵抗力"
        elif "Lactobacillus" in sp:
            return "乳酸菌偏低可能影响肠道的酸性环境和病原体抑制能力"
        else:
            return "低于健康人群预期水平"


_MET_REF = {
    "butyrate": "0.5-5.0", "propionate": "0.3-3.0", "acetate": "2.0-15.0",
    "succinate": "<0.5", "lactate": "<1.0", "indole": "0.01-0.5",
    "serotonin": "0.01-0.3", "gamma-aminobutyrate": "0.01-0.2",
    "trimethylamine": "<0.1", "deoxycholate": "<0.05", "choline": "0.1-1.0",
}


def _met_ref(name: str) -> str:
    n = name.lower()
    for k, v in _MET_REF.items():
        if k in n:
            return v
    return "N/A"


_PATHWAY_IMPLICATIONS = {
    "BUTYRATE": "丁酸代谢 - 结肠细胞主要能量来源，抗炎，维持肠道屏障",
    "PROPIONATE": "丙酸代谢 - 参与糖异生，调节食欲",
    "ACETATE": "乙酸代谢 - 最丰富的 SCFA，脂质合成底物",
    "SUCCINATE": "琥珀酸代谢 - TCA 循环中间体，免疫信号分子",
    "LACTATE": "乳酸代谢 - 发酵中间产物，可被交叉喂养转化为丁酸",
    "ARGININE": "精氨酸代谢 - 参与 NO 产生，免疫功能调节",
    "TRYPTOPHAN": "色氨酸代谢 - 5-羟色胺、犬尿氨酸通路前体",
    "FOLATE": "叶酸生物合成 - 维生素 B9，DNA 合成必需",
    "BIOTIN": "生物素生物合成 - 维生素 B7，羧化反应辅酶",
    "COBALAMIN": "钴胺素生物合成 - 维生素 B12，神经功能必需",
}

_ENTEROTYPE_DESC = {
    "Bacteroides": "**Bacteroides 优势肠型（肠型1）**：西方人群最常见，与高动物蛋白饮食相关。维生素 C/B 合成能力较强，高效多糖降解，部分研究中与炎症风险增加相关。",
    "Prevotella": "**Prevotella 优势肠型（肠型2）**：植物性饮食人群常见。通常具有更高微生物多样性，碳水化合物发酵能力强，可能与更好的代谢健康指标相关。",
    "Ruminococcus": "**Ruminococcus 混合肠型（肠型3）**：通常与最高微生物多样性相关，富含黏液降解菌和产丁酸菌，通常与良好肠道健康相关。",
}


def normalize_report_markdown(report_md: str, sample_id: str) -> str:
    """规范化自由 Markdown 报告，尽量收敛为可控版式。

    目标：
    1. 去掉“由于没有现成 JSON / 我将直接生成报告”等过程性前言
    2. 统一报告主标题，避免 PDF 首段被自由文本污染
    3. 清理 emoji/装饰符，减少 pandoc/xelatex 的表格和换行异常
    4. 对超长表格单元格做软换行提示，降低 longtable 挤压重叠概率
    """
    if not report_md:
        return report_md

    text = report_md.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\u200b\u200d\ufeff\ufe0e\ufe0f]", "", text)

    # 去掉常见的 LLM 过程性前言，保留从正式标题开始的正文
    heading_match = re.search(
        r"(?m)^\s*#\s*(?:[📋🧬📊⚕️🔬💊🎯📚 ]*)?(?:WGS(?:\.FMT)?|肠道菌群|宏基因组).*$",
        text,
    )
    if heading_match:
        text = text[heading_match.start():]

    # 删除标题前残留的解释性句子
    text = re.sub(
        r"(?is)\A\s*(?:由于|看起来|不过没关系|让我|JSON文件路径不存在|generate_report 工具需要|报告生成工具需要).*?(?=^#\s)",
        "",
        text,
    )

    lines = text.split("\n")
    cleaned: list[str] = []
    in_table = False

    def _wrap_table_cell(cell: str) -> str:
        cell = re.sub(r"[📋🧬📊⚕️🔬💊🎯📚🚨⚠️✅❌🟢🟡🔴⭐]+", "", cell).strip()
        # 为过长的中英文混合串插入软换行点，减轻 LaTeX 表格横向挤压
        if len(cell) > 28:
            cell = re.sub(r"([()/,_\-])", r"\1 ", cell)
            cell = re.sub(r"([a-zA-Z])([A-Z])", r"\1 \2", cell)
            cell = re.sub(r"\s{2,}", " ", cell)
        return cell

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        is_table = stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2

        if is_table:
            in_table = True
            parts = [p.strip() for p in stripped.split("|")[1:-1]]
            parts = [_wrap_table_cell(p) for p in parts]
            cleaned.append("| " + " | ".join(parts) + " |")
            continue

        if in_table and stripped == "":
            cleaned.append("")
            in_table = False
            continue

        if stripped.startswith("#"):
            line = re.sub(r"[📋🧬📊⚕️🔬💊🎯📚🚨⚠️✅❌🟢🟡🔴⭐]+", "", line)
            line = re.sub(r"\s{2,}", " ", line).strip()

        cleaned.append(line)

    text = "\n".join(cleaned).strip()

    # 若标题不规范则补一个固定标题，保证 PDF 首页稳定
    if not re.search(r"(?m)^#\s+", text):
        text = f"# WGS.FMT 肠道菌群健康评估报告\n\n**样本编号**: {sample_id}\n\n" + text

    # 统一主标题，避免同一批报告标题漂移
    text = re.sub(
        r"(?m)^#\s+.*(?:健康评估报告|完整健康评估报告|宏基因组健康评估报告).*$",
        "# WGS.FMT 肠道菌群健康评估报告",
        text,
        count=1,
    )
    return text + "\n"


# ── 核心函数：生成完整 Markdown 报告 ──


def build_full_report(
    sample_id, species_data, compare_data, enterotype_data, pathway_data,
    metabolite_data, drug_data, disease_data, knowledge_data, llm_advice="",
    fmt_matching_data=None, protein_data=None, report_context=None,
):
    """Render the template-aligned health report for all report formats."""
    from wgs_agent.reporting.document import build_document, render_markdown
    from wgs_agent.reporting.narrative import validate_payload

    context = report_context or {}
    document = context.get("report_document")
    if document is None:
        document = build_document(
            sample_id, species_data, compare_data, enterotype_data, pathway_data,
            metabolite_data, drug_data, disease_data, knowledge_data,
            protein_data, fmt_matching_data, context,
        )
        if llm_advice:
            from wgs_agent.reporting.word_template import narrative_sections
            document["word_sections"] = narrative_sections(document)
            check = validate_payload(llm_advice, document, document["word_sections"])
            for section in document["word_sections"]:
                for topic in section["topics"]:
                    item = check["accepted"].get(topic["id"])
                    if item:
                        topic.update({"interpretation": item["interpretation"], "advice": item["advice"],
                                      "narrative_source": "llm", "narrative_evidence_ids": item["evidence_ids"],
                                      "support_quotes": item["support_quotes"]})
    if document.get("sample_id") != sample_id:
        raise ValueError("report document belongs to a different sample")
    return render_markdown(document)


# ── 生成 PDF（优先 xelatex LaTeX 排版，降级 weasyprint） ──


# def generate_pdf(report_md: str, sample_id: str, output_path: str) -> str:
#     """
#     将 Markdown 报告转为 PDF 文件，返回输出路径。

#     优先级: xelatex (LaTeX 排印级) > pandoc+weasyprint (HTML) > 纯 .md 降级
#     """
#     import subprocess
#     import shutil
#     import tempfile

#     pandoc = shutil.which("pandoc") or os.path.expanduser("$HOME/.local/bin/pandoc")
#     if not shutil.which(pandoc) and not os.path.isfile(pandoc):
#         alt_path = output_path.replace(".pdf", ".md")
#         with open(alt_path, "w", encoding="utf-8") as f:
#             f.write(report_md)
#         print(f"[PDF] pandoc 未安装，降级为 Markdown: {alt_path}")
#         return alt_path

#     xelatex_bin = os.path.expanduser("~/texlive/2026/bin/x86_64-linux/xelatex")
#     has_xelatex = shutil.which(xelatex_bin) is not None or os.path.isfile(xelatex_bin)

#     try:
#         # ── 写入 Markdown 临时文件 ──
#         with tempfile.NamedTemporaryFile(
#             mode="w", suffix=".md", delete=False, encoding="utf-8"
#         ) as md_f:
#             md_f.write(report_md)
#             md_path = md_f.name

#         env = os.environ.copy()
#         env["PATH"] = os.path.expanduser("$HOME/.local/bin") + ":" + env.get("PATH", "")

#         # ════════════════════════════════════════════════════════════
#         # 方案 A: Markdown → pandoc → LaTeX → xelatex → PDF（排印级）
#         # ════════════════════════════════════════════════════════════
#         if has_xelatex:
#             try:
#                 out_dir = os.path.dirname(output_path) or "."
#                 build_dir = os.path.join(out_dir, "_build")
#                 os.makedirs(build_dir, exist_ok=True)
#                 base_name = os.path.splitext(os.path.basename(output_path))[0]
#                 tex_path = os.path.join(build_dir, f"{base_name}.tex")

#                 # Step 1: pandoc 将 Markdown 转为 LaTeX
#                 pandoc_cmd = [
#                     pandoc, md_path,
#                     "-o", tex_path,
#                     "--from", "markdown+pipe_tables+grid_tables-auto_identifiers",
#                     "--to", "latex",
#                     "--standalone",
#                     "--metadata", f"title=WGS.FMT 肠道菌群健康评估报告 - {sample_id}",
#                     "-V", "documentclass=ctexart",
#                     "-V", "classoption=11pt,a4paper",
#                     "-V", "CJKmainfont=Noto Sans CJK SC",
#                     "-V", "CJKsansfont=Noto Sans CJK SC",
#                     "-V", "CJKmonofont=Noto Sans CJK SC",
#                     "-V", "mainfont=Noto Sans CJK SC",
#                     "-V", "sansfont=Noto Sans CJK SC",
#                     "-V", "monofont=Noto Sans CJK SC",
#                     "-V", "geometry=margin=2.2cm",
#                     "-V", "colorlinks=true",
#                     "-V", "linkcolor=blue",
#                     "--pdf-engine=xelatex",
#                     "--pdf-engine-opt=-interaction=nonstopmode",
#                     "--pdf-engine-opt=-output-directory",
#                     f"--pdf-engine-opt={build_dir}",
#                 ]
#                 # 如果想直接用 pandoc 一步生成 PDF（内部会调 xelatex），也可以；但分步调试更友好
#                 # 分步：先得到 .tex，再手动编译两次
#                 result_tex = subprocess.run(pandoc_cmd, capture_output=True, text=True, env=env, timeout=120)

#                 # 无论 pandoc 是否生成 .tex，我们都用两步编译确保目录正确
#                 # 如果 pandoc 失败，用自定义 preamble 包裹
#                 if result_tex.returncode != 0 or not os.path.isfile(tex_path):
#                     # pandoc tex 转换失败，用自定义简易 preamble
#                     preamble = r"""\documentclass[11pt,a4paper]{ctexart}
# \usepackage{fontspec}
# \setmainfont{Noto Sans CJK SC}
# \setsansfont{Noto Sans CJK SC}
# \usepackage[dvipsnames,svgnames,table]{xcolor}
# \usepackage{geometry}\geometry{a4paper,left=22mm,right=22mm,top=25mm,bottom=25mm}
# \usepackage{longtable,booktabs,array,multirow,graphicx,tikz}
# \usepackage[colorlinks=true,linkcolor=blue,urlcolor=blue]{hyperref}
# \usepackage{enumitem,fancyhdr,microtype}
# \usepackage[many]{tcolorbox}\tcbuselibrary{skins,breakable}
# \usepackage{fontawesome5}
# \definecolor{WgsBlue}{RGB}{25,60,120}
# \definecolor{WgsLightBlue}{RGB}{50,90,150}
# \definecolor{WgsGreen}{RGB}{0,140,60}
# \definecolor{WgsWarn}{RGB}{200,130,0}
# \definecolor{WgsDanger}{RGB}{200,50,50}
# \definecolor{graytext}{RGB}{100,100,100}
# \definecolor{darkgray}{RGB}{45,45,45}
# \definecolor{rowgray}{RGB}{243,247,252}
# \newtcolorbox{infobox}[1]{enhanced,breakable,colback=WgsBlue!8!white,colframe=WgsBlue!30,coltitle=white,fonttitle=\sffamily\bfseries,title={\faInfoCircle\ #1},attach boxed title to top left={xshift=3mm,yshift=-3mm},boxed title style={colback=WgsBlue,sharp corners},sharp corners}
# \newtcolorbox{recommendbox}[1]{enhanced,breakable,colback=WgsGreen!8!white,colframe=WgsGreen!40,coltitle=white,fonttitle=\sffamily\bfseries,title={\faCheckCircle\ #1},attach boxed title to top left={xshift=3mm,yshift=-3mm},boxed title style={colback=WgsGreen,sharp corners},sharp corners}
# \newtcolorbox{warnbox}[1]{enhanced,breakable,colback=WgsWarn!5!white,colframe=WgsWarn!30,coltitle=white,fonttitle=\sffamily\bfseries,title={\faExclamationTriangle\ #1},attach boxed title to top left={xshift=3mm,yshift=-3mm},boxed title style={colback=WgsWarn,sharp corners},sharp corners}
# \pagestyle{fancy}\fancyhf{}\fancyhead[L]{\small\color{graytext}WGS.FMT 肠道菌群健康评估报告}\fancyhead[R]{\small\color{graytext}\leftmark}\fancyfoot[C]{\small\color{graytext}— \thepage\ —}\renewcommand{\headrulewidth}{0.4pt}
# \linespread{1.15}
# \titleformat{\section}{\sffamily\bfseries\Large\color{WgsBlue}}{\thesection}{1em}{}[\vspace{-0.5em}\titlerule\vspace{0.5em}]
# \titleformat{\subsection}{\sffamily\bfseries\large\color{WgsLightBlue}}{\thesubsection}{1em}{}
# \setlist{nosep,leftmargin=*,itemsep=2pt}
# \title{WGS.FMT 肠道菌群健康评估报告}
# \author{WGS.FMT Pipeline}
# \date{\today}
# \begin{document}
# \maketitle
# \tableofcontents
# """
#                     # 用 pandoc 的 fragment 模式生成 body（不含 preamble）
#                     body_tex_path = tex_path + ".body"
#                     body_cmd = [
#                         pandoc, md_path,
#                         "-o", body_tex_path,
#                         "--from", "markdown+pipe_tables+grid_tables-auto_identifiers",
#                         "--to", "latex",
#                     ]
#                     subprocess.run(body_cmd, capture_output=True, text=True, env=env, timeout=60)
#                     body_content = ""
#                     if os.path.isfile(body_tex_path):
#                         with open(body_tex_path, "r", encoding="utf-8") as bf:
#                             body_content = bf.read()
#                         os.unlink(body_tex_path)
#                     else:
#                         # 最后兜底：直接把 Markdown 内容逐段包裹
#                         body_content = (
#                             report_md
#                             .replace("&", r"\&")
#                             .replace("%", r"\%")
#                             .replace("$", r"\$")
#                             .replace("#", r"\#")
#                             .replace("_", r"\_")
#                         )

#                     with open(tex_path, "w", encoding="utf-8") as tf:
#                         tf.write(preamble + "\n" + body_content + "\n\\end{document}\n")

#                 # Step 2: xelatex 编译两次
#                 for i in range(2):
#                     compile_result = subprocess.run(
#                         [xelatex_bin, "-interaction=nonstopmode", "-output-directory", build_dir, tex_path],
#                         capture_output=True, text=True, timeout=180, env=env,
#                     )
#                     if compile_result.returncode != 0 and i == 1:
#                         log_path = os.path.join(build_dir, f"{base_name}.log")
#                         print(f"[PDF/xelatex] 编译失败，日志: {log_path}")
#                         print(compile_result.stdout[-1500:])
#                         raise RuntimeError("xelatex compile failed")

#                 src_pdf = os.path.join(build_dir, f"{base_name}.pdf")
#                 if os.path.isfile(src_pdf):
#                     shutil.copyfile(src_pdf, output_path)
#                     # 清理辅助文件
#                     for ext in (".aux", ".log", ".out", ".toc"):
#                         aux = os.path.join(build_dir, f"{base_name}{ext}")
#                         if os.path.isfile(aux):
#                             try: os.unlink(aux)
#                             except OSError: pass
#                 else:
#                     raise RuntimeError(f"xelatex 未生成 PDF: {src_pdf}")

#                 # 清理 md 临时文件
#                 try: os.unlink(md_path)
#                 except OSError: pass

#                 if os.path.isfile(output_path):
#                     return output_path
#             except Exception as xe:
#                 print(f"[PDF] xelatex 失败 '{xe}'，降级为 weasyprint")

#         # ════════════════════════════════════════════════════════════
#         # 方案 B: pandoc + weasyprint（HTML → PDF，降级）
#         # ════════════════════════════════════════════════════════════
#         css = """@page { size: A4; margin: 20mm 15mm 25mm; }
# body { font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif; font-size: 11pt; line-height: 1.8; color: #2B2D42; }
# h1 { font-size: 22pt; color: #1a5276; border-bottom: 2.5pt solid #2980b9; padding-bottom: 6pt; margin-top: 0; page-break-after: avoid; }
# h2 { font-size: 15pt; color: #2471a3; border-bottom: 1pt solid #85c1e9; padding-bottom: 4pt; margin-top: 18pt; page-break-after: avoid; }
# h3 { font-size: 12pt; color: #2e86c1; margin-top: 14pt; page-break-after: avoid; }
# table { width: 100%; border-collapse: collapse; margin: 10pt 0 14pt; font-size: 8.5pt; page-break-inside: avoid; }
# thead { display: table-header-group; }
# th { background: #1a5276; color: white; font-weight: bold; padding: 6pt 5pt; text-align: left; font-size: 8pt; }
# td { padding: 4pt 5pt; border-bottom: 0.5pt solid #d5dbdb; vertical-align: top; }
# tr:nth-child(even) td { background: #f0f4f8; }
# ul, ol { margin: 6pt 0; padding-left: 20pt; }
# li { margin-bottom: 3pt; }
# blockquote { background: #eaf2f8; border-left: 3pt solid #2980b9; margin: 10pt 0; padding: 6pt 12pt; font-size: 9.5pt; color: #2c3e50; }
# code { font-family: "Noto Sans Mono CJK SC", monospace; font-size: 9pt; background: #f4f6f6; padding: 2pt 5pt; border-radius: 3pt; }
# pre { background: #f4f6f6; padding: 8pt; font-size: 8.5pt; border-radius: 4pt; }
# hr { border: none; border-top: 1pt solid #bdc3c7; margin: 16pt 0; }
# p { margin: 6pt 0; }
# @page { @bottom-center { content: "— " counter(page) " —"; font-size: 8pt; color: #95a5a6; font-family: "Noto Sans CJK SC", sans-serif; } }
# """
#         with tempfile.NamedTemporaryFile(
#             mode="w", suffix=".css", delete=False, encoding="utf-8"
#         ) as css_f:
#             css_f.write(css)
#             css_path = css_f.name

#         cmd = [
#             pandoc, md_path,
#             "-o", output_path,
#             "--pdf-engine=weasyprint",
#             "--metadata", f"title=WGS.FMT 健康评估报告 - {sample_id}",
#             "--css", css_path,
#             "--from", "markdown+pipe_tables+grid_tables",
#             "--standalone",
#             "-V", "mainfont=Noto Sans CJK SC",
#             "-V", "sansfont=Noto Sans CJK SC",
#             "-V", "monofont=Noto Sans Mono CJK SC",
#             "-V", "margin-top=20mm",
#             "-V", "margin-bottom=25mm",
#             "-V", "margin-left=15mm",
#             "-V", "margin-right=15mm",
#         ]

#         result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)

#         # 清理临时文件
#         for tmp in (md_path, css_path):
#             try:
#                 os.unlink(tmp)
#             except OSError:
#                 pass

#         if result.returncode == 0 and os.path.isfile(output_path):
#             return output_path
#         else:
#             print(f"[PDF] weasyprint 失败: {result.stderr[:500]}")
#             raise RuntimeError("weasyprint failed")

#     except Exception as e:
#         print(f"[PDF] 转换失败 '{e}'，降级为 Markdown")
#         alt_path = output_path.replace(".pdf", ".md")
#         with open(alt_path, "w", encoding="utf-8") as f:
#             f.write(report_md)
#         return alt_path
def _paginate_pdf_table_rows(
    pdf, table_rows, col_widths=None, *, body_style=None, line_height=5.0, padding=1.4,
):
    """Yield (source row index, cells), splitting only rows too tall for a page.

    fpdf2 can move whole table rows across pages, but cannot split a single row.
    Measure with the same font, wrapping and padding as the renderer, reserving
    space for the repeated heading. Keep every character in each source cell;
    continuation rows repeat short category labels for context.
    """
    from fpdf.fonts import FontFace

    if not table_rows:
        return
    ncols = len(table_rows[0])
    proportions = col_widths or [1] * ncols
    widths = [pdf.epw * value / sum(proportions) for value in proportions]

    def height(text, column, face=None):
        with pdf.use_font_face(face or FontFace()):
            return pdf.multi_cell(
                widths[column], line_height, text, padding=padding,
                max_line_height=line_height, align="JUSTIFY", wrapmode="WORD",
                dry_run=True, output="HEIGHT", new_x="RIGHT", new_y="TOP",
            )

    headers = list(table_rows[0])
    header_height = max(
        height(cell, column, FontFace(emphasis="BOLD"))
        for column, cell in enumerate(headers)
    )
    available_height = pdf.eph - header_height - 1.0
    if available_height < line_height + 2 * padding:
        raise ValueError("PDF table heading leaves no room for a data row")
    yield 0, headers

    # Shorter continuation blocks also make useful progress near a page bottom.
    continuation_height = min(80.0, available_height)

    def take_prefix(text, column):
        if not text or height(text, column, body_style) <= continuation_height:
            return text, ""
        low, high = 0, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if height(text[:middle], column, body_style) <= continuation_height:
                low = middle
            else:
                high = middle - 1
        if not low:
            raise ValueError("PDF table column is too narrow for one character")
        # Prefer a clause/word boundary without discarding its separator.
        boundary = max(text.rfind(sep, 0, low) for sep in ("；", "\n", " "))
        if boundary >= low // 2:
            low = boundary + 1
        return text[:low], text[low:]

    for row_index, cells in enumerate(table_rows[1:], 1):
        cells = (list(cells) + [""] * ncols)[:ncols]
        if max(height(cell, column, body_style) for column, cell in enumerate(cells)) <= available_height:
            yield row_index, cells
            continue
        remaining = cells[:]
        continuation_label = cells[0] + "（续）"
        repeat_label = bool(cells[0]) and height(continuation_label, 0, body_style) <= continuation_height
        first = True
        while any(remaining):
            fragments = []
            for column, text in enumerate(remaining):
                fragment, remaining[column] = take_prefix(text, column)
                fragments.append(fragment)
            if not first and not fragments[0] and repeat_label:
                fragments[0] = continuation_label
            yield row_index, fragments
            first = False


def _generate_fpdf_report(report_md: str, sample_id: str, output_path: str) -> str:
    """Render a real Unicode PDF when a TeX distribution is unavailable.

    The supplied Word contract controls paper, colors, typography and tables.
    Charts and diagrams are shared PNGs with the online preview.
    """
    import os
    import re
    from datetime import datetime
    from fpdf import FPDF

    from wgs_agent.reporting.catalog import TITLE
    from wgs_agent.reporting.fonts import resolve_cjk_fonts

    regular_font, bold_font = resolve_cjk_fonts()

    class WgsReportPDF(FPDF):
        def header(self):
            pass

        def footer(self):
            self.set_y(-12)
            self.set_font("WgsCN", "", 7)
            self.set_text_color(120, 120, 120)
            self.cell(0, 6, f"{getattr(self, 'chapter_title', '肠道菌群报告')}  |  {self.page_no()}", align="R")

    def clean(text: str) -> str:
        text = str(text).replace("\u2009", " ").replace("\u202f", " ")
        text = re.sub(r"[\ufe0e\ufe0f\u200b\u200d\ufeff]", "", str(text))
        text = re.sub(r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF]", "", text)
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "[图表见在线报告]", text)
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
        # Double underscores are valid sample IDs, not necessarily emphasis.
        text = text.replace("**", "").replace("`", "")
        return text.strip()

    from wgs_agent.reporting.word_template import contract
    style = contract()["style"]
    left, top, right, bottom = style["margins_mm"]
    pdf = WgsReportPDF(format=tuple(style["page_mm"]), unit="mm")
    pdf.set_margins(left, top, right)
    pdf.set_auto_page_break(auto=True, margin=bottom)
    pdf.add_font("WgsCN", "", regular_font)
    pdf.add_font("WgsCN", "B", bold_font if os.path.isfile(bold_font) else regular_font)
    pdf.set_title(f"{TITLE} - {sample_id}")
    pdf.set_author("WGS.FMT")
    pdf.set_lang("zh-CN")

    # Cover page
    pdf.add_page()
    pdf.set_y(44)
    pdf.set_font("WgsCN", "", 12)
    pdf.set_text_color(52, 101, 164)
    pdf.cell(0, 10, "WGS.FMT  /  微生态健康评估", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(17)
    pdf.set_font("WgsCN", "B", 29)
    pdf.set_text_color(52, 101, 164)
    pdf.multi_cell(0, 16, "肠道菌群\n精准健康分析报告", align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.set_font("WgsCN", "", 12)
    pdf.set_text_color(70, 80, 95)
    pdf.cell(0, 8, f"样本编号：{sample_id}", new_x="LMARGIN", new_y="NEXT")
    date_match = re.search(r"(?m)^报告日期[：:]\s*(\S+)", report_md)
    date_text = date_match.group(1) if date_match else datetime.now().strftime('%Y-%m-%d')
    pdf.cell(0, 8, f"报告日期：{date_text}", new_x="LMARGIN", new_y="NEXT")
    if "演示说明：" in report_md:
        pdf.set_font("WgsCN", "B", 11)
        pdf.set_text_color(155, 102, 20)
        pdf.cell(0, 9, "合成数据演示 · 非真实检测报告", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(18)
    pdf.set_fill_color(226, 237, 240)
    pdf.set_draw_color(184, 205, 210)
    pdf.set_font("WgsCN", "", 10.5)
    pdf.multi_cell(
        0, 8,
        "菌群组成与生态结构 · 重点菌与菌株证据 · 耐药组\n底物与代谢功能 · 宿主互作 · 症状与模型 · 综合建议",
        align="L", new_x="LMARGIN", new_y="NEXT",
    )
    pdf.set_y(242)
    pdf.set_font("WgsCN", "", 9)
    pdf.set_text_color(110, 120, 125)
    pdf.multi_cell(0, 6, "本报告用于健康管理与研究参考，需结合个人背景及临床检查阅读。", new_x="LMARGIN", new_y="NEXT")

    pdf.add_page()
    in_table = False
    source_lines = report_md.splitlines()
    skip_until = -1

    def render_toc(toc_pdf, outline):
        toc_pdf.set_x(toc_pdf.l_margin)
        toc_pdf.set_text_color(52, 101, 164)
        toc_pdf.set_font("WgsCN", "B", 17)
        toc_pdf.multi_cell(0, 10, "目录", new_x="LMARGIN", new_y="NEXT")
        toc_pdf.ln(4)
        for item in outline:
            if item.level != 0:
                continue
            toc_pdf.set_font("WgsCN", "", 10.5)
            toc_pdf.set_text_color(35, 45, 60)
            link = toc_pdf.add_link(page=item.page_number)
            toc_pdf.cell(toc_pdf.epw - 15, 8, item.name, link=link)
            toc_pdf.cell(15, 8, str(item.page_number), align="R", link=link,
                         new_x="LMARGIN", new_y="NEXT")

    for line_index, raw_line in enumerate(source_lines):
        if line_index <= skip_until:
            continue
        line = raw_line.strip()
        if line == "## 目录":
            # The PDF uses actual page destinations, not the Markdown link list.
            cursor = line_index + 1
            while cursor < len(source_lines) and not source_lines[cursor].startswith("## "):
                cursor += 1
            skip_until = cursor - 1
            in_table = False
            pdf.insert_toc_placeholder(render_toc, pages=1)
            continue
        if not line:
            if not in_table:
                pdf.ln(1.5)
            continue
        if re.fullmatch(r"[-|: ]{3,}", line):
            continue
        image_match = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", line)
        if image_match:
            in_table = False
            from pathlib import Path
            allowed_root = Path(output_path).resolve().parent
            image_path = Path(image_match.group(2))
            if not image_path.is_absolute():
                image_path = allowed_root / image_path
            image_path = image_path.resolve()
            if image_path.is_file() and image_path.is_relative_to(allowed_root):
                from PIL import Image
                with Image.open(image_path) as im:
                    image_h = pdf.epw * im.height / im.width
                image_w = pdf.epw
                max_h = pdf.eph - 14
                if image_h > max_h:
                    image_w *= max_h / image_h
                    image_h = max_h
                if pdf.get_y() + image_h > pdf.h - pdf.b_margin:
                    pdf.add_page()
                pdf.image(str(image_path), x=pdf.l_margin + (pdf.epw-image_w)/2, w=image_w)
                pdf.ln(3)
            else:
                pdf.set_font("WgsCN", "", 9.5)
                pdf.multi_cell(0, 6, "图表不可用：" + image_match.group(1), new_x="LMARGIN", new_y="NEXT")
            continue
        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading:
            in_table = False
            level = len(heading.group(1))
            title = clean(heading.group(2))
            if level == 1:
                continue  # The cover already carries the report title.
            chapter = level == 2 and bool(re.match(r"^\d+\s", title))
            if chapter or (level == 2 and title == "附录与参考资料"):
                pdf.add_page()
                pdf.chapter_title = title
            else:
                reserve = 48 if level == 3 else 35
                if level == 3:
                    # Word keeps a subsection heading with its first visual.
                    leading = 0
                    for candidate in source_lines[line_index+1:]:
                        candidate = candidate.strip()
                        if candidate.startswith(("##", "|")):
                            break
                        match = re.fullmatch(r"!\[[^\]]*\]\(([^)]+)\)", candidate)
                        if match:
                            from pathlib import Path
                            from PIL import Image
                            root=Path(output_path).resolve().parent
                            path=(root/match[1]).resolve()
                            if path.is_relative_to(root) and path.is_file():
                                with Image.open(path) as im:
                                    reserve=min(pdf.eph-2, 22+leading*6+pdf.epw*im.height/im.width)
                            break
                        if candidate:
                            leading += 1
                if pdf.will_page_break(reserve):
                    pdf.add_page()
            pdf.start_section(title, level=0 if level == 2 else 1)
            pdf.ln(4 if level <= 2 else 2)
            pdf.set_text_color(234, 117, 0) if level == 3 else pdf.set_text_color(52, 101, 164)
            pdf.set_font("WgsCN", "B", {1: 23, 2: 23 if chapter else 17, 3: 16, 4: 10.5}[level])
            pdf.multi_cell(0, 9 if level==2 else 7, title, new_x="LMARGIN", new_y="NEXT")
            continue
        if line.startswith("|") and line.endswith("|"):
            table_rows = []
            cursor = line_index
            while cursor < len(source_lines):
                table_line = source_lines[cursor].strip()
                if not (table_line.startswith("|") and table_line.endswith("|")):
                    break
                cells = [clean(cell) for cell in table_line.strip("|").split("|")]
                if not all(re.fullmatch(r"[: -]+", cell or "-") for cell in cells):
                    table_rows.append(cells)
                cursor += 1
            skip_until = cursor - 1
            in_table = False
            if table_rows:
                from fpdf.fonts import FontFace
                pdf.set_font("WgsCN", "", 10)
                pdf.set_text_color(0, 0, 0)
                pdf.set_draw_color(217, 217, 217)
                pdf.set_line_width(0.12)
                ncols = len(table_rows[0])
                widths = {2:(.34,.66), 3:(.30,.35,.35), 4:(.25,.25,.25,.25),
                          5:(.24,.23,.15,.22,.16), 6:(.15,.23,.20,.13,.15,.14)}.get(ncols)
                widths = {
                    ("关注顺序", "本次重点发现", "关注依据", "详见"): (.12,.30,.46,.12),
                    ("优先级", "本次发现", "证据充分程度", "实际相关性"): (.12,.30,.16,.42),
                    ("分类层级", "主要类群", "相对丰度"): (.12,.60,.28),
                    ("微生物名称", "功能或关注背景", "检出状态", "相对丰度", "人群分位数"): (.27,.28,.16,.18,.11),
                    ("重点物种", "本次丰度", "参考区间", "人群分位数", "比较结果"): (.28,.15,.34,.11,.12),
                    ("功能或项目", "本次结果", "参考比较", "主要贡献菌与证据"): (.26,.16,.22,.36),
                    ("产物或功能分支", "反应方向", "本次功能结果", "主要贡献菌与证据"): (.30,.17,.15,.38),
                }.get(tuple(table_rows[0]), widths)
                for chapter_spec in contract()["chapters"]:
                    for block in chapter_spec["blocks"]:
                        if block["type"]=="table" and block["rows"][0]==table_rows[0] and len(block["widths"])==ncols:
                            widths=tuple(block["widths"])
                if table_rows[0][:2] in (["菌群范围", "具体物种"], ["关注类别", "微生物名称"]):
                    weights = {"菌群范围": 12, "关注类别": 12, "具体物种": 22, "微生物名称": 22, "功能背景": 30, "关注说明": 30, "检出状态": 10, "主分析丰度": 12, "对照谱丰度": 12, "人群分位数": 11}
                    widths = tuple(weights.get(header, 15) for header in table_rows[0])
                score_style = (
                    FontFace(color=(52,101,164), size_pt=18)
                    if table_rows[0] == ["综合健康分", "失衡分", "模型肠龄"] else None
                )
                with pdf.table(col_widths=widths, line_height=5.0, padding=1.4,
                               headings_style=FontFace(emphasis="BOLD", color=(0,0,0), fill_color=(226,237,240)),
                               cell_fill_color=(246,248,249), cell_fill_mode="ROWS",
                               borders_layout="ALL", v_align="TOP") as report_table:
                    for row_index, cells in _paginate_pdf_table_rows(
                        pdf, table_rows, widths, body_style=score_style,
                    ):
                        row = report_table.row(style=score_style if row_index else None)
                        for cell in cells:
                            row.cell(cell)
            continue
        in_table = False
        if line in {"---", "***", "___"}:
            pdf.ln(2)
            pdf.set_draw_color(190, 200, 210)
            pdf.line(pdf.l_margin, pdf.y, pdf.w - pdf.r_margin, pdf.y)
            pdf.ln(2)
            continue
        quote = line.startswith(">")
        bullet = bool(re.match(r"^[-*+]\s+", line))
        numbered = bool(re.match(r"^\d+[.)]\s+", line))
        # Only remove real list markers; '**检测结果**' is emphasis, not a bullet.
        text = clean(re.sub(r"^(?:>\s*|[-*+]\s+|\d+[.)]\s+)", "", line))
        if not text:
            continue
        pdf.set_font("WgsCN", "", 11)
        pdf.set_text_color(0, 0, 0)
        if re.match(r"^[图表]\s*\d+[- ]\d+", text) or text == "相关知识子图":
            pdf.set_font("WgsCN", "B", 10)
            # Keep the caption with its image when both fit on a fresh page.
            next_image = next((v.strip() for v in source_lines[line_index+1:] if v.strip()), "")
            match = re.fullmatch(r"!\[[^\]]*\]\(([^)]+)\)", next_image)
            if match:
                from pathlib import Path
                from PIL import Image
                root = Path(output_path).resolve().parent
                path = (root / match[1]).resolve()
                if path.is_relative_to(root) and path.is_file():
                    with Image.open(path) as im:
                        needed = 12 + pdf.epw * im.height / im.width
                    if needed < pdf.eph and pdf.will_page_break(needed):
                        pdf.add_page()
            elif next_image.startswith("|") and pdf.will_page_break(30):
                pdf.add_page()
        if quote:
            pdf.multi_cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")
        elif bullet or numbered:
            marker = "• " if bullet else "– "
            pdf.multi_cell(0, 7, marker + text, align="L", wrapmode="CHAR", new_x="LMARGIN", new_y="NEXT")
        else:
            if re.match(r"^\[\d+\]\s", text):
                pdf.set_font("WgsCN", "", 9.5)
                pdf.multi_cell(0, 6, text, align="L", wrapmode="WORD", new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.multi_cell(0, 6, text, align="L", wrapmode="CHAR", new_x="LMARGIN", new_y="NEXT")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    pdf.output(output_path)
    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError("FPDF 未生成有效 PDF 文件")
    return output_path


def generate_pdf(report_md: str, sample_id: str, output_path: str) -> str:
    """
    将 Markdown 报告转为 PDF 文件，返回输出路径。
    优先 xelatex (LaTeX 排印) > 降级 Markdown
    """
    import subprocess
    import shutil as _shutil
    import os
    import re as _re

    xelatex_bin = os.path.expanduser("~/texlive/2026/bin/x86_64-linux/xelatex")
    if not (os.path.isfile(xelatex_bin) or _shutil.which("xelatex")):
        print("[PDF] 未检测到 xelatex，使用内置 Unicode PDF 渲染器")
        return _generate_fpdf_report(report_md, sample_id, output_path)

    # 注意：确保这一步能导入，或直接用下面的兜底字符清洗
    try:
        from wgs_agent.pipeline.pdf_builder import escape_latex
    except ImportError:
        def escape_latex(text):
            # 简单的 LaTeX 特殊字符转义兜底
            for ch in ['&', '%', '$', '#', '_', '{', '}']:
                text = text.replace(ch, '\\' + ch)
            return text

    env = os.environ.copy()
    env["PATH"] = os.path.expanduser("~/.local/bin") + ":" + env.get("PATH", "")

    out_dir = os.path.dirname(output_path) or "."
    build_dir = os.path.join(out_dir, "_build")
    os.makedirs(build_dir, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(output_path))[0]
    tex_path = os.path.join(build_dir, f"{base_name}.tex")

    # 先将自由 markdown 收敛为可控格式，再做字符级清洗
    normalized_md = normalize_report_markdown(report_md, sample_id)

    # 过滤 emoji 变体选择符（U+FE0F 等）和某些不可打印字符，避免 xelatex 字符缺失警告
    _clean_md = _re.sub(r'[\ufe0f\ufe0e\u200d\u200b\ufeff]', '', normalized_md)

    # 步骤 1: 用 pandoc fragment 模式把 Markdown 转成 LaTeX body
    pandoc = _shutil.which("pandoc") or os.path.expanduser("~/.local/bin/pandoc")
    body_tex = ""
    if _shutil.which(pandoc) or os.path.isfile(pandoc):
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as tf_md:
                tf_md.write(_clean_md)
                md_path = tf_md.name
            body_path = tex_path + ".body"
            body_cmd = [
                pandoc, md_path, "-o", body_path,
                "--from", "markdown+pipe_tables+grid_tables-auto_identifiers",
                "--to", "latex",
                "-V", "numbersections=false",
            ]
            subprocess.run(body_cmd, capture_output=True, text=True, env=env, timeout=60)
            if os.path.isfile(body_path):
                with open(body_path, "r", encoding="utf-8") as bf:
                    body_tex = bf.read()
                os.unlink(body_path)
            try: os.unlink(md_path)
            except OSError: pass
        except Exception as e:
            print(f"[PDF] Pandoc 转换失败: {e}")

    if not body_tex:
        body_tex = escape_latex(_clean_md)

    # 步骤 2: 包裹进 WGS.FMT 定制 preamble
    preamble = r"""\documentclass[11pt,a4paper,UTF8,headings=small]{ctexart}
\usepackage{fontspec}
\setmainfont{Noto Sans CJK SC}
\setsansfont{Noto Sans CJK SC}
\usepackage[a4paper,left=22mm,right=22mm,top=25mm,bottom=25mm,headheight=22pt,headsep=8mm,footskip=12mm]{geometry}
\usepackage[dvipsnames,svgnames,table]{xcolor}
\definecolor{WgsBlue}{RGB}{25, 60, 120}
\definecolor{WgsLightBlue}{RGB}{50, 90, 150}
\definecolor{WgsGreen}{RGB}{0, 140, 60}
\definecolor{WgsWarn}{RGB}{200, 130, 0}
\definecolor{WgsDanger}{RGB}{200, 50, 50}
\definecolor{graytext}{RGB}{100, 100, 100}
\definecolor{darkgray}{RGB}{45, 45, 45}
\definecolor{rowgray}{RGB}{243, 247, 252}
\colorlet{WgsBg}{WgsBlue!8!white}
\usepackage{array,booktabs,longtable,tabularx,ltablex,multirow,colortbl,graphicx,tikz,float,enumitem,fancyhdr,microtype,ragged2e}
\usepackage[colorlinks=true,linkcolor=WgsBlue,urlcolor=WgsBlue,citecolor=WgsBlue]{hyperref}
\setlist{nosep, leftmargin=*, itemsep=4pt, parsep=0pt}

% 声明支持自动换行且不强行两端对齐的左对齐列类型
\newcolumntype{L}[1]{>{\RaggedRight\arraybackslash}p{#1}}
\newcolumntype{Y}{>{\RaggedRight\arraybackslash}X}
\keepXColumns

\pagestyle{fancy}\fancyhf{}
\fancyhead[L]{\small\color{graytext} 肠道菌群健康评估报告}
\fancyhead[R]{\small\color{graytext} """ + escape_latex(sample_id) + r"""}
\fancyfoot[C]{\small\color{graytext} —\ \thepage\ —}
\renewcommand{\headrulewidth}{0.6pt}
\renewcommand{\headrule}{\hbox to\headwidth{\color{WgsBlue!40}\leaders\hrule height \headrulewidth\hfill}}
\usepackage{titlesec}
\titleformat{\section}{\sffamily\bfseries\Large\color{WgsBlue}}{\thesection}{1em}{}
\titleformat{\subsection}{\sffamily\bfseries\large\color{WgsLightBlue}}{\thesubsection}{1em}{}
\usepackage[many]{tcolorbox}\tcbuselibrary{skins,breakable}
\tcbset{reportbox/.style={enhanced,breakable,sharp corners,before skip=12pt,after skip=14pt,top=4mm,bottom=4mm,left=4mm,right=4mm,boxsep=1pt,toptitle=2mm,bottomtitle=2mm}}
\setcounter{secnumdepth}{0}
\setlength{\LTpre}{0.5em}
\setlength{\LTpost}{0.75em}
\setlength{\LTleft}{0pt}
\setlength{\LTright}{0pt}
\renewcommand{\arraystretch}{1.4} 
\linespread{1.2}
\begin{document}
"""

    # ── 彻底重构 longtable 替换逻辑（解决重叠的关键） ──
    def _estimate_column_count(spec: str) -> int:
        clean_spec = _re.sub(r'@\{[^}]*\}', '', spec)
        clean_spec = clean_spec.replace('|', '').replace(' ', '')
        # 兼容一些带有定宽参数的复杂 Pandoc 声明
        tokens = _re.findall(r'[lcrXm]|p\{[^}]+\}|b\{[^}]+\}|m\{[^}]+\}', clean_spec)
        return max(len(tokens), 1)

    def _normalized_widths(n: int) -> list[float]:
        # 收紧总比例到 0.88-0.90，预留充足的 tabcolsep 空间防止超出页面边缘导致挤压重叠
        presets = {
            1: [0.90],
            2: [0.28, 0.56],
            3: [0.30, 0.18, 0.38],
            4: [0.24, 0.16, 0.12, 0.30],
            5: [0.18, 0.12, 0.12, 0.12, 0.28],
            6: [0.22, 0.13, 0.09, 0.09, 0.09, 0.22],
            7: [0.18, 0.11, 0.09, 0.09, 0.09, 0.10, 0.18],
        }
        return presets.get(n, [0.88 / n] * n)

    def _fix_longtable_structure(m):
        # 匹配完整的 \begin{longtable} 及其大括号内容
        full_begin = m.group(0)
        # 提取括号里的原始格式声明
        cols_spec = m.group(1) if len(m.groups()) >= 1 else "l"
        n = _estimate_column_count(cols_spec)
        widths = _normalized_widths(n)
        
        # 构造强力的定宽换行 L 列组合
        specs = [f'L{{{w}\\textwidth}}' for w in widths]
        
        # 强制在表格前注入环境重置，显式缩减 tabcolsep 间距（从默认 6pt 缩减到 2pt）
        # 这是防止大表格因为边距过宽导致列重叠的关键技术手段
        return (
            r'\getlongtablewidth' + '\n'  # 配合 ltablex 的重置（如果使用过）
            r'\begingroup\footnotesize\setlength{\tabcolsep}{2pt}\renewcommand{\arraystretch}{1.25}\RaggedRight'
            + '\n'
            + r'\begin{longtable}{' + ''.join(specs) + r'}'
        )

    # 更加精准健壮的正则：匹配包含可选参数 [] 和格式大括号 {} 的完整开头
    body_tex = _re.sub(
        r'\\begin\{longtable\}(?:\[[^\]]*\])?\{([^}]+)\}',
        _fix_longtable_structure,
        body_tex
    )
    
    # 统一闭合环境，释放内存与字体大小
    body_tex = _re.sub(r'\\end\{longtable\}', r'\\end{longtable}\n\\endgroup\n', body_tex)

    # 清洗：Pandoc 有时会在单元格内部塞入 \textnormal{\textbf{...}} 导致其不可换行，将其剥离
    body_tex = _re.sub(r'\\textnormal\{([^}]+)\}', r'\1', body_tex)
    body_tex = _re.sub(r'\\textbf\{([^}]{30,}?)\}', r'\1', body_tex)
    body_tex = body_tex.replace(r'\toprule', r'\toprule\rowcolor{WgsBlue!12}')
    body_tex = body_tex.replace(r'\midrule', r'\midrule')
    
    # 修复参考文献及长英文字符串无空格导致无法换行挤压的问题
    body_tex = body_tex.replace(r'\begin{itemize}', r'\begin{itemize}\RaggedRight\small')

    tex_content = preamble + body_tex + "\n\\end{document}\n"
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex_content)

    compiler = xelatex_bin if os.path.isfile(xelatex_bin) else "xelatex"
    try:
        for i in range(2):
            result = subprocess.run(
                [compiler, "-interaction=nonstopmode", "-output-directory", build_dir, tex_path],
                capture_output=True, text=True, env=env, timeout=180,
            )
            src_pdf = os.path.join(build_dir, f"{base_name}.pdf")
            if os.path.isfile(src_pdf) and os.path.getsize(src_pdf) > 0:
                continue
            if result.returncode != 0:
                log_path = os.path.join(build_dir, f"{base_name}.log")
                print(f"[PDF/xelatex] 编译失败 (pass {i+1})，日志: {log_path}")
                raise RuntimeError(f"xelatex 编译错误")

        src_pdf = os.path.join(build_dir, f"{base_name}.pdf")
        if os.path.isfile(src_pdf):
            _shutil.copyfile(src_pdf, output_path)
            # 清理中间文件
            for ext in (".aux", ".log", ".out", ".toc", ".tex.body"):
                aux = os.path.join(build_dir, f"{base_name}{ext}")
                if os.path.isfile(aux):
                    try: os.unlink(aux)
                    except OSError: pass
            return output_path
        else:
            raise FileNotFoundError(f"未找到 PDF: {src_pdf}")
    except Exception as e:
        print(f"[PDF] xelatex 失败 '{e}'，使用内置 Unicode PDF 渲染器")
        return _generate_fpdf_report(report_md, sample_id, output_path)
