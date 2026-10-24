# -*- coding: utf-8 -*-
"""
UP366 Job 管理器
==========================
只提供 import 接口，无命令行。通过传入 app_dir（内含 up366_*.json）读取。

用法:
    from job_manager import JobManager
    jm = JobManager('D:/wjhBot')

    # 1) 列出所有书籍
    for b in jm.list_books():
        print(b['book_id'], b['book_name'], b['job_count'])

    # 2) 列出所有 Job（可限定某本书）
    for j in jm.list_jobs():
        print(j['book_name'], '|', j['test_name'], '|', j['job_hash'])

    # 3) 按 testName 关键词搜索 → [(job_hash, book_id), ...]
    hits = jm.search_jobs('听力练习2')
    # hits == [('452eb04875384b7c921e46d30cdc626f',
    #           '59A0044287BEAB997F7C03AE4B9FC101')]

    # 4) 取答案内容（字符串列表，不含字母、不含 HTML 标签）
    answers = jm.get_answers(*hits[0])
    # ['The Mandalorian.', 'His watch was slow.', 'He’s a firefighter.', ...]

    # 5) 训练目录
    jm.get_train_root()                 # → Path('D:/wjhBot/decode')
    jm.get_train_dir(*hits[0])          # → Path('D:/wjhBot/decode/<book>/<job>')
"""

import json
import re
from pathlib import Path


def _load_json(path):
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _strip_html(text):
    return re.sub(r'<[^>]+>', '', text or '').strip()


class JobManager:
    def __init__(self, app_dir):
        self.app_dir = Path(app_dir)
        self.config = _load_json(self.app_dir / 'up366_config.json')
        self._index = _load_json(self.app_dir / 'up366_index.json')
        self._answers = _load_json(self.app_dir / 'up366_answers.json')
        self._index_books = self._index.get('books') or {}
        self._answer_books = self._answers.get('books') or {}
        self._decode_root = Path(self.config.get('decode_root') or self.app_dir)

    # ---------------------------------------------------------------- 目录
    def get_train_root(self):
        """训练 / 解密根目录"""
        return self._decode_root

    def get_train_dir(self, job_hash, book_id):
        """某任务的训练目录：decode_root/<book_id>/<job_hash>"""
        return self._decode_root / book_id / job_hash

    # ---------------------------------------------------------------- 列表
    def list_books(self):
        """[{'book_id', 'book_name', 'job_count'}, ...]"""
        return [
            {
                'book_id': bid,
                'book_name': book.get('bookName', ''),
                'job_count': len(book.get('jobs') or {}),
            }
            for bid, book in self._index_books.items()
        ]

    def list_jobs(self, book_id=None):
        """[{'book_id', 'book_name', 'job_hash', 'test_name', 'question_count'}, ...]"""
        result = []
        for bid, book in self._index_books.items():
            if book_id and bid != book_id:
                continue
            for jh, job in (book.get('jobs') or {}).items():
                ans_job = (
                    self._answer_books.get(bid, {})
                    .get('jobs', {})
                    .get(jh, {})
                ) or {}
                result.append({
                    'book_id': bid,
                    'book_name': book.get('bookName', ''),
                    'job_hash': jh,
                    'test_name': job.get('testName') or job.get('jobName') or '',
                    'question_count': ans_job.get('question_count', 0),
                })
        return result

    # ---------------------------------------------------------------- 搜索
    def search_jobs(self, keyword):
        """
        按 testName 关键词模糊搜索（不区分大小写）
        返回: [(job_hash, book_id), ...]
        """
        kw = (keyword or '').lower()
        if not kw:
            return []
        hits = []
        for bid, book in self._index_books.items():
            for jh, job in (book.get('jobs') or {}).items():
                name = (job.get('testName') or job.get('jobName') or '').lower()
                if kw in name:
                    hits.append((jh, bid, name))
        return hits

    # ---------------------------------------------------------------- 答案
    def get_answers(self, job_hash, book_id):
        """
        返回答案内容列表（字符串列表，只含 content）。
        · 选择题(qtype=1)   → 正确选项的 content（去 HTML 标签）
        · 其他题型(qtype=9) → answer 字段值（去 HTML 标签）
        · 容器题           → 跳过
        · 无答案的题       → 空字符串占位（保持与题目顺序对齐）
        """
        job = (
            self._answer_books.get(book_id, {})
            .get('jobs', {})
            .get(job_hash)
        )
        if not job:
            return []
        return [
            self._extract_content(q)
            for q in (job.get('questions') or [])
            if q.get('qtype') == 1
        ]

    @staticmethod
    def _extract_content(q):
        ans = q.get('answer') or ''
        if not ans:
            return ''
        if q.get('qtype') == 1:
            for opt in (q.get('options') or []):
                if opt.get('id') == ans:
                    return _strip_html(opt.get('content', ''))
        return _strip_html(ans)