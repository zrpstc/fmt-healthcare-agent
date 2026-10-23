#!/usr/bin/env python3
"""
===============================================================================
报告公共模块 - 字体配置、PDF基类、常量（微软雅黑 + 11-13号字全宽中心填充版）
===============================================================================
"""

import os
from datetime import datetime
from typing import Tuple, List, Dict

from fpdf import FPDF
from wgs_fmt_platform.paths import (
    legacy_output_root, project_path, runtime_path, species_reference_path,
)

# ============================================================================
# 路径配置
# ============================================================================
BASE_DIR = str(legacy_output_root())
_REFERENCE_DIR = runtime_path("WGS_REFERENCE_DIR", "reference")
DATA_DIR = str(project_path(os.environ.get("WGS_LEGACY_DATA_DIR") or os.environ.get("WGS_DATA_DIR") or _REFERENCE_DIR))
OUTPUT_DIR = str(runtime_path("WGS_RESULTS_DIR", "results"))
MODEL_DIR = str(runtime_path("WGS_LEGACY_MODEL_DIR", "models", "Qwen3-0.6B"))

# 物种/通路/代谢物/药物数据矩阵
METAPHLAN_SPECIES_FILE = os.path.join(BASE_DIR, "05_matrix", "relative_abundance_species.tsv")
METAPHLAN_GENUS_FILE = os.path.join(BASE_DIR, "05_matrix", "relative_abundance_genus.tsv")
PATHWAY_KNOWN_FILE = os.path.join(BASE_DIR, "04_pathway", "pathway_abundance_known.tsv")
PATHWAY_CONTRIB_FILE = os.path.join(BASE_DIR, "04_pathway", "pathway_species_contribution.tsv")
PATHWAY_COMBINED_FILE = os.path.join(BASE_DIR, "04_pathway", "species_pathway_combined.tsv")
METABOLITE_MATRIX_FILE = os.path.join(BASE_DIR, "06_metabolite", "metabolite_content_matrix.tsv")
METABOLITE_SUMMARY_FILE = os.path.join(BASE_DIR, "06_metabolite", "metabolite_content_matrix_summary.tsv")
METABOLITE_CONTRIB_FILE = os.path.join(BASE_DIR, "06_metabolite", "metabolite_content_matrix_pathway_contribution.tsv")
DRUG_ANALYSIS_DIR = os.path.join(BASE_DIR, "07_drug_analysis")
DRUG_ANALYSIS_FILE = os.path.join(DRUG_ANALYSIS_DIR, "drug_analysis_report_{sample}.tsv")
METABOLITE_DRUG_FILE = os.path.join(DRUG_ANALYSIS_DIR, "metabolite_drug_links.tsv")
METHOD_COMPARISON_FILE = os.path.join(DRUG_ANALYSIS_DIR, "method_comparison_summary.tsv")
SPECIES_REF_FILE = os.path.join(DATA_DIR, "species_matrix_P5_P95.csv")
SPECIES_REF_EXTENDED = str(species_reference_path())
SPECIES_STATS_FILE = os.path.join(DATA_DIR, "health_species_stats.csv")
GENUS_STATS_FILE = os.path.join(DATA_DIR, "health_genus_stats.csv")
PHENOTYPE_FILE = os.path.join(DATA_DIR, "phenotype_species_stats.csv")


# ============================================================================
# 工具函数
# ============================================================================

def parse_p5p95(range_str: str) -> Tuple[float, float]:
    try:
        parts = range_str.strip().split('-')
        return float(parts[0]), float(parts[1])
    except:
        return 0.0, 0.0

def metaphlan_name_to_species(metaphlan_name: str) -> str:
    parts = metaphlan_name.split('|')
    for part in parts:
        if part.startswith('s__'):
            return part[3:].replace('_', ' ').strip()
    return ''

def metaphlan_name_to_genus(metaphlan_name: str) -> str:
    parts = metaphlan_name.split('|')
    for part in parts:
        if part.startswith('g__'):
            return part[3:].strip()
    return ''

def get_health_status(abundance: float, p5: float, p95: float) -> Tuple[str, str]:
    if abundance == 0:
        return "absent", "未检出"
    if p5 == 0 and p95 == 0:
        return "unknown", "无参考"
    if abundance < p5:
        return "low", "偏低"
    if abundance > p95:
        return "high", "偏高"
    return "normal", "正常"

def format_pathway_name(pw_name: str) -> str:
    if ':' in pw_name:
        return pw_name.split(':', 1)[1].strip()
    if '|' in pw_name:
        return pw_name.split('|')[-1].strip()
    return pw_name


# ============================================================================
# Matplotlib 中文字体配置（同样切为微软雅黑或系统等价高质量字体）
# ============================================================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_CN_FONT_PATH = os.path.join(CURRENT_DIR, "MSYH.TTC")  # 请确保该路径下有微软雅黑字体文件，或改为您的实际系统路径

def setup_cn_font():
    """配置 Matplotlib 使用中文字体（全局生效）"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.font_manager as fm
    import matplotlib.pyplot as plt
    try:
        font_prop = fm.FontProperties(fname=_CN_FONT_PATH)
        font_name = font_prop.get_name()
        fm.fontManager.addfont(_CN_FONT_PATH)
        plt.rcParams['font.family'] = font_name
        plt.rcParams['axes.unicode_minus'] = False
    except Exception as e:
        print(f'   [WARN] Matplotlib 中文字体配置失败: {e}')

# ============================================================================
# PDF 基类 - 微软雅黑 + 页面中心整体填充优化版
# ============================================================================

class HealthReportPDF(FPDF):
    """自定义中文 PDF 报告生成器（排版与全宽美化版）"""

    FONT_DIR = "/usr/share/fonts/dejavu"
    # 【修改项】将中文字体路径指向微软雅黑 (msyh.ttc 或 msyh.ttf)
    CJK_FONT_PATH = "/usr/share/fonts/msyh.ttc" 

    # 现代微生态报告颜色方案
    PRIMARY_COLOR = (25, 60, 120)      # 深蓝 - 标题
    SECONDARY_COLOR = (50, 90, 150)     # 中蓝 - 子标题
    ACCENT_COLOR = (0, 130, 200)        # 亮蓝 - 强调
    GREEN_COLOR = (0, 140, 60)          # 绿色 - 正常
    WARN_COLOR = (200, 130, 0)          # 橙色 - 警告
    DANGER_COLOR = (200, 50, 50)        # 红色 - 危险
    GRAY_COLOR = (100, 100, 100)        # 灰色 - 辅助文字
    LIGHT_BG = (242, 246, 252)          # 浅蓝灰色背景
    GREEN_BG = (235, 248, 235)          # 浅绿背景
    WARN_BG = (255, 248, 235)           # 浅橙背景

    def __init__(self, sample_id: str):
        super().__init__('P', 'mm', 'A4')  # A4 宽210mm, 高297mm
        self.sample_id = sample_id
        # 【排版美化】自动换页阈值，因为字号调大，底部留空调整为 22mm
        self.set_auto_page_break(True, 22)
        # 【排版美化】设置左右上下页边距为 15mm。页面可用中心总宽度 = 210 - 15*2 = 180mm
        self.set_margin(15)

        # 颜色别名简写
        self.PRIMARY = self.PRIMARY_COLOR
        self.SECONDARY = self.SECONDARY_COLOR
        self.ACCENT = self.ACCENT_COLOR
        self.GREEN = self.GREEN_COLOR
        self.WARN = self.WARN_COLOR
        self.DANGER = self.DANGER_COLOR
        self.GRAY = self.GRAY_COLOR
        self.BG_LIGHT = self.LIGHT_BG
        self.BG_GREEN = self.GREEN_BG
        self.BG_WARN = self.WARN_BG

        # ─── 【核心修改：智能动态检测字体路径，完美解决大小写与路径问题】 ───
        # 1. 动态获取当前脚本 (report_common.py) 所在的绝对路径目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 2. 列出本地目录下、系统目录下可能存在的各种微软雅黑文件名（严格区分并穷举大小写）
        possible_paths = [
            # 优先查找当前脚本同目录下的文件（支持大写和小写后缀）
            os.path.join(current_dir, "MSYH.TTC"),
            os.path.join(current_dir, "msyh.ttc"),
            os.path.join(current_dir, "MSYH.TTF"),
            os.path.join(current_dir, "msyh.ttf"),
            # 其次查找系统可能存在的其他自定义路径
            "/usr/share/fonts/winfonts/MSYH.TTC",
            "/usr/share/fonts/winfonts/msyh.ttc",
            "/usr/share/fonts/msyh.ttc",
            # 最后的开源兜底（如果你安装了文泉驿微米黑）
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"
        ]
        
        # 3. 循环匹配，一旦找到存在的路径立刻锁定
        valid_font_path = None
        for path in possible_paths:
            if os.path.exists(path):
                valid_font_path = path
                break
                
        # 4. 如果所有可能路径都没找到，抛出友好具体的错误提示
        if valid_font_path is None:
            raise FileNotFoundError(
                f"\n❌ [错误] 无法定位中文字体文件！\n"
                f"代码已尝试在本地目录：'{current_dir}' 中寻找 MSYH.TTC 等文件，但未找到。\n"
                f"请检查 Windows 复制过来的字体文件是否确实放在该目录下，且名称在以下列表中:\n"
                f"期待的文件名列表: ['MSYH.TTC', 'msyh.ttc', 'MSYH.TTF', 'msyh.ttf']"
            )

        # 5. 将最终锁定、切实存在的路径赋值给 CJK_FONT_PATH
        self.CJK_FONT_PATH = valid_font_path
        print(f"   [INFO] 成功加载中文字体路径: {self.CJK_FONT_PATH}")

        # 注册微软雅黑字体 (作为 'CJK' 核心别名)
        self.add_font('CJK', '', self.CJK_FONT_PATH)
        self.add_font('CJK', 'B', self.CJK_FONT_PATH)
        self.add_font('CJK', 'I', self.CJK_FONT_PATH)
        # 【兼容修改】因为系统缺乏 DejaVu 字体，直接复用已成功加载的微软雅黑来渲染英文数字
        self.add_font('DejaVu', '', self.CJK_FONT_PATH)
        self.add_font('DejaVu', 'B', self.CJK_FONT_PATH)
        self.add_font('DejaVu', 'I', self.CJK_FONT_PATH)
        
    def header(self):
        if self.page_no() > 1:
            self.set_font('DejaVu', 'I', 8)
            self.set_text_color(*self.GRAY_COLOR)
            self.cell(0, 5, f'Gut Microbiome Health Report - {self.sample_id}',
                      new_x="RIGHT", new_y="TOP")
            self.cell(0, 5, f'Page {self.page_no()}/{{nb}}',
                      new_x="LMARGIN", new_y="NEXT", align='R')
            self.set_draw_color(200, 200, 200)
            self.line(15, 12, 195, 12)  # 全宽对齐分割线
            self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font('DejaVu', 'I', 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")} | '
                         f'WGS.FMT Pipeline | {self.sample_id}',
                  align='C')

    # ---------- 标题层级 (全宽 180mm 动态填充) ----------
    def section_title(self, title: str, color: Tuple[int, int, int] = None):
        """一级章节标题 - 全宽底纹装饰"""
        if color is None:
            color = self.PRIMARY_COLOR
        self.ln(3)
        self.set_fill_color(*color)
        self.set_text_color(255, 255, 255)
        # 【修改项】一级标题提升至 15 号字，高度扩展至 11mm
        self.set_font('CJK', 'B', 15)
        self.cell(180, 11, f'  {title}', fill=True, new_x="LMARGIN", new_y="NEXT")
        self.ln(5)
        self.set_text_color(0, 0, 0)

    def subsection(self, title: str):
        """二级小节标题"""
        # 【修改项】二级标题提升至 13 号字，确保层级清晰
        self.set_font('CJK', 'B', 13)
        self.set_text_color(*self.SECONDARY_COLOR)
        self.cell(180, 9, f'> {title}', new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def sub_subsection(self, title: str):
        """三级标题"""
        # 【修改项】三级标题提升至 11.5 号字
        self.set_font('CJK', 'B', 11.5)
        self.set_text_color(60, 60, 60)
        self.cell(180, 8, f'  {title}', new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)

    # ---------- 信息提示框 (全宽 180mm 整体填充) ----------
    def info_box(self, title: str, content: str, color: Tuple[int, int, int] = None):
        """全宽自适应提示框"""
        if color is None:
            color = self.LIGHT_BG
        self.set_fill_color(*color)
        self.set_draw_color(max(0, color[0]-25), max(0, color[1]-25), max(0, color[2]-25))
        
        # 记录起始Y坐标，用来画整体外包围框线
        start_y = self.get_y()
        
        # 1. 标题行：字号 12，行高 8.5
        self.set_font('CJK', 'B', 12)
        self.set_text_color(*self.PRIMARY_COLOR)
        self.cell(180, 8.5, f'  {title}', fill=True, border='TLR', new_x="LMARGIN", new_y="NEXT")

        # 2. 内容行：字号 11 (符合11-13需求)，行高 7mm 防止内容重叠
        self.set_font('CJK', '', 11)
        self.set_text_color(45, 45, 45)
        
        lines = content.split('\n')
        for i, line in enumerate(lines):
            # 检查换页安全性
            if self.get_y() > 255:
                self.add_page()
                self.set_fill_color(*color)
            border_str = 'LR' if i < len(lines) - 1 else 'LBR'
            self.cell(180, 7.0, f'    {line}', fill=True, border=border_str, new_x="LMARGIN", new_y="NEXT")
            
        self.ln(4)
        self.set_text_color(0, 0, 0)

    # ---------- 全宽中心表格组件 ----------
    def add_table(self, headers: List[str], data: List[List[str]], col_widths: List[float] = None):
        """全宽条纹美化表格"""
        if col_widths is None:
            col_widths = [180.0 / len(headers)] * len(headers)
        
        # 验证列宽总和是否精确等于 180mm，若不相等则按比例微调，防止表格偏左或越界
        total_w = sum(col_widths)
        if abs(total_w - 180.0) > 0.1:
            col_widths = [w * (180.0 / total_w) for w in col_widths]

        # 1. 绘制表头：字号 11.5，行高扩展至 9mm 承载大字
        self.set_fill_color(*self.PRIMARY_COLOR)
        self.set_text_color(255, 255, 255)
        self.set_font('CJK', 'B', 11.5)
        self.set_draw_color(215, 215, 215)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 9, f' {h}', border=1, align='C', fill=True)
        self.ln()

        # 2. 绘制表体：字号 11.0 (满足11-13要求)，行高升级至 7.5mm
        self.set_text_color(35, 35, 35)
        self.set_font('CJK', '', 11.0)
        fill = False
        
        for ri, row in enumerate(data):
            # 换页控制：大字号占用空间多，提前到 252mm 触发换页
            if self.get_y() > 252:
                self.add_page()
                # 跨页自动补全表头
                self.set_fill_color(*self.PRIMARY_COLOR)
                self.set_text_color(255, 255, 255)
                self.set_font('CJK', 'B', 11.5)
                for i, h in enumerate(headers):
                    self.cell(col_widths[i], 9, f' {h}', border=1, align='C', fill=True)
                self.ln()
                self.set_text_color(35, 35, 35)
                self.set_font('CJK', '', 11.0)

            bg = (247, 250, 255) if fill else (255, 255, 255)
            self.set_fill_color(*bg)
            for i, cell_val in enumerate(row):
                align = 'L' if i == 0 else 'C'
                # 截断长度适当放宽
                display_text = str(cell_val)[:40]
                self.cell(col_widths[i], 7.5, f' {display_text}', border=1, align=align, fill=True)
            self.ln()
            fill = not fill
        self.ln(3)

    # ---------- 核心正文文本块 ----------
    def text_block(self, text: str):
        """标准正文段落：11.5号字，7.5mm行高，填满180mm可用宽度"""
        self.set_font('CJK', '', 11.5)
        self.multi_cell(180, 7.5, text)
        self.ln(2)

    # ---------- 核心正文列表项 ----------
    def bullet(self, text: str, indent: int = 0, bold_prefix: str = None):
        """高级子弹点列表：11号字，7mm行高"""
        self.set_font('CJK', '', 11.0)
        prefix = '  ' * indent + '● '
        if bold_prefix:
            self.set_font('CJK', 'B', 11.0)
            self.cell(180, 7, f'{prefix}{bold_prefix}', new_x="LMARGIN", new_y="NEXT")
            self.set_font('CJK', '', 11.0)
            self.set_x(22 + indent * 4)
            self.multi_cell(173 - indent * 4, 7, text)
        else:
            self.set_x(15 + indent * 4)
            self.multi_cell(180 - indent * 4, 7, f'{prefix}{text}')
