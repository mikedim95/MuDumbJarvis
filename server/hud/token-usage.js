/* A scrolling graph of measured, reported usage; no character-count estimates. */
(() => {
  if(!document.body.classList.contains('ai-minimal'))return;
  const el=id=>document.getElementById(id),svg=el('tokenUsageGraph'),line=el('tokenUsageLine'),area=el('tokenUsageArea');
  const compact=new Intl.NumberFormat(undefined,{notation:'compact',maximumFractionDigits:1});
  const exact=new Intl.NumberFormat(undefined,{maximumFractionDigits:1});
  let snapshot=null,offset=0,polling=false,frame=0,lastPaint=0;
  function present(data){
    snapshot=data;offset=data.at-Date.now()/1000;
    const rate=data.status==='ok'?data.tokens_per_second:null;
    el('tokenUsageValue').textContent=rate===null?'—':compact.format(rate);
    el('tokenUsageTotal').textContent=compact.format(data.total_tokens)+' total';
    el('tokenUsageReadout').dataset.status=data.status;
    const description=(rate===null?'Current rate unavailable':exact.format(rate)+' reported tokens per second')+
      '; '+exact.format(data.total_tokens)+' total tokens ('+exact.format(data.input_tokens)+' input, '+exact.format(data.output_tokens)+' output). '+
      'Chat and all agents. Usage is reported when runs finish; this is usage reporting rate, not generation speed.';
    el('tokenUsageReadout').title=description;el('tokenUsageReadout').setAttribute('aria-label',description);
    svg.setAttribute('aria-label','Reported input and output token usage over the last '+data.window_seconds+' seconds');
    draw();
  }
  function draw(){
    if(!snapshot)return;
    const w=svg.clientWidth,h=svg.clientHeight;if(!w||!h)return;
    const now=Date.now()/1000+offset,windowSeconds=snapshot.window_seconds||60;
    const points=snapshot.points.filter(point=>point[0]>=now-windowSeconds-5);
    const max=Math.max(1,...points.map(point=>point[1]??0))*1.15;
    svg.setAttribute('viewBox','0 0 '+w+' '+h);
    const x=at=>Math.max(0,(at-(now-windowSeconds))/windowSeconds*w),y=value=>h-5-value/max*(h-12);
    let path='',fill='',segment=[];
    function flush(){
      if(!segment.length)return;
      path+='M'+segment.map(p=>p[0].toFixed(2)+','+p[1].toFixed(2)).join(' L');
      fill+='M'+segment[0][0].toFixed(2)+','+(h-3)+' L'+segment.map(p=>p[0].toFixed(2)+','+p[1].toFixed(2)).join(' L')+
        ' L'+segment.at(-1)[0].toFixed(2)+','+(h-3)+' Z';segment=[];
    }
    for(const [at,value] of points){if(value===null){flush();continue;}segment.push([x(at),y(value)]);}
    const last=points.at(-1);
    if(last&&last[1]!==null&&now-last[0]<=snapshot.interval_seconds*2)segment.push([w,y(last[1])]);
    flush();line.setAttribute('d',path);area.setAttribute('d',fill);
    const spacing=w/6,shift=(now%10)/windowSeconds*w;
    el('tokenUsageGrid').setAttribute('d',Array.from({length:8},(_,i)=>'M'+(i*spacing-shift).toFixed(2)+',0 V'+h).join(' ')+
      ' M0,'+(h-5)+' H'+w+' M0,'+(h/2)+' H'+w);
    if(now-snapshot.at>15){el('tokenUsageValue').textContent='—';el('tokenUsageReadout').dataset.status='stale';}
  }
  async function poll(){
    if(polling||document.hidden)return;polling=true;
    try{
      const response=await fetch('/api/usage/live',{cache:'no-store',signal:AbortSignal.timeout(6000)});
      if(!response.ok)throw new Error('Usage unavailable');
      present(await response.json());
    }catch{
      el('tokenUsageValue').textContent='—';el('tokenUsageReadout').dataset.status='stale';
      el('tokenUsageReadout').title='Token usage is temporarily unavailable. Reconnecting…';
    }finally{polling=false;}
  }
  function animate(at){
    if(!document.hidden&&at-lastPaint>=50){draw();lastPaint=at;}
    frame=requestAnimationFrame(animate);
  }
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll();});
  new ResizeObserver(draw).observe(svg);
  window.addEventListener('pagehide',()=>cancelAnimationFrame(frame),{once:true});
  poll();setInterval(poll,5000);frame=requestAnimationFrame(animate);
})();
