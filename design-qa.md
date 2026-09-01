# Mobile request page design QA

- Source references: user-provided mobile screenshots and Taobao catalog/specification examples in the conversation.
- Implementation: `app.py`, mobile media-query rules for the material request page.
- Mobile viewport: 390 x 844 CSS pixels.
- Desktop viewport: 1440 x 900 CSS pixels.

## Comparison history

1. The original mobile form used one full-width field per row. It now uses a two-column grid; controls are 26-28 px high and long-text fields are 36 px high.
2. The original catalog/specification controls consumed most of the viewport. The catalog now uses two image-led cards per row and specifications open in one centered, internally scrollable panel.
3. Product headings previously collided with card borders. Card spacing and title line height were tightened while keeping the title inside its card.
4. Mobile language and navigation controls are available from the compact top-left toolbar.
5. Desktop verification retained six catalog columns and the existing desktop form behavior.

## Evidence

- Mobile computed controls: input 26 px, select 28 px, textarea 36 px.
- Mobile catalog computed columns: 172.844 px and 172.859 px at 390 px viewport width.
- Automated regression: 432 passed, 3 subtests passed.

final result: passed
