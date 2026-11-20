(() => {
  const byId = id => document.getElementById(id);
  const panel = byId('projectPackages'), form = byId('projectPackageForm');
  const controls = byId('projectPackageControls'), choices = byId('projectPackageChoices');
  const all = byId('projectPackageAll'), status = byId('projectPackageStatus'), reload = byId('projectPackageReload');
  const cliStatus = byId('projectCliStatus');
  let project = null, revision = null, generation = 0;

  function sync() {
    const inputs = [...choices.querySelectorAll('input')];
    const count = inputs.filter(input => input.checked).length;
    all.checked = inputs.length > 0 && count === inputs.length;
    all.indeterminate = count > 0 && count < inputs.length;
  }
  function reset() {
    generation++;
    revision = null;
    controls.disabled = true;
    choices.replaceChildren();
    reload.hidden = true;
    status.textContent = '';
    cliStatus.textContent = '';
    sync();
  }
  async function request(method, body) {
    const url = '/api/projects/' + project + '/development-packages';
    const response = await fetch(url,{method, cache:'no-store',headers:{'Content-Type':'application/json'},
      body: body ? JSON.stringify(body) : undefined});
    const result = await response.json();
    if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'Package approvals unavailable.');
    return result;
  }
  async function load() {
    reset();
    if (!project || !panel.open) return;
    const current = generation;
    status.textContent = 'Loading…';
    try {
      const data = await request('GET');
      if (current !== generation) return;
      revision = data.revision;
      cliStatus.textContent = data.project_cli === 'running'
        ? ['Kali CLI running', '/project', 'jarvis-projects-local', data.project_container?.ipv4].filter(Boolean).join(' · ')
        : 'Project CLI · ' + (data.project_cli || 'unconfirmed');
      for (const item of data.catalog) {
        const input = document.createElement('input'), label = document.createElement('label');
        input.type = 'checkbox';
        input.value = item.name;
        input.checked = data.approved.includes(item.name);
        label.append(input, ' ' + item.name + ' · ' + item.version);
        choices.append(label);
      }
      controls.disabled = false;
      sync();
      status.textContent = data.outdated.length ? 'Review updated packages before approving their new versions.' : '';
    } catch (err) {
      if (current === generation) { status.textContent = err.message; reload.hidden = false; }
    }
  }
  all.onchange = () => {
    for (const input of choices.querySelectorAll('input')) input.checked = all.checked;
    sync();
  };
  choices.onchange = sync;
  panel.ontoggle = load;
  reload.onclick = load;
  form.onsubmit = async event => {
    event.preventDefault();
    if (!project || controls.disabled) return;
    const current = ++generation;
    controls.disabled = true;
    try {
      const packages = [...choices.querySelectorAll('input:checked')].map(input => input.value);
      const data = await request('PUT',{packages,expected_revision:revision});
      if (generation !== current) return;
      revision = data.revision;
      controls.disabled = false;
      status.textContent = data.approved.length ? 'Project approvals saved.' : 'Project approvals cleared.';
    } catch (err) {
      if (current === generation) { status.textContent = err.message; reload.hidden = false; }
    }
  };
  window.JarvisProjectPackages = {select(id) {
    if (id === project) return;
    reset();
    project = id;
    panel.open = false;
    panel.hidden = !id;
  }};
  window.JarvisModes?.render();
})();
