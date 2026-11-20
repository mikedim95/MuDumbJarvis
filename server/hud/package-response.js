/* The project popup and the CEO profile use the same approval controls. */
customElements.define('jarvis-package-response', class extends HTMLElement {
  connectedCallback() {
    if (this.firstElementChild) return;
    this.innerHTML = `<p>Yes queues a Debian installation for this assignment’s offline package environment.</p>
    <div class="package-choices" role="group" aria-label="Answer the package request">
      <button type="button" data-answer="Yes">Yes</button><button type="button" data-answer="No">No</button>
      <button type="button" data-other aria-expanded="false">Other</button>
    </div><form hidden><label>Feedback for the CEO<textarea required rows="2" maxlength="8000"></textarea></label>
      <button type="submit">Send feedback</button></form><p role="status" aria-live="polite"></p>`;
    const choices = this.querySelector('.package-choices');
    const form = this.querySelector('form');
    const input = this.querySelector('textarea');
    const other = this.querySelector('[data-other]');
    const notice = this.querySelector('[role=status]');
    const buttons = [...this.querySelectorAll('button')];
    let pendingNote, busy = false;
    other.onclick = () => {
      form.hidden = !form.hidden;
      other.setAttribute('aria-expanded', String(!form.hidden));
      if (!form.hidden) input.focus();
    };
    const submit = async (value, feedback) => {
      if (busy || !value) return;
      busy = true;
      for (const button of buttons) button.disabled = true;
      input.readOnly = true;
      notice.textContent = 'Sending…';
      try {
        if (feedback && pendingNote?.text !== value) pendingNote = {text:value, id:crypto.randomUUID()};
        const receipt = await window.JarvisTasks.replyToQuestion(
          this.getAttribute('task-id'), this.getAttribute('question-id'), value, feedback ? pendingNote.id : undefined);
        if (feedback) {
          pendingNote = null;
          input.value = '';
          notice.textContent = 'Feedback sent to the CEO. You can still choose Yes or No.';
        } else {
          if (receipt.decision !== (value === 'Yes' ? 'accepted' : 'rejected')) throw new Error('Decision was not confirmed.');
          choices.hidden = true;
          notice.textContent = value === 'Yes' ? 'Approved. Package setup is queued.' : 'Declined.';
        }
        form.hidden = true;
        other.setAttribute('aria-expanded','false');
      } catch (error) {
        notice.textContent = error.message || 'Could not send your response. Try again.';
      } finally {
        busy = false;
        input.readOnly = false;
        for (const button of buttons) button.disabled = false;
        if (feedback && form.hidden) other.focus();
      }
    };
    for (const button of choices.querySelectorAll('[data-answer]'))
      button.onclick = () => submit(button.dataset.answer, false);
    form.onsubmit = event => {
      event.preventDefault();
      if (!input.value.trim()) { notice.textContent = 'Enter your feedback.'; input.focus(); return; }
      submit(input.value.trim(), true);
    };
  }
});
