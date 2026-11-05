import copy
import csv
import io
import json
from pathlib import Path
import tempfile
import subprocess
import unittest

import budget_server as b
from demo import create_demo, DEMO_CONFIG


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.original = [copy.deepcopy(v) for v in [b.CATEGORIES, b.CATEGORY_MAP, b.CATEGORY_GROUPS]]
        self.roles = b.SUBSCRIPTION_CATEGORY, b.FALLBACK_CATEGORY

    def tearDown(self):
        for target, original in zip([b.CATEGORIES, b.CATEGORY_MAP, b.CATEGORY_GROUPS], self.original):
            target.clear(); target.update(original)
        b.SUBSCRIPTION_CATEGORY, b.FALLBACK_CATEGORY = self.roles

    def test_launchers_forward_arguments_from_another_directory(self):
        root = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            for launcher in ['Open net-month.command', 'Open Budget.command']:
                for argument, status in [('--help', 0), ('--unknown-option', 2)]:
                    with self.subTest(launcher=launcher, argument=argument):
                        result = subprocess.run([str(root / launcher), argument], cwd=directory,
                                                capture_output=True, text=True)
                        self.assertEqual(result.returncode, status, result.stderr)
                        self.assertIn('--data-dir', result.stdout + result.stderr)

    def config(self):
        return {'categories': {'Home': 1000, 'Memberships': 30, 'Other': 200},
                'category_map': {'rent': 'Home', 'shopping': 'Other'},
                'subscription_category': 'Memberships', 'fallback_category': 'Other',
                'groups': {'Essentials': ['Home'], 'Flexible': ['Memberships', 'Other']}}

    def export_amount(self, amount, legacy=False):
        output = io.StringIO(); writer = csv.writer(output)
        if legacy:
            writer.writerow(['Date', 'Original Date', 'Account Name', 'Name', 'Amount', 'Category'])
            writer.writerow(['2026-10-01', '2026-10-01', 'Demo card', 'Synthetic purchase', amount, 'Groceries'])
        else:
            writer.writerow(['Date', 'Account', 'Description', 'Category', 'Amount'])
            writer.writerow(['2026-10-01', 'Demo card', 'Synthetic purchase', 'Groceries', amount])
        return output.getvalue()

    def test_import_money_formats_and_legacy_signs(self):
        accepted = {'-1,234.56': -123456, '-$12.34': -1234, '$-12.34': -1234,
                    ' $1,234.50 ': 123450, '+12.3': 1230, '1000': 100000,
                    '-1,234,567.89': -123456789}
        for legacy in [False, True]:
            for text, expected in accepted.items():
                with self.subTest(text=text, legacy=legacy):
                    state = b.empty()
                    preview = b.preview_import(state, self.export_amount(text, legacy), 'synthetic.csv')
                    b.commit_import(state, preview, {})
                    with tempfile.TemporaryDirectory() as directory:
                        store = b.Store(directory); store.save(state)
                        saved = store.load()['transactions'][0]
                    self.assertEqual(saved['cents'], expected * (-1 if legacy else 1))
                    self.assertEqual(saved['original_amount'], text)

    def test_malformed_amounts_fail_before_import(self):
        rejected = ['-12,34', '-1,23.45', '-1$2.34', '1,,234', '12,3456', '1234,567',
                    '1.234,56', '1,234.', '$$12', '$-+12', '1 234.56', '1e3',
                    'NaN', 'Infinity', '12.345', '', '0', '-0.00']
        state = b.empty()
        b.mutate(state, 'transaction', dict(date='2026-10-01', amount='-100', description='Existing record',
                 kind='expense', category='Miscellaneous'))
        original = copy.deepcopy(state)
        for legacy in [False, True]:
            for text in rejected:
                with self.subTest(text=text, legacy=legacy):
                    with self.assertRaisesRegex(b.Invalid, 'CSV row 2:'):
                        b.preview_import(state, self.export_amount(text, legacy), 'synthetic.csv')
                    self.assertEqual(state, original)

    def test_snapshot_preserves_order_and_multiple_credit_endpoints(self):
        state = b.empty()
        for date, amount, description, kind, allocations in [
            ('2026-01-01', '-100.01', 'Annual', 'expense',
             [{'month': '2026-03', 'amount': '33.33'}, {'month': '2026-01', 'amount': '33.34'}, {'month': '2026-02', 'amount': '33.34'}]),
            ('2026-01-02', '-60', 'Dinner', 'expense', []),
            ('2026-04-01', '30', 'Shared credit', 'refund', []),
            ('2026-05-01', '10', 'Partial credit', 'reimbursement', []),
        ]:
            b.mutate(state, 'transaction', dict(date=date, amount=amount, description=description,
                     kind=kind, category='Miscellaneous', allocations=allocations))
        annual, dinner, shared, partial = state['transactions']
        b.mutate(state, 'links', {'id': shared['id'], 'links': [
            {'expense_id': dinner['id'], 'amount': '10'}, {'expense_id': annual['id'], 'amount': '20'}]})
        b.mutate(state, 'links', {'id': partial['id'], 'links': [{'expense_id': annual['id'], 'amount': '5'}]})
        original = copy.deepcopy(state); result = b.snapshot(state)
        self.assertEqual(state, original)
        a, d, c, p = result['transactions']
        self.assertEqual(a['allocations'], state['allocations'][:3])
        self.assertEqual(a['links'], state['links'][1:])
        self.assertEqual(d['links'], state['links'][:1])
        self.assertEqual(c['links'], state['links'][:2])
        self.assertEqual(p['links'], state['links'][2:])
        self.assertEqual([t['linked_cents'] for t in result['transactions']], [2500, 1000, 3000, 500])
        self.assertEqual([result['summaries'][m]['total'] for m in ['2026-01', '2026-02', '2026-03']], [7500, 2501, 2500])
        self.assertEqual(result['summaries']['2026-05']['unresolved_cents'], 500)

    def test_custom_categories_import_subscription_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'; path.write_text(json.dumps(self.config()))
            b.configure(path)
            s = b.empty()
            text = 'Date,Account,Description,Category,Amount\n2026-09-01,Demo,Home,Rent,-1000\n2026-09-05,Demo,Example App,Online Services,-12\n2026-10-05,Demo,Example App,Online Services,-12\n'
            p = b.preview_import(s, text, 'demo.csv'); b.commit_import(s, p, {})
            self.assertEqual(s['transactions'][0]['category'], 'Home')
            self.assertEqual(s['transactions'][1]['category'], 'Memberships')
            self.assertEqual(s['budgets']['2026-09']['Home'], 100000)
            store = b.Store(directory); store.save(s); self.assertEqual(store.load(), s)
            self.assertEqual(b.snapshot(s)['groups'], self.config()['groups'])
            original = store.path.read_bytes()
            config = self.config(); config['categories']['Extra'] = 0; config['groups']['Flexible'].append('Extra')
            path.write_text(json.dumps(config)); b.configure(path)
            with self.assertRaises(b.Invalid): store.load()
            self.assertEqual(store.path.read_bytes(), original)

    def test_invalid_config_does_not_change_runtime(self):
        cases = []
        for value in ['NaN', '-1', '1.001']:
            c = self.config(); c['categories']['Home'] = value; cases.append(c)
        c = self.config(); c['category_map']['rent'] = 'Missing'; cases.append(c)
        c = self.config(); c['groups']['Flexible'].append('Home'); cases.append(c)
        c = self.config(); c['subscription_category'] = None; cases.append(c)
        c = self.config(); c['category_map'][' RENT '] = 'Other'; cases.append(c)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            for config in cases:
                path.write_text(json.dumps(config))
                with self.assertRaises(b.Invalid): b.configure(path)
                self.assertEqual(b.CATEGORIES, self.original[0])

    def test_demo_allocations_credits_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as parent:
            folder = Path(parent) / 'demo'; create_demo(folder)
            self.assertEqual(json.loads((folder / 'config.json').read_text()), DEMO_CONFIG)
            snapshot = b.snapshot(b.Store(folder).load())
            categories = [f'Category {i}' for i in range(1, 8)]
            self.assertEqual(snapshot['categories'], categories)
            october = snapshot['summaries']['2026-10']
            self.assertEqual((october['planned'], october['gross'], october['credits'], october['total']),
                             (200000, 180000, 20000, 160000))
            self.assertTrue(october['complete'])
            self.assertTrue(october['reviewed'])
            self.assertEqual([october['categories'][c]['net'] for c in categories],
                             [40000, 30000, 20000, 40000, 20000, 10000, 0])
            for category, row in october['categories'].items():
                amounts = [october['budget'][category], row['gross'], row['credits'], row['net'],
                           row['net'] - october['budget'][category]]
                self.assertTrue(all(value == 0 or 10000 <= abs(value) <= 50000 for value in amounts), category)
            self.assertEqual(snapshot['summaries']['2026-11']['categories']['Category 4']['net'], 0)
            annual = next(t for t in snapshot['transactions'] if t['description'] == 'Annual insurance')
            self.assertEqual((annual['date'], annual['cents'], len(annual['allocations'])),
                             ('2026-08-10', -360000, 12))
            self.assertTrue(all(a['cents'] == 30000 for a in annual['allocations']))
            self.assertEqual(annual['linked_cents'], 120000)
            dinner = next(t for t in snapshot['transactions'] if t['description'] == 'Dinner with friends')
            self.assertEqual((dinner['cents'], dinner['linked_cents']), (-30000, 10000))
            original = {name: (folder / name).read_bytes() for name in ['dashboard_data.csv', 'config.json']}
            with self.assertRaises(FileExistsError): create_demo(folder)
            self.assertEqual({name: (folder / name).read_bytes() for name in original}, original)


if __name__ == '__main__':
    unittest.main()
