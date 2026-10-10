"""前端模拟服务调用真实计算器，只处理管道内的夹具数据。"""
import json
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace


def dispatch(request):
    from module.runtime.mind_calculator import calculate, catalog, revision
    from module.api.mind_calculator_service import MindCalculatorService, import_ships
    action = request['action']
    ships = request.get('ships', [])
    if action == 'catalog':
        data = catalog()
        return dict(updated_at=data['updated_at'], ships=list(data['ships'].values()))
    if action in ('report', 'calculate'):
        return dict(revision=revision(ships), **calculate(ships))
    if action == 'import':
        return {'ships': import_ships(request['filename'], request['content'])}
    saved = {'MindCalculatorScan': {'MindCalculator': {'Result': {'ships': ships}}}}
    service = MindCalculatorService(SimpleNamespace(read=lambda _: (saved, ''), path=lambda _: None))
    if action == 'export':
        return service.export(request['instance'], request.get('format', 'xlsx'))
    if action == 'recognize':
        return service.recognize(request['instance'], request['filename'], request['content'])
    raise ValueError('未知模拟操作')


if __name__ == '__main__':
    try:
        request = json.load(sys.stdin)
        with redirect_stdout(sys.stderr):
            result = dispatch(request)
    except Exception as exc:
        result = {'error': str(exc)}
    print(json.dumps(result, ensure_ascii=False))
