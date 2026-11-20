(() => {
  const panel = document.getElementById('projectSharing');
  const form = document.getElementById('sharingForm');
  const enabled = document.getElementById('sharingEnabled');
  const notes = document.getElementById('sharingNotes');
  const status = document.getElementById('sharingStatus');
  const results = document.getElementById('sharingResults');
  const controls = document.getElementById('sharingControls');
  const save = document.getElementById('sharingSave');
  let scope = null, revision = null, sequence = 0;

  function reset() {
    sequence++;
    form.reset();
    results.replaceChildren();
    revision = null;
    status.textContent = '';
    controls.disabled = true;
  }
  async function request(method, data) {
    const response = await fetch('/api/projects/' + scope + '/shared-workspace', {
      method, cache: 'no-store', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
    });
    const body = await response.json();
    if (!response.ok) throw Error(body.detail || 'Workspace unavailable');
    return body;
  }
  async function load() {
    if (!scope || !panel.open) return;
    reset();
    const current = sequence;
    status.textContent = 'Loading…';
    try {
      const data = await request('GET');
      if (sequence !== current) return;
      revision = data.revision;
      enabled.checked = data.enabled;
      notes.value = data.notes;
      controls.disabled = false;
      save.disabled = false;
      for (const row of data.recent_results || []) {
        const item = document.createElement('li');
        const counts = ['items_reviewed','checks_passed','checks_failed']
          .filter(key => key in row).map(key => row[key] + ' ' + key.replaceAll('_',' '));
        item.textContent = [row.task, row.outcome.replaceAll('_',' '), ...counts].join(' · ');
        results.append(item);
      }
      status.textContent = data.results_incomplete ? 'Some project results are unavailable.' : '';
    } catch (e) {
      if (sequence === current) status.textContent = e.message;
    }
  }
  function select(id) {
    if (scope === id) return;
    reset();
    scope = id;
    panel.open = false;
    panel.hidden = !scope;
  }
  panel.ontoggle = () => { if (panel.open) load(); else reset(); };
  document.getElementById('sharingReload').onclick = load;
  form.onsubmit = async event => {
    event.preventDefault();
    if (!scope || controls.disabled) return;
    const current = ++sequence;
    controls.disabled = true;
    try {
      const data = await request('PUT', {enabled: enabled.checked, notes: notes.value, expected_revision: revision});
      if (current !== sequence) return;
      revision = data.revision;
      notes.value = data.notes;
      if (!data.enabled) results.replaceChildren();
      status.textContent = data.enabled ? 'Shared with agents on this project.' : 'Project sharing is off.';
    } catch (e) {
      if (current === sequence) status.textContent = e.message;
    } finally {
      if (current === sequence) controls.disabled = false;
    }
  };
  window.JarvisTeamWorkspace = {select};
  window.JarvisModes?.render();
})();
