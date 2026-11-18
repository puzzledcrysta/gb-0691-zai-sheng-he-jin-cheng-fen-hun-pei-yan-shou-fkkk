from flask import Blueprint, render_template, request
from app.config import TITLE, MODULES, SHORT, SAMPLE, ORDERS_SAMPLE
from app.pipeline import calculate
from app.store import latest, save, get_run, list_releases
bp=Blueprint('web',__name__)
@bp.route('/')
@bp.route('/work/<int:stage>')
def work(stage=1):
    if stage<1 or stage>8:
        from flask import abort
        abort(404)
    run=get_run(request.args['run_id']) if request.args.get('run_id') else latest()
    if run is None: run=save(calculate())
    if '8' not in run['stages']:
        run=save(calculate())
    current=run['stages'][str(stage)]
    return render_template('m'+str(stage)+'.html', title=TITLE, modules=MODULES, short=SHORT,
                           run=run, current=current, stage=stage,
                           sample=SAMPLE.read_text(encoding='utf-8-sig'),
                           orders_sample=ORDERS_SAMPLE.read_text(encoding='utf-8-sig'),
                           releases=list_releases())
