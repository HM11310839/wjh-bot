# -*- coding: utf-8 -*-
"""
UP366 任务管理 + 题目提取工具 v5
=================================
配置文件:   <程序目录>/up366_config.json
解压信息:   <程序目录>/up366_index.json
答案存储:   <程序目录>/up366_answers.json
解密输出:   <配置 decode_root>/<bookId>/<job_hash>/

依赖: pip install pycryptodome

v5 变更：
    · 恢复 os.walk 顺序（page*.js 优先，questionData.js 补充）
    · 记录所有题目答案（type=9 中文翻译等也保留）
    · 简洁模式显示全部题目，type != 1 不显示答案列内容
    · 完整模式显示全部题目、题干、选项、答案
    · 新增「📋 复制答案」按钮
    · 保留：红色删除所有信息按钮 / 双击跳转 / Del 键删除
"""

import os
import re
import sys
import csv
import json
import base64
import shutil
import threading
import queue
import traceback
from pathlib import Path
from datetime import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

# ------------------------------------------------------------------ 常量
APP_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = APP_DIR / 'up366_config.json'
INDEX_FILE = APP_DIR / 'up366_index.json'
ANSWERS_FILE = APP_DIR / 'up366_answers.json'
DEFAULT_KEY = 'dv8UqXZbadxSEllGtpOlKQ=='
EXPECTED_MAGIC = bytes.fromhex('125b8131626869121ebf8d1b')
ENC_SUFFIX = '.u3enc'
MAGIC_LEN, MD5_LEN, IV_LEN = 12, 32, 16
HEADER_LEN = MAGIC_LEN + MD5_LEN + IV_LEN


# ================================================================== 配置
def load_config():
    default = {
        'source_root': r'D:\Up366StudentFiles',
        'decode_root': str(APP_DIR / 'decode'),
        'key': DEFAULT_KEY,
        'strict_magic': True,
    }
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
            for k, v in default.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    save_config(default)
    return default


def save_config(cfg):
    CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')


def load_json(path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            pass
    return default if default is not None else {}


def save_json(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


# ================================================================== 解密
def load_key(s):
    s = (s or '').strip()
    if not s:
        raise ValueError('密钥为空')
    try:
        k = base64.b64decode(s, validate=True)
        if len(k) == 16:
            return k
    except Exception:
        pass
    if len(s) == 16:
        return s.encode('latin-1')
    raise ValueError('密钥无效')


def decrypt_blob(data, key, strict_magic=True):
    if len(data) < HEADER_LEN:
        raise ValueError(f'文件过短({len(data)})')
    if strict_magic and data[:MAGIC_LEN] != EXPECTED_MAGIC:
        raise ValueError(f'魔数不符: {data[:MAGIC_LEN].hex()}')
    iv = data[MAGIC_LEN + MD5_LEN:HEADER_LEN]
    ct = data[HEADER_LEN:]
    if not ct or len(ct) % 16 != 0:
        raise ValueError('密文长度非法')
    pt = AES.new(key, AES.MODE_CBC, iv).decrypt(ct)
    try:
        pt = unpad(pt, AES.block_size)
    except ValueError:
        pass
    return pt


# ================================================================== app.log 解析
TS_RE = re.compile(r'^\[([^\]]+)\]')
RE_OPEN_CHAPTER = re.compile(
    r'打开章节:.*?pageId:\s*(\w+),\s*url:\s*local://flipbooks/([^/\\]+)/([^/\\]+)/')
RE_PRICHECK = re.compile(
    r'priCheckFiles start,\s*path:\s*(.+?)\s*,\s*ignoreNotExistFileList')


def parse_app_log(path):
    jobs, books, pending = {}, {}, []
    if not path.exists():
        return {'jobs': jobs, 'books': books}

    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        tm = TS_RE.match(line)
        ts = tm.group(1) if tm else ''

        if 'AA - doDownloadFlipBook ' in line:
            idx = line.find('AA - doDownloadFlipBook ')
            rest = line[idx + len('AA - doDownloadFlipBook '):].strip()
            try:
                data = json.loads(rest)
            except Exception:
                continue
            bookId, bookName = data.get('bookId', ''), data.get('bookName', '')
            if bookId and bookName:
                books[bookId] = bookName
            jobName = ''
            ext = data.get('extParams', '')
            if isinstance(ext, str):
                try:
                    jobName = (json.loads(ext).get('studyTaskDetail') or {}).get('jobName', '')
                except Exception:
                    pass
            pending.append({
                'ts': ts,
                'bookId': bookId,
                'pageId': data.get('pageId', ''),
                'chapterId': data.get('chapterId', ''),
                'studyTaskId': data.get('studyTaskId', ''),
                'testName': data.get('testName', ''),
                'jobName': jobName or data.get('testName', ''),
            })
            continue

        m = RE_OPEN_CHAPTER.search(line)
        if m:
            pageId, bookId, job_hash = m.group(1), m.group(2), m.group(3)
            if job_hash in jobs and jobs[job_hash].get('testName'):
                continue
            match = next((p for p in pending if p['pageId'] == pageId), None)
            info = {'bookId': bookId, 'job_hash': job_hash,
                    'pageId': pageId, 'ts': ts}
            if match:
                info.update({
                    'testName': match['testName'],
                    'jobName': match['jobName'],
                    'chapterId': match['chapterId'],
                    'studyTaskId': match['studyTaskId'],
                })
            jobs[job_hash] = info
            continue

        m = RE_PRICHECK.search(line)
        if m:
            try:
                parts = Path(m.group(1).strip()).parts
                if len(parts) >= 2:
                    job_hash, bookId = parts[-1], parts[-2]
                    if (len(job_hash) == 32
                            and all(c in '0123456789abcdefABCDEF' for c in job_hash)
                            and job_hash not in jobs):
                        jobs[job_hash] = {
                            'bookId': bookId, 'job_hash': job_hash, 'ts': ts,
                        }
            except Exception:
                pass

    used = {i['pageId'] for i in jobs.values() if i.get('pageId')}
    for info in jobs.values():
        if info.get('testName'):
            continue
        cands = [p for p in pending
                 if p['bookId'] == info.get('bookId')
                 and p['pageId'] not in used
                 and p['ts'] <= info.get('ts', '')]
        if cands:
            best = max(cands, key=lambda x: x['ts'])
            info.update({
                'testName': best['testName'],
                'jobName': best['jobName'],
                'pageId': best['pageId'],
                'chapterId': best['chapterId'],
                'studyTaskId': best['studyTaskId'],
            })
            used.add(best['pageId'])

    return {'jobs': jobs, 'books': books}


# ================================================================== 扫描
def scan_flipbooks(source_root: Path):
    result = {}
    flipbooks = source_root / 'flipbooks'
    if not flipbooks.exists():
        return result
    for book_dir in flipbooks.iterdir():
        if not book_dir.is_dir():
            continue
        bookId = book_dir.name
        if not (len(bookId) == 32 and all(c in '0123456789abcdefABCDEF' for c in bookId)):
            continue
        jobs = {}
        for job_dir in book_dir.iterdir():
            name = job_dir.name
            if (job_dir.is_dir() and len(name) == 32
                    and all(c in '0123456789abcdefABCDEF' for c in name)):
                jobs[name] = job_dir
        if jobs:
            result[bookId] = jobs
    return result


def decrypt_job(src_dir: Path, dst_dir: Path, key, strict_magic=True, log_fn=None):
    stats = {'ok': 0, 'fail': 0}
    dst_dir.mkdir(parents=True, exist_ok=True)
    for root, _dirs, files in os.walk(src_dir):
        rel_root = Path(root).relative_to(src_dir)
        for name in files:
            src_path = Path(root) / name
            if name.lower().endswith(ENC_SUFFIX):
                out_name = name[:-len(ENC_SUFFIX)]
                dst_path = dst_dir / rel_root / out_name
                try:
                    data = src_path.read_bytes()
                    pt = decrypt_blob(data, key, strict_magic)
                    dst_path.parent.mkdir(parents=True, exist_ok=True)
                    dst_path.write_bytes(pt)
                    stats['ok'] += 1
                except Exception as e:
                    stats['fail'] += 1
                    if log_fn and stats['fail'] <= 5:
                        log_fn(f'    ❌ {rel_root / name}: {e}')
            else:
                dst_path = dst_dir / rel_root / name
                try:
                    if not dst_path.exists():
                        dst_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src_path, dst_path)
                except Exception:
                    pass
    return stats


# -------------------------------------------------------- 题目提取
def parse_js_config(text):
    m = re.search(r'pageConfig\s*=\s*', text)
    if not m:
        return None
    try:
        return json.JSONDecoder().raw_decode(text, m.end())[0]
    except json.JSONDecodeError:
        return None


def _emit_question(obj, parent_qid, source):
    results = []
    qid = obj.get('question_id', '')
    qtype = obj.get('question_type', 0)
    sub = obj.get('questions_list') or []
    if sub:
        # 有子题的容器题（一般是 type=99）
        results.append({
            'qid': qid, 'parent_qid': parent_qid, 'qtype': qtype,
            'stem': obj.get('question_text', ''),
            'options': [], 'answer': '',
            'media': (obj.get('media') or {}).get('file', ''),
            'source': source, 'is_container': True,
        })
        for s in sub:
            results.extend(_emit_question(s, parent_qid=qid, source=source))
        return results
    opts = obj.get('options') or []
    results.append({
        'qid': qid, 'parent_qid': parent_qid, 'qtype': qtype,
        'stem': obj.get('question_text', ''),
        'options': opts,
        'answer': obj.get('answer_text', ''),
        'media': (obj.get('media') or {}).get('file', ''),
        'source': source,
        # 只有 type=99 且无选项时才标记为容器（v4 曾误把 type=9 也标成容器）
        'is_container': (qtype == 99 and not opts),
    })
    return results


def extract_questions(job_dir: Path):
    """
    v5 排序策略：完全按 os.walk 顺序（自然文件系统顺序）
    - 第一遍：page*.js（提供 slides 顺序）
    - 第二遍：questionData.js（补充）
    """
    raw = []
    seen = set()

    def _add(qs):
        for q in qs:
            if q['qid'] and q['qid'] not in seen:
                raw.append(q)
                seen.add(q['qid'])

    # 按 os.walk 顺序收集所有 js
    all_js = []
    for root, _dirs, files in os.walk(job_dir):
        for name in files:
            if name.endswith('.js'):
                all_js.append(Path(root) / name)

    # 1. page*.js 优先（提供页面顺序）
    for fp in all_js:
        if not fp.name.startswith('page'):
            continue
        try:
            text = fp.read_text(encoding='utf-8', errors='replace')
            cfg = parse_js_config(text)
        except Exception:
            continue
        if not cfg:
            continue
        src = str(fp.relative_to(job_dir))
        for slide in (cfg.get('slides') or []):
            for q in (slide.get('questionList') or []):
                _add(_emit_question(q, None, src))

    # 2. questionData.js 补充
    for fp in all_js:
        if fp.name.startswith('page'):
            continue
        try:
            text = fp.read_text(encoding='utf-8', errors='replace')
            cfg = parse_js_config(text)
        except Exception:
            continue
        if not cfg:
            continue
        src = str(fp.relative_to(job_dir))
        qo = cfg.get('questionObj')
        if isinstance(qo, dict):
            _add(_emit_question(qo, None, src))

    return raw


# ================================================================== 处理器
class Processor:
    def __init__(self, cfg, log_fn, progress_fn=None):
        self.cfg = cfg
        self.log = log_fn
        self.progress = progress_fn or (lambda *a: None)
        self.source_root = Path(cfg['source_root'])
        self.decode_root = Path(cfg['decode_root'])
        self.key = load_key(cfg['key'])
        self.strict_magic = bool(cfg.get('strict_magic', True))

        self.index = load_json(INDEX_FILE, {'books': {}})
        self.answers = load_json(ANSWERS_FILE, {'books': {}})
        self.log_jobs = {}
        self.log_books = {}
        self.fs = {}

    def run(self):
        self.log('=' * 60)
        self.log('① 解析 app.log')
        log_path = self.source_root / 'logs' / 'app.log'
        if not log_path.exists():
            self.log(f'  ⚠ 未找到 {log_path}')
        else:
            data = parse_app_log(log_path)
            self.log_jobs, self.log_books = data['jobs'], data['books']
            named = sum(1 for j in self.log_jobs.values() if j.get('testName'))
            self.log(f'  {len(self.log_jobs)} 个 job（{named} 个有 testName），'
                     f'{len(self.log_books)} 个 book')

        self.log('=' * 60)
        self.log('② 扫描 flipbooks')
        self.fs = scan_flipbooks(self.source_root)
        self.log(f'  {len(self.fs)} 个 book，共 '
                 f'{sum(len(v) for v in self.fs.values())} 个 job 目录')

        self.log('=' * 60)
        self.log('③ 合并索引')
        self._merge()

        self.log('=' * 60)
        self.log('④ 解压新任务')
        todo = [(b, j) for b, book in self.index['books'].items()
                for j, job in book['jobs'].items()
                if job['status'] in ('pending', 'missing_decode')
                and j in self.fs.get(b, {})]
        self.log(f'  待解压 {len(todo)} 个')
        for i, (bId, jh) in enumerate(todo, 1):
            testName = self.index['books'][bId]['jobs'][jh].get('testName') or '(未命名)'
            self.log(f'  [{i}/{len(todo)}] {testName}  {jh[:12]}...')
            self._extract_job(bId, jh)
            self.progress('extract', i, len(todo))

        self.log('=' * 60)
        self.log('⑤ 提取题目（v5：全部题目都会保存）')
        todo2 = [(b, j) for b, book in self.index['books'].items()
                 for j, job in book['jobs'].items()
                 if job['status'] == 'extracted']
        self.log(f'  待提取 {len(todo2)} 个')
        for i, (bId, jh) in enumerate(todo2, 1):
            self._extract_questions_for(bId, jh)
            self.progress('questions', i, len(todo2))

        save_json(INDEX_FILE, self.index)
        save_json(ANSWERS_FILE, self.answers)
        self.log('=' * 60)
        self.log('✅ 完成')
        return True

    def _merge(self):
        for bId in set(self.fs) | set(self.log_books):
            if bId not in self.index['books']:
                self.index['books'][bId] = {
                    'bookId': bId,
                    'bookName': self.log_books.get(bId, ''),
                    'jobs': {},
                }
            elif not self.index['books'][bId].get('bookName'):
                self.index['books'][bId]['bookName'] = self.log_books.get(bId, '')

        for bId, jobs in self.fs.items():
            book = self.index['books'][bId]
            for jh, jp in jobs.items():
                if jh not in book['jobs']:
                    log_info = self.log_jobs.get(jh, {})
                    book['jobs'][jh] = {
                        'job_hash': jh,
                        'testName': log_info.get('testName', ''),
                        'jobName': log_info.get('jobName', ''),
                        'pageId': log_info.get('pageId', ''),
                        'chapterId': log_info.get('chapterId', ''),
                        'studyTaskId': log_info.get('studyTaskId', ''),
                        'source_path': str(jp),
                        'decode_path': str(self.decode_root / bId / jh),
                        'status': 'pending',
                        'unmarked': not bool(log_info.get('testName')),
                        'created_at': datetime.now().isoformat(),
                    }
                    self.log(f'  + 新任务 {jh[:12]}  '
                             f'{log_info.get("testName") or "(未记录任务名)"}')
                else:
                    job = book['jobs'][jh]
                    log_info = self.log_jobs.get(jh)
                    if log_info and not job.get('testName'):
                        job.update({
                            'testName': log_info.get('testName', ''),
                            'jobName': log_info.get('jobName', ''),
                            'pageId': log_info.get('pageId', ''),
                            'chapterId': log_info.get('chapterId', ''),
                            'studyTaskId': log_info.get('studyTaskId', ''),
                            'unmarked': False,
                        })
                    if job['status'] == 'extracted' and \
                            not Path(job.get('decode_path', '')).exists():
                        job['status'] = 'missing_decode'

        for bId, book in self.index['books'].items():
            for jh, job in book['jobs'].items():
                if jh not in self.fs.get(bId, {}):
                    if job['status'] not in ('missing_source', 'removed'):
                        job['status'] = 'missing_source'

    def _extract_job(self, bId, jh):
        job = self.index['books'][bId]['jobs'][jh]
        src = Path(job['source_path'])
        dst = Path(job['decode_path'])
        if not src.exists():
            job['status'] = 'missing_source'
            return
        try:
            stats = decrypt_job(src, dst, self.key, self.strict_magic, log_fn=self.log)
            job['status'] = 'extracted'
            job['extracted_at'] = datetime.now().isoformat()
            job['decrypt_ok'] = stats['ok']
            job['decrypt_fail'] = stats['fail']
            self.log(f'    解密 ok={stats["ok"]} fail={stats["fail"]}')
        except Exception as e:
            job['status'] = 'failed'
            job['error'] = str(e)
            self.log(f'    ❌ {e}')

    def _extract_questions_for(self, bId, jh):
        """v5：保存全部题目（不去 type 过滤）"""
        job = self.index['books'][bId]['jobs'][jh]
        dst = Path(job['decode_path'])
        if not dst.exists():
            return
        try:
            qs = extract_questions(dst)

            ab = self.answers.setdefault('books', {}).setdefault(
                bId, {'bookName': job.get('bookName', '') or
                      self.index['books'][bId].get('bookName', ''),
                      'jobs': {}})
            ab['jobs'][jh] = {
                'testName': job.get('testName', ''),
                'jobName': job.get('jobName', ''),
                'question_count': len(qs),
                'extracted_at': datetime.now().isoformat(),
                'questions': qs,
            }
            job['question_count'] = len(qs)
            type1 = sum(1 for q in qs if q.get('qtype') == 1)
            self.log(f'    提取题目 {len(qs)} 道（type=1: {type1} 道）')
        except Exception as e:
            job['error'] = f'题目提取失败: {e}'
            self.log(f'    ❌ {e}')


# ================================================================== UI
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('UP366 任务管理 + 题目提取工具 v5')
        self.geometry('1680x900')
        self.minsize(1280, 720)

        self.msg_q = queue.Queue()
        self.worker = None
        self.cfg = load_config()
        self.index = load_json(INDEX_FILE, {'books': {}})
        self.answers = load_json(ANSWERS_FILE, {'books': {}})
        self.processor = None

        self._build_ui()
        self._pump()
        self.protocol('WM_DELETE_WINDOW', self._on_close)
        if not HAS_CRYPTO:
            self.log('❌ 缺少 pycryptodome，请 pip install pycryptodome')
        self.after(200, self.reload_all)

    # -------- UI --------
    def _build_ui(self):
        bar = ttk.Frame(self)
        bar.pack(fill='x', padx=8, pady=(8, 4))

        ttk.Button(bar, text='⚙ 配置',
                   command=self.show_config_dialog).pack(side='left', padx=2)
        ttk.Button(bar, text='🔄 刷新',
                   command=self.reload_all).pack(side='left', padx=2)
        ttk.Button(bar, text='▶ 扫描 & 解压',
                   command=self.run_processor).pack(side='left', padx=2)
        ttk.Button(bar, text='📂 打开程序目录',
                   command=lambda: os.startfile(str(APP_DIR))).pack(side='left', padx=2)
        ttk.Button(bar, text='📂 打开解密目录',
                   command=self.open_decode_dir).pack(side='left', padx=2)
        ttk.Button(bar, text='🧹 清空 app.log',
                   command=self.clear_app_log).pack(side='left', padx=2)

        self.progress = ttk.Progressbar(bar, mode='determinate', length=220)
        self.progress.pack(side='right', padx=6)
        self.var_prog = tk.StringVar(value='就绪')
        ttk.Label(bar, textvariable=self.var_prog).pack(side='right', padx=6)

        nb = ttk.Notebook(self)
        nb.pack(fill='both', expand=True, padx=8, pady=4)
        self.nb = nb

        # --- Tab1: 书籍与任务 ---
        f1 = ttk.Frame(nb)
        nb.add(f1, text='📚 书籍与任务')

        self.tree_jobs = ttk.Treeview(
            f1, columns=('type', 'name', 'status', 'count', 'ts', 'path'),
            show='tree headings', height=18)
        self.tree_jobs.heading('#0', text='层级')
        self.tree_jobs.column('#0', width=250, anchor='w')
        for c, t, w in [('type', '类型', 60), ('name', '名称 / ID', 400),
                        ('status', '状态', 110), ('count', '题数', 60),
                        ('ts', '解压时间', 160), ('path', '路径', 420)]:
            self.tree_jobs.heading(c, text=t)
            self.tree_jobs.column(c, width=w, anchor='w',
                                  stretch=(c in ('path', 'name')))
        vsb = ttk.Scrollbar(f1, orient='vertical', command=self.tree_jobs.yview)
        hsb = ttk.Scrollbar(f1, orient='horizontal', command=self.tree_jobs.xview)
        self.tree_jobs.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree_jobs.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        f1.rowconfigure(0, weight=1)
        f1.columnconfigure(0, weight=1)

        self.tree_jobs.bind('<<TreeviewSelect>>', self.on_job_select)
        self.tree_jobs.bind('<Double-1>', self.on_job_double_click)
        self.tree_jobs.bind('<Delete>', self._on_del_key)

        for tag, color in [('unmarked', '#b8860b'), ('failed', '#b00020'),
                           ('missing', '#888888'), ('pending', '#0066cc')]:
            self.tree_jobs.tag_configure(tag, foreground=color)

        op = ttk.Frame(f1)
        op.grid(row=2, column=0, columnspan=2, sticky='ew', pady=4)

        tk.Button(
            op, text='🗑 删除所有信息',
            bg='#d32f2f', fg='white',
            activebackground='#b71c1c', activeforeground='white',
            relief='raised', bd=1, padx=10, pady=2,
            font=('TkDefaultFont', 9, 'bold'),
            command=self.delete_all_info,
        ).pack(side='left', padx=(2, 6))

        ttk.Button(op, text='🗑 删除原始 flipbooks',
                   command=lambda: self.delete_part('flipbooks')).pack(side='left', padx=2)
        ttk.Button(op, text='🗑 删除解压后文件',
                   command=lambda: self.delete_part('decode')).pack(side='left', padx=2)
        ttk.Button(op, text='🗑 删除答案',
                   command=lambda: self.delete_part('answers')).pack(side='left', padx=2)
        ttk.Button(op, text='🗑 删除解压记录',
                   command=lambda: self.delete_part('index')).pack(side='left', padx=2)
        ttk.Button(op, text='🔁 强制重解压选中',
                   command=self.force_reextract).pack(side='left', padx=8)

        # --- Tab2: 答案与题目 ---
        f2 = ttk.Frame(nb)
        nb.add(f2, text='📝 答案与题目')

        ob = ttk.Frame(f2)
        ob.pack(fill='x', padx=4, pady=4)
        self.var_view = tk.StringVar(value='simple')
        ttk.Radiobutton(ob, text='简洁视图（仅 type=1 显示答案）',
                        variable=self.var_view, value='simple',
                        command=self.render_questions).pack(side='left', padx=4)
        ttk.Radiobutton(ob, text='完整视图（题干 + 选项 + 全部答案）',
                        variable=self.var_view, value='full',
                        command=self.render_questions).pack(side='left', padx=4)
        ttk.Button(ob, text='📋 复制答案',
                   command=self.copy_answers).pack(side='left', padx=8)
        self.var_cur = tk.StringVar(value='（未选择任务）')
        ttk.Label(ob, textvariable=self.var_cur,
                  foreground='#0066cc').pack(side='left', padx=16)
        ttk.Button(ob, text='导出当前任务 CSV',
                   command=self.export_csv).pack(side='right', padx=4)

        qf = ttk.Frame(f2)
        qf.pack(fill='both', expand=True, padx=4, pady=(0, 4))
        q_cols = ('idx', 'qid', 'parent', 'type', 'stem', 'options',
                  'answer', 'media')
        self.tree_q = ttk.Treeview(qf, columns=q_cols, show='headings', height=20)
        widths = {'idx': 40, 'qid': 240, 'parent': 240, 'type': 50,
                  'stem': 420, 'options': 420, 'answer': 140, 'media': 200}
        titles = {'idx': '#', 'qid': '题目 ID', 'parent': '父题 ID',
                  'type': '类型', 'stem': '题干', 'options': '选项',
                  'answer': '答案', 'media': '媒体'}
        for c in q_cols:
            self.tree_q.heading(c, text=titles[c])
            self.tree_q.column(c, width=widths[c], anchor='w',
                               stretch=(c in ('stem', 'options')))
        vsb2 = ttk.Scrollbar(qf, orient='vertical', command=self.tree_q.yview)
        hsb2 = ttk.Scrollbar(qf, orient='horizontal', command=self.tree_q.xview)
        self.tree_q.configure(yscrollcommand=vsb2.set, xscrollcommand=hsb2.set)
        self.tree_q.pack(side='top', fill='both', expand=True)
        vsb2.pack(side='right', fill='y')
        hsb2.pack(side='bottom', fill='x')
        # 配色沿用上一版
        self.tree_q.tag_configure('container', background='#f3e8ff')  # 紫色=容器题
        self.tree_q.tag_configure('no_answer', background='#fff3cd')  # 黄色=无答案

        self._apply_column_visibility()

        # --- Tab3: 日志 ---
        f3 = ttk.Frame(nb)
        nb.add(f3, text='📜 日志')
        self.log_text = scrolledtext.ScrolledText(f3, wrap='word')
        self.log_text.pack(fill='both', expand=True)

        self.status = tk.StringVar(value='就绪')
        ttk.Label(self, textvariable=self.status, relief='sunken',
                  anchor='w').pack(fill='x', side='bottom')

    # -------- 列显示 --------
    def _apply_column_visibility(self):
        """简洁视图隐藏题干 + 选项列；完整视图全部显示"""
        if self.var_view.get() == 'simple':
            self.tree_q['displaycolumns'] = (
                'idx', 'qid', 'parent', 'type', 'answer', 'media')
        else:
            self.tree_q['displaycolumns'] = (
                'idx', 'qid', 'parent', 'type', 'stem', 'options',
                'answer', 'media')

    # -------- 事件 --------
    def show_config_dialog(self):
        win = tk.Toplevel(self)
        win.title('配置')
        win.geometry('640x240')
        win.transient(self)
        pad = {'padx': 6, 'pady': 4}

        rows = [('source_root', '源目录（含 flipbooks/）'),
                ('decode_root', '解密输出目录'),
                ('key', '密钥（base64 16 字节）')]
        vars_ = {}
        for i, (k, label) in enumerate(rows):
            ttk.Label(win, text=label + '：').grid(row=i, column=0, sticky='e', **pad)
            var = tk.StringVar(value=self.cfg.get(k, ''))
            vars_[k] = var
            ttk.Entry(win, textvariable=var, width=50).grid(
                row=i, column=1, sticky='ew', **pad)
            if k != 'key':
                ttk.Button(win, text='浏览...',
                           command=lambda v=var: self._pick_dir(v)).grid(
                    row=i, column=2, **pad)
        win.columnconfigure(1, weight=1)
        strict_var = tk.BooleanVar(value=self.cfg.get('strict_magic', True))
        ttk.Checkbutton(win, text='严格校验魔数',
                        variable=strict_var).grid(row=3, column=1, sticky='w', **pad)

        def save():
            for k, v in vars_.items():
                self.cfg[k] = v.get().strip()
            self.cfg['strict_magic'] = strict_var.get()
            save_config(self.cfg)
            self.log('✓ 配置已保存')
            win.destroy()
        ttk.Button(win, text='保存', command=save).grid(
            row=4, column=1, sticky='e', **pad)

    def _pick_dir(self, var):
        d = filedialog.askdirectory()
        if d:
            var.set(os.path.normpath(d))

    def open_decode_dir(self):
        dec = Path(self.cfg.get('decode_root', ''))
        dec.mkdir(parents=True, exist_ok=True)
        os.startfile(str(dec))

    def clear_app_log(self):
        log_path = Path(self.cfg['source_root']) / 'logs' / 'app.log'
        if not log_path.exists():
            messagebox.showinfo('提示', f'app.log 不存在：\n{log_path}')
            return
        if not messagebox.askyesno(
                '确认', f'清空 {log_path}？\n（不影响 index / answers / 解密文件）'):
            return
        try:
            log_path.write_text('', encoding='utf-8')
            self.log('✓ app.log 已清空')
        except Exception as e:
            messagebox.showerror('失败', str(e))

    def reload_all(self):
        self.cfg = load_config()
        self.index = load_json(INDEX_FILE, {'books': {}})
        self.answers = load_json(ANSWERS_FILE, {'books': {}})
        self.render_jobs()

    def run_processor(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning('提示', '处理中，请稍候')
            return
        self.cfg = load_config()
        self.processor = Processor(self.cfg, self.log, self._set_progress)
        self.worker = threading.Thread(target=self._run_worker, daemon=True)
        self.worker.start()

    def _run_worker(self):
        try:
            self.processor.run()
            self.msg_q.put(('done', None))
        except Exception as e:
            self.msg_q.put(('log', '❌ ' + str(e)))
            self.msg_q.put(('log', traceback.format_exc()))
            self.msg_q.put(('done', str(e)))

    def log(self, msg):
        self.msg_q.put(('log', msg))

    def _set_progress(self, stage, cur, total):
        self.msg_q.put(('progress', (stage, cur, total)))

    def _pump(self):
        try:
            while True:
                kind, payload = self.msg_q.get_nowait()
                if kind == 'log':
                    self.log_text.insert('end', payload + '\n')
                    self.log_text.see('end')
                    self.status.set(payload[:120])
                elif kind == 'progress':
                    stage, cur, total = payload
                    self.progress['maximum'] = max(total, 1)
                    self.progress['value'] = cur
                    self.var_prog.set(f'{stage} {cur}/{total}')
                elif kind == 'done':
                    self.progress['value'] = 0
                    self.var_prog.set('完成' if not payload else '失败')
                    self.reload_all()
                    self.status.set('✅ 完成' if not payload else '❌ ' + payload)
        except queue.Empty:
            pass
        self.after(80, self._pump)

    # -------- 渲染 --------
    def render_jobs(self):
        self.tree_jobs.delete(*self.tree_jobs.get_children())
        self.index = load_json(INDEX_FILE, {'books': {}})
        if not self.index['books']:
            return
        for bId, book in sorted(self.index['books'].items()):
            bookName = book.get('bookName') or '(未知书名)'
            jobs = book.get('jobs', {})
            book_iid = self.tree_jobs.insert(
                '', 'end', text=f'📚 {bookName}',
                values=('Book', f'{bookName} / {bId}',
                        f'{len(jobs)} 个任务', '', '', bId),
                open=True)
            for jh, job in sorted(jobs.items(),
                                   key=lambda kv: kv[1].get('testName', '')):
                testName = job.get('testName') or '(未记录任务名)'
                status = job.get('status', '?')
                cnt = job.get('question_count', 0)
                tag = ''
                if status == 'failed':
                    tag = 'failed'
                elif status in ('missing_source', 'removed'):
                    tag = 'missing'
                elif status == 'pending':
                    tag = 'pending'
                elif job.get('unmarked'):
                    tag = 'unmarked'
                iid = f'{bId}:{jh}'
                self.tree_jobs.insert(
                    book_iid, 'end', iid=iid,
                    text=f'📝 {testName}',
                    values=('Job', f'{testName} / {jh[:16]}...',
                            self._status_text(status),
                            cnt if cnt else '-',
                            (job.get('extracted_at') or '')[:19],
                            job.get('decode_path', '')),
                    tags=(tag,) if tag else ())

    @staticmethod
    def _status_text(s):
        return {'extracted': '✓ 已解压',
                'pending': '⏳ 待解压',
                'missing_decode': '⚠ 缺解密文件',
                'missing_source': '⚠ 源已删除',
                'removed': '已删除',
                'failed': '❌ 失败'}.get(s, s)

    def _selected_book_job(self):
        sel = self.tree_jobs.selection()
        if not sel:
            return None
        iid = sel[0]
        if ':' not in iid:
            return None
        bId, jh = iid.split(':', 1)
        return bId, jh

    def on_job_select(self, _event=None):
        sel = self._selected_book_job()
        if not sel:
            self.var_cur.set('（未选择任务）')
            self.tree_q.delete(*self.tree_q.get_children())
            return
        bId, jh = sel
        job = self.index.get('books', {}).get(bId, {}).get('jobs', {}).get(jh, {})
        testName = job.get('testName') or '(未记录)'
        self.var_cur.set(f'当前：{testName}  [{jh[:12]}...]')
        self._render_questions_for(bId, jh)

    def on_job_double_click(self, event):
        iid = self.tree_jobs.identify_row(event.y)
        if not iid or ':' not in iid:
            return
        if self.tree_jobs.selection() != (iid,):
            self.tree_jobs.selection_set(iid)
            self.on_job_select()
        self.nb.select(1)
        self.tree_q.focus_set()
        self.status.set('双击任务 → 已切换到答案页')

    def _on_del_key(self, _event):
        if self._selected_book_job():
            self.delete_all_info()
            return 'break'
        return None

    def render_questions(self):
        self._apply_column_visibility()
        sel = self._selected_book_job()
        if sel:
            self._render_questions_for(*sel)

    def _render_questions_for(self, bId, jh):
        self.tree_q.delete(*self.tree_q.get_children())
        job_data = self.answers.get('books', {}).get(bId, {}).get('jobs', {}).get(jh)
        if not job_data:
            self.tree_q.insert('', 'end', values=(
                '-', '-', '-', '-', '', '', '（尚未提取题目，请点击"扫描 & 解压"）', ''))
            return

        qs = job_data.get('questions') or []
        if not qs:
            self.tree_q.insert('', 'end', values=(
                '-', '-', '-', '-', '', '', '（没有题目）', ''))
            return

        view = self.var_view.get()
        for i, q in enumerate(qs, 1):
            is_type1 = (q.get('qtype') == 1)
            is_container = q.get('is_container', False)

            tags = []
            if is_container:
                tags.append('container')
            if not q.get('answer'):
                tags.append('no_answer')

            # 简洁模式：只有 type=1 显示答案
            # 完整模式：所有题目都显示答案（type=9 中文翻译也会显示）
            if view == 'simple':
                ans_text = self._answer_display(q) if is_type1 else ''
            else:
                ans_text = self._answer_display(q)

            self.tree_q.insert('', 'end', values=(
                i, q['qid'], q.get('parent_qid', '') or '-',
                q['qtype'], q.get('stem', ''),
                self._options_display(q), ans_text,
                q.get('media', '')),
                tags=tuple(tags))

    @staticmethod
    def _options_display(q):
        opts = q.get('options') or []
        return ' | '.join(f"{o.get('id', '?')}.{o.get('content', '')}" for o in opts)

    @staticmethod
    def _answer_display(q):
        ans = q.get('answer', '')
        if not ans:
            return ''
        if q.get('qtype') == 1:
            for o in (q.get('options') or []):
                if o.get('id') == ans:
                    return f"{ans}.{o.get('content', '')}"
        return ans

    # -------- 复制答案 --------
    def copy_answers(self):
        """将 type=1 的答案以 '#{i}: {answer_content}\\n' 格式复制到剪贴板"""
        sel = self._selected_book_job()
        if not sel:
            messagebox.showinfo('提示', '请先选择一个任务')
            return
        bId, jh = sel
        job_data = self.answers.get('books', {}).get(bId, {}).get('jobs', {}).get(jh)
        if not job_data:
            messagebox.showinfo('提示', '该任务尚未提取题目')
            return

        lines = []
        idx = 0
        for q in (job_data.get('questions') or []):
            if q.get('qtype') != 1:
                continue
            idx += 1
            ans = q.get('answer', '')
            content = ''
            if ans:
                for o in (q.get('options') or []):
                    if o.get('id') == ans:
                        content = o.get('content', '')
                        break
                if not content:
                    content = ans  # 选项内容没匹配到，就用字母
            lines.append(f'#{idx}: {content}')

        if not lines:
            messagebox.showinfo('提示', '没有 type=1 的题目')
            return

        text = '\n'.join(lines)
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()
            messagebox.showinfo(
                '已复制',
                f'已复制 {idx} 道 type=1 题目的答案到剪贴板\n\n'
                f'预览（前 3 行）：\n' + '\n'.join(lines[:3])
                + ('\n...' if len(lines) > 3 else ''))
            self.status.set(f'✓ 已复制 {idx} 道答案到剪贴板')
        except Exception as e:
            messagebox.showerror('失败', str(e))

    # -------- 删除 --------
    def delete_part(self, part):
        sel = self._selected_book_job()
        if not sel:
            messagebox.showinfo('提示', '请先选择一个任务')
            return
        bId, jh = sel
        book = self.index.get('books', {}).get(bId, {})
        job = book.get('jobs', {}).get(jh, {})
        name = job.get('testName') or jh[:12]
        if not messagebox.askyesno('确认',
                                    f'删除 {part}：\n{name}\n{jh}\n\n继续？'):
            return
        try:
            if part == 'flipbooks':
                p = Path(job.get('source_path', ''))
                if p.exists():
                    shutil.rmtree(p)
                    self.log(f'✓ 已删除源: {p}')
                job['status'] = 'missing_source'
            elif part == 'decode':
                p = Path(job.get('decode_path', ''))
                if p.exists():
                    shutil.rmtree(p)
                    self.log(f'✓ 已删除解密目录: {p}')
                if job['status'] == 'extracted':
                    job['status'] = 'missing_decode'
                ab = self.answers.get('books', {}).get(bId, {})
                ab.get('jobs', {}).pop(jh, None)
                job['question_count'] = 0
            elif part == 'answers':
                ab = self.answers.get('books', {}).get(bId, {})
                if jh in ab.get('jobs', {}):
                    del ab['jobs'][jh]
                    self.log('✓ 已删除答案')
                job['question_count'] = 0
            elif part == 'index':
                book['jobs'].pop(jh, None)
                self.answers.get('books', {}).get(bId, {}).get('jobs', {}).pop(jh, None)
                self.log('✓ 已删除索引 & 答案')
            save_json(INDEX_FILE, self.index)
            save_json(ANSWERS_FILE, self.answers)
            self.render_jobs()
        except Exception as e:
            messagebox.showerror('失败', str(e))

    def delete_all_info(self):
        sel = self._selected_book_job()
        if not sel:
            messagebox.showinfo('提示', '请先在列表中选中一个任务')
            return
        bId, jh = sel
        book = self.index.get('books', {}).get(bId, {})
        job = book.get('jobs', {}).get(jh, {})
        if not job:
            messagebox.showinfo('提示', '任务不存在于索引中')
            return

        name = job.get('testName') or jh[:12]
        src_path = job.get('source_path', '')
        dec_path = job.get('decode_path', '')

        if not messagebox.askyesno(
                '⚠ 确认删除所有信息',
                f'即将删除该任务的全部本地数据（app.log 不受影响）：\n\n'
                f'  任务名   : {name}\n'
                f'  job_hash : {jh}\n'
                f'  源目录   : {src_path}\n'
                f'  解密目录 : {dec_path}\n\n'
                f'将删除：\n'
                f'  • flipbooks 原始目录\n'
                f'  • 解密后的 decode 目录\n'
                f'  • 答案存储记录\n'
                f'  • 解压索引记录\n\n'
                f'此操作不可撤销，是否继续？'):
            return

        errors = []

        if src_path:
            p = Path(src_path)
            try:
                if p.exists() and p.is_dir():
                    shutil.rmtree(p)
                    self.log(f'✓ 已删除源目录: {p}')
            except Exception as e:
                errors.append(f'删除源目录失败: {e}')

        if dec_path:
            p = Path(dec_path)
            try:
                if p.exists() and p.is_dir():
                    shutil.rmtree(p)
                    self.log(f'✓ 已删除解密目录: {p}')
            except Exception as e:
                errors.append(f'删除解密目录失败: {e}')

        ans_book = self.answers.get('books', {}).get(bId, {})
        if jh in ans_book.get('jobs', {}):
            del ans_book['jobs'][jh]

        book.get('jobs', {}).pop(jh, None)

        try:
            save_json(INDEX_FILE, self.index)
            save_json(ANSWERS_FILE, self.answers)
        except Exception as e:
            errors.append(f'保存索引/答案失败: {e}')

        self.tree_q.delete(*self.tree_q.get_children())
        self.var_cur.set('（未选择任务）')
        self.render_jobs()

        if errors:
            messagebox.showwarning('部分失败', '\n'.join(errors))
        else:
            messagebox.showinfo('完成',
                                f'已删除「{name}」的所有信息\n')
            self.status.set(f'✓ 已删除任务 {jh[:12]}')

    def force_reextract(self):
        sel = self._selected_book_job()
        if not sel:
            return
        bId, jh = sel
        book = self.index.get('books', {}).get(bId, {})
        job = book.get('jobs', {}).get(jh)
        if job:
            job['status'] = 'pending'
            save_json(INDEX_FILE, self.index)
            self.render_jobs()
            self.run_processor()

    # -------- 导出 CSV --------
    def export_csv(self):
        sel = self._selected_book_job()
        if not sel:
            return
        bId, jh = sel
        job_data = self.answers.get('books', {}).get(bId, {}).get('jobs', {}).get(jh)
        if not job_data:
            messagebox.showinfo('提示', '该任务尚未提取题目')
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.csv', filetypes=[('CSV', '*.csv')],
            initialfile=f'{bId}_{jh[:8]}.csv')
        if not path:
            return
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(['#', '题目ID', '父题ID', '类型', '题干',
                            '选项', '答案', '媒体'])
                idx = 0
                for q in job_data.get('questions', []):
                    idx += 1
                    w.writerow([idx, q.get('qid', ''), q.get('parent_qid', '') or '-',
                                q.get('qtype', ''), q.get('stem', ''),
                                self._options_display(q),
                                self._answer_display(q), q.get('media', '')])
            messagebox.showinfo('完成', f'已导出 {idx} 条题目：\n{path}')
        except Exception as e:
            messagebox.showerror('失败', str(e))

    def _on_close(self):
        self.destroy()


if __name__ == '__main__':
    App().mainloop()