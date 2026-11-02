import copy
import json
from pathlib import Path
import tempfile
import unittest

import budget_server as b
from demo import create_demo, demo_state


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.original = [copy.deepcopy(v) for v in [b.CATEGORIES, b.CATEGORY_MAP, b.CATEGORY_GROUPS]]
        self.roles = b.SUBSCRIPTION_CATEGORY, b.FALLBACK_CATEGORY

    def tearDown(self):
        for target, original in zip([b.CATEGORIES, b.CATEGORY_MAP, b.CATEGORY_GROUPS], self.original):
            target.clear(); target.update(original)
        b.SUBSCRIPTION_CATEGORY, b.FALLBACK_CATEGORY = self.roles

    def config(self):
        return {'categories': {'Home': 1000, 'Memberships': 30, 'Other': 200},
                'category_map': {'rent': 'Home', 'shopping': 'Other'},
                'subscription_category': 'Memberships', 'fallback_category': 'Other',
                'groups': {'Essentials': ['Home'], 'Flexible': ['Memberships', 'Other']}}

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
        state = demo_state(); snapshot = b.snapshot(state)
        self.assertEqual(snapshot['summaries']['2026-10']['categories']['Auto insurance']['net'], 8000)
        self.assertEqual(snapshot['summaries']['2026-10']['categories']['Groceries+Food']['net'], 36000)
        self.assertEqual(snapshot['summaries']['2026-11']['categories']['Groceries+Food']['net'], 0)
        annual = next(t for t in snapshot['transactions'] if t['description'] == 'Annual insurance')
        self.assertEqual((annual['date'], annual['cents'], len(annual['allocations'])), ('2026-08-10', -120000, 12))
        with tempfile.TemporaryDirectory() as parent:
            folder = Path(parent) / 'demo'; create_demo(folder)
            original = (folder / 'dashboard_data.csv').read_bytes()
            with self.assertRaises(FileExistsError): create_demo(folder)
            self.assertEqual((folder / 'dashboard_data.csv').read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
