/* Independent left/right columns. Narrow screens use dismissible side drawers. */
(() => {
  if(!document.body.classList.contains('ai-minimal'))return;
  const el=id=>document.getElementById(id),narrow=matchMedia('(max-width:1023px)');
  const panels={left:el('generalNav'),right:el('agentsRail')};
  const buttons={left:el('generalSidebarToggle'),right:el('agentsSidebarToggle')};
  const state={left:false,right:false};
  const storageKey=side=>'jarvis-panel:'+side+':'+(narrow.matches?'narrow':'wide');
  function restore(){for(const side of ['left','right'])state[side]=localStorage.getItem(storageKey(side))!=='closed'&&(!narrow.matches||localStorage.getItem(storageKey(side))==='open');}
  function render(){
    for(const side of ['left','right']){
      const available=!panels[side].hidden,open=available&&state[side],label=side==='left'?'conversations':'agents';
      document.body.dataset[side+'Panel']=open?'open':'closed';
      panels[side].inert=!open;panels[side].setAttribute('aria-hidden',String(!open));
      buttons[side].disabled=!available;buttons[side].setAttribute('aria-expanded',String(open));
      buttons[side].setAttribute('aria-label',(open?'Hide ':'Show ')+label+' sidebar');buttons[side].title=buttons[side].getAttribute('aria-label');
    }
    el('workspaceBackdrop').hidden=!narrow.matches||!Object.keys(state).some(side=>state[side]&&!panels[side].hidden);
    window.dispatchEvent(new CustomEvent('jarvis-panels-changed',{detail:{...state,narrow:narrow.matches}}));
  }
  function set(side,open,{persist=true}={}){
    if(!panels[side])return;
    if(open&&narrow.matches){const other=side==='left'?'right':'left';state[other]=false;if(persist)localStorage.setItem(storageKey(other),'closed');}
    state[side]=open;if(persist)localStorage.setItem(storageKey(side),open?'open':'closed');render();
  }
  function close(){for(const side of ['left','right']){state[side]=false;localStorage.setItem(storageKey(side),'closed');}render();}
  for(const side of ['left','right'])buttons[side].onclick=()=>set(side,!state[side]);
  el('workspaceBackdrop').onclick=close;
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&narrow.matches&&(state.left||state.right)){
      const side=state.right?'right':'left';close();buttons[side].focus();event.preventDefault();
    }
  });
  window.addEventListener('jarvis-mode-changed',()=>{if(narrow.matches)close();else render();});
  window.addEventListener('jarvis-tasks-updated',()=>{if(buttons.left.disabled!==panels.left.hidden)render();});
  narrow.addEventListener('change',()=>{restore();render();});
  window.JarvisPanels={open:side=>set(side,true),close:side=>set(side,false),snapshot:()=>({...state,narrow:narrow.matches})};
  restore();render();
})();
