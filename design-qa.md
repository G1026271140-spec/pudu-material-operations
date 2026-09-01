# Mobile request page design QA

- Source visual truth: `C:/Users/gaohongyuan1/AppData/Roaming/LarkShell/sdk_storage/eb5ca27929f63de7192a073d17f0a140/resources/images/img_v3_02154_72122594-6cd0-402c-9ef7-6dda8677a80g.jpg` plus the user-provided Taobao catalog/specification examples in the conversation.
- Implementation screenshot: `C:/Users/gaohongyuan1/AppData/Local/Temp/pudu-mobile-v1.8.6-spec.png`.
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
6. Field labels previously crossed their control borders after the height reduction. Mobile labels now reserve vertical space and use an opaque section-colored background; the rendered form no longer overlaps.
7. The cart popover previously retained the native translated position even after becoming a fixed bottom sheet, leaving it below the viewport. Its transform is now reset and the empty-cart sheet was clicked and verified inside the 390 x 844 viewport.
8. Product-line groups use one compact row per product line on mobile, with two reduced-height model choices per internal row. Desktop retains three product-line columns.
9. The specification body previously required scrolling to the bottom to reach language and quantity. The model area now owns the only long scroll surface, while language, quantity, remark, and add-to-cart remain in a fixed lower section.
10. The mobile brand toolbar was lengthened horizontally to keep the PUDU logo, app icon, translate control, and navigation control inside distinct non-overlapping slots.

## Evidence

- Mobile computed controls: input 26 px, select 28 px, textarea 36 px; field-label separation verified visually at 390 x 844.
- Mobile catalog computed columns: 172.844 px and 172.859 px at 390 px viewport width.
- Primary interaction: empty cart opens as a visible bottom sheet at x=0, y=672, width=390 within the mobile viewport.
- Product lines: one group per mobile row; model buttons render two per internal row at reduced height without overlap. Desktop remains a three-column selector grid.
- Fixed specification controls: language uses three compact columns; quantity and remark share one row; add-to-cart is visible without scrolling the model list.
- Navigation interaction: material request and cultural-merchandise request visible; inventory query and material management absent.
- Full-view comparison: mobile form hierarchy, two-column catalog, fixed action bar, compact branded toolbar, and viewport density were compared in one combined image.
- Focused-region comparison: form labels, toolbar controls, specification product-line groups, model wrapping, and bottom-cart placement were inspected separately because they are too small to judge reliably in the full view.

final result: passed
