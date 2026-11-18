"""Use the same native scope rules in the HUD and employee runtimes."""
import importlib.util
from pathlib import Path

_path=Path(__file__).resolve().parents[1]/'hermes-plugin/jarvis_readonly/work_scope.py'
_spec=importlib.util.spec_from_file_location('jarvis_work_scope',_path)
_module=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_module)
GENERAL_PREFIX=_module.GENERAL_PREFIX
classify=_module.classify
routine_scope=_module.routine_scope
variables=_module.variables
closed=_module.closed
description=_module.description
description_scope=_module.description_scope
clean_description=_module.clean_description


async def routines_for(client,issues):
    if not any(i.get('originKind')=='routine_execution' for i in issues):return []
    return await client.request('GET','companies/'+client.company+'/routines')
