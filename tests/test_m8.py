from copy import deepcopy
from app.modules.m8_release.rules import apply, decide_batch, parse_orders, grade_states, parse_ts
from app.domain import GRADES


def _ctx(intervals, orders, now='2026-11-18T12:00:00Z', retest_hours=8):
    return {'intervals': intervals, 'orders': orders, 'now': now, 'retest_hours': retest_hours,
            'quarantine': [], 'stages': {}}


def _orders(rows):
    header = 'order_id,grade,batch,cutoff\n'
    return header + '\n'.join(','.join(r) for r in rows)


ORDERS = _orders([
    ('O-1', '低牌号', 'B1', '2026-11-18T23:59:00Z'),
    ('O-2', '高牌号', 'B1', '2026-11-20T10:00:00Z'),
])

# 高牌号 Cu[8,11] Zn[4,6]；低牌号 Cu[7.5,12.5] Zn[3,7]
LOW_PASS = [
    {'炉次': 'B1', '元素': 'Cu', '含量下界_pct': '9', '含量上界_pct': '10'},
    {'炉次': 'B1', '元素': 'Zn', '含量下界_pct': '4.5', '含量上界_pct': '5.5'},
]
HIGH_PASS = [
    {'炉次': 'B1', '元素': 'Cu', '含量下界_pct': '8.5', '含量上界_pct': '10.5'},
    {'炉次': 'B1', '元素': 'Zn', '含量下界_pct': '4.2', '含量上界_pct': '5.8'},
]
STRADDLE_HIGH = [
    {'炉次': 'B1', '元素': 'Cu', '含量下界_pct': '10.5', '含量上界_pct': '11.5'},
    {'炉次': 'B1', '元素': 'Zn', '含量下界_pct': '5', '含量上界_pct': '5.5'},
]
BOTH_FAIL = [
    {'炉次': 'B1', '元素': 'Cu', '含量下界_pct': '13', '含量上界_pct': '14'},
    {'炉次': 'B1', '元素': 'Zn', '含量下界_pct': '8', '含量上界_pct': '9'},
]
STRADDLE_BOTH = [
    {'炉次': 'B1', '元素': 'Cu', '含量下界_pct': '9.26', '含量上界_pct': '12.67'},
    {'炉次': 'B1', '元素': 'Zn', '含量下界_pct': '4.82', '含量上界_pct': '8.30'},
]


def test_grade_states_full_interval_inside_is_pass():
    states = grade_states(HIGH_PASS)
    assert states['高牌号']['summary'] == '合格' and states['低牌号']['summary'] == '合格'


def test_straddling_limit_is_pending_not_pass():
    states = grade_states(STRADDLE_HIGH)
    assert states['高牌号']['summary'] == '待确认'
    assert states['低牌号']['summary'] == '合格'


def test_entire_interval_outside_is_fail():
    states = grade_states(BOTH_FAIL)
    assert states['高牌号']['summary'] == '不合格' and states['低牌号']['summary'] == '不合格'


def test_high_grade_pass_takes_precedence():
    r = decide_batch('B1', HIGH_PASS, parse_orders(ORDERS), parse_ts('2026-11-18T12:00:00Z'), 8)
    assert r['决定'] == '放行' and r['放行牌号'] == '高牌号'


def test_low_pass_high_pending_wait_keeps_high_chance():
    # 补测 20:00 完成，不晚于低牌号 23:59 截单 → 等补测
    r = decide_batch('B1', STRADDLE_HIGH, parse_orders(ORDERS), parse_ts('2026-11-18T12:00:00Z'), 8)
    assert r['决定'] == '等补测' and r['放行牌号'] == '—'
    assert any('等补测' in b for b in r['依据'].split('；'))


def test_low_pass_high_pending_release_when_retest_misses_low_cutoff():
    # 23:30 判定，补测次日07:30 → 错过低牌号23:59；高牌号订单也存在但高牌号待确认
    r = decide_batch('B1', STRADDLE_HIGH, parse_orders(ORDERS), parse_ts('2026-11-18T23:30:00Z'), 8)
    assert r['决定'] == '放行' and r['放行牌号'] == '低牌号'
    assert any('错过低牌号订单' in b for b in r['依据'].split('；'))


def test_pending_grade_never_released_on_interval():
    r = decide_batch('B1', STRADDLE_BOTH, parse_orders(ORDERS), parse_ts('2026-11-18T12:00:00Z'), 8)
    assert r['决定'] == '等补测' and r['放行牌号'] == '—'


def test_pending_with_all_cutoffs_missed_cannot_release():
    r = decide_batch('B1', STRADDLE_BOTH, parse_orders(ORDERS), parse_ts('2026-11-21T00:00:00Z'), 8)
    assert r['决定'] == '不能放行'


def test_both_fail_cannot_release_even_before_cutoff():
    r = decide_batch('B1', BOTH_FAIL, parse_orders(ORDERS), parse_ts('2026-11-18T12:00:00Z'), 8)
    assert r['决定'] == '不能放行'
    assert any('越限' in b for b in r['依据'].split('；'))


def test_low_pass_without_high_order_releases_low():
    orders = _orders([('O-1', '低牌号', 'B1', '2026-11-18T23:59:00Z')])
    r = decide_batch('B1', STRADDLE_HIGH, parse_orders(orders), parse_ts('2026-11-18T12:00:00Z'), 8)
    assert r['决定'] == '放行' and r['放行牌号'] == '低牌号'


def test_apply_metrics_and_decision_fields():
    result = apply(_ctx(STRADDLE_BOTH, ORDERS))
    row = result['rows'][0]
    assert set(['炉次', '决定', '放行牌号', '补测完成_UTC', '判定时刻_UTC', '依据', '元素判定', '订单']).issubset(row)
    assert [m[0] for m in result['metrics']][:3] == ['放行', '等补测', '不能放行']


def test_invalid_order_grade_rejected():
    import pytest
    from app.errors import DomainError
    bad = _orders([('O-9', '超高牌号', 'B1', '2026-11-18T23:59:00Z')])
    with pytest.raises(DomainError):
        parse_orders(bad)


def test_duplicate_order_keeps_latest_cutoff():
    dup = ORDERS + '\nO-1,低牌号,B1,2026-11-19T08:00:00Z'
    orders = parse_orders(dup)
    low = next(o for o in orders if o['batch'] == 'B1' and o['grade'] == '低牌号')
    assert low['cutoff'] == '2026-11-19T08:00:00Z' and len(orders) == 2


def test_basis_explains_limit_and_interval_numbers():
    r = decide_batch('B1', STRADDLE_HIGH, parse_orders(ORDERS), parse_ts('2026-11-18T12:00:00Z'), 8)
    assert '10.5000~11.5000' in r['依据'] and '8~11' in r['依据']
