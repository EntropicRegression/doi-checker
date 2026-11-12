# -*- coding: utf-8 -*-
"""用 Crossref / doi.org 線上驗證參考文獻是否真實存在、資訊是否正確。"""
import html
import re
import threading
import time
from urllib.parse import quote

import requests

from parser import CJK, compact, fold

API = 'https://api.crossref.org/works'
_session = requests.Session()
_slots = threading.Semaphore(2)
_cache = {}
_cache_lock = threading.Lock()


def _get(url, params=None, email=None):
    headers = {'User-Agent': 'RefChecker/1.0 (reference list checking tool)'}
    params = dict(params or {})
    if email and 'crossref.org' in url:
        params['mailto'] = email  # 使用者自願提供時才帶上，可進入 Crossref 較快的 polite pool
    for attempt in range(4):
        with _slots:
            try:
                r = _session.get(url, params=params, headers=headers, timeout=25)
            except requests.RequestException:
                r = None
        if r is not None and r.status_code not in (429, 500, 502, 503, 504):
            return r
        wait = 2.0 * (attempt + 1)
        if r is not None:
            try:
                wait = max(wait, float(r.headers.get('Retry-After', 0)))
            except ValueError:
                pass
        time.sleep(min(wait, 15))
    return None


def _tokens(s):
    return re.findall('[a-z0-9]+|[' + CJK + ']', fold(s))


def _clean_title(t):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', t or ''))).strip()


def title_overlap(title, ref_text):
    """Crossref 標題有多少比例出現在參考文獻文字中（0~1）。"""
    if not title:
        return 0.0
    ct, cr = compact(title), compact(ref_text)
    if ct and ct in cr:
        return 1.0
    tt = _tokens(title)
    if not tt:
        return 0.0
    rt = set(_tokens(ref_text))
    return sum(1 for t in tt if t in rt) / len(tt)


def _years(item):
    ys = set()
    for k in ('issued', 'published', 'published-print', 'published-online', 'created'):
        parts = (item.get(k) or {}).get('date-parts') or []
        if parts and parts[0] and parts[0][0]:
            if k == 'created' and ys:
                continue
            ys.add(str(parts[0][0]))
    return ys


def _summary(item):
    authors = item.get('author') or []
    names = [a.get('family') or a.get('name') or '' for a in authors]
    ys = sorted(_years({k: v for k, v in item.items() if k != 'created'}) or _years(item))
    return {
        'title': _clean_title((item.get('title') or [''])[0]),
        'authors': ', '.join(n for n in names[:6] if n) + (' 等' if len(names) > 6 else ''),
        'first_author': names[0] if names else '',
        'year': '/'.join(ys),
        'years': ys,
        'journal': _clean_title((item.get('container-title') or [''])[0]),
        'doi': item.get('DOI', ''),
        'type': item.get('type', ''),
    }


def _compare(ref, info, issues):
    """比對年份與第一作者。"""
    y = ref.get('year') or ''
    if re.fullmatch(r'\d{4}', y) and info['years'] and y not in info['years']:
        issues.append({'level': 'warn', 'msg': '年份不符：文中寫 %s，Crossref 登記為 %s' % (y, info['year'])})
    fa = info['first_author']
    if fa and compact(fa) and compact(fa) not in compact(ref['text']):
        issues.append({'level': 'warn', 'msg': '第一作者不符：Crossref 登記為 %s' % fa})
    elif fa and ref.get('first_author') and compact(fa) != compact(ref['first_author']) \
            and compact(fa) not in compact(ref['first_author']) \
            and compact(ref['first_author']) not in compact(fa) \
            and not re.search('[' + CJK + ']', ref['first_author']):
        # 作者有出現但不是排第一位
        if compact(ref['text']).find(compact(fa)) > 80:
            issues.append({'level': 'warn', 'msg': '作者順序可能有誤：Crossref 的第一作者是 %s' % fa})


def _doi_exists_elsewhere(doi):
    r = _get('https://doi.org/api/handles/' + quote(doi, safe='/'))
    if r is None:
        return None
    try:
        return r.json().get('responseCode') == 1
    except ValueError:
        return None


def _verify(ref, email):
    issues = []
    text = ref.get('text', '')

    # 1) 有 DOI：直接查
    for n, doi in enumerate(ref.get('doi_candidates') or []):
        r = _get(API + '/' + quote(doi, safe='/'), email=email)
        if r is None:
            return {'status': 'unknown', 'issues': [{'level': 'info', 'msg': '連線失敗，無法驗證'}]}
        if r.status_code == 200:
            info = _summary(r.json().get('message', {}))
            ov = title_overlap(info['title'], text)
            if info['title'] and ov < 0.5:
                issues.append({'level': 'error',
                               'msg': 'DOI 指向另一篇文獻（或標題差異很大）：「%s」' % info['title']})
            elif info['title'] and ov < 0.8:
                issues.append({'level': 'warn', 'msg': '標題與 DOI 登記的略有出入：「%s」' % info['title']})
            if not any(i['level'] == 'error' for i in issues):
                _compare(ref, info, issues)
            if n > 0:
                info['doi'] = doi
            return {'status': _level(issues), 'issues': issues, 'match': info, 'via': 'doi'}
    if ref.get('doi_candidates'):
        doi = ref['doi_candidates'][0]
        exists = _doi_exists_elsewhere(doi)
        if exists:
            return {'status': 'ok', 'via': 'doi',
                    'issues': [{'level': 'info', 'msg': 'DOI 存在，但不是 Crossref 登記的（例如 DataCite），無法比對內容'}]}
        if exists is None:
            return {'status': 'unknown', 'issues': [{'level': 'info', 'msg': '連線失敗，無法驗證 DOI'}]}
        issues.append({'level': 'error', 'msg': 'DOI 不存在：%s' % doi})

    # 2) 沒有 DOI（或 DOI 不存在）：用整筆文字搜尋
    r = _get(API, params={
        'query.bibliographic': text[:500], 'rows': 5,
        'select': 'DOI,title,author,issued,published,published-print,published-online,container-title,type',
    }, email=email)
    if r is None or r.status_code != 200:
        issues.append({'level': 'info', 'msg': '連線失敗，無法搜尋 Crossref'})
        return {'status': _level(issues) if _level(issues) == 'error' else 'unknown', 'issues': issues}
    y = ref.get('year') or ''
    best, best_score = None, 0.0
    for item in r.json().get('message', {}).get('items', []):
        title = _clean_title((item.get('title') or [''])[0])
        if len(_tokens(title)) < 3:
            continue
        ov = title_overlap(title, text)
        if ov < 0.85:
            continue
        info = _summary(item)
        fa = compact(info['first_author'])
        if fa and fa not in compact(text):
            continue  # 標題相同但作者不同，視為不同文獻
        score = ov + (0.5 if y in info['years'] else 0)
        if score > best_score:
            best, best_score = info, score
    if best is not None:
        info = best
        had_doi = bool(ref.get('doi_candidates'))
        if re.fullmatch(r'\d{4}', y) and info['years'] and y not in info['years']:
            issues.append({'level': 'warn',
                           'msg': 'Crossref 有同標題同作者的文獻，但年份是 %s（文中寫 %s）；可能是年份有誤，'
                                  '也可能是不同版本，請確認。DOI：%s' % (info['year'], y, info['doi'])})
        elif had_doi:
            issues.append({'level': 'info', 'msg': '正確的 DOI 可能是 %s' % info['doi']})
        else:
            issues.append({'level': 'info', 'msg': '可補上 DOI：%s' % info['doi']})
        return {'status': _level(issues), 'issues': issues, 'match': info, 'via': 'search'}
    issues.append({'level': 'info',
                   'msg': 'Crossref 查無相符文獻（書籍、網頁、學位論文、中文文獻常查不到；也可能是標題等資訊有誤）'})
    return {'status': 'error' if _level(issues) == 'error' else 'notfound', 'issues': issues}


def _level(issues):
    lv = {i['level'] for i in issues}
    return 'error' if 'error' in lv else 'warn' if 'warn' in lv else 'ok'


def verify_reference(ref, email=None):
    key = (ref.get('text', ''), tuple(ref.get('doi_candidates') or []))
    with _cache_lock:
        if key in _cache:
            return _cache[key]
    try:
        res = _verify(ref, email)
    except Exception as e:  # 單筆失敗不要影響其他筆
        res = {'status': 'unknown', 'issues': [{'level': 'info', 'msg': '驗證時發生錯誤：%s' % e}]}
    if res.get('status') != 'unknown':
        with _cache_lock:
            _cache[key] = res
    return res
