/* Job card SSE handling: live progress updates, refresh card on terminal state. */
(function () {
  const activeCards = () => document.querySelectorAll('.job-card[data-job-id]');

  async function refreshJobs() {
    const list = document.getElementById('job-list');
    if (!list) return;
    const resp = await fetch('/jobs');
    if (resp.ok) {
      list.innerHTML = await resp.text();
      initSSE();
    }
  }

  function initSSE() {
    activeCards().forEach((card) => {
      const id = card.dataset.jobId;
      const status = card.dataset.status;
      if ((status === 'running' || status === 'pending') && !card.dataset.sse) {
        card.dataset.sse = '1';
        const es = new EventSource(`/job/${id}/progress`);
        const progressBar = card.querySelector('[data-role="progress"]');
        const badge = card.querySelector('[data-role="badge"]');

        es.onmessage = (e) => {
          const data = JSON.parse(e.data);
          if (progressBar) progressBar.style.width = `${data.progress}%`;
          if (badge) badge.textContent = data.status;
          if (data.status === 'running' && card.dataset.status === 'pending') {
            card.dataset.status = 'running';
            card.classList.remove('status-pending');
            card.classList.add('status-running');
          }
          if (['completed', 'failed', 'aborted', 'gone'].includes(data.status)) {
            es.close();
            setTimeout(refreshJobs, 500);
          }
        };
        es.onerror = () => {
          es.close();
          setTimeout(refreshJobs, 1500);
        };
      }
    });
  }

  document.addEventListener('DOMContentLoaded', initSSE);
  document.addEventListener('htmx:afterSwap', initSSE);
})();