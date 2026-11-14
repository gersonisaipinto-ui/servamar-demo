/* SERVAMAR v61 - read-only preview for fictitious PostgreSQL reports. */
async function servamarDemoPreview() {
  const output = document.getElementById('dbdemo-preview');
  if (!output) return;
  output.replaceChildren();
  output.textContent = 'Consultando registros ficticios…';
  const params = new URLSearchParams({
    period: document.getElementById('report-period').value,
    field: document.getElementById('report-field').value
  });
  if (params.get('period') === 'custom') {
    const toISO = value => {
      const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value.trim());
      if (!match) return '';
      const iso = match[3] + '-' + match[2] + '-' + match[1];
      const date = new Date(iso + 'T12:00:00Z');
      return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === iso ? iso : '';
    };
    const from = toISO(document.getElementById('report-from').value);
    const to = toISO(document.getElementById('report-to').value);
    if (!from || !to) {
      output.textContent = 'Introduce ambas fechas válidas en formato dd/mm/yyyy.';
      return;
    }
    params.set('from', from);
    params.set('to', to);
  }
  try {
    const response = await fetch('/api/demo/export/preview?' + params.toString(), {cache:'no-store'});
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'No se pudo consultar la vista previa');
    output.replaceChildren();
    const heading = document.createElement('p');
    heading.textContent = data.count === 0
      ? 'No hay expedientes ficticios para el período seleccionado. Cambia el filtro antes de descargar.'
      : data.count + ' expediente(s) ficticio(s) encontrado(s) en PostgreSQL DEMO.';
    output.appendChild(heading);
    if (!data.count) return;
    const table = document.createElement('table');
    const head = document.createElement('thead');
    const tr = document.createElement('tr');
    ['Registro', 'Embarcación', 'Capitán', 'Etapa', 'Ingreso', 'Vencimiento'].forEach(label => {
      const th = document.createElement('th'); th.textContent = label; tr.appendChild(th);
    });
    head.appendChild(tr); table.appendChild(head);
    const body = document.createElement('tbody');
    data.items.forEach(item => {
      const row = document.createElement('tr');
      ['registration','vessel_name','captain','stage','entry_date','due_date'].forEach(key => {
        const td = document.createElement('td'); td.textContent = item[key] || ''; row.appendChild(td);
      });
      body.appendChild(row);
    });
    table.appendChild(body);
    const wrap = document.createElement('div'); wrap.className = 'tablewrap'; wrap.appendChild(table);
    output.appendChild(wrap);
    if (data.truncated) {
      const note = document.createElement('p');
      note.textContent = 'Vista previa limitada a 20 registros; la exportación incluye todos los resultados filtrados.';
      output.appendChild(note);
    }
  } catch (error) {
    output.textContent = 'Error de vista previa: ' + error.message;
  }
}
