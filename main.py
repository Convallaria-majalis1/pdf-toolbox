# -*- coding: utf-8 -*-
"""
PDF 批处理器 —— 图形界面
四个标签页：合并 / 拆分 / 加水印 / 提取文字。
所有操作都在后台线程跑，界面不会卡死；结果永远写到新文件。
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import core

APP_TITLE = "PDF 批处理器 v1.0"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def open_folder(folder: str):
    try:
        if sys.platform.startswith("win"):
            os.startfile(folder)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception:
        pass


class FileList(ttk.LabelFrame):
    """一个可复用的 PDF 文件列表控件"""

    def __init__(self, parent, title=" PDF 文件 ", with_reorder=False, show_pages=True, height=5):
        super().__init__(parent, text=title)
        self.files: list[str] = []
        self.show_pages = show_pages

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=8, pady=(6, 0))

        self.listbox = tk.Listbox(body, height=height, selectmode=tk.EXTENDED, font=("Microsoft YaHei", 9))
        self.listbox.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.listbox.yview)
        scroll.pack(side="right", fill="y")
        self.listbox.configure(yscrollcommand=scroll.set)

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=8, pady=6)
        ttk.Button(buttons, text="添加 PDF", command=self.add_files).pack(side="left")
        ttk.Button(buttons, text="移除选中", command=self.remove_selected).pack(side="left", padx=4)
        ttk.Button(buttons, text="清空", command=self.clear).pack(side="left")
        if with_reorder:
            ttk.Button(buttons, text="上移", command=lambda: self.move(-1)).pack(side="left", padx=(12, 2))
            ttk.Button(buttons, text="下移", command=lambda: self.move(1)).pack(side="left")
        self.count_label = ttk.Label(buttons, text="0 个文件", foreground="#666666")
        self.count_label.pack(side="right")

    # ----
    def add_files(self):
        selected = filedialog.askopenfilenames(
            title="选择 PDF 文件", filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")]
        )
        for path in selected:
            if path in self.files:
                continue
            self.files.append(path)
        self._refresh()

    def remove_selected(self):
        for index in reversed(self.listbox.curselection()):
            del self.files[index]
        self._refresh()

    def clear(self):
        self.files.clear()
        self._refresh()

    def move(self, delta: int):
        selected = self.listbox.curselection()
        if len(selected) != 1:
            return
        index = selected[0]
        new_index = index + delta
        if 0 <= new_index < len(self.files):
            self.files[index], self.files[new_index] = self.files[new_index], self.files[index]
            self._refresh(select=new_index)

    def _refresh(self, select=None):
        self.listbox.delete(0, tk.END)
        for path in self.files:
            label = Path(path).name
            if self.show_pages:
                try:
                    info = core.pdf_info(path)
                    label += "（加密）" if info.encrypted else f"（{info.pages} 页）"
                except Exception:
                    label += "（无法读取）"
            self.listbox.insert(tk.END, label)
        self.count_label.configure(text=f"{len(self.files)} 个文件")
        if select is not None and 0 <= select < len(self.files):
            self.listbox.selection_set(select)

    def paths(self) -> list[str]:
        return list(self.files)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.last_output_dir = ""

        root.title(APP_TITLE)
        root.geometry("1060x860")
        root.minsize(940, 780)

        self._build_ui()
        self._poll_log()

    # ---------------- 界面骨架 ----------------
    def _build_ui(self):
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=12, pady=(10, 0))

        title_box = ttk.Frame(header)
        title_box.pack(side="left", anchor="n")
        ttk.Label(title_box, text="PDF 批处理器", font=("Microsoft YaHei", 15, "bold")).pack(anchor="w")
        ttk.Label(
            title_box,
            text="合并 / 拆分 / 加水印 / 提取文字 —— 结果都输出到新文件，不动原件。",
            foreground="#666666",
        ).pack(anchor="w", pady=(2, 0))

        ttk.Button(header, text="打开上次输出位置", command=self.open_last_output).pack(
            side="right", anchor="n", pady=(4, 0)
        )

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=8)

        self.tab_merge = ttk.Frame(self.notebook)
        self.tab_split = ttk.Frame(self.notebook)
        self.tab_mark = ttk.Frame(self.notebook)
        self.tab_text = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_merge, text="  合并  ")
        self.notebook.add(self.tab_split, text="  拆分  ")
        self.notebook.add(self.tab_mark, text="  加水印  ")
        self.notebook.add(self.tab_text, text="  提取文字  ")

        self._build_merge_tab()
        self._build_split_tab()
        self._build_mark_tab()
        self._build_text_tab()
        self._build_log()

    def _build_log(self):
        frame = ttk.LabelFrame(self.root, text=" 日志 ")
        frame.pack(fill="x", padx=12, pady=(0, 10))
        self.log_text = tk.Text(frame, height=6, wrap="word", font=("Consolas", 9), state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=6)

    # ---------------- 合并 ----------------
    def _build_merge_tab(self):
        pad = {"padx": 8, "pady": 4}
        self.merge_files = FileList(self.tab_merge, " 待合并的 PDF（按下面的顺序拼接） ", with_reorder=True, height=6)
        self.merge_files.pack(fill="both", expand=True, **pad)

        row = ttk.Frame(self.tab_merge)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="输出文件").pack(side="left")
        self.var_merge_out = tk.StringVar(value=str(app_dir() / "合并结果.pdf"))
        ttk.Entry(row, textvariable=self.var_merge_out).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="另存为…", command=self._pick_merge_out).pack(side="left")

        row2 = ttk.Frame(self.tab_merge)
        row2.pack(fill="x", **pad)
        self.var_merge_bookmark = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="给每个文件加书签（方便在阅读器里跳转）",
                        variable=self.var_merge_bookmark).pack(side="left")
        self.btn_merge = ttk.Button(row2, text="开始合并", command=self.do_merge)
        self.btn_merge.pack(side="left", padx=12)
        ttk.Label(row2, text="至少选 2 个文件", foreground="#888888").pack(side="left")

    def _pick_merge_out(self):
        path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF 文件", "*.pdf")])
        if path:
            self.var_merge_out.set(path)

    def do_merge(self):
        files = self.merge_files.paths()
        if len(files) < 2:
            messagebox.showwarning("文件不够", "合并至少需要 2 个 PDF 文件。")
            return
        out = self.var_merge_out.get().strip()
        if not out:
            messagebox.showwarning("还没设输出", "请先指定输出文件。")
            return

        def task():
            return core.merge_pdfs(files, out, self.var_merge_bookmark.get(), log=self._log)

        self._start_task(self.btn_merge, task, self._merge_done)

    def _merge_done(self, result):
        self.last_output_dir = str(Path(result["output"]).parent)
        self._log(f"合并完成：{result['files']} 个文件、共 {result['pages']} 页")
        messagebox.showinfo("完成", f"已合并 {result['pages']} 页，保存到：\n{result['output']}")

    # ---------------- 拆分 ----------------
    def _build_split_tab(self):
        pad = {"padx": 8, "pady": 4}
        self.split_files = FileList(self.tab_split, " 要拆分的 PDF（每个文件拆到同名子文件夹） ", height=5)
        self.split_files.pack(fill="both", expand=True, **pad)

        row = ttk.Frame(self.tab_split)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="输出目录").pack(side="left")
        self.var_split_out = tk.StringVar()
        ttk.Entry(row, textvariable=self.var_split_out).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="浏览…", command=lambda: self._pick_dir(self.var_split_out)).pack(side="left")

        row2 = ttk.Frame(self.tab_split)
        row2.pack(fill="x", **pad)
        ttk.Label(row2, text="拆分方式").pack(side="left")
        self.var_split_mode = tk.StringVar(value="每页单独一个文件")
        combo = ttk.Combobox(row2, textvariable=self.var_split_mode, width=20, state="readonly",
                             values=list(core.SPLIT_MODES.keys()))
        combo.pack(side="left", padx=6)
        combo.bind("<<ComboboxSelected>>", self._on_split_mode)

        ttk.Label(row2, text="每 N 页").pack(side="left", padx=(10, 2))
        self.var_split_n = tk.StringVar(value="1")
        self.spin_split_n = ttk.Spinbox(row2, from_=1, to=999, textvariable=self.var_split_n, width=5, state="disabled")
        self.spin_split_n.pack(side="left")

        ttk.Label(row2, text="页码范围").pack(side="left", padx=(12, 2))
        self.var_split_range = tk.StringVar()
        self.entry_split_range = ttk.Entry(row2, textvariable=self.var_split_range, width=18, state="disabled")
        self.entry_split_range.pack(side="left")
        ttk.Label(row2, text='例：1-3,5,8-', foreground="#888888").pack(side="left", padx=6)

        row3 = ttk.Frame(self.tab_split)
        row3.pack(fill="x", **pad)
        ttk.Label(row3, text="提示：拆出的文件名形如 合同_001-005.pdf；“只提取指定页码”会把选中的页合成一个新文件。",
                  foreground="#888888").pack(side="left")
        self.btn_split = ttk.Button(row3, text="开始拆分", command=self.do_split)
        self.btn_split.pack(side="right", padx=8)

    def _on_split_mode(self, _event=None):
        mode = core.SPLIT_MODES.get(self.var_split_mode.get())
        every_state = "normal" if mode == "every" else "disabled"
        range_state = "normal" if mode == "range" else "disabled"
        self.spin_split_n.configure(state=every_state)
        self.entry_split_range.configure(state=range_state)

    def do_split(self):
        files = self.split_files.paths()
        if not files:
            messagebox.showwarning("还没选文件", "请先添加要拆分的 PDF。")
            return
        out_dir = self.var_split_out.get().strip()
        if not out_dir:
            out_dir = str(Path(files[0]).parent / "拆分结果")
            self.var_split_out.set(out_dir)

        mode = core.SPLIT_MODES.get(self.var_split_mode.get(), "single")
        pages_per = 1
        try:
            pages_per = max(1, int(self.var_split_n.get()))
        except ValueError:
            pass

        def task():
            return core.split_many(files, out_dir, mode, pages_per, self.var_split_range.get(), log=self._log)

        self._start_task(self.btn_split, task, lambda result: self._split_done(result, out_dir))

    def _split_done(self, result, out_dir):
        self.last_output_dir = out_dir
        self._log(f"拆分完成：生成 {result['files']} 个文件")
        messagebox.showinfo("完成", f"共生成 {result['files']} 个文件，保存在：\n{out_dir}")

    # ---------------- 加水印 ----------------
    def _build_mark_tab(self):
        pad = {"padx": 8, "pady": 4}
        self.mark_files = FileList(self.tab_mark, " 要加水印的 PDF ", height=5)
        self.mark_files.pack(fill="both", expand=True, **pad)

        row = ttk.Frame(self.tab_mark)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="输出目录").pack(side="left")
        self.var_mark_out = tk.StringVar()
        ttk.Entry(row, textvariable=self.var_mark_out).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="浏览…", command=lambda: self._pick_dir(self.var_mark_out)).pack(side="left")

        row2 = ttk.Frame(self.tab_mark)
        row2.pack(fill="x", **pad)
        ttk.Label(row2, text="水印文字").pack(side="left")
        self.var_mark_text = tk.StringVar(value="第 {page} 页 / 共 {total} 页")
        ttk.Entry(row2, textvariable=self.var_mark_text).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Label(row2, text="可用占位符：{page} {total} {date} {filename}", foreground="#888888").pack(side="left")

        row3 = ttk.Frame(self.tab_mark)
        row3.pack(fill="x", **pad)
        ttk.Label(row3, text="位置").pack(side="left")
        self.var_mark_pos = tk.StringVar(value="右下")
        ttk.Combobox(row3, textvariable=self.var_mark_pos, width=6, state="readonly",
                     values=core.POSITIONS).pack(side="left", padx=4)

        ttk.Label(row3, text="字号").pack(side="left", padx=(10, 2))
        self.var_mark_size = tk.StringVar(value="10")
        ttk.Spinbox(row3, from_=6, to=72, textvariable=self.var_mark_size, width=4).pack(side="left")

        ttk.Label(row3, text="透明度").pack(side="left", padx=(10, 2))
        self.var_mark_opacity = tk.StringVar(value="0.5")
        ttk.Spinbox(row3, from_=0.1, to=1.0, increment=0.1, textvariable=self.var_mark_opacity, width=5).pack(side="left")

        ttk.Label(row3, text="旋转角度").pack(side="left", padx=(10, 2))
        self.var_mark_rotate = tk.StringVar(value="0")
        ttk.Combobox(row3, textvariable=self.var_mark_rotate, width=6, state="readonly",
                     values=["0", "45", "90", "-45", "-90"]).pack(side="left")

        ttk.Label(row3, text="从第几页开始").pack(side="left", padx=(10, 2))
        self.var_mark_start = tk.StringVar(value="1")
        ttk.Spinbox(row3, from_=1, to=9999, textvariable=self.var_mark_start, width=5).pack(side="left")

        row4 = ttk.Frame(self.tab_mark)
        row4.pack(fill="x", **pad)
        self.var_mark_over = tk.BooleanVar(value=True)
        ttk.Checkbutton(row4, text="水印盖在内容上方（取消则放在内容下方）",
                        variable=self.var_mark_over).pack(side="left")
        self.btn_mark = ttk.Button(row4, text="开始加水印", command=self.do_mark)
        self.btn_mark.pack(side="right", padx=8)

    def do_mark(self):
        files = self.mark_files.paths()
        if not files:
            messagebox.showwarning("还没选文件", "请先添加要处理的 PDF。")
            return
        text = self.var_mark_text.get().strip()
        if not text:
            messagebox.showwarning("水印为空", "请填写水印文字，比如“第 {page} 页”。")
            return
        out_dir = self.var_mark_out.get().strip()
        if not out_dir:
            out_dir = str(Path(files[0]).parent / "加水印结果")
            self.var_mark_out.set(out_dir)

        try:
            size = int(float(self.var_mark_size.get()))
            opacity = float(self.var_mark_opacity.get())
            rotation = int(float(self.var_mark_rotate.get()))
            start_page = max(1, int(self.var_mark_start.get()))
        except ValueError:
            messagebox.showwarning("参数有误", "字号、透明度、角度、起始页需要填数字。")
            return

        def task():
            return core.watermark_many(
                files, out_dir, text, position=self.var_mark_pos.get(),
                font_size=size, opacity=opacity, rotation=rotation,
                start_page=start_page, over=self.var_mark_over.get(), log=self._log,
            )

        self._start_task(self.btn_mark, task, lambda result: self._mark_done(result, out_dir))

    def _mark_done(self, result, out_dir):
        self.last_output_dir = out_dir
        self._log(f"加水印完成：{result['files']} 个文件、共 {result['pages']} 页")
        messagebox.showinfo("完成", f"已处理 {result['pages']} 页，保存到：\n{out_dir}")

    # ---------------- 提取文字 ----------------
    def _build_text_tab(self):
        pad = {"padx": 8, "pady": 4}
        self.text_files = FileList(self.tab_text, " 要提取文字的 PDF ", height=6)
        self.text_files.pack(fill="both", expand=True, **pad)

        row = ttk.Frame(self.tab_text)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="输出 txt").pack(side="left")
        self.var_text_out = tk.StringVar(value=str(app_dir() / "提取文字.txt"))
        ttk.Entry(row, textvariable=self.var_text_out).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="另存为…", command=self._pick_text_out).pack(side="left")

        row2 = ttk.Frame(self.tab_text)
        row2.pack(fill="x", **pad)
        self.var_text_marker = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="每页前面加“--- 第 N 页 ---”标记",
                        variable=self.var_text_marker).pack(side="left")
        self.btn_text = ttk.Button(row2, text="开始提取", command=self.do_text)
        self.btn_text.pack(side="right", padx=8)
        ttk.Label(row2, text="扫描件（图片型 PDF）提不出文字，会提示空页数量",
                  foreground="#888888").pack(side="left", padx=10)

    def _pick_text_out(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("文本文件", "*.txt")])
        if path:
            self.var_text_out.set(path)

    def do_text(self):
        files = self.text_files.paths()
        if not files:
            messagebox.showwarning("还没选文件", "请先添加要提取的 PDF。")
            return
        out = self.var_text_out.get().strip()
        if not out:
            messagebox.showwarning("还没设输出", "请先指定输出的 txt 文件。")
            return

        def task():
            return core.extract_text(files, out, self.var_text_marker.get(), log=self._log)

        self._start_task(self.btn_text, task, self._text_done)

    def _text_done(self, result):
        self.last_output_dir = str(Path(result["output"]).parent)
        self._log(f"提取完成：共 {result['pages']} 页，其中空页 {result['empty_pages']} 页")
        tip = ""
        if result["empty_pages"]:
            tip = f"\n注意：有 {result['empty_pages']} 页没有提取到文字，可能是扫描件。"
        messagebox.showinfo("完成", f"已提取 {result['pages']} 页，保存到：\n{result['output']}{tip}")

    # ---------------- 公共 ----------------
    def _pick_dir(self, var: tk.StringVar):
        folder = filedialog.askdirectory()
        if folder:
            var.set(folder)

    def _log(self, message: str):
        """线程安全：所有日志先入队，由主线程刷到界面"""
        self.log_queue.put(str(message))

    def _poll_log(self):
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert(tk.END, message + "\n")
                self.log_text.see(tk.END)
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(150, self._poll_log)

    def _start_task(self, button, func, on_success):
        original_text = button.cget("text")
        button.configure(state="disabled", text="处理中…")

        def worker():
            try:
                result = func()
            except Exception as e:
                self.root.after(0, lambda: self._task_failed(button, str(e), original_text))
            else:
                self.root.after(0, lambda: self._task_ok(button, result, on_success, original_text))

        threading.Thread(target=worker, daemon=True).start()

    def _task_ok(self, button, result, on_success, original_text):
        button.configure(state="normal", text=original_text)
        try:
            on_success(result)
        except Exception as e:
            messagebox.showerror("出错", str(e))

    def _task_failed(self, button, message, original_text):
        button.configure(state="normal", text=original_text)
        self._log(f"处理失败：{message}")
        messagebox.showerror("处理失败", message)

    def open_last_output(self):
        if self.last_output_dir and Path(self.last_output_dir).exists():
            open_folder(self.last_output_dir)
        else:
            messagebox.showinfo("还没有输出", "处理完成一次之后，这里可以直接打开结果文件夹。")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
