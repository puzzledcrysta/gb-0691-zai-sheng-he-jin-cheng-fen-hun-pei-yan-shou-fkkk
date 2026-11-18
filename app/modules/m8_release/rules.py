from datetime import datetime, timedelta, timezone
from app.domain import GRADES, GRADE_ORDER, DEFAULT_RETEST_HOURS
from app.numeric import number, fmt
from app.errors import DomainError

ORDER_COLUMNS = ['order_id', 'grade', 'batch', 'cutoff']


def parse_ts(value):
    """ISO8601 时间，一律按 UTC 解释；返回带时区的 datetime。"""
    text = str(value).strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise DomainError('TIME', '时间须为ISO8601格式（如2026-11-18T23:59:00Z）')
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_utc(value=None):
    if value in (None, ''):
        return datetime.now(timezone.utc)
    return parse_ts(value)


def parse_orders(source):
    """接受CSV文本或dict列表；重复订单保留最晚截单，其他字段以首次为准。"""
    if source is None:
        from app.config import ORDERS_SAMPLE
        source = ORDERS_SAMPLE.read_text(encoding='utf-8-sig')
    if isinstance(source, str):
        import csv
        import io
        rows = list(csv.DictReader(io.StringIO(source)))
        if rows and set(rows[0].keys()) != set(ORDER_COLUMNS):
            raise DomainError('ORDER', '订单列须为 order_id,grade,batch,cutoff')
    elif isinstance(source, list):
        rows = source
    else:
        raise DomainError('ORDER', '订单须为CSV文本或对象数组')
    orders = {}
    for row in rows:
        if not isinstance(row, dict) or set(row.keys()) != set(ORDER_COLUMNS):
            raise DomainError('ORDER', '订单列须为 order_id,grade,batch,cutoff')
        grade = row['grade'].strip()
        if grade not in GRADES:
            raise DomainError('ORDER', '牌号无效，仅支持高牌号/低牌号')
        if not str(row.get('order_id') or '').strip():
            raise DomainError('ORDER', '订单号为空')
        cutoff = parse_ts(row['cutoff'])
        key = (str(row['batch']).strip(), grade)
        if not key[0]:
            raise DomainError('ORDER', '订单炉次为空')
        if key not in orders or cutoff > orders[key]['cutoff_dt']:
            orders[key] = {
                'order_id': str(row['order_id']).strip(),
                'grade': grade,
                'batch': key[0],
                'cutoff': cutoff.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'cutoff_dt': cutoff,
            }
    return list(orders.values())


def element_state(low, high, limits):
    """完整区间对单一限值的判定：合格=整区间在内；不合格=整区间在外；待确认=跨界。"""
    lo, hi = limits
    if low >= lo and high <= hi:
        return '合格'
    if high < lo or low > hi:
        return '不合格'
    return '待确认'


def grade_states(interval_rows):
    """每个牌号汇总元素状态；任一不合格即不合格，否则任一待确认即待确认。"""
    answer = {}
    for grade in GRADE_ORDER:
        spec = GRADES[grade]
        elements = []
        for r in interval_rows:
            element = r['元素']
            if element not in spec:
                continue
            a, b = number(r['含量下界_pct']), number(r['含量上界_pct'])
            state = element_state(a, b, spec[element])
            elements.append({
                '元素': element,
                '含量下界_pct': fmt(a),
                '含量上界_pct': fmt(b),
                '规格下限_pct': str(spec[element][0]),
                '规格上限_pct': str(spec[element][1]),
                '状态': state,
            })
        if not elements:
            summary = '不合格'
        elif any(e['状态'] == '不合格' for e in elements):
            summary = '不合格'
        elif any(e['状态'] == '待确认' for e in elements):
            summary = '待确认'
        else:
            summary = '合格'
        answer[grade] = {'summary': summary, 'elements': elements}
    return answer


def decide_batch(batch, interval_rows, order_rows, now, retest_hours):
    """依据订单要求、牌号限值与完整区间，输出放行/等补测/不能放行及逐条依据。"""
    states = grade_states(interval_rows)
    ready = now + timedelta(hours=float(retest_hours))
    orders = [o for o in order_rows if o['batch'] == batch]
    basis = []

    for grade in GRADE_ORDER:
        spec = GRADES[grade]
        state = states[grade]['summary']
        matched = [o for o in orders if o['grade'] == grade]
        for e in states[grade]['elements']:
            basis.append(
                f"{grade}{e['元素']} 区间{e['含量下界_pct']}~{e['含量上界_pct']}% "
                f"对照限值{e['规格下限_pct']}~{e['规格上限_pct']}% → {e['状态']}"
            )
        if not matched:
            basis.append(f'{grade}：无对应订单，不纳入放行选择')
        else:
            for o in matched:
                alive = now <= o['cutoff_dt']
                word = '未截单' if alive else '已截单'
                basis.append(
                    f"订单{o['order_id']}（{grade}）截单{o['cutoff']}，当前{word}；"
                    f"牌号区间判定：{state}"
                )
                if alive and state == '待确认':
                    basis.append(
                        f"补测最早{ready.strftime('%Y-%m-%dT%H:%M:%SZ')}完成，"
                        f"{'晚于' if ready > o['cutoff_dt'] else '不晚于'}该订单截单"
                    )

    def active(grade):
        return [o for o in orders if o['grade'] == grade and now <= o['cutoff_dt']]

    high_state, low_state = states['高牌号']['summary'], states['低牌号']['summary']
    high_orders, low_orders = active('高牌号'), active('低牌号')
    release_grade, decision = None, None

    # 1. 高牌号整区间合格且有未截单高牌号订单：直接争取高牌号
    if high_state == '合格' and high_orders:
        decision, release_grade = '放行', '高牌号'
        basis.append('高牌号完整区间合格且有未截单订单，优先按高牌号放行')
    # 2. 低牌号整区间合格且有未截单低牌号订单
    elif low_state == '合格' and low_orders:
        if high_state == '待确认' and high_orders:
            if ready > low_orders[0]['cutoff_dt']:
                decision, release_grade = '放行', '低牌号'
                basis.append('补测完成晚于低牌号订单截单，等待将错过低牌号订单，按低牌号放行')
            else:
                decision = '等补测'
                basis.append('补测不晚于低牌号订单截单，先等补测以保留争取高牌号订单的机会')
        else:
            decision, release_grade = '放行', '低牌号'
            basis.append('低牌号完整区间合格且有未截单订单，按低牌号放行')
    # 3. 无牌号可立即放行：判断等待是否仍有意义
    else:
        wait_candidates = []
        for grade, state, live in (('高牌号', high_state, high_orders), ('低牌号', low_state, low_orders)):
            if state == '待确认' and live and ready <= live[0]['cutoff_dt']:
                wait_candidates.append((grade, live[0]))
        if wait_candidates:
            decision = '等补测'
            grade, order = wait_candidates[0]
            basis.append(f"{grade}待确认且补测不晚于订单{order['order_id']}截单，等补测后再裁决")
        else:
            decision = '不能放行'
            if high_state == '不合格' and low_state == '不合格':
                basis.append('两个牌号均存在整区间越限元素，无放行依据')
            elif not (high_orders or low_orders):
                basis.append('无未截单订单，放行没有接收对象')
            else:
                basis.append('待确认牌号的补测完成时间均晚于对应订单截单，且无合格牌号可放行')

    return {
        '炉次': batch,
        '决定': decision,
        '放行牌号': release_grade or '—',
        '补测完成_UTC': ready.strftime('%Y-%m-%dT%H:%M:%SZ'),
        '判定时刻_UTC': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        '高牌号判定': high_state,
        '低牌号判定': low_state,
        '依据': '；'.join(basis),
        '元素判定': states,
        '订单': [
            {
                'order_id': o['order_id'], 'grade': o['grade'], 'cutoff': o['cutoff'],
                '状态': '未截单' if now <= o['cutoff_dt'] else '已截单',
            } for o in orders
        ],
    }


def apply(ctx):
    now = now_utc(ctx.get('now'))
    retest_hours = number(DEFAULT_RETEST_HOURS if ctx.get('retest_hours') in (None,'') else ctx.get('retest_hours'))
    if retest_hours <= 0:
        raise DomainError('RANGE', '补测时长必须大于零')
    order_rows = parse_orders(ctx.get('orders'))
    batches = sorted({r['炉次'] for r in ctx['intervals']})
    rows = [
        decide_batch(batch, [r for r in ctx['intervals'] if r['炉次'] == batch],
                     order_rows, now, retest_hours)
        for batch in batches
    ]
    ctx['release_decisions'] = rows
    return {
        'rows': rows,
        'metrics': [
            ['放行', sum(r['决定'] == '放行' for r in rows), '炉'],
            ['等补测', sum(r['决定'] == '等补测' for r in rows), '炉'],
            ['不能放行', sum(r['决定'] == '不能放行' for r in rows), '炉'],
            ['补测时长', str(retest_hours), '小时'],
        ],
    }
