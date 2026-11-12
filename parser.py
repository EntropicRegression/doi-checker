# -*- coding: utf-8 -*-
"""找出參考文獻列表與內文引用，並互相比對。"""
import re
import unicodedata
from difflib import SequenceMatcher

from extractor import SUP_OPEN, SUP_CLOSE

J = '⁠'  # 接合記號：DOI／網址被斷行時，標記「這裡可能是硬接起來的」
CJK = '一-鿿'
YEAR = r'(?:1[6-9]|20)\d{2}'
UP = 'A-ZÀ-ÖØ-ÞŁŚŠŽČĆŻŹĐŐŰİ'
LET = "A-Za-zÀ-ÖØ-öø-ÿĀ-ſ'’\\-"
PART = r'(?:(?:van|von|de|der|den|del|della|di|da|dos|du|la|le|el|al|bin|ibn|ten|ter)\s+){0,3}'
PART_WORDS = 'van von de der den del della di da dos du la le el al bin ibn ten ter'.split()
NAME = PART + '[' + UP + '][' + LET + ']+'
NAMES = NAME + r'(?:,?\s+et\s+al\.?|(?:,\s+' + NAME + r')*,?\s+(?:and|&)\s+' + NAME + r')?'
NAME_RE = re.compile(NAME)
NAMES_RE = re.compile(NAMES)
NARR_RE = re.compile('(' + NAMES + r")(?:'s|’s)?,?\s*$")

MONTHS = {'january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september',
          'october', 'november', 'december', 'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug',
          'sep', 'sept', 'oct', 'nov', 'dec', 'spring', 'summer', 'fall', 'autumn', 'winter'}
STOP = {w.lower() for w in '''
In The A An See Table Tables Figure Figures Fig Since During After Before Until By From Version
Study Experiment Equation Eq Section Chapter Circa As And Of For On At Between Around Year Years
Early Late Mid Copyright Vol No Appendix Model Phase Wave Sample Data Law Act Note Notes However
Although While Whereas Unlike Like Similarly Moreover Furthermore Additionally Recently Later
Earlier Finally First Second Third Thus Therefore Hence Indeed Notably Specifically Interestingly
Importantly Conversely Nevertheless Nonetheless Instead Also Then Here Following According Based
Using Per Both Either Neither When Where But Yet So Because Though If With Without Among Within
Contrary Consistent Compared Building Extending To That This These Those What Which Who Whether
Not Only Even Just Still Once Overall Meanwhile Subsequently Previously Likewise Besides Next
Again Further Elsewhere Revised Updated Accessed Retrieved Published Received Accepted Fiscal FY
Its It Their Our We They He She Many Some Most Several All Other Others Such Released Released
Until Prior Group Groups Total Volume Issue Edition Rev Ed Eds Trans Original Work Reprinted
Online Available Cited Adapted Reviewed Dated Effective Census Survey Report Reports Level Type
Class Grade Round Period Season Step Stage Part Item Case Cases Trial Trials Cohort Day Week Month
'''.split()} | MONTHS

HEADINGS = {'references', 'reference', 'referencelist', 'referencescited', 'bibliography',
            'workscited', 'literaturecited', 'citedliterature', 'referencesandnotes',
            '參考文獻', '参考文献', '參考資料', '参考资料', '引用文獻', '引用文献', '參考書目',
            '参考书目', '文獻參考', '參考文獻列表'}
END_RE = re.compile(
    r'^\s*(?:appendix|appendices|supplementa\w+|supporting information|acknowledg\w+|'
    r'author contributions?|authors[\'’]? contributions?|funding|conflicts? of interest|'
    r'competing interests?|declarations?|data availability|figure captions?|figure legends?|'
    r'list of (?:figures|tables)|附錄|附录|致謝|致谢|謝誌|誌謝|作者簡介|附件)\b', re.I)

DOI_RE = re.compile(r'\b(10\.\d{4,9}/[^\s"<>]+)', re.I)


def fold(s):
    """去重音、轉小寫。"""
    s = unicodedata.normalize('NFKD', s or '')
    return ''.join(c for c in s if not unicodedata.combining(c)).casefold()


def name_tokens(s):
    return re.findall('[a-z]+|[' + CJK + ']+', fold(s))


def compact(s):
    return re.sub(r'[^a-z0-9' + CJK + ']', '', fold(s))


def is_cjk(s):
    return bool(re.search('[' + CJK + ']', s or ''))


def name_eq(a, b):
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return False
    if ta == tb or ''.join(ta) == ''.join(tb):
        return True
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(''.join(short)) < 3 and not is_cjk(''.join(short)):
        return False
    n = len(short)
    if any(long_[i:i + n] == short for i in range(len(long_) - n + 1)):
        return True
    if is_cjk(a) and is_cjk(b):
        ca, cb = ''.join(ta), ''.join(tb)
        return ca in cb or cb in ca
    return False


# ------------------------------------------------------------ 接行

def join_lines(parts):
    out = ''
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not out:
            out = p
            continue
        last = out.rsplit(None, 1)[-1]
        url_like = re.search(r'https?://|doi\.org/|^doi:|^10\.\d{4,}/', last, re.I)
        if url_like and (' ' not in p or out[-1] in '-/._'):
            out += J + p
        elif re.search('[' + LET + ']-$', out) and not out.endswith(' -'):
            out += p  # 行尾斷字
        elif re.search('[' + CJK + '，。、；：]$', out) and re.match('[' + CJK + '（《「]', p):
            out += p
        else:
            out += ' ' + p
    return out


# ------------------------------------------------------------ 找參考文獻區段

def find_ref_heading(lines):
    found = None
    for i, ln in enumerate(lines):
        t = ln.text
        if len(t) > 40:
            continue
        t = re.sub(r'^\s*(?:\d+|[IVXivx]+|[一二三四五六七八九十]+|第[一二三四五六七八九十\d]+[章節])[.、．:：]?\s*', '', t)
        t = re.sub(r'[\s:：.]', '', t).lower()
        if t in HEADINGS:
            found = i
    return found


def find_ref_end(lines, start):
    for i in range(start + 3, len(lines)):
        t = lines[i].text
        if len(t) <= 45 and END_RE.match(t) and not re.search(YEAR, t):
            return i
    return len(lines)


# ------------------------------------------------------------ 切分參考文獻

NUM_RE = re.compile(
    r'^\s*(?:\[(\d{1,3})\]|\((\d{1,3})\)|(\d{1,3})\s*[.)、](?!\d)|(\d{1,3})(?=\s+[A-Z' + CJK + r']))\s*(.*)$',
    re.S)


def parse_num(text):
    m = NUM_RE.match(text)
    if not m:
        return None
    n = int(next(g for g in m.groups()[:4] if g))
    return n, m.group(5)


def split_numbered(lines):
    hits = {}
    expected = 1
    for i, ln in enumerate(lines):
        r = parse_num(ln.text)
        if not r:
            continue
        n = r[0]
        if expected == 1:
            ok = n == 1 and i <= 3
        else:
            ok = expected <= n <= expected + 2
        if ok:
            hits[i] = r
            expected = n + 1
    if len(hits) < 3:
        return None
    entries, cur = [], None
    for i, ln in enumerate(lines):
        if i in hits:
            cur = {'number': hits[i][0], 'parts': [hits[i][1]]}
            entries.append(cur)
        elif cur is not None:
            cur['parts'].append(ln.text)
    return entries


AUTHOR_START = re.compile(
    '^(?:'
    '[' + UP + '][' + LET + ']+(?:[ ][' + UP + 'a-z][' + LET + r']+){0,3},\s*(?:[' + UP + r']\.|[' + UP + r'][a-z]+|&)'
    '|[' + UP + '][' + LET + r']+\s+[A-Z]{1,3}[,.]'
    r'|(?:[A-Z]\.\s*){1,4}[' + UP + '][' + LET + ']+'
    '|[' + CJK + r']{2,8}\s*[(、,.]'
    ')')


def looks_like_start(text):
    if AUTHOR_START.match(text):
        return True
    if re.match('[' + UP + CJK + ']', text) and re.match(r'.{2,120}?\((?:' + YEAR + r'|n\.d\.)', text):
        return True
    return False


def looks_complete(text):
    t = text.strip()
    if not re.search(YEAR + r'|n\.d\.|in press', t):
        return False
    return bool(re.search(r'[.)\]\d/。]$|https?://\S+$|doi\S*$', t))


def _split_by_text(lines):
    entries, cur = [], None
    for ln in lines:
        if cur is None or (looks_like_start(ln.text) and looks_complete(join_lines(cur['parts']))):
            cur = {'number': None, 'parts': [ln.text]}
            entries.append(cur)
        else:
            cur['parts'].append(ln.text)
    return entries


def _split_by_indent(lines):
    """利用懸掛縮排（或首行縮排）切分；判斷不出來就回傳 None。"""
    if len(lines) < 4:
        return None
    rel = ['jump']
    for a, b in zip(lines, lines[1:]):
        dx = b.x0 - a.x0
        if a.page != b.page or b.y0 <= a.y0 or abs(dx) > 72:
            rel.append('jump')
        elif dx > 3:
            rel.append('in')
        elif dx < -3:
            rel.append('out')
        else:
            rel.append('same')
    n_in, n_out = rel.count('in'), rel.count('out')
    if n_in < 2 or n_out < 1 or (n_in + n_out) < 0.15 * len(lines):
        return None
    after_out = [l for l, r in zip(lines, rel) if r == 'out']
    after_in = [l for l, r in zip(lines, rel) if r == 'in']
    s_out = sum(looks_like_start(l.text) for l in after_out) / max(1, len(after_out))
    s_in = sum(looks_like_start(l.text) for l in after_in) / max(1, len(after_in))
    if s_out == s_in:
        return None
    start_level = 0 if s_out > s_in else 1  # 0 = 靠左那層是開頭（懸掛縮排）

    entries, cur, level = [], None, start_level
    for ln, r in zip(lines, rel):
        if r == 'in':
            level = 1
        elif r == 'out':
            level = 0
        elif r == 'jump':
            if cur is None:
                level = start_level
            elif looks_like_start(ln.text) and looks_complete(join_lines(cur['parts'])):
                level = start_level
            else:
                level = 1 - start_level
        if cur is None or level == start_level:
            cur = {'number': None, 'parts': [ln.text]}
            entries.append(cur)
        else:
            cur['parts'].append(ln.text)
    return entries


def _quality(entries):
    if not entries:
        return 0.0
    good = sum(1 for e in entries
               if re.search(YEAR + r'|n\.d\.|in press', join_lines(e['parts']))
               and len(join_lines(e['parts'])) > 25)
    return good / len(entries)


def split_references(lines, kind):
    """回傳 (entries, numbered)。"""
    entries = split_numbered(lines)
    if entries:
        return entries, True
    if kind == 'docx':
        entries = []
        for ln in lines:
            if entries and re.match(r'(?:https?://|doi:|10\.\d{4,}/)', ln.text, re.I):
                entries[-1]['parts'].append(ln.text)
            else:
                entries.append({'number': None, 'parts': [ln.text]})
        return entries, False
    by_text = _split_by_text(lines)
    by_indent = _split_by_indent(lines)
    if by_indent and _quality(by_indent) >= max(0.6, _quality(by_text) - 0.05):
        return by_indent, False
    return by_text, False


# ------------------------------------------------------------ 解析單筆參考文獻

def extract_dois(text):
    """回傳 DOI 候選（最可能的排前面）。"""
    def clean(d):
        d = d.rstrip('.,;:')
        while d and d[-1] in ')]}' and d.count('(') < d.count(')') + d.count(']'):
            if d[-1] == ')' and d.count('(') >= d.count(')'):
                break
            d = d[:-1].rstrip('.,;:')
        return d

    cands = []
    m = DOI_RE.search(text.replace(J, ''))
    if m:
        cands.append(clean(m.group(1)))
    m = DOI_RE.search(text.replace(J, ' '))
    if m:
        d = clean(m.group(1))
        if d not in cands:
            cands.append(d)
    return [c for c in cands if len(c) > 8]


def parse_year(text):
    t = re.sub(r'https?://\S+|doi:?\s*10\.\S+|10\.\d{4,9}/\S+', ' ', text.replace(J, ''), flags=re.I)
    m = re.search(r'\(\s*(' + YEAR + r')([a-z])?\s*(?:,[^()]{0,40})?\)', t)
    if m:
        return m.group(1), m.group(2) or '', m.start()
    m = re.search(r'\(\s*n\.\s?d\.\s*\)', t, re.I)
    if m:
        return 'n.d.', '', m.start()
    m = re.search(r'\(\s*(?:in press|forthcoming)\s*\)|印刷中', t, re.I)
    if m:
        return 'in press', '', m.start()
    m = re.search(r'(?<![\w/\-–.])(' + YEAR + r')([a-z])?\s*;', t)
    if m:
        return m.group(1), m.group(2) or '', m.start()
    m = re.search(r'[.,]\s*(' + YEAR + r')([a-z])?\s*[.,]', t)
    if m:
        return m.group(1), m.group(2) or '', m.start()
    ms = list(re.finditer(r'(?<![\w/\-–.:])(' + YEAR + r')([a-z])?(?![\w\-–/])', t))
    if ms:
        m = ms[-1]
        return m.group(1), m.group(2) or '', m.start()
    return '', '', -1


def parse_first_author(text):
    t = text.strip()
    m = re.match('([' + CJK + r'·]{2,4})(?=[\s、,(.:等])', t)
    if m:
        return m.group(1)
    m = re.match('([' + CJK + '][' + CJK + r'\w·]{1,30}?)\s*[(,、.]', t)
    if m:
        return m.group(1)
    m = re.match(r'([^\d,.()\[\]:;]{2,40}?),\s*(?:[' + UP + r']\.|[' + UP + r']\b|[' + UP + r'][a-z]+\b)', t)
    if m and len(m.group(1).split()) <= 4:
        return m.group(1).strip()
    m = re.match(r'((?:[a-z]{2,5}\s){0,2}[' + UP + '][' + LET + r']+)\s+[A-Z]{1,3}(?=[,.]|\s+et al|$)', t)
    if m:
        return m.group(1).strip()
    m = re.match(r'(?:[A-Z]\.[\s\-]?){1,4}(' + NAME + ')', t)
    if m:
        return m.group(1).strip()
    m = re.match(r'(.{2,100}?)\s*(?:\(|\.\s|,\s)', t)
    if m:
        return m.group(1).strip()
    return t[:40]


def parse_reference(idx, entry):
    raw = join_lines(entry['parts'])
    text = raw.replace(J, '')
    year, suffix, ypos = parse_year(raw)
    dois = extract_dois(raw)
    return {
        'id': idx,
        'number': entry.get('number'),
        'text': text,
        'first_author': parse_first_author(text),
        'authors_text': text[:ypos] if ypos > 0 else text[:300],
        'year': year,
        'suffix': suffix,
        'doi': dois[0] if dois else '',
        'doi_candidates': dois,
        'cited': 0,
        'issues': [],
    }


# ------------------------------------------------------------ 內文

def build_body(lines, kind):
    """把內文接成一個字串，並記錄每個位置對應的頁碼。"""
    out, page_map = '', []
    for ln in lines:
        t = ln.text
        if not t:
            continue
        if not out:
            sep = ''
        elif kind == 'docx':
            sep = '\n'
        elif re.search('[' + LET + ']-$', out) and not out.endswith(' -'):
            sep = ''
        elif re.search('[' + CJK + '，。、；：]$', out) and re.match('[' + CJK + '（《「]', t):
            sep = ''
        else:
            sep = ' '
        out += sep
        page_map.append((len(out), ln.page))
        out += t
    return out, page_map


def page_at(page_map, pos):
    lo, hi = 0, len(page_map) - 1
    ans = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if page_map[mid][0] <= pos:
            ans = page_map[mid][1]
            lo = mid + 1
        else:
            hi = mid - 1
    return ans


def snippet(body, start, end, width=45):
    a, b = max(0, start - width), min(len(body), end + width)
    s = body[a:b].replace('\n', ' ')
    s = s.replace(SUP_OPEN, '^').replace(SUP_CLOSE, '')
    return ('…' if a > 0 else '') + s + ('…' if b < len(body) else '')


def _expand_numbers(s):
    nums = []
    for piece in re.split(r'[,;]', s):
        piece = piece.strip()
        m = re.fullmatch(r'(\d{1,3})\s*[-–—]\s*(\d{1,3})', piece)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a < b and b - a <= 60:
                nums.extend(range(a, b + 1))
            else:
                nums.extend([a, b])
        elif piece.isdigit():
            nums.append(int(piece))
    return nums


def find_numeric(body, allow_paren):
    """回傳 (來源, [(編號, start, end)])。"""
    def collect(pattern):
        res = []
        for m in re.finditer(pattern, body):
            nums = _expand_numbers(m.group(1))
            if not nums or 0 in nums:
                continue
            res.extend((n, m.start(), m.end()) for n in nums)
        return res

    br = collect(r'\[\s*(\d{1,3}(?:\s*[-–—,;]\s*\d{1,3})*)\s*\]')
    sup = collect(re.escape(SUP_OPEN) + r'\s*(\d{1,3}(?:\s*[-–—,]\s*\d{1,3})*)\s*,?' + re.escape(SUP_CLOSE))
    if br and len(br) >= len(sup):
        return 'bracket', br
    if sup:
        return 'superscript', sup
    if allow_paren:
        pr = collect(r'\(\s*(\d{1,3}(?:\s*[-–—,]\s*\d{1,3})*)\s*\)')
        if pr:
            return 'paren', pr
    return 'bracket', br


PREFIX_RE = re.compile(
    r'^(?:see(?: also)?|e\.g\.,?|i\.e\.,?|cf\.?|also|but see|as cited in|cited in|adapted from|'
    r'reviewed (?:in|by)|for (?:a |an )?(?:review|example|overview|details|discussion)[^,]{0,30},?(?: see)?|'
    r'and|參見|引自|見|如|例如|轉引自)[\s,:]+', re.I)
YEAR_TOK = re.compile(r'(?<![\w./\-–])(?:(' + YEAR + r')([a-z])?(?![\w/])|(n\.d\.)|(in press))')


def parse_author_text(auth, had_comma):
    a = re.sub(r'\s*\[[^\]]*\]\s*$', '', auth.strip()).strip(' ,')
    if not a or len(a) > 90:
        return None
    if re.match('[' + CJK + ']', a):
        etal = bool(re.search('等人?$', a))
        a2 = re.sub('等人?$', '', a).strip()
        names = [x.strip() for x in re.split(r'[、,&]|\s+and\s+|(?<=[' + CJK + '])[與和及](?=[' + CJK + ']{2})', a2) if x.strip()]
        if names and all(re.fullmatch('[' + CJK + r'·A-Za-z.\s]{2,20}', x) for x in names) and len(names[0]) <= 12:
            return {'names': names, 'etal': etal}
        return None
    if NAMES_RE.fullmatch(a):
        names = [re.sub(r"['’]s$", '', n) for n in NAME_RE.findall(a)]
        first = names[0].lower()
        if first in MONTHS:
            if not had_comma:
                return None
        elif first in STOP:
            return None
        return {'names': names, 'etal': bool(re.search(r'\bet\s+al', a))}
    # 姓氏忘了大寫，例如 (choi, 2020)：仍視為引用，但標記出來
    if had_comma:
        keep = {'et', 'al', 'al.', 'and', '&'} | set(PART_WORDS)
        a2 = ' '.join(w if w in keep else w[:1].upper() + w[1:] for w in a.split(' '))
        if a2 != a and NAMES_RE.fullmatch(a2):
            names = [re.sub(r"['’]s$", '', a[m.start():m.end()]) for m in NAME_RE.finditer(a2)]
            if names[0].lower() not in STOP:
                return {'names': names, 'etal': bool(re.search(r'\bet\s+al', a)), 'lower': True}
    # 機構作者，例如 World Health Organization
    if re.fullmatch('[' + UP + r"][A-Za-zÀ-ÿ&.,'’\- ]{2,80}", a) and len(a.split()) <= 8:
        if a.split()[0].lower().strip('.,') in STOP:
            return None
        return {'names': [a], 'etal': False}
    return None


def narrative_author(pre):
    pre = pre.rstrip()
    m = NARR_RE.search(pre)
    if m:
        names = [re.sub(r"['’]s$", '', n) for n in NAME_RE.findall(m.group(1))]
        while names and names[0].lower() in STOP:
            names.pop(0)
        if names:
            return {'names': names, 'etal': bool(re.search(r'\bet\s+al', m.group(1)))}
    m = re.search('([' + CJK + '、·]{2,16})$', pre)
    if m:
        ctx = m.group(1)
        return {'names': [], 'etal': bool(re.search('等人?$', ctx)), 'cjk_ctx': ctx}
    return None


def find_author_year(body):
    cites = []
    for m in re.finditer(r'\(([^()]{1,400})\)', body):
        content = m.group(1)
        if not YEAR_TOK.search(content):
            continue
        prev = None
        for pi, part in enumerate(content.split(';')):
            p = part.strip()
            for _ in range(3):
                p2 = PREFIX_RE.sub('', p)
                if p2 == p:
                    break
                p = p2
            ym = YEAR_TOK.search(p)
            if not ym:
                continue
            before = p[:ym.start()]
            auth = before.strip().rstrip(',').strip()
            narrative = False
            if not auth:
                if pi == 0:
                    info = narrative_author(body[max(0, m.start() - 120):m.start()])
                    narrative = True
                else:
                    info = prev
            else:
                info = parse_author_text(auth, ',' in before[len(before.rstrip(' ,')):] or before.rstrip().endswith(','))
            if not info:
                continue
            prev = info
            years = []
            if ym.group(1):
                years.append((ym.group(1), ym.group(2) or ''))
            elif ym.group(3):
                years.append(('n.d.', ''))
            else:
                years.append(('in press', ''))
            rest = p[ym.end():]
            while True:
                m2 = re.match(r'\s*(?:,\s*(?:and|&)?|and|&)\s*(' + YEAR + r')([a-z])?(?!\w)', rest)
                if m2:
                    years.append((m2.group(1), m2.group(2) or ''))
                    rest = rest[m2.end():]
                    continue
                m3 = re.match(r'\s*,\s*([a-z])(?![\w.])', rest)
                if m3 and years[-1][1]:
                    years.append((years[-1][0], m3.group(1)))
                    rest = rest[m3.end():]
                    continue
                break
            for y, suf in years:
                cites.append({
                    'names': list(info['names']), 'etal': info['etal'],
                    'cjk_ctx': info.get('cjk_ctx'), 'narrative': narrative,
                    'lower': info.get('lower', False),
                    'year': y, 'suffix': suf, 'start': m.start(), 'end': m.end(),
                })
    return cites


# ------------------------------------------------------------ 比對

def cite_label(c):
    if c.get('cjk_ctx') and not c['names']:
        who = '…' + c['cjk_ctx'][-6:]
    else:
        names = c['names']
        cjk = is_cjk(names[0])
        if c['etal']:
            who = names[0] + ('等' if cjk else ' et al.')
        elif len(names) == 1:
            who = names[0]
        elif cjk:
            who = '、'.join(names)
        elif len(names) == 2:
            who = names[0] + ' & ' + names[1]
        else:
            who = ', '.join(names[:-1]) + ', & ' + names[-1]
    return '%s (%s%s)' % (who, c['year'], c['suffix'])


def ref_label(r):
    if r.get('number'):
        return '[%d] %s' % (r['number'], r['text'][:60])
    return '%s (%s%s)' % (r['first_author'], r['year'] or '無年份', r['suffix'])


def _acronym_match(name, ref):
    if not re.fullmatch(r'[A-Z]{2,8}', name):
        return False
    words = [w for w in re.findall(r'[A-Za-z]+', ref['first_author'])
             if w.lower() not in ('of', 'the', 'and', 'for', 'on', 'in')]
    if ''.join(w[0] for w in words).upper() == name:
        return True
    return bool(re.search(r'[\[(]' + name + r'[\])]', ref['text'][:200]))


def match_citation(c, refs):
    """回傳 (matched_refs, issues)；issues 為 [(level, msg)]。"""
    same_year = [r for r in refs if r['year'] == c['year']]

    def by_name(pool, name):
        return [r for r in pool if name_eq(name, r['first_author']) or _acronym_match(name, r)]

    matches = []
    if c.get('cjk_ctx') and not c['names']:
        ctx = c['cjk_ctx']
        matches = [r for r in same_year if is_cjk(r['first_author']) and r['first_author'] in ctx]
        if matches:
            best = max(matches, key=lambda r: len(r['first_author']))
            c['names'] = [best['first_author']]
            matches = [r for r in matches if r['first_author'] == best['first_author']]
    else:
        tries = [0]
        if c['narrative'] and len(c['names']) >= 3:
            tries.append(1)  # 例如「However, Smith and Jones (2020)」誤把句首詞當成作者
        for i in tries:
            matches = by_name(same_year, c['names'][i])
            if matches:
                if i:
                    c['names'] = c['names'][i:]
                break

    issues = []
    if matches:
        if c['suffix']:
            exact = [r for r in matches if r['suffix'] == c['suffix']]
            if exact:
                matches = exact
            else:
                issues.append(('warn', '內文年份帶有字母「%s」，但參考文獻中沒有對應的 %s%s'
                               % (c['suffix'], c['year'], c['suffix'])))
        if len(matches) > 1 and len(c['names']) >= 2:
            narrowed = [r for r in matches
                        if all(compact(n) in compact(r['authors_text']) for n in c['names'][1:])]
            if narrowed:
                matches = narrowed
        if len(matches) > 1:
            issues.append(('warn', '對應到 %d 筆同作者同年份的參考文獻，無法分辨（需要加 a、b 區分）'
                           % len(matches)))
        elif len(c['names']) >= 2 and not c.get('cjk_ctx'):
            r = matches[0]
            missing = [n for n in c['names'][1:] if compact(n) not in compact(r['text'][:max(300, len(r['authors_text']))])]
            if missing:
                issues.append(('warn', '作者「%s」不在對應參考文獻的作者中' % '、'.join(missing)))
        return matches, issues

    # 找不到 → 看看是不是年份或拼字寫錯
    if c['names']:
        first = c['names'][0]
        diff_year = by_name(refs, first)
        if diff_year:
            issues.append(('error', '年份不符：參考文獻列表中是 %s'
                           % '；'.join(ref_label(r) for r in diff_year[:3])))
            return [], issues
        fa = compact(first)
        close = [r for r in same_year
                 if SequenceMatcher(None, fa, compact(r['first_author'])).ratio() >= 0.8]
        if close:
            issues.append(('error', '作者拼字可能有誤：參考文獻列表中是 %s'
                           % '；'.join(ref_label(r) for r in close[:3])))
            return [], issues
    issues.append(('error', '參考文獻列表中找不到這筆引用'))
    return [], issues


# ------------------------------------------------------------ 主流程

def _status(issues):
    levels = {i['level'] for i in issues}
    return 'error' if 'error' in levels else 'warn' if 'warn' in levels else 'ok'


def analyze(lines, kind):
    notes = []
    h = find_ref_heading(lines)
    if h is None:
        return {'error': '找不到參考文獻區段。請確認文件中有獨立一行的標題，例如「References」、'
                         '「Bibliography」或「參考文獻」。'}
    end = find_ref_end(lines, h + 1)
    ref_lines = [l for l in lines[h + 1:end] if l.text.strip()]
    body_lines = lines[:h] + lines[end:]
    if not ref_lines:
        return {'error': '找到了參考文獻標題，但下面沒有內容。'}

    entries, numbered = split_references(ref_lines, kind)
    refs = []
    for e in entries:
        text = join_lines(e['parts'])
        if len(text) < 12 or not re.search('[A-Za-z' + CJK + ']', text):
            if refs:
                refs[-1]['text'] += ' ' + text.replace(J, '')
            continue
        refs.append(parse_reference(len(refs) + 1, e))
    if not refs:
        return {'error': '參考文獻區段無法切分成個別條目。'}

    body, page_map = build_body(body_lines, kind)
    num_src, num_cites = find_numeric(body, allow_paren=numbered)
    clean_body = body
    ay_cites = find_author_year(re.sub(re.escape(SUP_OPEN) + '[^' + SUP_CLOSE + ']*' + re.escape(SUP_CLOSE),
                                       lambda m: ' ' * len(m.group(0)), clean_body))

    if numbered:
        style = 'numeric' if (num_cites or not ay_cites) else 'author-year'
    elif len(num_cites) >= 3 and len(num_cites) > 2 * len(ay_cites):
        style = 'numeric'
        for i, r in enumerate(refs, 1):
            r['number'] = i
        notes.append('參考文獻列表本身沒有編號（可能是 Word 自動編號），已依出現順序編為 1、2、3…')
    else:
        style = 'author-year'

    citations = []
    if style == 'numeric':
        if num_src == 'superscript':
            notes.append('內文引用是以上標數字辨識的，註腳編號或數學上標可能被誤判，請留意。')
        elif num_src == 'paren':
            notes.append('內文引用是以圓括號數字 (1) 辨識的，條列編號可能被誤判，請留意。')
        by_num = {r['number']: r for r in refs if r['number']}
        groups = {}
        for n, s, e in num_cites:
            g = groups.setdefault(n, {'count': 0, 'pages': set(), 'first': (s, e)})
            g['count'] += 1
            pg = page_at(page_map, s)
            if pg:
                g['pages'].add(pg)
        for n in sorted(groups):
            g = groups[n]
            r = by_num.get(n)
            issues = []
            if r:
                r['cited'] += g['count']
            else:
                issues.append({'level': 'error', 'msg': '參考文獻列表中沒有第 %d 筆（列表共 %d 筆）' % (n, len(refs))})
            citations.append({
                'text': '[%d]' % n, 'count': g['count'], 'pages': sorted(g['pages']),
                'matched': [r['id']] if r else [], 'matched_label': r['text'][:90] if r else '',
                'context': snippet(body, *g['first']), 'issues': issues, 'status': _status(issues),
            })
        if not num_cites:
            notes.append('內文中找不到 [1] 這類數字引用。若引用是上標數字且 PDF 沒有保留上標格式，就無法辨識。')
    else:
        groups = {}
        order = []
        for c in ay_cites:
            matched, issues = match_citation(c, refs)
            if c.get('lower'):
                issues.append(('warn', '作者姓氏沒有大寫'))
            label = cite_label(c)
            key = fold(label) + ('|lower' if c.get('lower') else '')
            if key not in groups:
                groups[key] = {'text': label, 'count': 0, 'pages': set(), 'matched': matched,
                               'issues': issues, 'first': (c['start'], c['end'])}
                order.append(key)
            g = groups[key]
            g['count'] += 1
            pg = page_at(page_map, c['start'])
            if pg:
                g['pages'].add(pg)
            for r in matched:
                r['cited'] += 1
        for key in order:
            g = groups[key]
            issues = [{'level': lv, 'msg': msg} for lv, msg in g['issues']]
            citations.append({
                'text': g['text'], 'count': g['count'], 'pages': sorted(g['pages']),
                'matched': [r['id'] for r in g['matched']],
                'matched_label': '；'.join(r['text'][:90] for r in g['matched']),
                'context': snippet(body, *g['first']), 'issues': issues, 'status': _status(issues),
            })
        if not ay_cites:
            notes.append('內文中找不到 (作者, 年份) 形式的引用。')

    # 參考文獻本身的檢查
    for r in refs:
        if not r['year']:
            r['issues'].append({'level': 'warn', 'msg': '找不到出版年份'})
        if r['cited'] == 0:
            r['issues'].append({'level': 'warn', 'msg': '內文中沒有引用這筆文獻'})
    seen = {}
    for r in refs:
        keys = []
        if r['doi']:
            keys.append('doi:' + r['doi'].lower())
        keys.append('txt:' + compact(r['text'])[:120])
        for k in keys:
            if k in seen and seen[k] is not r:
                what = 'DOI 與第 %d 筆相同（其中一筆可能貼錯）' if k.startswith('doi:') else '與第 %d 筆疑似重複'
                r['issues'].append({'level': 'warn', 'msg': what % seen[k]['id']})
                break
        for k in keys:
            seen.setdefault(k, r)
    if style == 'author-year':
        groups = {}
        for r in refs:
            if r['year']:
                groups.setdefault((compact(r['first_author']), r['year'], r['suffix']), []).append(r)
        for (_, _, suf), rs in groups.items():
            if len(rs) > 1 and not suf:
                same_authors = len({compact(x['authors_text']) for x in rs}) == 1
                if same_authors:
                    for x in rs:
                        x['issues'].append({'level': 'warn', 'msg': '有 %d 筆作者與年份完全相同的文獻，應加上 a、b 區分' % len(rs)})

    for r in refs:
        r['status'] = _status(r['issues'])
        del r['authors_text']

    return {
        'style': style,
        'kind': kind,
        'references': refs,
        'citations': citations,
        'notes': notes,
    }
