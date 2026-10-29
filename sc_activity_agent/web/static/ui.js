// Client-side paging for <table data-page="N">, optional filters (<select data-filter="tableId" data-col="i">),
// and closing open Can do pickers on an outside click. The whole table stays in its form, so ticked boxes survive paging.
document.querySelectorAll('table[data-page]').forEach(t => {
  const size = +t.dataset.page, rows = [...t.tBodies[0].rows].filter(r => !r.querySelector('td[colspan]'));
  const filters = t.id ? [...document.querySelectorAll(`select[data-filter="${t.id}"]`)] : [];
  const bar = document.createElement('div'); bar.className = 'pager'; t.after(bar);
  let page = 0;
  const draw = () => {
    const hit = rows.filter(r => filters.every(f => !f.value || r.cells[+f.dataset.col].textContent.trim() === f.value));
    const pages = Math.max(1, Math.ceil(hit.length / size)); page = Math.min(page, pages - 1);
    rows.forEach(r => r.hidden = true); hit.slice(page * size, (page + 1) * size).forEach(r => r.hidden = false);
    bar.replaceChildren();
    if (rows.length && !hit.length) { bar.textContent = 'No matching rows.'; return; }
    if (hit.length <= size) return;
    const mk = (txt, to) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'sm'; b.textContent = txt;
      b.disabled = to < 0 || to >= pages; b.onclick = () => { page = to; draw(); }; return b; };
    const info = document.createElement('span'); info.className = 'mono'; info.textContent = `Page ${page + 1} of ${pages} (${hit.length} rows)`;
    bar.append(info, mk('Previous', page - 1), mk('Next', page + 1));
  };
  filters.forEach(f => f.onchange = () => { page = 0; draw(); });
  draw();
});
document.addEventListener('click', e => document.querySelectorAll('details.ms[open]').forEach(d => { if (!d.contains(e.target)) d.open = false; }));
