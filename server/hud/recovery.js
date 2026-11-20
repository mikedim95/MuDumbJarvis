/* Native recovery controls shared by project jobs and agent profiles. */
(() => {
  const node=(tag,value,className)=>{const n=document.createElement(tag);n.textContent=value;if(className)n.className=className;return n;};
  const panels=new Map();
  function control(job,place='project') {
    if(!job.recovery)return null;
    const key=JSON.stringify([place,job.id,job.recovery.run_id,job.recovery.action_id,job.recovery.can_retry,job.recovery.needs_reconciliation]);
    if(panels.has(key))return panels.get(key);
    const panel=node('section','','job-recovery');panel.dataset.recoveryTaskId=job.id;
    panels.set(key,panel);if(panels.size>100)panels.delete(panels.keys().next().value);
    panel.append(node('p',job.recovery.reason));
    if(job.recovery.needs_reconciliation&&job.recovery.can_retry){
      const open=node('button','Resolve block','job-retry');open.type='button';
      open.dataset.resolveTaskId=job.id;open.setAttribute('aria-label','Resolve block for '+(job.identifier||job.title||'task'));
      const form=node('form','','execution-resolution');form.hidden=true;
      const outcome=node('select');outcome.setAttribute('aria-label','Previous work outcome');
      for(const [value,label] of [['mixed','Some work completed'],['not_performed','No work was performed'],['completed','Work completed and verified']]){
        const option=node('option',label);option.value=value;outcome.append(option);
      }
      const evidence=node('textarea');evidence.rows=3;evidence.required=true;evidence.minLength=20;evidence.maxLength=2000;
      evidence.placeholder='Describe what is verified, what failed, and how Jarvis should continue.';
      evidence.setAttribute('aria-label','Resolution details');
      const label=node('label','','execution-stop-confirmation'),stopped=node('input');stopped.type='checkbox';stopped.required=true;
      label.append(stopped,document.createTextNode('The previous execution has stopped.'));
      const send=node('button','Save and continue','job-retry');send.type='submit';
      const message=node('p','','job-recovery-message');message.setAttribute('role','status');
      form.append(outcome,evidence,label,send,message);panel.append(open,form);
      open.onclick=()=>{form.hidden=!form.hidden;open.setAttribute('aria-expanded',String(!form.hidden));if(!form.hidden)evidence.focus();};
      form.onsubmit=async event=>{
        event.preventDefault();if(send.disabled||!form.reportValidity())return;
        send.disabled=true;message.textContent='';
        try{
          await window.JarvisTasks.resolveExecution(job,{provider_stopped:stopped.checked,action_outcome:outcome.value,evidence:evidence.value.trim()});
          message.textContent='Resolution saved. Jarvis can continue this task.';
        }catch(error){message.textContent=error.message;}
        finally{send.disabled=false;}
      };
      return panel;
    }
    if(job.recovery.can_retry){
      const button=node('button','Retry task','job-retry');button.type='button';
      button.dataset.retryTaskId=job.id;
      button.setAttribute('aria-label','Retry '+(job.identifier||job.title||'task'));
      const message=node('p','','job-recovery-message');message.setAttribute('role','status');
      button.onclick=async()=>{
        if(button.disabled)return;
        button.disabled=true;button.textContent='Retrying…';message.textContent='';
        try{
          await window.JarvisTasks.retry(job.id,job.recovery.run_id);
          message.textContent='Retry accepted. Saved work is preserved.';
        }catch(error){message.textContent=error.message;}
        finally{button.disabled=false;button.textContent='Retry task';}
      };
      panel.append(button,message);
    }else panel.append(node('p',job.recovery.next_action||'Jarvis must review this execution before it can continue.'));
    return panel;
  }
  window.JarvisRecovery={control};
})();
