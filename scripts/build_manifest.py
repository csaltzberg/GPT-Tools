#!/usr/bin/env python3
"""Build a static hub from local repository files; no API calls or third-party dependencies.

The source index is a template. Only the deployment copy is regenerated.
Hidden means absent from navigation, NOT private or excluded from publication.
"""
from __future__ import annotations
import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

VERSION = re.compile(r'^(.*?)[_-]v(\d+(?:[_.-]\d+)*)$', re.I)
RESERVED = {'.git', '.github', 'scripts', 'tests', 'docs', 'node_modules', '__pycache__', '_site', '_preview'}
ACRONYMS = {'tsc', 'ots', 'gpt', 'lego', 'html', 'pdf', 'qr', 'api', 'ai', 'si', 'bsc', 'ui'}
START, END = '<!-- HUB:START -->', '<!-- HUB:END -->'


def humanize(text):
    text = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
    words = re.sub(r'[_-]+', ' ', text).split()
    return ' '.join(w.upper() if w.lower() in ACRONYMS else w[:1].upper() + w[1:] for w in words)


def safe_path(value):
    if not isinstance(value, str) or not value or '\\' in value or value.startswith('/'):
        raise ValueError(f'Invalid repository path: {value!r}')
    if any(part in ('.', '..', '') for part in value.split('/')):
        raise ValueError(f'Invalid repository path: {value!r}')
    return value


def glob_matches(path, pattern):
    """Case-sensitive globs; **/ includes zero directory levels."""
    out, i = '', 0
    while i < len(pattern):
        if pattern[i:i+3] == '**/':
            out += '(?:.*/)?'; i += 3
        elif pattern[i:i+2] == '**':
            out += '.*'; i += 2
        elif pattern[i] == '*':
            out += '[^/]*'; i += 1
        elif pattern[i] == '?':
            out += '[^/]'; i += 1
        else:
            out += re.escape(pattern[i]); i += 1
    return re.fullmatch(out, path) is not None


def validate_config(config):
    if config.get('schema_version') != 1:
        raise ValueError('hub_config.json requires schema_version 1')
    for key in ('site', 'discovery', 'categories', 'folders', 'items'):
        if not isinstance(config.get(key, {}), dict):
            raise ValueError(f'{key} must be an object')
    for key in ('category_order', 'custom_items'):
        if not isinstance(config.get(key, []), list):
            raise ValueError(f'{key} must be a list')
    d = config.get('discovery', {})
    for key in ('extensions', 'ignore_folders', 'ignore_paths', 'hidden_paths'):
        if not isinstance(d.get(key, []), list) or not all(isinstance(x, str) for x in d.get(key, [])):
            raise ValueError(f'discovery.{key} must be a list of strings')
    for group in ('categories', 'folders', 'items'):
        for key, options in config.get(group, {}).items():
            if not isinstance(options, dict):
                raise ValueError(f'{group}.{key} must be an object')
            if 'order' in options and (isinstance(options['order'], bool) or not isinstance(options['order'], (int, float))):
                raise ValueError(f'{group}.{key}.order must be numeric')
            if 'hidden' in options and not isinstance(options['hidden'], bool):
                raise ValueError(f'{group}.{key}.hidden must be true or false')
            if group == 'folders' and options.get('mode', 'project') not in ('project', 'contents'):
                raise ValueError(f'{group}.{key}.mode must be project or contents')
    ZoneInfo(config.get('site', {}).get('timezone', 'America/New_York'))


class TitleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False; self.done = False; self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag == 'title' and not self.done: self.active = True
    def handle_endtag(self, tag):
        if tag == 'title' and self.active: self.active = False; self.done = True
    def handle_data(self, data):
        if self.active: self.parts.append(data)


def page_title(path):
    if path.suffix.lower() not in ('.html', '.htm'): return ''
    parser = TitleParser()
    with path.open(encoding='utf-8', errors='replace') as stream:
        for _ in range(64):
            chunk = stream.read(4096)
            if not chunk: break
            parser.feed(chunk)
            if parser.done: break
    text = ' '.join(''.join(parser.parts).split())
    return re.sub(r'\s*(?:[|—–-]\s*)?v\d+(?:[_.-]\d+)*\s*$', '', text, flags=re.I).strip()


def discover_paths(root):
    # CI uses tracked files only. Extracted review ZIPs also work without a Git checkout.
    if (root / '.git').exists():
        names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    else:
        names = [p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()]
    result = []
    for name in names:
        if not name or name.split('/')[0] in RESERVED: continue
        safe_path(name)
        path = root / name
        if path.is_symlink(): raise ValueError(f'Symlinks are not published: {name}')
        if path.is_file(): result.append(name)
    return sorted(set(result))


def hidden(path, config):
    parts = path.split('/'); d = config.get('discovery', {})
    if any(p.startswith(('.', '_')) for p in parts): return True
    if any(p in d.get('ignore_folders', []) for p in parts[:-1]): return True
    if path in d.get('ignore_paths', ['index.html', '404.html']): return True
    if any(glob_matches(path, p) for p in d.get('hidden_paths', [])): return True
    return any(config.get('folders', {}).get('/'.join(parts[:i]), {}).get('hidden', False)
               for i in range(1, len(parts)))


def build_model(root, config, paths=None):
    validate_config(config)
    paths = discover_paths(root) if paths is None else sorted(paths)
    d = config.get('discovery', {}); extensions = d.get('extensions', ['.html', '.htm', '.pdf'])
    visible = [p for p in paths if Path(p).suffix.lower() in extensions and not hidden(p, config)]
    project_dirs = set()
    if d.get('folder_index_is_project', True):
        project_dirs = {str(PurePosixPath(p).parent) for p in visible
                        if '/' in p and Path(p).name.lower() in ('index.html', 'index.htm')
                        and config.get('folders', {}).get(str(PurePosixPath(p).parent), {}).get('mode') != 'contents'}
    groups = {}
    for path in visible:
        p = PurePosixPath(path); directory = '' if str(p.parent) == '.' else str(p.parent)
        containing = [x for x in project_dirs if path.startswith(x + '/')]
        if containing:
            project = min(containing, key=lambda x: len(x.split('/')))
            if directory != project or p.name.lower() not in ('index.html', 'index.htm', 'index.pdf'):
                continue
        parsed = VERSION.fullmatch(p.stem)
        base, version = (parsed[1], parsed[2]) if parsed else (p.stem, None)
        parts = tuple(map(int, re.split(r'[_.-]', version))) if version else ()
        normalized = parts
        while normalized and normalized[-1] == 0: normalized = normalized[:-1]
        version_key = normalized if version is not None else None
        key = directory if p.stem.lower() == 'index' and directory else '/'.join(x for x in (directory, base) if x)
        group = groups.setdefault(key, {'key': key, 'directory': directory, 'base': base, 'variants': {}})
        variant = group['variants'].setdefault(version_key, {'version': '.'.join(map(str, parts)) if version else None, 'formats': {}})
        ext = p.suffix.lower()
        if ext in variant['formats']:
            raise ValueError(f'Ambiguous equivalent versions: {variant["formats"][ext]} and {path}')
        variant['formats'][ext] = path
    categories = defaultdict(list)
    root_category = d.get('root_category', 'Uncategorized')
    for group in groups.values():
        variants = sorted(group['variants'].items(), key=lambda x: (x[0] is not None, x[0] or ()), reverse=True)
        def release(v):
            fs = v['formats']; priority = sorted(fs, key=lambda e: (['.html', '.htm', '.pdf'].index(e) if e in ['.html', '.htm', '.pdf'] else 99, e))
            return {'version': v['version'], 'path': fs[priority[0]],
                    'alternatives': [{'path': fs[e], 'label': 'Printable PDF' if e == '.pdf' else 'Webpage'} for e in priority[1:]]}
        releases = [release(v) for _, v in variants]
        options = config.get('items', {}).get(group['key'], {})
        if options.get('hidden'): continue
        if options.get('current'):
            selected = next((r for r in releases if r['path'] == options['current']), None)
            if selected is None: raise ValueError(f'Configured current file not in group: {group["key"]}')
            releases.remove(selected); releases.insert(0, selected)
        current = releases[0]
        category = group['directory'].split('/')[0] if group['directory'] else root_category
        folder = group['directory'].split('/')[1:]
        if Path(current['path']).stem.lower() == 'index' and folder: folder = folder[:-1]
        physical_category = category
        if options.get('category') and options['category'] != category:
            category = options['category']; folder = []
        if config.get('categories', {}).get(category, {}).get('hidden'): continue
        fallback = Path(group['directory']).name if group['base'].lower() == 'index' else group['base']
        label = options.get('label') or page_title(root / current['path']) or humanize(fallback)
        item = {'key': group['key'], 'label': label, 'icon': options.get('icon', '📄' if current['path'].lower().endswith('.pdf') else '🌐'),
                'description': options.get('description', ''), 'order': options.get('order', 10000),
                'folder': folder, 'physical_category': physical_category, 'current': current, 'older': releases[1:]}
        categories[category].append(item)
    for custom in config.get('custom_items', []):
        if custom.get('hidden'): continue
        if not custom.get('label') or urlsplit(custom.get('url', '')).scheme not in ('https', 'http'):
            raise ValueError('Custom items require a label and an http(s) URL')
        categories[custom.get('category', root_category)].append({'key': 'custom:' + custom['url'], 'label': custom['label'],
            'icon': custom.get('icon', '🔗'), 'description': custom.get('description', ''), 'order': custom.get('order', 10000),
            'folder': [], 'current': {'path': custom['url'], 'version': None, 'alternatives': []}, 'older': [], 'external': True})
    order = config.get('category_order', [])
    output = []
    for key, items in categories.items():
        options = config.get('categories', {}).get(key, {})
        if options.get('hidden'): continue
        output.append({'key': key, 'label': options.get('label', humanize(key)), 'icon': options.get('icon', '📦' if key == root_category else '📁'),
            'open': options.get('open', False), 'order': options.get('order', order.index(key) * 10 if key in order else 20000 if key == root_category else 10000),
            'items': sorted(items, key=lambda x: (x['order'], x['label'].casefold(), x['key']))})
    output.sort(key=lambda x: (x['order'], x['label'].casefold(), x['key']))
    return {'schema_version': 1, 'categories': output, 'item_count': sum(len(c['items']) for c in output)}


def esc(value): return html.escape(str(value), quote=True)

def href(path):
    return esc(path if urlsplit(path).scheme in ('https', 'http') else quote(safe_path(path), safe='/'))


def render_item(item):
    current = item['current']; versions = [current] + item['older']
    search = [item['label'], item['description'], item['key']]
    for v in versions:
        search.extend([v['path'], 'v' + (v['version'] or '')])
        search.extend(f['path'] + ' ' + f['label'] for f in v['alternatives'])
    chunks = [f'<article class="hub-item" data-key="{esc(item["key"])}" data-search="{esc(" ".join(search).lower())}">']
    chunks.append(f'<a class="card" href="{href(current["path"])}"><span class="emoji" aria-hidden="true">{esc(item["icon"])}</span><span class="card-copy"><span class="card-title">{esc(item["label"])}</span>')
    if current['version']: chunks.append(f'<span class="badge">Current v{esc(current["version"])}</span>')
    chunks.append(f'<span class="card-file">{esc(current["path"])}</span>')
    if item['description']: chunks.append(f'<span class="description">{esc(item["description"])}</span>')
    chunks.append('</span></a>')
    for alt in current['alternatives']:
        chunks.append(f'<a class="alternative" href="{href(alt["path"])}">{esc(alt["label"])}<span class="card-file">{esc(alt["path"])}</span></a>')
    if item['older']:
        chunks.append(f'<details class="versions"><summary>Older versions ({len(item["older"])})</summary><div class="version-links">')
        for v in item['older']:
            text = 'v' + v['version'] if v['version'] else 'Unversioned copy'
            chunks.append(f'<div class="version-row" data-search="{esc((text + " " + v["path"] + " " + " ".join(a["path"] for a in v["alternatives"])).lower())}"><a href="{href(v["path"])}">{esc(item["label"])} {esc(text)}<span class="card-file">{esc(v["path"])}</span></a>')
            for alt in v['alternatives']: chunks.append(f'<a href="{href(alt["path"])}">{esc(alt["label"])}</a>')
            chunks.append('</div>')
        chunks.append('</div></details>')
    chunks.append('</article>')
    return ''.join(chunks)


def render_model(model, config):
    def contents(items, category, prefix=()):
        direct = [i for i in items if tuple(i['folder']) == prefix]
        out = ['<div class="cards">' + ''.join(render_item(i) for i in direct) + '</div>'] if direct else []
        children = {i['folder'][len(prefix)] for i in items if len(i['folder']) > len(prefix) and tuple(i['folder'][:len(prefix)]) == prefix}
        def opts(name): return config.get('folders', {}).get('/'.join((category,) + prefix + (name,)), {})
        for name in sorted(children, key=lambda n: (opts(n).get('order', 10000), opts(n).get('label', humanize(n)).casefold())):
            key = '/'.join((category,) + prefix + (name,)); options = opts(name)
            out.append(f'<details class="folder" data-folder="{esc(key)}" {"open" if options.get("open", True) else ""}><summary>📁 {esc(options.get("label", humanize(name)))}</summary>')
            out.append(contents(items, category, prefix + (name,))); out.append('</details>')
        return ''.join(out)
    out = []
    for c in model['categories']:
        out.append(f'<details class="section" data-category="{esc(c["key"])}" {"open" if c["open"] else ""}><summary><span>{esc(c["icon"])} {esc(c["label"])}</span> <span class="count">{len(c["items"])}</span></summary>')
        out.append(contents(c['items'], c['key'])); out.append('</details>')
    return '\n'.join(out)


def redirect_document(old, new):
    relative = quote(os.path.relpath(new, str(PurePosixPath(old).parent)).replace(os.sep, '/'), safe='/')
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Page moved</title><meta name="robots" content="noindex">'
            f'<meta http-equiv="refresh" content="0;url={esc(relative)}">'
            f'<p>This page has moved. <a id="destination" href="{esc(relative)}">Continue to the page</a>.</p>'
            '<script>const target=new URL(document.getElementById("destination").href);target.search=location.search;target.hash=location.hash;location.replace(target.href);</script></html>')


def build(root, output, config):
    root, output = root.resolve(), output.resolve()
    if output == root or output in root.parents or (output.is_relative_to(root) and output.relative_to(root).parts[0] not in ('_site', '_preview')):
        raise ValueError('Use a dedicated _site or _preview output directory, never a source directory')
    paths = discover_paths(root)
    model = build_model(root, config, paths)
    now = datetime.now(ZoneInfo(config.get('site', {}).get('timezone', 'America/New_York')))
    model['generated'] = now.isoformat(timespec='seconds')
    model['source_commit'] = os.environ.get('GITHUB_SHA', 'local-preview')
    if output.exists() and any(output.iterdir()) and not (output / '.hub-build').exists():
        raise ValueError('Refusing to clear an output directory not created by this builder')
    if output.exists(): shutil.rmtree(output)
    output.mkdir(parents=True); (output / '.hub-build').write_text('Generated by build_manifest.py\n')
    for name in paths:
        if name.split('/')[0].startswith('.'): continue
        target = output / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, target)
    template = (root / 'index.html').read_text(encoding='utf-8')
    if template.count(START) != 1 or template.count(END) != 1: raise ValueError('Index template requires one HUB:START and HUB:END marker')
    result = template.split(START)[0] + START + '\n' + render_model(model, config) + '\n' + END + template.split(END)[1]
    result = re.sub(r'<!-- Web Hub revision:.*?-->', f'<!-- Web Hub revision: {now.strftime("%Y-%m-%d %H:%M:%S %Z %z")} -->', result)
    result = result.replace('{{SITE_TITLE}}', esc(config['site']['title'])).replace('{{SITE_SUBTITLE}}', esc(config['site'].get('subtitle', '')))
    result = result.replace('{{BUILD_INFO}}', esc(f'{model["item_count"]} resources · Updated {now.strftime("%Y-%m-%d %H:%M:%S %Z")}'))
    (output / 'index.html').write_text(result, encoding='utf-8')
    (output / 'hub_manifest.json').write_text(json.dumps(model, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    redirects_file = root / 'hub_redirects.json'
    redirects = json.loads(redirects_file.read_text()) if redirects_file.exists() else {}
    for old, new in redirects.items():
        safe_path(old); safe_path(new)
        target, source = output / old, output / new
        if not source.is_file(): raise ValueError(f'Redirect target missing: {new}')
        if old in paths: raise ValueError(f'Legacy path collides with a source file: {old}')
        target.parent.mkdir(parents=True, exist_ok=True)
        if Path(old).suffix.lower() in ('.html', '.htm'):
            target.write_text(redirect_document(old, new), encoding='utf-8')
        else:
            # A 404 HTML page cannot redirect an embedded image/audio/download request.
            shutil.copy2(source, target)
            assert hashlib.sha256(target.read_bytes()).digest() == hashlib.sha256(source.read_bytes()).digest()
    (output / '.nojekyll').touch()
    print(f'Built {model["item_count"]} resources in {len(model["categories"])} categories; {len(redirects)} legacy addresses preserved.')
    return model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, default=Path('_site'))
    args = parser.parse_args()
    config = json.loads((args.root / 'hub_config.json').read_text(encoding='utf-8'))
    build(args.root, args.output, config)

if __name__ == '__main__': main()
