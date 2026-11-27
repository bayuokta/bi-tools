# Lucide icons (vendored)

Icon geometry comes from [Lucide](https://lucide.dev) `lucide-static` **0.468.0**,
licensed under ISC (see `LICENSE`). Only the icons the interface uses are
vendored; the package is not loaded from a CDN and there is no build step.

## Files

| File | Purpose |
|---|---|
| `icons.json` | Pinned version plus the inner SVG markup of every used icon |
| `LICENSE` | ISC license text |
| `../../index.html` | `<svg class="icon-sprite">` block with one `<symbol id="i-<name>">` per icon |

The sprite in `index.html` is the only runtime source. It is generated from
`icons.json`; a guard test (`tests/test_web_icons.py`) checks that both lists
match and that every `href="#i-..."` reference resolves.

## Usage

Static markup:

```html
<svg class="od-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
     stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"
     aria-hidden="true"><use href="#i-table"></use></svg>
```

Generated markup uses the `icon()` helper from `web/js/core/icons.js`:

```js
import { icon } from "../core/icons.js";
var markup = icon("table", "row-ico", 1.6);
```

## Regenerate

Update `version` in the snippet below, download the used icons, then rebuild the
sprite block in `index.html` between `<!-- lucide:sprite:begin -->` and
`<!-- lucide:sprite:end -->`:

```python
import json, re, urllib.request
from pathlib import Path

VERSION = "0.468.0"
names = json.loads(Path("web/vendor/lucide/icons.json").read_text("utf-8"))["icons"].keys()
icons = {}
for name in names:
    url = f"https://unpkg.com/lucide-static@{VERSION}/icons/{name}.svg"
    with urllib.request.urlopen(url) as response:
        raw = response.read().decode("utf-8")
    body = raw.split("<svg", 1)[1].split(">", 1)[1].rsplit("</svg>", 1)[0]
    icons[name] = re.sub(r"\s+", " ", body).strip()
```

Keep `icons.json`, the sprite, and `version` in sync. Do not add a CDN
`<script>` or fetch icons at runtime; `web/` must stay static (see
`tests/test_architecture.py`).
