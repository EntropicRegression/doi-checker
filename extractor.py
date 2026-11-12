# -*- coding: utf-8 -*-
"""把 PDF / DOCX 轉成一行一行的文字（保留縮排位置與頁碼，供後續切分參考文獻用）。"""
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass

# 上標數字（例如期刊常見的上標引用）會被包成 ⟦^1,2⟧ 這種記號
SUP_OPEN, SUP_CLOSE = '⟦^', '⟧'
_SUP_TEXT = re.compile(r'[\d,\-–\s]+')


class ExtractError(Exception):
    pass


@dataclass
class Line:
    text: str
    x0: float = 0.0
    y0: float = 0.0
    page: int = 0  # 1 起算；0 表示未知（DOCX）


def _norm(s):
    s = unicodedata.normalize('NFKC', s)
    s = s.replace('­', '')
    s = re.sub(r'[​‌‍﻿]', '', s)
    s = re.sub(r'[ \t ]+', ' ', s)
    return s.strip()


def _merge_sup(s):
    return re.sub(re.escape(SUP_CLOSE) + r'\s*' + re.escape(SUP_OPEN), '', s)


# ---------------------------------------------------------------- PDF

def extract_pdf(path):
    import pymupdf as fitz

    try:
        doc = fitz.open(path)
    except Exception as e:
        raise ExtractError('無法開啟 PDF：%s' % e)
    if doc.needs_pass:
        raise ExtractError('這個 PDF 有密碼保護，請先解除密碼。')

    pages = []  # 每頁: (height, [[text, x0, y0, x1], ...])
    for page in doc:
        height = page.rect.height
        d = page.get_text('dict', flags=fitz.TEXT_PRESERVE_WHITESPACE)
        raw = []
        for b in d.get('blocks', []):
            if b.get('type') != 0:
                continue
            for l in b.get('lines', []):
                if abs(l.get('dir', (1, 0))[1]) > 0.3:
                    continue  # 直排／旋轉文字
                spans = [s for s in l.get('spans', []) if s.get('text')]
                if not spans:
                    continue
                big = max(spans, key=lambda s: s['size'])
                parts = []
                for s in spans:
                    t = s['text']
                    is_sup = bool(s['flags'] & 1) or (
                        s['size'] <= 0.8 * big['size']
                        and s['origin'][1] < big['origin'][1] - 1.0)
                    if is_sup and t.strip() and _SUP_TEXT.fullmatch(t):
                        t = SUP_OPEN + t.strip() + SUP_CLOSE
                    parts.append(t)
                text = _norm(''.join(parts))
                if not text:
                    continue
                x0, y0, x1, _ = l['bbox']
                raw.append([text, x0, y0, x1])
        pages.append((height, raw))
    doc.close()

    total_chars = sum(len(r[0]) for _, raw in pages for r in raw)
    if total_chars < 200:
        raise ExtractError('這個 PDF 幾乎沒有可擷取的文字（可能是掃描影像檔），請先做 OCR 再上傳。')

    # 行號（投稿稿件常見）：大量純數字行 → 全部丟掉
    all_lines = sum(len(raw) for _, raw in pages)
    digit_lines = sum(1 for _, raw in pages for r in raw if re.fullmatch(r'\d{1,4}', r[0]))
    drop_digits = digit_lines > 5 * len(pages) and digit_lines > 0.2 * all_lines

    # 頁首頁尾：在頁面上下邊緣重複出現的文字
    def zone(height, y):
        return y < height * 0.07 or y > height * 0.93

    seen = {}
    for pno, (height, raw) in enumerate(pages):
        for r in raw:
            if zone(height, r[2]):
                seen.setdefault(re.sub(r'\d+', '#', r[0]), set()).add(pno)
    limit = max(3, 0.3 * len(pages))
    repeated = {k for k, v in seen.items() if len(v) >= limit}

    out = []
    for pno, (height, raw) in enumerate(pages, 1):
        kept = []
        for text, x0, y0, x1 in raw:
            pure_digit = re.fullmatch(r'\d{1,4}', text)
            if pure_digit and (drop_digits or zone(height, y0)):
                continue
            if zone(height, y0) and re.sub(r'\d+', '#', text) in repeated:
                continue
            kept.append([text, x0, y0, x1])
        # 同一水平線上被拆開的片段（例如「[12]」和後面的文字）合併回一行
        merged = []
        for text, x0, y0, x1 in kept:
            if merged:
                p = merged[-1]
                gap = x0 - p[3]
                if abs(y0 - p[2]) < 3 and gap > -2 and (gap < 15 or len(p[0]) <= 6):
                    p[0] = p[0] + (' ' if gap > 1 else '') + text
                    p[3] = x1
                    continue
            merged.append([text, x0, y0, x1])
        for text, x0, y0, x1 in merged:
            out.append(Line(_merge_sup(text), x0, y0, pno))
    return out


# ---------------------------------------------------------------- DOCX

_W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def _run_text(r):
    sup = False
    rpr = r.find(_W + 'rPr')
    if rpr is not None:
        va = rpr.find(_W + 'vertAlign')
        if va is not None and va.get(_W + 'val') == 'superscript':
            sup = True
    parts = []
    for ch in r:
        tag = ch.tag
        if tag == _W + 't':
            parts.append(ch.text or '')
        elif tag == _W + 'tab':
            parts.append(' ')
        elif tag in (_W + 'br', _W + 'cr'):
            parts.append('\n')
        elif tag == _W + 'noBreakHyphen':
            parts.append('-')
    t = ''.join(parts)
    if sup and t.strip() and _SUP_TEXT.fullmatch(t):
        t = SUP_OPEN + t.strip() + SUP_CLOSE
    return t


def _para_text(p):
    out = []

    def walk(el):
        for ch in el:
            tag = ch.tag
            if tag == _W + 'p':
                continue  # 巢狀段落（文字方塊）另外處理
            if tag == _W + 'r':
                out.append(_run_text(ch))
            elif tag in (_W + 'del', _W + 'moveFrom'):
                continue  # 追蹤修訂中被刪除的文字
            else:
                walk(ch)

    walk(p)
    return ''.join(out)


def _docx_part_lines(zf, name):
    try:
        data = zf.read(name)
    except KeyError:
        return []
    root = ET.fromstring(data)
    lines = []
    for p in root.iter(_W + 'p'):
        for piece in _para_text(p).split('\n'):
            t = _merge_sup(_norm(piece))
            if t:
                lines.append(Line(t))
    return lines


def extract_docx(path):
    try:
        zf = zipfile.ZipFile(path)
    except Exception:
        raise ExtractError('無法開啟 DOCX（檔案可能損毀，或其實是舊版 .doc 格式，請另存為 .docx）。')
    with zf:
        if 'word/document.xml' not in zf.namelist():
            raise ExtractError('這不是有效的 Word (.docx) 檔案。')
        notes = _docx_part_lines(zf, 'word/footnotes.xml') + _docx_part_lines(zf, 'word/endnotes.xml')
        body = _docx_part_lines(zf, 'word/document.xml')
    # 註腳放在最前面：裡面的引用仍會被找到，又不會混進文末的參考文獻列表
    return notes + body


def extract(path, filename=None):
    name = (filename or path).lower()
    if name.endswith('.pdf'):
        return extract_pdf(path), 'pdf'
    if name.endswith('.docx'):
        return extract_docx(path), 'docx'
    if name.endswith('.doc'):
        raise ExtractError('不支援舊版 .doc 格式，請在 Word 中另存為 .docx 後再上傳。')
    raise ExtractError('只支援 PDF 與 DOCX 檔案。')
