from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "request_web/frontend/src/ShippingTemplatePage.tsx").read_text(encoding="utf-8")


def test_excess_freight_opens_dialog_before_generation():
    generation = SOURCE.split("async function generate()", 1)[1].split("return <div", 1)[0]
    assert 'if (freightExceeds) { warnFreight(true); return; }' in generation
    assert generation.index("warnFreight(true)") < generation.index('fetch("/api/admin/shipping/generate"')
    assert 'disabled={busy||(freightInvalid&&!freightExceeds)}' in SOURCE


def test_notice_shows_amounts_and_only_returns_to_editing():
    assert 'role="alertdialog"' in SOURCE and 'aria-modal="true"' in SOURCE
    assert 'originalValue.toFixed(2)' in SOURCE
    assert 'freightValue.toFixed(2)' in SOURCE
    assert '(freightValue-originalValue).toFixed(2)' in SOURCE
    assert 'autoFocus onClick={closeFreightNotice}' in SOURCE
    assert 'Shipping Cost Exceeds Goods Value' in SOURCE
    assert 'OK, Back to Edit' in SOURCE


def test_input_completion_checks_excess_without_repeated_same_value_alerts():
    assert SOURCE.count('onBlur={()=>warnFreight()}') == 3
    assert 'acknowledgedFreight.current === signature' in SOURCE
    assert 'if(e.key==="Escape")' in SOURCE
    assert 'if(e.key==="Tab")' in SOURCE
