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
