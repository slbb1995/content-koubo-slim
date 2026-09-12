"""Synthetic reference boundaries and draft delivery regressions."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ('Skills' if (ROOT / 'Skills/content-koubo-slim').is_dir() else 'skills/content-mainline') / 'content-koubo-slim'
sys.path.insert(0, str(SKILL))
from runtime.reference_prep import preflight_references, write_prepared_references
from runtime.error_model import SlimRuntimeError
from runtime.schema_validation import validate_writer_result


class ReferencePiecesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / 'references.md'
        self.source.write_text('合集说明\n' + '\n'.join(f'## 对标{i}\n独立开场{i}。\n具体内容{i}。\n独立结尾{i}。' for i in range(1, 6)) + '\n')
        self.raw = self.source.read_bytes()
        self.plan = {
            'source_path': str(self.source), 'source_sha256': hashlib.sha256(self.raw).hexdigest(),
            'items': [{'title': f'对标{i+1}', 'start_line': 2+i*4, 'end_line': 5+i*4} for i in range(5)],
            'excluded_ranges': [{'start_line': 1, 'end_line': 1, 'reason': '合集说明不是独立口播'}],
        }
        self.mapping = self.root / 'collection.reference-map.json'

    def prepare(self, plan=None, extra=None):
        self.mapping.write_text(json.dumps(plan or self.plan, ensure_ascii=False))
        return preflight_references([self.mapping] + (extra or []))

    def test_five_pieces_preserve_full_content_and_original_coordinates(self):
        prepared = self.prepare()
        self.assertEqual([r.reference_id for r in prepared], [f'REF-{i:03d}' for i in range(1, 6)])
        for i, ref in enumerate(prepared, 1):
            self.assertIn(f'独立开场{i}', ref.content)
            self.assertIn(f'独立结尾{i}', ref.content)
            self.assertNotIn(f'具体内容{i+1}', ref.content)
            self.assertEqual(ref.private_index_item()['source_lines'], [2+(i-1)*4, 5+(i-1)*4])
            self.assertIn('独立篇目', ref.analyzer_item()['source_boundary'])
        run = self.root / 'run'; run.mkdir()
        path, index = write_prepared_references(run, prepared)
        self.assertEqual(index['reference_count'], 5)
        self.assertIn('独立结尾5', (path/'REF-005.md').read_text())
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_source_drift_rejects_before_preparation(self):
        self.source.write_text('changed')
        with self.assertRaises(SlimRuntimeError): self.prepare()

    def test_gaps_overlap_bad_order_bounds_and_empty_exclusion_fail(self):
        variants = []
        p = copy.deepcopy(self.plan); p['excluded_ranges'] = []; variants.append(p)
        p = copy.deepcopy(self.plan); p['items'][1]['start_line'] = 5; variants.append(p)
        p = copy.deepcopy(self.plan); p['items'].reverse(); variants.append(p)
        p = copy.deepcopy(self.plan); p['items'][-1]['end_line'] = 999; variants.append(p)
        p = copy.deepcopy(self.plan); p['items'][0]['start_line'] = True; variants.append(p)
        p = copy.deepcopy(self.plan); p['excluded_ranges'][0]['reason'] = ''; variants.append(p)
        for plan in variants:
            with self.subTest(plan=plan), self.assertRaises(SlimRuntimeError): self.prepare(plan)

    def test_duplicate_whole_source_cannot_bypass_five_piece_limit(self):
        with self.assertRaises(SlimRuntimeError): self.prepare(extra=[self.source])
        p = copy.deepcopy(self.plan)
        p['items'] = p['items'][:1]
        p['excluded_ranges'].append({'start_line': 6, 'end_line': 21, 'reason': '本次未选择这些篇目'})
        with self.assertRaises(SlimRuntimeError): self.prepare(p, [self.source])

    def test_symlink_and_unknown_map_fields_are_rejected(self):
        link = self.root/'linked.md'; link.symlink_to(self.source)
        p = copy.deepcopy(self.plan); p['source_path'] = str(link)
        with self.assertRaises(SlimRuntimeError): self.prepare(p)
        p = copy.deepcopy(self.plan); p['items'][0]['content'] = '替换原文'
        with self.assertRaises(SlimRuntimeError): self.prepare(p)

    def test_plain_single_reference_remains_compatible(self):
        refs = preflight_references([self.source])
        self.assertEqual(len(refs), 1)
        self.assertNotIn('source_lines', refs[0].private_index_item())
        self.assertEqual(refs[0].content, self.raw.decode().strip())


class DraftDeliveryTests(unittest.TestCase):
    def test_rejects_process_markup_and_numbered_alternatives(self):
        for paragraphs in [
            ['<think>process placeholder</think>'],
            ['正文。\n<analysis>process placeholder</analysis>'],
            [f'脚本{i}：独立开场、内容和结尾。' for i in range(1, 11)],
            ['第1版：独立口播。\n第2版：另一条口播。'],
            ['口播稿A：第一条。', '口播稿B：第二条。'],
            ['第1条口播：第一条。', '第2条口播：第二条。'],
            ['口播文案1：第一条。', '口播文案2：第二条。'],
        ]:
            with self.subTest(paragraphs=paragraphs), self.assertRaises(SlimRuntimeError):
                validate_writer_result({'paragraphs': [{'text': p} for p in paragraphs]})

    def test_spoken_steps_and_discussion_of_versions_are_valid(self):
        paragraphs = ['第一步，先想清楚你要解决什么问题。', '第二步，拿一个真实任务试一试。', '这个工具有十个版本，我们今天只讲最常用的那个。', '方案一：先自己试试。', '方案二：参加现场课程。']
        normalized, body = validate_writer_result({'paragraphs': [{'text': p} for p in paragraphs]})
        self.assertEqual(body, '\n\n'.join(paragraphs))
        self.assertEqual(len(normalized['paragraphs']), 5)


if __name__ == '__main__': unittest.main()
