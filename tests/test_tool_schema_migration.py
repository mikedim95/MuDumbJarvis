import copy
import importlib.util
from pathlib import Path

import pytest
from test_employee_work import work

spec=importlib.util.spec_from_file_location('tool_schema_migration',Path(__file__).resolve().parents[1]/'deploy/migrate_tool_schemas.py')
migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)


@pytest.fixture
def contract(work,monkeypatch):
    monkeypatch.setenv('JARVIS_PROFILE','research')
    registered=[]
    ctx=type('Context',(),{'register_tool':lambda self,**kw:registered.append(kw)})()
    work.module.register(ctx)
    live=next(t['schema'] for t in registered if t['name']=='research_sources')
    old=copy.deepcopy(live)
    for key in migration.FIELDS:old['parameters']['properties'].pop(key)
    old['description']='Owner-customized tool guidance retained verbatim.'
    other={'type':'function','function':{'name':'publish_artifact','parameters':{'owner':'custom'}}}
    pin={'version':'0.23.1','tools':[other,{'type':'function','function':old}], 'custom':'preserve'}
    return pin,live


def test_pinned_schema_migration_uses_registered_contract_and_preserves_tool_authority(contract):
    pin,live=contract;original=copy.deepcopy(pin)
    updated=migration.migrate_pin(pin,live)
    assert pin==original and updated['version']==pin['version'] and updated['custom']=='preserve'
    assert updated['tools'][0]==pin['tools'][0]
    tool=updated['tools'][1]['function']
    assert tool['name']=='research_sources' and tool['description']==pin['tools'][1]['function']['description']
    assert tool['parameters']==live['parameters']
    assert migration.migrate_pin(updated,live)==updated


def test_pinned_schema_manual_conflicts_fail_before_replacement(contract):
    pin,live=contract
    pin['tools'][1]['function']['parameters']['properties']['limit']={'type':'integer','maximum':100}
    with pytest.raises(ValueError,match='customization conflicts'):migration.migrate_pin(pin,live)
    pin['tools'][1]['function']['parameters']['properties'].pop('limit')
    pin['tools'][1]['function']['parameters']['required']=['issue_ids']
    with pytest.raises(ValueError,match='required fields differ'):migration.migrate_pin(pin,live)


def test_migration_never_adds_an_unapproved_tool(contract):
    pin,live=contract;pin['tools']=pin['tools'][:1]
    with pytest.raises(ValueError,match='did not authorize'):migration.migrate_pin(pin,live)
