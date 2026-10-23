from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
PORTAL = (ROOT / "request_web/frontend/src/Portal.tsx").read_text(encoding="utf-8")
CSS = (ROOT / "request_web/frontend/src/portal.css").read_text(encoding="utf-8")


def test_corporate_apparel_entry_is_enabled_admin_only():
    assert 'currentUser?.permission_status === "enabled" && currentUser.roles.includes("管理员")' in PORTAL
    entry = re.search(r'\{canManage && <a\s+(.*?)</a>\}', PORTAL, re.S)
    assert entry is not None
    assert 'className="corporate-apparel-link"' in entry.group(1)
    assert 'href="/corporate-apparel"' in entry.group(1)
    assert 'target="_blank"' in entry.group(1)
    assert 'rel="noopener noreferrer"' in entry.group(1)


def test_corporate_apparel_independent_route_and_bilingual_labels_remain():
    assert 'corporateApparel: "企业文化衫领取"' in PORTAL
    assert 'corporateApparel: "Corporate Apparel Request"' in PORTAL
    assert 'const directCorporateApparel = normalizedPath() === "/corporate-apparel"' in PORTAL
    assert re.search(r'if \(directCorporateApparel\) \{\s+return .*?<CorporateApparelPage currentUser=\{currentUser\}', PORTAL, re.S)


def test_corporate_apparel_entry_reuses_navigation_style_and_mobile_scroll():
    assert '.sidebar nav button,\n.sidebar nav .corporate-apparel-link {' in CSS
    assert '.sidebar nav .corporate-apparel-link:focus-visible' in CSS
    assert 'grid-template-columns: repeat(4, max-content)' in CSS
    assert 'grid-template-columns: repeat(4, minmax(132px, 1fr))' in CSS
