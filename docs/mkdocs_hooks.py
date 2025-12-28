"""MkDocs hooks to provide legacy .md URLs alongside pretty URLs."""

from __future__ import annotations

from pathlib import Path
from typing import Dict


_DOC_REDIRECTS: Dict[str, str] = {}

_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Redirecting...</title>
  <link rel="canonical" href="{url}">
  <script>
    var anchor = window.location.hash.substr(1);
    location.href = "{url}" + (anchor ? "#" + anchor : "");
  </script>
  <meta http-equiv="refresh" content="0; url={url}">
</head>
<body>
  You're being redirected to a <a href="{url}">new destination</a>.
</body>
</html>
"""


def on_files(files, config, **kwargs):  # type: ignore[override]
    """Capture documentation pages to generate .md redirects after build."""
    global _DOC_REDIRECTS
    _DOC_REDIRECTS = {}
    for doc in files.documentation_pages():
        src_path = doc.src_path.replace("\\", "/")
        url = f"/{doc.url}" if doc.url else "/"
        _DOC_REDIRECTS[src_path] = url
    return files


def on_post_build(config, **kwargs):  # type: ignore[override]
    """Write redirect pages at legacy .md paths."""
    site_dir = Path(config["site_dir"])
    for src_path, url in _DOC_REDIRECTS.items():
        redirect_dir = site_dir / src_path
        redirect_dir.mkdir(parents=True, exist_ok=True)
        (redirect_dir / "index.html").write_text(
            _HTML_TEMPLATE.format(url=url), encoding="utf-8"
        )
