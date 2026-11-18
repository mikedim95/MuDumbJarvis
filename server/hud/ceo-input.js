/* Input routing only. Paperclip owns objective state and execution. */
(() => {
  function route(value, objectiveId = null, mode = 'direct') {
    const input = String(value || '').trim();
    if (!input) return {kind: 'empty'};
    if (mode !== 'projects') {
      const text = /^\/chat(?:\s|$)/i.test(input) ? input.replace(/^\/chat\s*/i, '').trim() : input;
      return text ? {kind: 'direct', input: text} : {kind: 'invalid', message: 'Write a message for Direct Chat.'};
    }
    if (/^\/(approve|reject)(?:\s|$)/i.test(input)) {
      const match = input.match(/^\/(approve|reject)\s+([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:\s+([\s\S]+))?$/i);
      return match ? {kind: 'decision', decision: match[1].toLowerCase(), approval_id: match[2], note: match[3]?.trim() || 'Human ' + match[1].toLowerCase() + ' decision through the JARVIS conversation.'} :
        {kind: 'invalid', message: 'Use /approve <approval UUID> [note] or /reject <approval UUID> [note].'};
    }
    if (/^\/chat(?:\s|$)/i.test(input)) {
      const text = input.replace(/^\/chat\s*/i, '').trim();
      return text ? {kind: 'direct', input: text} : {kind: 'invalid', message: 'Write a message after /chat for separate Codex chat.'};
    }
    if (/^\/new(?:\s|$)/i.test(input)) {
      const text = input.replace(/^\/new\s*/i, '').trim();
      return text ? {kind: 'new', input: text} : {kind: 'reset'};
    }
    if (/^@ceo(?:\s|$)/i.test(input)) {
      const text = input.replace(/^@ceo\s*/i, '').trim();
      return text ? {kind: 'new', input: text} : {kind: 'invalid', message: 'Write a new objective after @ceo.'};
    }
    return objectiveId ? {kind: 'followup', input, task_id: objectiveId} : {kind: 'new', input};
  }
  function publishedText(text) {
    // Signed runtime appendices stay in the native evidence panels. The
    // conversation shows the actual published prose preceding those records.
    return String(text||'').split(/\n\nVerified (?:delegated execution|local_ollama_models) data:\n/)[0].trim();
  }
  function latestReply(task) {
    return [...(task?.comments||[])].filter(comment=>comment.authorAgentId===task.assigneeAgentId&&
      typeof comment.body==='string'&&comment.body.trim()&&
      !/^\[JARVIS (?:TOOL EVENT|CEO PLAN|CEO REVIEW|CEO RESULTS READY)/.test(comment.body))
      .sort((a,b)=>(a.createdAt||'').localeCompare(b.createdAt||'')).at(-1);
  }
  globalThis.JarvisCEOInput = Object.freeze({route,publishedText,latestReply});
})();
