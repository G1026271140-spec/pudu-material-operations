# Mobile request page design QA

- Source visual truth: `C:/Users/gaohongyuan1/AppData/Roaming/LarkShell/sdk_storage/eb5ca27929f63de7192a073d17f0a140/resources/images/img_v3_02154_72122594-6cd0-402c-9ef7-6dda8677a80g.jpg` plus the user-provided Taobao catalog/specification examples in the conversation.
- Implementation screenshot: browser visual check for V1.8.7 at 390 x 844 CSS pixels.
- Combined visual comparison: `C:/Users/gaohongyuan1/AppData/Local/Temp/pudu-mobile-v1.8.6-comparison.png`.
- Implementation: `app.py`, mobile media-query rules for the material request page.
- Mobile viewport: 390 x 844 CSS pixels.
- Desktop viewport: 1440 x 900 CSS pixels.
- Density normalization: browser capture at device scale factor 1; the source screenshot was proportionally reduced to 390 px width for the combined comparison.
- State: request catalog loaded; focused checks additionally covered open specification panel, open empty-cart sheet, language control, and mobile navigation menu.

## Comparison history

1. The original mobile form used one full-width field per row. It now uses a two-column grid; controls are 26-28 px high and long-text fields are 36 px high.
2. The original catalog/specification controls consumed most of the viewport. The catalog now uses two image-led cards per row and specifications open in one centered, internally scrollable panel.
3. Product headings previously collided with card borders. Card spacing and title line height were tightened while keeping the title inside its card.
4. The mobile toolbar now presents the real PUDU logo and application icon before separate translate and menu controls. The menu contains only material request and cultural-merchandise request.
5. Desktop verification retained six catalog columns and the existing desktop form behavior.
6. Field labels previously crossed their control borders after the height reduction. Mobile labels now remain in normal document flow with no overlay background, text shadow, or field shadow; the rendered form no longer overlaps.
7. The cart popover previously retained the native translated position even after becoming a fixed bottom sheet, leaving it below the viewport. Its transform is now reset and the empty-cart sheet was clicked and verified inside the 390 x 844 viewport.
8. Product-line groups use one compact row per product line on mobile, with two reduced-height model choices per internal row. Desktop retains three product-line columns.
9. The specification body previously required scrolling to the bottom to reach language and quantity. The model area now owns the only long scroll surface, while language, quantity, remark, and add-to-cart remain in a fixed lower section.
10. The mobile brand toolbar keeps the PUDU logo, app icon, translate icon, and navigation icon in distinct non-overlapping slots, with all toolbar and icon-button frames removed.
11. Specification-window sizing now uses the number of model options. Single/no-model materials use a content-height window, while longer model lists retain a separately scrollable model area and fixed language/quantity/add-to-cart controls.

## Evidence

- Mobile computed controls: input 26 px, select 28 px, textarea 36 px; field labels and inputs have no text shadow or box shadow at 390 x 844.
- Mobile catalog computed columns: 172.844 px and 172.859 px at 390 px viewport width.
- Primary interaction: empty cart opens as a visible bottom sheet at x=0, y=672, width=390 within the mobile viewport.
- Product lines: one group per mobile row; model buttons render two per internal row at reduced height without overlap. Desktop remains a three-column selector grid.
- Fixed specification controls: language uses three compact columns; quantity and remark share one row; add-to-cart is visible without scrolling the model list. The no-model brand-handbook window measured 448 px high rather than the previous fixed 84dvh panel, with no unused lower area.
- Navigation interaction: material request and cultural-merchandise request visible; inventory query and material management absent.
- Full-view comparison: mobile form hierarchy, two-column catalog, fixed action bar, borderless branded toolbar, and viewport density were compared at 390 x 844.
- Focused-region comparison: form labels, toolbar controls, specification product-line groups, model wrapping, and bottom-cart placement were inspected separately because they are too small to judge reliably in the full view.

final result: passed

## V1.9.1 short-viewport action verification

- Source visual truth: `C:/Users/gaohongyuan1/AppData/Roaming/LarkShell/sdk_storage/eb5ca27929f63de7192a073d17f0a140/resources/images/img_v3_02154_b76c1c19-4743-479f-a254-45563d5dcf3g.jpg` (1080 x 2351 px), showing the add-to-cart action clipped at the bottom of the mobile specification window.
- Implementation screenshots: `C:/Users/gaohongyuan1/AppData/Local/Temp/pudu-mobile-v1.9.1-spec-390x849.png` at 390 x 849 CSS pixels and `pudu-mobile-v1.9.1-short-spec.png` at 390 x 600 CSS pixels, device scale factor 1.
- Combined comparison: `C:/Users/gaohongyuan1/AppData/Local/Temp/pudu-mobile-v1.9.1-spec-comparison.png`; the source was normalized to 390 x 849 px to match the implementation viewport.
- Earlier P1: the real mobile WebView allowed the language and option regions to consume the remaining modal height, clipping the primary add-to-cart action. Fix: language pills now use smaller type, tighter line height, 16 px minimum controls, and reduced gaps/padding; quantity and remark controls are also compacted.
- Earlier P1: short viewports had no guaranteed space for the primary action. Fix: the add-to-cart wrapper is sticky inside the modal's fixed action region, and viewports at or below 760 px use a responsive 108 px model-region minimum instead of forcing 136 px.
- Post-fix evidence at 390 x 600: modal y=48-552, language region height=133.86 px, add-to-cart y=489.72-516.09 and fully visible.
- Extreme-height evidence at 390 x 520: modal y=41.60-478.40, add-to-cart y=421.30-447.68 and fully visible.
- Primary interaction: the button reported enabled with pointer events active; clicking it successfully changed the cart count from 0 to 1.
- Typography: language labels remain readable at the smaller mobile size; selected and unselected states retain clear hierarchy.
- Spacing/layout: model, language, option, and action regions remain separated without overlap; the saved vertical space is assigned to the primary action rather than blank padding.
- Colors/tokens: the V1.9.0 section colors and selected-button blue remain unchanged.
- Image quality: no logos, product images, or icons were changed.
- Copy/content: all language names, labels, and action copy remain unchanged.
- Desktop guard: all new compact and short-height rules remain inside the mobile media query.

final result: passed

## V1.9.0 specification-section verification

- Source visual truth: `C:/Users/gaohongyuan1/AppData/Local/Temp/codex-clipboard-fa467b8b-e943-4ed4-92bb-89dedfc9f0cf.png` (482 x 863 px).
- Implementation screenshot: `C:/Users/gaohongyuan1/AppData/Local/Temp/pudu-mobile-v1.9.0-spec.png` (390 x 720 px) at a 390 x 720 CSS viewport and device scale factor 1.
- Combined comparison: `C:/Users/gaohongyuan1/AppData/Local/Temp/pudu-mobile-v1.9.0-spec-comparison.png`; the source was proportionally normalized to 390 px wide before comparison.
- State: the Product Flyer specification window is open with a multi-product-line model list, one selected language, quantity 1, an empty remark, and the add-to-cart action enabled.
- Earlier P1: the model section did not expose its own title, while language and quantity did. Fix: a sticky `型号选择` / `Model Selection` heading now anchors the upper-left corner of the model region.
- Earlier P2: model, language, and quantity/remark regions visually blended together. Fix: the three regions now use restrained blue-gray, teal, and warm-neutral backgrounds with matching low-contrast borders.
- Earlier P2: the model selector exposed only 104 px of vertical space. Fix: the mobile model region now measures 136 px at 390 x 720, while remaining independently scrollable and keeping the add-to-cart action visible.
- Typography: existing compact type sizes and weights are retained; the new model heading matches the hierarchy of the existing language and quantity labels without wrapping.
- Spacing/layout: all three sections have distinct padding and 9 px radii; no controls overlap, and the add-to-cart button remains fully inside the 604.8 px modal body.
- Colors/tokens: section fills are `#F3F6FA`, `#EEF8F6`, and `#FFF7ED`; contrast remains sufficient and selected-button blue is unchanged.
- Image quality: no product image, logo, or icon assets were changed.
- Copy/content: Chinese and English model-section labels are present; existing product, language, quantity, remark, and action copy is unchanged.
- Primary interaction: model selection remains scrollable; language selection, quantity input, remark input, and add-to-cart remain visible and interactive.
- Desktop guard: all new styling remains inside the existing mobile media query; desktop specification layout is unchanged.

final result: passed

## V1.8.9 mobile regression verification

- Source references: `C:/Users/gaohongyuan1/AppData/Roaming/LarkShell/sdk_storage/eb5ca27929f63de7192a073d17f0a140/resources/images/img_v3_02154_95cb697d-5946-4602-a1aa-17ebac11f14g.jpg`, `img_v3_02154_b4ea0ad8-13ee-409b-948b-ca494b110efg.jpg`, and `img_v3_02154_b38fba07-afde-43a1-93c8-2dccfac13f9g.jpg`.
- Implementation captures: `C:/Users/gaohongyuan1/AppData/Local/Temp/pudu-mobile-v1.8.9-form.png` and `C:/Users/gaohongyuan1/AppData/Local/Temp/pudu-mobile-v1.8.9-spec.png` at 390 x 720 CSS pixels, device scale factor 1.
- Combined comparison inputs: `C:/Users/gaohongyuan1/AppData/Local/Temp/pudu-mobile-v1.8.9-form-comparison.png` and `C:/Users/gaohongyuan1/AppData/Local/Temp/pudu-mobile-v1.8.9-spec-comparison.png`.
- P1 finding: Streamlit collapsed the heading wrapper to about 10 px and field-label wrappers to about 2-6 px, so their text overflowed across the following control border. Mobile-only wrapper minimum heights and margins now keep every label in normal flow; typography, colors, wording, and desktop sizing remain unchanged.
- P1 finding: the complex specification window's model selector consumed the available vertical space and the body clipped the add-to-cart action. The window is now a column flex layout: the model list is the only shrinking, scrollable region, while language, quantity, remark, and add-to-cart remain visible in a non-shrinking lower region.
- Post-fix mobile measurement: specification body y=57.6-662.4; model list y=159.7-263.7 with independent scrolling; fixed controls y=271.0-534.8; add-to-cart y=507.6-534.0 and fully inside the body.
- Visual inspection: heading and field labels are readable with clear vertical separation; input borders have no label collision; the complex and no-model specification states retain the existing type scale, colors, copy, product imagery, model wrapping, and primary action styling.
- Desktop guard check at 1440 x 900: catalog remains six columns, the business section remains 1098 px wide, and the desktop heading height remains 35.95 px.

final result: passed
