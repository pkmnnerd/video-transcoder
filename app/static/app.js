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

  /* Upload progress via XHR (multipart form POST with HX-Request so the server
     returns the job card partial, same as the htmx form did before). */
  function setupUpload() {
    const form = document.getElementById('upload-form');
    if (!form) return;

    const bar = document.getElementById('upload-progress');
    const fill = document.getElementById('upload-progress-fill');
    const phase = document.getElementById('upload-phase');
    const pct = document.getElementById('upload-percent');
    const error = document.getElementById('upload-error');
    const fileInput = form.querySelector('input[type="file"]');
    const btn = form.querySelector('button[type="submit"]');

    form.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!fileInput.files || !fileInput.files.length) return;

      error.hidden = true;
      bar.hidden = false;
      fill.style.width = '0%';
      pct.textContent = '0%';
      phase.textContent = 'Uploading…';
      btn.disabled = true;

      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/jobs');
      xhr.setRequestHeader('HX-Request', 'true');

      xhr.upload.onprogress = (ev) => {
        if (!ev.lengthComputable) return;
        const p = Math.round((ev.loaded / ev.total) * 100);
        fill.style.width = p + '%';
        pct.textContent = p + '%';
      };

      xhr.onload = () => {
        if (xhr.status === 200) {
          const list = document.getElementById('job-list');
          if (list) {
            list.insertAdjacentHTML('afterbegin', xhr.responseText);
            if (window.htmx) htmx.process(list);
          }
          initSSE();
          form.reset();
          const label = document.getElementById('file-label');
          if (label) label.textContent = 'Choose a video file…';
        } else {
          let msg = 'Upload failed (HTTP ' + xhr.status + ')';
          try {
            const d = JSON.parse(xhr.responseText);
            if (d.detail) msg = typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail);
          } catch (_) { /* not JSON */ }
          showUploadError(msg);
        }
        bar.hidden = true;
        btn.disabled = false;
      };

      xhr.onerror = () => {
        showUploadError('Network error during upload');
        bar.hidden = true;
        btn.disabled = false;
      };

      xhr.send(new FormData(form));
    });

    function showUploadError(msg) {
      error.textContent = msg;
      error.hidden = false;
    }
  }

  setupUpload();

  /* Show the jobs-list spinner only while polling when there are no jobs yet. */
  function setupJobsSpinner() {
    const list = document.getElementById('job-list');
    const spinner = document.getElementById('jobs-loading');
    if (!list || !spinner) return;

    list.addEventListener('htmx:beforeRequest', () => {
      if (!list.querySelector('.job-card')) spinner.hidden = false;
    });
    list.addEventListener('htmx:afterRequest', () => {
      spinner.hidden = true;
    });
  }

  setupJobsSpinner();
})();