# -*- coding: utf-8 -*-
"""
生成测试用的示例 PDF
运行：python generate_samples.py
"""
import shutil
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

base = Path(__file__).parent / "示例PDF"
if base.exists():
    shutil.rmtree(base)
base.mkdir(parents=True)


def make_pdf(path: Path, pages: int, title: str, code: str, with_text: bool = True):
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    for i in range(1, pages + 1):
        if with_text:
            c.setFont("STSong-Light", 20)
            c.drawString(60, height - 80, f"{title}")
            c.setFont("STSong-Light", 12)
            c.drawString(60, height - 120, f"这是第 {i} 页的正文内容，用于测试文字提取。")
            c.drawString(60, height - 145, f"文件编号：{code}-2026-{i:03d}")
        else:
            # 只有图形没有文字，模拟扫描件
            c.setFillColorRGB(0.6, 0.6, 0.6)
            c.rect(60, height - 200, 400, 120, fill=1)
        if with_text:
            c.setFont("Helvetica", 9)
            c.drawString(60, 40, f"Page {i}")
        c.showPage()
    c.save()


make_pdf(base / "合同_2026.pdf", 5, "合同正文", "HT")
make_pdf(base / "报价单.pdf", 3, "报价单", "BJ")
make_pdf(base / "扫描件_无文字.pdf", 2, "扫描件", "SM", with_text=False)

print(f"示例 PDF 已生成：{base}")
for f in sorted(base.glob("*.pdf")):
    print("  ", f.name)
