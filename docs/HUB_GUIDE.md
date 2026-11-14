# Web Hub — Uploading and Organizing Pages

## Everyday use after activation

Open the appropriate folder in GitHub, upload your file, and commit the upload. The **Build and validate Web Hub** workflow rebuilds the published index. Once that run is green and deployment finishes, reload the live site. You do not edit or rename `index.html` for routine additions.

For a new folder on Android, use **Add file → Create new file** and enter a path such as `Flashcards/placeholder`. Commit it, open the new folder, and upload the real files there. A placeholder alone does not create a visible hub section. Delete it once real content is present.

Example: uploading `Flashcards/cranial_nerves.html` automatically creates a **Flashcards** section and its resource card. Upload a new OTS version into `TSC-Work/OTS-Generator/`, not the repository root.

## Automatic rules

| Addition | Result |
|---|---|
| New root-level content folder | New category after configured categories, alphabetically |
| `.html` or `.htm` | Webpage card |
| PDF without a matching webpage | PDF card |
| Matching HTML and PDF, same folder and basename | One resource with a printable-PDF alternative |
| `Tool_v2_10_0.html` alongside `Tool_v2_9_9.html` | v2.10.0 current; v2.9.9 under Older versions |
| A new file in a nested folder | That folder appears within its category |
| A folder with `index.html` | One project card; its helper pages are not separately listed by default |
| Supported file left at the root | Uncategorized |
| Images, audio, CSS, JavaScript, JSON, GeoJSON, ZIPs, or placeholders | Support files, not cards |

Versions group only when their directory and version-free basename match. `ducks.html` and `ducks_2.html` remain separate resources. A PDF for an older release stays with that release, never silently attached to the newest HTML. Filename versions, not upload dates or internal page titles, determine version order. Equivalent duplicates such as `Tool_v2_2.html` and `Tool_v2_2_0.html` deliberately stop the build instead of choosing arbitrarily.

Known broken OTS v2.1.6 is excluded even if uploaded again. In this migration, v2.2.0 remains current and the seven valid older releases remain available.

## Organize Hub: one optional configuration file

The **Organize Hub** shortcut opens `hub_config.json`. You only edit it for an exception; new pages and folders require no configuration entry.

JSON requires double quotes, commas between entries, and no trailing comma after the last entry. A malformed configuration fails validation and does not replace the previously successful published site.

### Category order and names

`category_order` lists preferred top-level folder names in order. New unlisted categories appear afterward alphabetically. `categories` can set `label`, `icon`, `open`, `hidden`, or numeric `order`. An explicit numeric order overrides the default position; smaller values come first. Uncategorized is last by default.

### Nested folders

`folders` uses full folder paths. It can set `label`, `order`, `open`, `hidden`, or `mode`.

```json
"folders": {
  "TSC-Work/OTS-Generator": {"label": "OTS Generator", "order": 10},
  "TSC-Work/Logo-Generator": {"label": "Logo Generator", "order": 20},
  "Experiments/Project-With-Many-Pages": {"mode": "contents"}
}
```

`mode: "contents"` lists pages inside a folder even when that folder has an `index.html`. The default is one project card for such a folder. `hidden: true` on a folder hides its whole subtree from navigation.

Within a folder, individual cards appear before child-folder groups. Cards sort by their configured item order, then by visible label; child folders have their own order, then label. Folder and category open/closed choices are remembered on each device, so `open` is an initial default, not a forced preference.

### Individual items

Keys use the full path without the extension or version suffix. A folder entry page uses its folder path as the key.

```json
"TSC-Work/OTS-Generator/TSC_OTS_Generator": {
  "label": "TSC OTS Generator",
  "icon": "📅",
  "order": 10
}
```

Supported options: `label`, `icon`, `description`, `order`, `hidden`, `category`, and `current`. Normally omit `current` so the newest release wins. To temporarily keep an older working release current, set `current` to its exact full HTML path. That path must belong to the same resource group.

A `category` override changes only the visible grouping. It does not physically move any files. Removing an override restores automatic organization.

Labels use this priority: configured label, HTML `<title>` with a trailing version removed, then cleaned filename. Hyphens and underscores in fallback names become spaces.

### Hide particular files

Add paths or patterns to `discovery.hidden_paths`. `*` matches within a folder; `**` crosses folders; `**/` also matches at the root.

```json
"hidden_paths": [
  "**/TSC_OTS_Generator_v2_1_6.html",
  "Experiments/test_*"
]
```

Names beginning with `.` or `_`, and the configured support folders, are omitted from discovery. Case matters in filenames and folder names.

**Hiding is not privacy.** A hidden resource can still be opened by its direct URL, and this repository is public. Do not upload private material here. Images/audio needed by pages are published even though they are not navigation cards.

### Optional external links

`custom_items` can contain entries with `label`, `url` (HTTP or HTTPS), `category`, `icon`, `description`, `order`, and `hidden`. Leave it empty for an entirely file-driven hub.

## What was reorganized

The real repository now uses Apps, Web-Tools, TSC-Work, GPT-Tools, Articles, Duck-Game, Experiments, Lego, and Guides. The existing Campus Map ZIP was extracted to `Experiments/Campus-Map/`, and the original ZIP remains under `Archives/Source-Packages/`.

`docs/migration_map.json` records all original/new paths and SHA-256 checksums. The 23 moved files and six extracted ZIP members were preserved without application-content edits. Only the two empty folder-creation placeholders were deleted.

Existing OTS source inconsistency retained: the file named `TSC_OTS_Generator_v2_2_0.html` has an internal title of v2.1.9.11. The hub correctly follows the filename. Repairing the application's internal labeling is a separate task.

## How the automation works

A repository commit triggers the workflow. It validates configuration and local links, scans tracked files, generates `hub_manifest.json`, inserts the cards into the deployment copy of `index.html`, runs browser checks, and deploys the complete site only from `main`.

The repository's root `index.html` is a stable source template. The generated deployment copy is also named `index.html`, with a date/time/timezone comment. The cards are ordinary HTML, so they work without JavaScript and do not depend on the public GitHub API. JavaScript adds search, theme switching, and remembered folder state. The manifest is an inspectable build output, not a runtime dependency or a file to edit manually.

## Existing bookmarks and asset links

`hub_redirects.json` stores the migration's old-to-new paths. The deployment build creates small redirect pages at the 17 old HTML addresses, preserving query strings and fragments. These are browser redirects, not server-side HTTP 301 responses. It also publishes byte-identical compatibility copies at six old image/audio/ZIP addresses. A 404 HTML page alone cannot fix embedded image or audio requests.

Compatibility files exist only in the generated deployment, not as clutter in the repository root. A generic `404.html` returns visitors to the hub for unknown addresses. Future file moves appear automatically in navigation, but preserving additional old bookmarks requires adding their old/new pair to `hub_redirects.json`. Update those mappings when deliberately removing or moving a target again; missing targets fail the build.

## Review and activation — Carl approves the live change

The migration is prepared on `reorganize-hub`. Do not merge it or change Pages settings until Carl approves the review.

After approval, the one-time activation is:

1. Open repository **Settings → Pages** and select **GitHub Actions** as the publishing source. The workflow does not change this setting for you.
2. Merge the reviewed pull request into `main`.
3. Check the **Build and validate Web Hub** Actions run and its deployment job, then open the live hub.

The review branch and pull-request checks do not deploy to the live site. Their downloadable `hub-preview` artifact is the built site; `hub-browser-report` contains browser results and screenshots. These artifacts are not a hosted preview and expire after 14 days.

GitHub reference: https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages

## Tests and local preview

```sh
python -m unittest discover -s tests -v
python scripts/build_manifest.py --root . --output _site
python -m pip install playwright==1.57.0
python -m playwright install chromium
python tests/browser_checks.py --site _site --report-dir /tmp/hub-browser
python -m http.server 8000 --directory _site
```

For the one-time migration audit only, prefix the test commands with `HUB_MIGRATION_AUDIT=1`. It verifies original checksums and the initial inventory, and compares app loads before/after relocation. This mode runs on the migration review branch, not routine `main` builds, so future additions and intentional app updates are not constrained to today's inventory.

Browser checks use Chromium at desktop and phone-sized viewports; they do not substitute for testing a physical Android or iPhone. External CDNs, map tiles, YouTube, TSC date lookup, and export services are not end-to-end verified by the migration comparison.
