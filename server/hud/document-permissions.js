/* Owner-controlled document reads. Keep the open form stable during profile polling. */
(() => {
  const panels=new Map();
  function element(tag,text=''){const el=document.createElement(tag);el.textContent=text;return el;}
  async function api(path, body){
    const res=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'});
    const data=await res.json();if(!res.ok)throw Error(data.detail||'Could not load permissions');return data;
  }
  function panel(agent,jobs){
    const key=[agent.id,...jobs.map(j=>j.id)].join('/');
    if(panels.has(key))return panels.get(key);
    const details=element('details');details.className='agent-group document-permissions';details.append(element('summary','Document permissions'));
    const task=element('select');task.setAttribute('aria-label','Assignment');
    for(const j of jobs)task.add(new Option(j.identifier+' · '+j.title,j.id));
    const form=element('div'),status=element('p');status.setAttribute('role','status');
    details.append(task,form,status);let revision=0;
    async function load(){
      const seq=++revision,id=task.value,path='/api/tasks/'+id+'/document-permissions';
      form.replaceChildren();status.textContent='Loading…';
      try{
        const data=await api(path);if(seq!==revision)return;status.textContent='';
        if(data.private_sibling_inputs)form.append(element('p','Allowed files can be copied into this assignment’s private inputs.'));
        const source=element('select'),doc=element('select');
        source.setAttribute('aria-label','Source task');doc.setAttribute('aria-label','Document');
        source.add(new Option('Select source task',''));
        for(const r of data.sources)source.add(new Option(r.label,r.id));
        async function change(row,state){
          const request={agent_id:agent.id,source_id:row.source_id,artifact_id:row.artifact_id,sha256:row.sha256,state,expected_revision:data.revision,request_id:crypto.randomUUID()};
          await api(path,request);
          if(row.approval_id)await api('/api/approvals/'+row.approval_id+'/decision',{decision:state==='allowed'?'approve':'reject',note:'Owner document permission decision.'});
          await load();
        }
        function button(label,fn){
          const b=element('button',label);b.type='button';b.className='relation-link';
          b.onclick=async()=>{b.disabled=true;try{await fn();}catch(e){status.textContent=e.message;}finally{b.disabled=false;}};
          return b;
        }
        for(const row of data.permissions){
          const line=element('div');line.append(element('span',row.source+' · '+row.name+' · '+row.state+' '));
          if(['approved','allowed'].includes(row.state))line.append(button('Revoke',()=>change(row,'revoked')));
          else{line.append(button('Allow',()=>change(row,'allowed')));if(row.state==='pending')line.append(button('Deny',()=>change(row,'denied')));}
          form.append(line);
        }
        form.append(source,doc);
        const choose=state=>async()=>{
          const item=doc.selectedOptions[0];if(!item?.value)return;
          await change({source_id:source.value,artifact_id:item.value,sha256:item.dataset.sha},state);
        };
        const allow=button('Allow document',choose('allowed')),deny=button('Deny document',choose('denied'));
        allow.disabled=deny.disabled=true;form.append(allow,deny);doc.onchange=()=>{allow.disabled=deny.disabled=!doc.value;};
        source.onchange=async()=>{
          const selected=source.value;doc.replaceChildren();allow.disabled=deny.disabled=true;if(!selected)return;
          try{const result=await api(path+'?source_id='+encodeURIComponent(selected));
            if(seq!==revision||source.value!==selected)return;
            doc.add(new Option('Select document',''));for(const item of result.documents){const opt=new Option(item.originalFilename,item.id);opt.dataset.sha=item.sha256;doc.add(opt);}
          }catch(e){status.textContent=e.message;}
        };
      }catch(e){if(seq===revision)status.textContent=e.message;}
    }
    task.onchange=load;details.ontoggle=()=>{if(details.open)load();};
    panels.set(key,details);if(panels.size>20)panels.delete(panels.keys().next().value);
    return details;
  }
  window.JarvisDocumentPermissions={panel};
})();
