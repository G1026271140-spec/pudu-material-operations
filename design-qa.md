# Control Center Design QA

- Source visual truth: `work/control_center/qa/maa-reference.png`
- Implementation screenshot: `work/control_center/qa/control-center-settings-v2.png`
- Full comparison: `work/control_center/qa/maa-vs-control-center.png`
- Focused comparison: `work/control_center/qa/maa-vs-control-center-focus.png`
- Source pixels: 800 x 600 at Windows desktop density
- Implementation pixels: 1196 x 819 at Windows desktop density; Tk content geometry 1180 x 780 plus native frame
- Normalization: both windows were contained in adjacent 800 x 600 comparison cells without stretching; the focused comparison uses equal 800 x 360 cells
- State: MAA automatic-battle shell versus PUDU settings shell. The business content is intentionally different; navigation, density, color, controls, borders, and layout rhythm are the comparison target.

## Full-view evidence

The implementation carries over the visible MAA shell language: native Windows frame, white/light-gray canvas, centered top navigation, thin blue selected-tab rule, low-contrast borders, restrained blue accents, and a narrow numbered settings rail. The wider PUDU window is intentional because it must show editable values plus local source, platform entry, and activation scope for 74 settings.

## Focused-region evidence

The focused comparison covers the top navigation, primary controls, first configuration cards, and category rail. Text and inputs remain readable at the implementation's native capture. A separate focus was necessary because the full-view comparison reduces the PUDU window to fit beside the 800 x 600 source.

## Required fidelity surfaces

- Fonts and typography: Microsoft YaHei UI/Segoe UI match the native Windows character of the reference. Hierarchy, weights, line height, and truncation are consistent and readable.
- Spacing and layout rhythm: large white regions, thin separators, compact controls, and steady vertical spacing match MAA's restrained rhythm. The PUDU cards are denser by product necessity.
- Colors and tokens: white, soft gray, neutral text, and Windows blue are consistently applied. The green side-management status is an intentional semantic addition.
- Image quality and assets: no decorative imagery is needed. The application uses the real project icon rather than a drawn placeholder.
- Copy and content: labels describe the actual PUDU settings, local storage location, platform entry, activation scope, and non-interruption behavior.

## Comparison history

1. First implementation capture: the fixed-height editor container clipped entry fields and Save buttons. Severity P1.
2. Fix: removed the fixed-height/pack-propagation constraint and gave controls stable native widths.
3. Revised capture: `control-center-settings-v2.png` shows complete values, controls, source guidance, and category navigation with no clipping.

## Findings

No actionable P0, P1, or P2 visual differences remain for the requested MAA-inspired direction.

## Follow-up polish

- P3: a future signed installer could add Windows publisher identity; the current portable EXE is intentionally unsigned and project-local.

final result: passed

# Shipping Template Compact Layout QA

- Source visual truth: `C:/Users/gaohongyuan1/AppData/Local/Temp/codex-clipboard-da695bff-62d6-4243-a21d-eb2cbfa37244.png`
- Implementation screenshots: `C:/Users/gaohongyuan1/AppData/Local/Temp/shipping-v1.9.3-recipient-final2.png` and `C:/Users/gaohongyuan1/AppData/Local/Temp/shipping-v1.9.3-cartons-final.png`
- Combined comparison screenshots: `C:/Users/gaohongyuan1/AppData/Local/Temp/shipping-v1.9.3-comparison.png` and `C:/Users/gaohongyuan1/AppData/Local/Temp/shipping-v1.9.3-comparison-cartons.png`
- Source pixels: 1640 x 824
- Implementation browser viewport: 1280 x 720 CSS pixels at device scale factor 1
- Normalization: the recipient comparison places the full source and implementation captures in equal-width browser columns; the focused carton comparison preserves the implementation's native browser capture without stretching.
- State: shipping-template page with recipient fields empty, two cartons, automatic metrics at their zero/default state, and two available category pools.

## Full-view evidence

The recipient panel now fits the date, country code, and automatic invoice number in one row; contact details use four columns; email, delivery term, and payment term use one final row. The panel is materially shorter while every original field remains visible and readable.

## Focused-region evidence

The focused carton capture shows boxes 01 and 02 on the same row. Each card retains its box title, category count, dimensions, computed volume and weights, both category pools, and the empty-content message without overlap or clipping.

## Required fidelity surfaces

- Fonts and typography: existing application typography is preserved; field labels and compact-card supporting text are reduced without truncation.
- Spacing and layout rhythm: recipient rows and carton cards use tighter vertical gaps and padding; the two-column carton grid has a consistent center gutter.
- Colors and visual tokens: existing borders, background colors, metric treatment, and semantic information panel remain unchanged.
- Image quality and assets: this form contains no application imagery or decorative raster assets; no placeholders or artificial icons were introduced.
- Copy and content: all field labels, carton copy, category names, units, and automatic-calculation descriptions are unchanged except for the new visible `发票编号（自动）` label.

## Comparison history

1. First implementation: widget heights were smaller but the recipient panel still used the original six-row structure, so the visible height reduction was modest. Severity P2.
2. Fix: moved the automatic invoice number into the first row, grouped contact/phone fields into four columns, and moved payment terms into the final three-column row.
3. Responsive fix: corrected the narrow-layout selector to target Streamlit's `stColumn` nodes so the two-column carton row can return to one column below 900 px.
4. Revised evidence: the recipient panel is substantially shorter and two complete carton cards fit side by side at desktop width with no actionable clipping or overlap.

## Findings

No actionable P0, P1, or P2 visual differences remain for the requested compact shipping-template layout.

## Primary interactions and console

- Date, country, recipient, carton-count, dimension, weight, category, and quantity controls are present in the browser-rendered DOM.
- The two-carton default state renders both independent cards and all automatic metrics.
- Browser console checked: no errors.

final result: passed
