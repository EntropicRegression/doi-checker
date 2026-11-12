# -*- coding: utf-8 -*-
"""引用與參考文獻檢查工具 — 本機網頁介面。執行：python app.py"""
import io
import os
import re
import sys
import tempfile
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, request, send_file, send_from_directory

from extractor import ExtractError, extract
from parser import analyze
from verifier import verify_reference

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get('PORT', '8765'))

app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024
_pool = ThreadPoolExecutor(max_workers=4)


@app.get('/')
def index():
    return send_from_directory(os.path.join(HERE, 'static'), 'index.html')


@app.post('/api/analyze')
def api_analyze():
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify(error='沒有收到檔案。'), 400
    ext = os.path.splitext(f.filename)[1].lower()
    fd, tmp = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    try:
        f.save(tmp)
        lines, kind = extract(tmp, f.filename)
        result = analyze(lines, kind)
    except ExtractError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        app.logger.exception('analyze failed')
        return jsonify(error='分析時發生錯誤：%s' % e), 500
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if result.get('error'):
        return jsonify(error=result['error']), 422
    result['file'] = f.filename
    return jsonify(result)


@app.post('/api/verify')
def api_verify():
    data = request.get_json(force=True, silent=True) or {}
    refs = data.get('refs') or []
    email = (data.get('email') or '').strip() or None
    if email and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
        email = None
    results = list(_pool.map(lambda r: verify_reference(r, email), refs))
    return jsonify(results=[dict(res, id=r.get('id')) for r, res in zip(refs, results)])


STATUS_TEXT = {'ok': '正常', 'warn': '需留意', 'error': '有問題', 'notfound': '查無資料',
               'unknown': '無法驗證', '': '未驗證'}


@app.post('/api/export')
def api_export():
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    data = request.get_json(force=True, silent=True) or {}
    refs, cites = data.get('references') or [], data.get('citations') or []
    fills = {'ok': 'E2F0D9', 'warn': 'FFF2CC', 'error': 'F8CBAD', 'notfound': 'EDEDED', 'unknown': 'EDEDED'}

    def msgs(issues):
        return '\n'.join(i['msg'] for i in issues or [])

    def worst(*statuses):
        for s in ('error', 'warn'):
            if s in statuses:
                return s
        return 'ok'

    wb = Workbook()
    ws = wb.active
    ws.title = '參考文獻'
    ws.append(['編號', '參考文獻', '第一作者', '年份', 'DOI', '內文引用次數', '引用比對', '比對說明',
               '線上驗證', '驗證說明', 'Crossref 標題', 'Crossref 作者', 'Crossref 年份', 'Crossref 期刊', 'Crossref DOI'])
    for r in refs:
        v = r.get('verify') or {}
        m = v.get('match') or {}
        ws.append([r.get('number') or r.get('id'), r.get('text'), r.get('first_author'),
                   (r.get('year') or '') + (r.get('suffix') or ''), r.get('doi'), r.get('cited'),
                   STATUS_TEXT.get(r.get('status'), ''), msgs(r.get('issues')),
                   STATUS_TEXT.get(v.get('status', ''), ''), msgs(v.get('issues')),
                   m.get('title'), m.get('authors'), m.get('year'), m.get('journal'), m.get('doi')])
        fill = fills.get(worst(r.get('status'), v.get('status')))
        if fill and fill != fills['ok']:
            for c in ws[ws.max_row]:
                c.fill = PatternFill('solid', fgColor=fill)
    widths = [6, 70, 16, 8, 26, 10, 10, 36, 10, 46, 46, 28, 10, 28, 26]

    ws2 = wb.create_sheet('內文引用')
    ws2.append(['內文引用', '出現次數', '頁碼', '對應的參考文獻', '狀態', '說明', '上下文'])
    for c in cites:
        ws2.append([c.get('text'), c.get('count'), ', '.join(str(p) for p in c.get('pages') or []),
                    c.get('matched_label'), STATUS_TEXT.get(c.get('status'), ''), msgs(c.get('issues')),
                    c.get('context')])
        fill = fills.get(c.get('status'))
        if fill and c.get('status') != 'ok':
            for cell in ws2[ws2.max_row]:
                cell.fill = PatternFill('solid', fgColor=fill)
    widths2 = [30, 8, 14, 70, 10, 50, 70]

    for sheet, ws_widths in ((ws, widths), (ws2, widths2)):
        for i, w in enumerate(ws_widths, 1):
            sheet.column_dimensions[sheet.cell(row=1, column=i).column_letter].width = w
        for c in sheet[1]:
            c.font = Font(bold=True)
            c.fill = PatternFill('solid', fgColor='D9E1F2')
        for row in sheet.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical='top')
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    base = os.path.splitext(os.path.basename(data.get('file') or 'result'))[0]
    return send_file(buf, as_attachment=True, download_name='%s_引用檢查.xlsx' % base,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


if __name__ == '__main__':
    url = 'http://127.0.0.1:%d' % PORT
    print('引用檢查工具已啟動：%s  （關閉這個視窗即可結束）' % url)
    if not os.environ.get('NO_BROWSER') and '--no-browser' not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host='127.0.0.1', port=PORT, debug=False, threaded=True)
