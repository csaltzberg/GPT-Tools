"""Regression tests. HUB_MIGRATION_AUDIT=1 additionally checks the one-time baseline."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hub_builder', ROOT / 'scripts/build_manifest.py')
hub = importlib.util.module_from_spec(spec); spec.loader.exec_module(hub)
AUDIT = os.environ.get('HUB_MIGRATION_AUDIT') == '1'


def defaults():
    return {'schema_version': 1, 'site': {'title': 'Test Hub', 'timezone': 'America/New_York'},
            'discovery': {'extensions': ['.html', '.htm', '.pdf'], 'ignore_folders': ['assets', 'scripts', 'tests', 'docs', 'Archives'],
                          'ignore_paths': ['index.html', '404.html'], 'hidden_paths': ['**/TSC_OTS_Generator_v2_1_6.html'],
                          'root_category': 'Uncategorized', 'folder_index_is_project': True},
            'category_order': ['TSC-Work', 'Experiments'], 'categories': {}, 'folders': {}, 'items': {}, 'custom_items': []}


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.config = defaults()
    def add(self, name, title=None, content=None):
        p = self.root / name; p.parent.mkdir(parents=True, exist_ok=True)
        if content is None: content = f'<!doctype html><title>{title or ""}</title><p>fixture</p>' if p.suffix in ('.html', '.htm') else 'fixture'
        p.write_text(content, encoding='utf-8'); return p
    def model(self): return hub.build_model(self.root, self.config)
    def items(self): return [i for c in self.model()['categories'] for i in c['items']]
    def test_new_category_and_file_appear_without_configuration(self):
        self.add('Flashcards/cranial_nerves.html', 'Cranial Nerves')
        self.assertEqual(self.model()['categories'][0]['key'], 'Flashcards')
        self.assertEqual(self.model()['item_count'], 1); self.assertEqual(self.items()[0]['label'], 'Cranial Nerves')
    def test_no_section_for_assets_or_empty_placeholder(self):
        for p in ['Photos/photo.jpg', 'New-Folder/placeholder', 'assets/test.html']: self.add(p)
        self.assertEqual(self.model()['categories'], [])
    def test_root_files_use_uncategorized(self):
        self.add('new_demo.html'); self.assertEqual(self.model()['categories'][0]['key'], 'Uncategorized')
    def test_index_and_system_files_are_not_cards(self):
        for p in ['index.html', '404.html', '.github/a.html', 'scripts/a.html', '_Draft/a.html', 'A/_draft.html']: self.add(p)
        self.assertEqual(self.items(), [])
    def test_label_priority(self):
        self.add('Examples/a.html', 'Inside Title'); self.add('Examples/fallback_name.html')
        self.config['items']['Examples/a'] = {'label': 'Custom Label'}
        self.assertEqual([i['label'] for i in self.items()], ['Custom Label', 'Fallback Name'])
    def test_known_and_new_category_order(self):
        for cat in ['Zebra', 'TSC-Work', 'Alpha', 'Experiments']: self.add(cat + '/test.html')
        self.assertEqual([c['key'] for c in self.model()['categories']], ['TSC-Work', 'Experiments', 'Alpha', 'Zebra'])
    def test_numeric_category_override(self):
        self.add('Experiments/a.html'); self.add('New/b.html'); self.config['categories']['New'] = {'order': -10}
        self.assertEqual(self.model()['categories'][0]['key'], 'New')
    def test_items_alphabetical_unless_ordered(self):
        for title in ['Zebra', 'Alpha', 'Beta']: self.add('Examples/' + title + '.html', title)
        self.config['items']['Examples/Zebra'] = {'order': 1}
        self.assertEqual([i['label'] for i in self.items()], ['Zebra', 'Alpha', 'Beta'])
    def test_versions_are_numeric_and_newest_is_current(self):
        for v in ['2_9_9', '2_10_0', '1_5', '2_2_0']: self.add(f'TSC-Work/OTS/TSC_OTS_Generator_v{v}.html')
        self.assertEqual(self.items()[0]['current']['version'], '2.10.0')
        self.assertEqual([r['version'] for r in self.items()[0]['older']], ['2.9.9', '2.2.0', '1.5'])
        self.add('TSC-Work/OTS/TSC_OTS_Generator_v3_0_0.html'); self.assertEqual(self.items()[0]['current']['version'], '3.0.0')
    def test_version_group_does_not_cross_directories(self):
        self.add('A/demo_v1_0.html'); self.add('B/demo_v2_0.html')
        self.assertEqual(len(self.items()), 2); self.assertTrue(all(not i['older'] for i in self.items()))
    def test_non_version_number_is_a_separate_item(self):
        self.add('Duck-Game/ducks.html'); self.add('Duck-Game/ducks_2.html'); self.assertEqual(len(self.items()), 2)
    def test_broken_ots_version_hidden_at_any_depth(self):
        for prefix in ['', 'TSC-Work/OTS/']: self.add(prefix + 'TSC_OTS_Generator_v2_1_6.html')
        self.assertEqual(self.items(), [])
    def test_equivalent_version_collision_fails_clearly(self):
        self.add('A/demo_v2_2.html'); self.add('A/demo_v2_2_0.html')
        with self.assertRaisesRegex(ValueError, 'Ambiguous'): self.model()
    def test_matching_pdf_attaches_to_exact_release(self):
        self.add('A/demo_v1_0.html'); self.add('A/demo_v1_0.pdf'); self.add('A/demo_v2_0.html')
        self.assertEqual(self.items()[0]['current']['alternatives'], [])
        self.assertEqual(self.items()[0]['older'][0]['alternatives'][0]['path'], 'A/demo_v1_0.pdf')
    def test_unversioned_html_pdf_pair(self):
        self.add('Lego/codes.html'); self.add('Lego/codes.pdf'); self.assertEqual(len(self.items()), 1)
        self.assertEqual(self.items()[0]['current']['alternatives'][0]['label'], 'Printable PDF')
    def test_standalone_pdf_is_a_card(self):
        self.add('Guides/print.pdf'); self.assertEqual(self.items()[0]['current']['path'], 'Guides/print.pdf')
    def test_folder_index_is_single_project_by_default(self):
        for p in ['Experiments/Map/index.html', 'Experiments/Map/help.html', 'Experiments/Map/data/a.json']: self.add(p)
        self.assertEqual(len(self.items()), 1); self.assertEqual(self.items()[0]['key'], 'Experiments/Map')
    def test_folder_mode_can_expose_child_pages(self):
        self.add('Examples/Project/index.html'); self.add('Examples/Project/help.html')
        self.config['folders']['Examples/Project'] = {'mode': 'contents'}; self.assertEqual(len(self.items()), 2)
    def test_folder_hide_includes_descendants(self):
        self.add('Examples/Private/Sub/a.html'); self.add('Examples/Public/b.html')
        self.config['folders']['Examples/Private'] = {'hidden': True}; self.assertEqual(len(self.items()), 1)
    def test_category_and_item_visibility(self):
        self.add('A/a.html'); self.add('B/b.html'); self.config['categories']['A'] = {'hidden': True}; self.config['items']['B/b'] = {'hidden': True}
        self.assertEqual(self.items(), [])
    def test_custom_current_pin(self):
        self.add('A/tool_v1_0.html'); self.add('A/tool_v2_0.html'); self.config['items']['A/tool'] = {'current': 'A/tool_v1_0.html'}
        self.assertEqual(self.items()[0]['current']['version'], '1.0')
    def test_custom_category_changes_navigation_not_files(self):
        self.add('A/Folder/demo.html'); self.config['items']['A/Folder/demo'] = {'category': 'Featured'}
        self.assertEqual(self.model()['categories'][0]['key'], 'Featured'); self.assertEqual(self.items()[0]['current']['path'], 'A/Folder/demo.html'); self.assertEqual(self.items()[0]['folder'], [])
    def test_unsafe_custom_urls_rejected(self):
        self.config['custom_items'] = [{'label': 'Unsafe', 'url': 'javascript:alert(1)'}]
        with self.assertRaises(ValueError): self.model()
    def test_titles_are_escaped_and_url_characters_encoded(self):
        self.add('A/a #?%.html', '&lt;img src=x onerror=alert(1)&gt;'); rendered = hub.render_model(self.model(), self.config)
        self.assertNotIn('<img src=x', rendered); self.assertIn('&lt;img', rendered); self.assertIn('a%20%23%3F%25.html', rendered)
    def test_folder_labels_and_order(self):
        self.add('A/Zebra/a.html'); self.add('A/Alpha/b.html'); self.config['folders']['A/Zebra'] = {'order': 1, 'label': 'First folder'}
        rendered = hub.render_model(self.model(), self.config); self.assertLess(rendered.index('First folder'), rendered.index('A/Alpha'))
    def test_glob_semantics(self):
        self.assertTrue(hub.glob_matches('bad.html', '**/bad.html')); self.assertTrue(hub.glob_matches('A/B/bad.html', '**/bad.html')); self.assertFalse(hub.glob_matches('A/B/bad.html', 'A/*.html'))
    def test_invalid_config_fails_instead_of_publishing_empty_hub(self):
        self.config['items']['x'] = {'order': 'first'}
        with self.assertRaisesRegex(ValueError, 'numeric'): self.model()
    def test_output_cannot_overwrite_source(self):
        with self.assertRaises(ValueError): hub.build(self.root, self.root, self.config)
    def test_missing_redirect_target_stops_build(self):
        self.add('index.html', content='<!doctype html><!-- Web Hub revision: test -->' + hub.START + hub.END)
        self.add('hub_redirects.json', content=json.dumps({'old.html': 'missing.html'}))
        with self.assertRaisesRegex(ValueError, 'Redirect target missing'): hub.build(self.root, self.root / '_site', self.config)


class LinkParser(HTMLParser):
    def __init__(self): super().__init__(); self.urls = []
    def handle_starttag(self, tag, attrs):
        self.urls.extend(v for k, v in attrs if v and k in ('href', 'src', 'poster'))


class RepositoryTests(unittest.TestCase):
    @unittest.skipUnless(AUDIT, 'One-time audit; future intentional app updates must not be blocked')
    def test_migration_byte_preservation(self):
        record = json.loads((ROOT / 'docs/migration_map.json').read_text())
        for row in record['moves']:
            with self.subTest(path=row['to']):
                self.assertEqual(hashlib.sha256((ROOT / row['to']).read_bytes()).hexdigest(), row['sha256']); self.assertFalse((ROOT / row['from']).exists())
        for row in record['extracted']: self.assertEqual(hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest(), row['sha256'])
    def test_real_hub_and_legacy_targets(self):
        config = json.loads((ROOT / 'hub_config.json').read_text())
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'site'; model = hub.build(ROOT, out, config)
            items = [i for c in model['categories'] for i in c['items']]
            self.assertEqual(model['item_count'], len(items))
            if AUDIT:
                self.assertEqual(len(items), 14)
                ots = next(i for i in items if i['label'] == 'TSC OTS Generator')
                self.assertEqual(ots['current']['version'], '2.2.0')
                self.assertEqual([r['version'] for r in ots['older']], ['2.1.8', '2.1.5', '2.1', '2.0', '1.9', '1.8', '1.5'])
            page = (out / 'index.html').read_text(); self.assertNotIn('{{', page); self.assertIn('Web Hub revision:', page)
            redirects = json.loads((ROOT / 'hub_redirects.json').read_text())
            for old, new in redirects.items():
                self.assertTrue((out / old).is_file()); self.assertTrue((out / new).is_file())
                if not old.endswith(('.html', '.htm')): self.assertEqual((out / old).read_bytes(), (out / new).read_bytes())
                else: self.assertIn('target.search=location.search', (out / old).read_text())
            broken = []
            for path in out.rglob('*.html'):
                parser = LinkParser(); parser.feed(path.read_text(encoding='utf-8', errors='replace'))
                for url in parser.urls:
                    u = urlsplit(url)
                    if u.scheme or u.netloc or not u.path or any(x in url for x in ('${', '{{')): continue
                    if u.path.startswith('/'):
                        base = config['site']['base_path']
                        if not u.path.startswith(base): continue
                        target = out / unquote(u.path[len(base):])
                    else: target = path.parent / unquote(u.path)
                    if not target.exists(): broken.append((str(path.relative_to(out)), url))
            self.assertEqual(broken, [], f'Broken same-site references: {broken}')
            for path in out.rglob('*.geojson'): self.assertEqual(json.loads(path.read_text())['type'], 'FeatureCollection')
            self.assertFalse((out / 'scripts').exists()); self.assertFalse((out / '.github').exists())

if __name__ == '__main__': unittest.main()
