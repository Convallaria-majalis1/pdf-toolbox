# -*- coding: utf-8 -*-
"""
PDF 批处理器 —— 核心逻辑

四件事：
1. 合并：多个 PDF 按顺序拼成一个，可选给每个文件加书签
2. 拆分：按单页拆 / 每 N 页拆 / 提取指定页码
3. 加水印：批量加页码、日期、公司名，位置/字号/透明度/角度可调
4. 提取文字：把 PDF 里的文字抽到一个 txt（扫描件抽不出来，会提示）

安全约定：结果永远写到新文件，不会覆盖原始 PDF。
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

# 中文字体：reportlab 自带的 CID 字体，不用额外装字体文件
FONT_NAME = "STSong-Light"
pdfmetrics.registerFont(UnicodeCIDFont(FONT_NAME))

# 水印位置的九宫格
POSITIONS = ["左上", "上中", "右上", "左中", "居中", "右中", "左下", "下中", "右下"]


@dataclass
class PdfInfo:
    path: str
    pages: int
    size_kb: int
    encrypted: bool
    title: str


# ---------------- 基础 ----------------------------


def _check_input(path: str) -> Path:
    p = Path(path)
    if not p.exists():
        raise ValueError(f"文件不存在：{p.name}")
    if p.suffix.lower() != ".pdf":
        raise ValueError(f"不是 PDF 文件：{p.name}")
    return p


def _reader(path: str) -> PdfReader:
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise ValueError(f"《{Path(path).name}》是加密 PDF，需要密码才能处理，请先解密。")
    return reader


def _ensure_new_output(out_path: str, inputs: list[str]) -> Path:
    """输出不能和任何一个输入文件相同，避免把原件写坏"""
    out = Path(out_path)
    for item in inputs:
        try:
            if out.resolve() == Path(item).resolve():
                raise ValueError("输出文件不能和原文件同名，请换一个位置或文件名。")
        except OSError:
            continue
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def pdf_info(path: str) -> PdfInfo:
    p = Path(path)
    try:
        reader = _reader(path)
        pages = len(reader.pages)
        encrypted = False
        title = ""
        try:
            title = (reader.metadata or {}).get("/Title", "") or ""
        except Exception:
            title = ""
    except ValueError:
        # 加密文件也要能列出页数，方便用户识别
        pages = 0
        encrypted = True
        title = ""
    return PdfInfo(str(p), pages, max(1, p.stat().st_size // 1024), encrypted, str(title))


# ---------------- 合并 ----------------------------


def merge_pdfs(paths: list[str], out_path: str, add_bookmarks: bool = True, log=None) -> dict:
    if len(paths) < 2:
        raise ValueError("合并至少需要两个 PDF 文件")

    out = _ensure_new_output(out_path, paths)
    writer = PdfWriter()
    total_pages = 0

    for path in paths:
        reader = _reader(path)
        start_index = total_pages
        for page in reader.pages:
            writer.add_page(page)
            total_pages += 1
        if add_bookmarks:
            writer.add_outline_item(Path(path).stem, start_index)
        if log:
            log(f"已加入：{Path(path).name}（{len(reader.pages)} 页）")

    writer.add_metadata({"/Producer": "PDF 批处理器"})
    with open(out, "wb") as f:
        writer.write(f)

    return {"files": len(paths), "pages": total_pages, "output": str(out)}


# ---------------- 页码范围 ----------------------------


def parse_page_ranges(expr: str, total: int) -> list[int]:
    """
    解析页码表达式，返回 0 基索引： "1-3,5,7-"、"3"、"-2"
    """
    if not expr or not expr.strip():
        raise ValueError("请填写页码范围，例如 1-3,5,8-10")

    result: list[int] = []
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part.lstrip("-"):
                left, right = part.split("-", 1)
                start = int(left) if left.strip() else 1
                end = int(right) if right.strip() else total
            else:
                start = end = int(part)
        except ValueError:
            raise ValueError(f"页码格式写错了：{part}")

        if start > end:
            start, end = end, start
        if start < 1 or end > total:
            raise ValueError(f"页码 {part} 超出范围（这份 PDF 共 {total} 页）")

        result.extend(range(start - 1, end))

    # 去掉重复，保持顺序
    seen = set()
    unique = []
    for index in result:
        if index not in seen:
            seen.add(index)
            unique.append(index)
    return unique


# ---------------- 拆分 ----------------------------


SPLIT_MODES = {
    "每页单独一个文件": "single",
    "每 N 页一个文件": "every",
    "只提取指定页码": "range",
}


def split_pdf(
    path: str,
    out_dir: str,
    mode: str = "single",
    pages_per_file: int = 1,
    page_range: str = "",
    log=None,
) -> dict:
    reader = _reader(path)
    total = len(reader.pages)
    source = Path(path)
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    created: list[str] = []

    if mode == "range":
        indexes = parse_page_ranges(page_range, total)
        writer = PdfWriter()
        for index in indexes:
            writer.add_page(reader.pages[index])
        out_file = out_root / f"{source.stem}_提取{len(indexes)}页.pdf"
        with open(out_file, "wb") as f:
            writer.write(f)
        created.append(str(out_file))
        if log:
            log(f"提取 {len(indexes)} 页 -> {out_file.name}")
        return {"files": len(created), "pages": len(indexes), "outputs": created}

    step = 1 if mode == "single" else max(1, int(pages_per_file))
    for start in range(0, total, step):
        end = min(start + step, total)
        writer = PdfWriter()
        for index in range(start, end):
            writer.add_page(reader.pages[index])
        name = f"{source.stem}_{start + 1:03d}-{end:03d}.pdf"
        out_file = out_root / name
        with open(out_file, "wb") as f:
            writer.write(f)
        created.append(str(out_file))
        if log:
            log(f"{name}（{end - start} 页）")

    return {"files": len(created), "pages": total, "outputs": created}


def split_many(
    paths: list[str],
    out_dir: str,
    mode: str,
    pages_per_file: int = 1,
    page_range: str = "",
    log=None,
) -> dict:
    """多个 PDF 各自拆到同名子文件夹"""
    total_files = total_pages = 0
    all_outputs: list[str] = []
    for path in paths:
        sub_dir = Path(out_dir) / Path(path).stem
        if log:
            log(f"处理：{Path(path).name}")
        result = split_pdf(path, str(sub_dir), mode, pages_per_file, page_range, log=log)
        total_files += result["files"]
        total_pages += result["pages"]
        all_outputs.extend(result["outputs"])
    return {"files": total_files, "pages": total_pages, "outputs": all_outputs}


# ---------------- 加水印 ----------------------------


def _anchor(position: str, width: float, height: float, font_size: float, margin: float):
    """算出文字基准点坐标和水平对齐方式"""
    align = "left"
    if position in ("上中", "居中", "下中"):
        x = width / 2
        align = "center"
    elif position in ("右上", "右中", "右下"):
        x = width - margin
        align = "right"
    else:
        x = margin

    if position in ("左上", "上中", "右上"):
        y = height - margin - font_size
    elif position in ("左中", "居中", "右中"):
        y = height / 2 - font_size / 2
    else:
        y = margin

    return x, y, align


def _make_overlay(width, height, text, position, font_size, opacity, rotation, margin=36):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(float(width), float(height)))
    c.setFont(FONT_NAME, float(font_size))
    c.setFillAlpha(max(0.0, min(1.0, float(opacity))))
    x, y, align = _anchor(position, float(width), float(height), float(font_size), margin)

    c.saveState()
    c.translate(x, y)
    if rotation:
        c.rotate(float(rotation))
    if align == "center":
        c.drawCentredString(0, 0, text)
    elif align == "right":
        c.drawRightString(0, 0, text)
    else:
        c.drawString(0, 0, text)
    c.restoreState()
    c.showPage()
    c.save()
    buffer.seek(0)
    return PdfReader(buffer).pages[0]


def watermark_pdf(
    path: str,
    out_path: str,
    text_template: str,
    position: str = "右下",
    font_size: int = 10,
    opacity: float = 0.5,
    rotation: int = 0,
    start_page: int = 1,
    over: bool = True,
    log=None,
) -> dict:
    reader = _reader(path)
    total = len(reader.pages)
    writer = PdfWriter()
    stamped = 0

    for index, page in enumerate(reader.pages, start=1):
        if index >= max(1, int(start_page)):
            text = (
                text_template.replace("{page}", str(index))
                .replace("{total}", str(total))
                .replace("{date}", date.today().strftime("%Y-%m-%d"))
                .replace("{filename}", Path(path).stem)
            )
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            overlay = _make_overlay(width, height, text, position, font_size, opacity, rotation)
            page.merge_page(overlay, over=over)
            stamped += 1
        writer.add_page(page)

    out = _ensure_new_output(out_path, [path])
    with open(out, "wb") as f:
        writer.write(f)
    if log:
        log(f"{Path(path).name}：{stamped} 页已加水印 -> {Path(out).name}")
    return {"pages": stamped, "output": str(out)}


def watermark_many(
    paths: list[str],
    out_dir: str,
    text_template: str,
    suffix: str = "_已加水印",
    position: str = "右下",
    font_size: int = 10,
    opacity: float = 0.5,
    rotation: int = 0,
    start_page: int = 1,
    over: bool = True,
    log=None,
) -> dict:
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    total_pages = 0
    outputs = []
    for path in paths:
        out_file = out_root / f"{Path(path).stem}{suffix}.pdf"
        result = watermark_pdf(
            path, str(out_file), text_template, position, font_size,
            opacity, rotation, start_page, over, log=log,
        )
        total_pages += result["pages"]
        outputs.append(result["output"])
    return {"files": len(paths), "pages": total_pages, "outputs": outputs}


# ---------------- 提取文字 ----------------------------


def extract_text(
    paths: list[str],
    out_txt: str,
    with_page_marker: bool = True,
    log=None,
) -> dict:
    out = Path(out_txt)
    out.parent.mkdir(parents=True, exist_ok=True)

    total_pages = 0
    empty_pages = 0
    chunks: list[str] = []

    for path in paths:
        reader = _reader(path)
        chunks.append(f"\n{'=' * 20} {Path(path).name} {'=' * 20}\n")
        for index, page in enumerate(reader.pages, start=1):
            total_pages += 1
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            if not text.strip():
                empty_pages += 1
            if with_page_marker:
                chunks.append(f"\n--- 第 {index} 页 ---\n")
            chunks.append(text.strip() + "\n")
        if log:
            log(f"已提取：{Path(path).name}（{len(reader.pages)} 页）")

    out.write_text("".join(chunks), encoding="utf-8")
    if log:
        log(f"已保存：{out}")
    return {"pages": total_pages, "empty_pages": empty_pages, "output": str(out)}


# ---------------- 命令行入口 ----------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(description="PDF 批处理")
    sub = parser.add_subparsers(dest="command")

    p_merge = sub.add_parser("merge", help="合并多个 PDF")
    p_merge.add_argument("files", nargs="+")
    p_merge.add_argument("-o", "--output", required=True)
    p_merge.add_argument("--no-bookmark", action="store_true")

    p_split = sub.add_parser("split", help="拆分 PDF")
    p_split.add_argument("file")
    p_split.add_argument("-d", "--dir", required=True)
    p_split.add_argument("--mode", default="single", choices=list(SPLIT_MODES.values()))
    p_split.add_argument("--pages", type=int, default=1, help="每 N 页一个文件")
    p_split.add_argument("--range", dest="page_range", default="")

    p_wm = sub.add_parser("watermark", help="加水印")
    p_wm.add_argument("file")
    p_wm.add_argument("-o", "--output", required=True)
    p_wm.add_argument("--text", default="第 {page} 页 / 共 {total} 页")
    p_wm.add_argument("--position", default="右下", choices=POSITIONS)
    p_wm.add_argument("--size", type=int, default=10)
    p_wm.add_argument("--opacity", type=float, default=0.5)
    p_wm.add_argument("--rotation", type=int, default=0)

    p_text = sub.add_parser("extract", help="提取文字")
    p_text.add_argument("files", nargs="+")
    p_text.add_argument("-o", "--output", required=True)

    p_info = sub.add_parser("info", help="查看 PDF 信息")
    p_info.add_argument("file")

    args = parser.parse_args()

    if args.command == "merge":
        result = merge_pdfs(args.files, args.output, not args.no_bookmark, log=print)
    elif args.command == "split":
        result = split_pdf(args.file, args.dir, args.mode, args.pages, args.page_range, log=print)
    elif args.command == "watermark":
        result = watermark_pdf(
            args.file, args.output, args.text, args.position,
            args.size, args.opacity, args.rotation, log=print,
        )
    elif args.command == "extract":
        result = extract_text(args.files, args.output, log=print)
    elif args.command == "info":
        result = pdf_info(args.file).__dict__
    else:
        parser.print_help()
        return
    print(result)


if __name__ == "__main__":
    main()
