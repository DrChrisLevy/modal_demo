'use strict';

const $ = id => document.getElementById(id);
const palette = ['#7954d6', '#d97532', '#278c75', '#3879ce', '#c84a83', '#718a29', '#ad7425', '#7764a0'];
let labels = [];
let tasks = [];
let completed = false;
let recentTask = null;
let savingLabels = false;
const busyTasks = new Set();

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function showError(message, target = 'error') {
  $(target).textContent = message;
  $(target).hidden = !message;
}

async function request(path, options = {}) {
  const response = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    const message = Array.isArray(detail) ? detail.map(item => item.msg.replace(/^Value error, /, '')).join('. ') : detail;
    throw new Error(message || 'Could not save that change. Please try again.');
  }
  return response.status === 204 ? null : response.json();
}

function announce(task) {
  const label = labels.find(item => item.id === task.label_id);
  if (task.classification.status === 'unavailable') {
    $('sort-status').textContent = 'Saved in Unsorted. Jev is unavailable; you can retry from the task menu.';
  } else if (label && task.classification.status === 'sorted') {
    $('sort-status').textContent = `Sorted into ${label.name} · ${task.classification.duration_ms} ms`;
  } else {
    $('sort-status').textContent = label ? `Moved to ${label.name}` : 'Saved in Unsorted';
  }
}

async function changeTask(task, path, options, row) {
  if (busyTasks.has(task.id)) return;
  busyTasks.add(task.id);
  const controls = row.querySelectorAll('button, input, select');
  controls.forEach(control => { control.disabled = true; });
  row.setAttribute('aria-busy', 'true');
  showError('');
  try {
    const updated = await request(path, options);
    tasks = updated ? tasks.map(item => item.id === task.id ? updated : item) : tasks.filter(item => item.id !== task.id);
    if (updated && options.method === 'PATCH' && Object.hasOwn(JSON.parse(options.body), 'done')) {
      $('sort-status').textContent = updated.done ? 'Task completed. Little win, big energy!' : 'Task reopened';
      if (updated.done && !task.done) celebrate();
    } else if (updated) announce(updated);
    else $('sort-status').textContent = 'Task deleted';
    render();
  } catch (error) {
    showError(error.message);
    const checkbox = row.querySelector('input[type=checkbox]');
    if (checkbox) checkbox.checked = task.done;
    const select = row.querySelector('select');
    if (select) select.value = task.label_id ?? '';
  } finally {
    busyTasks.delete(task.id);
    controls.forEach(control => { control.disabled = false; });
    row.removeAttribute('aria-busy');
  }
}

function taskCard(task) {
  const card = element('li', `card${task.done ? ' done' : ''}${task.id === recentTask ? ' just-added' : ''}`);
  const main = element('div', 'task-main');
  const checkbox = element('input', 'task-check');
  checkbox.type = 'checkbox'; checkbox.checked = task.done; checkbox.id = `task-${task.id}`;
  const title = element('label', 'task-title', task.title);
  title.htmlFor = checkbox.id;
  checkbox.addEventListener('change', () => changeTask(task, `/api/tasks/${task.id}`, {method: 'PATCH', body: JSON.stringify({done: checkbox.checked})}, card));
  const menu = element('details', 'task-menu');
  const summary = element('summary', '', '···');
  summary.setAttribute('aria-label', `Options for ${task.title}`);
  const content = element('div', 'menu-content');
  const select = element('select');
  select.id = `move-${task.id}`;
  const moveLabel = element('label', '', 'Move to'); moveLabel.htmlFor = select.id;
  for (const label of [...labels, {id: '', name: 'Unsorted'}]) {
    const option = element('option', '', label.name); option.value = label.id; select.append(option);
  }
  select.value = task.label_id ?? '';
  select.addEventListener('change', () => changeTask(task, `/api/tasks/${task.id}`, {method: 'PATCH', body: JSON.stringify({label_id: select.value ? Number(select.value) : null})}, card));
  const retry = element('button', '', 'Sort again'); retry.type = 'button';
  retry.addEventListener('click', () => {
    $('sort-status').textContent = 'Jev is finding a place for this task…';
    changeTask(task, `/api/tasks/${task.id}/sort`, {method: 'POST'}, card);
  });
  const remove = element('button', 'delete', 'Delete task'); remove.type = 'button';
  remove.addEventListener('click', () => changeTask(task, `/api/tasks/${task.id}`, {method: 'DELETE'}, card));
  content.append(moveLabel, select, retry, remove); menu.append(summary, content);
  main.append(checkbox, title, menu); card.append(main);
  return card;
}

function celebrate() {
  const layer = $('celebration');
  layer.replaceChildren();
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  for (let index = 0; index < 24; index++) {
    const piece = element('span', 'confetti');
    piece.style.setProperty('--x', `${(Math.random() - .5) * 520}px`);
    piece.style.setProperty('--y', `${-100 - Math.random() * 260}px`);
    piece.style.setProperty('--spin', `${Math.random() * 720 - 360}deg`);
    piece.style.background = palette[index % palette.length];
    piece.addEventListener('animationend', () => piece.remove(), {once: true});
    layer.append(piece);
  }
}

function render() {
  const done = tasks.filter(task => task.done).length;
  const percent = tasks.length ? Math.round(done / tasks.length * 100) : 0;
  $('progress-message').textContent = !tasks.length ? 'A fresh start. Full of possibilities.' :
    done === tasks.length ? 'All done. Look at you go!' : done ? 'Look at that momentum. Keep it going!' : 'Big things start with one little task.';
  $('progress-count').textContent = `${done} of ${tasks.length} completed`;
  $('progress-fill').style.width = `${percent}%`;
  $('progress-fill').parentElement.setAttribute('aria-valuenow', String(percent));
  $('open-count').textContent = tasks.filter(task => !task.done).length;
  $('done-count').textContent = tasks.filter(task => task.done).length;
  $('board').replaceChildren();
  const visible = tasks.filter(task => task.done === completed);
  labels.forEach((label, index) => {
    const column = element('section', 'column');
    column.style.setProperty('--label-color', palette[index % palette.length]);
    column.setAttribute('aria-label', label.name);
    const matching = visible.filter(task => task.label_id === label.id);
    const heading = element('div', 'column-heading');
    const line = element('div', 'heading-line');
    line.append(element('span', 'dot'), element('h2', '', label.name), element('span', 'count', matching.length));
    const description = element('p', 'column-description', label.description); description.title = label.description;
    heading.append(line, description); column.append(heading);
    if (matching.length) {
      const list = element('ul', 'task-list');
      matching.forEach(task => list.append(taskCard(task))); column.append(list);
    } else {
      const empty = element('div', 'empty-column');
      empty.append(element('span', '', completed ? '✓' : '＋'), document.createTextNode(completed ? 'A little progress goes here' : 'Room for what’s next'));
      column.append(empty);
    }
    $('board').append(column);
  });
  const unsorted = visible.filter(task => !labels.some(label => label.id === task.label_id));
  $('unsorted-section').hidden = !unsorted.length;
  $('unsorted-count').textContent = unsorted.length;
  const unsortedList = element('ul', 'unsorted-list');
  unsorted.forEach(task => unsortedList.append(taskCard(task)));
  $('unsorted').replaceChildren(unsortedList);
  recentTask = null;
}

function setView(value) {
  completed = value;
  for (const [id, active] of [['open-view', !value], ['done-view', value]]) {
    $(id).classList.toggle('active', active); $(id).setAttribute('aria-pressed', String(active));
  }
  render();
}

$('open-view').addEventListener('click', () => setView(false));
$('done-view').addEventListener('click', () => setView(true));
$('add-form').addEventListener('submit', async event => {
  event.preventDefault();
  const title = $('title').value.trim();
  if (!title) { $('title').focus(); return; }
  showError(''); $('add-button').disabled = true; $('title').readOnly = true;
  $('add-button').firstElementChild.textContent = 'Sorting…';
  $('sort-status').textContent = 'Jev is finding a place for your task…';
  try {
    const task = await request('/api/tasks', {method: 'POST', body: JSON.stringify({title})});
    tasks.unshift(task); recentTask = task.id; $('title').value = ''; setView(false); announce(task);
  } catch (error) {
    showError(error.message); $('sort-status').textContent = 'Task not saved. Your text is still above.';
  } finally {
    $('add-button').disabled = false; $('title').readOnly = false;
    $('add-button').firstElementChild.textContent = 'Add task'; $('title').focus();
  }
});

function labelRow(label = {}) {
  const row = element('div', 'label-row');
  if (label.id) row.dataset.id = label.id;
  const name = element('input'); name.type = 'text'; name.value = label.name || ''; name.placeholder = 'Label name';
  name.maxLength = 32; name.required = true; name.setAttribute('aria-label', 'Label name');
  const description = element('textarea'); description.value = label.description || ''; description.placeholder = 'What belongs here? A sentence helps Jev sort accurately.';
  description.maxLength = 240; description.required = true; description.rows = 2; description.setAttribute('aria-label', 'Label description');
  const remove = element('button', 'icon-button remove-label', '×'); remove.type = 'button'; remove.setAttribute('aria-label', 'Remove label');
  remove.addEventListener('click', () => { row.remove(); updateLabelControls(); });
  row.append(name, remove, description); $('label-rows').append(row); updateLabelControls();
  return name;
}

function updateLabelControls() {
  const count = $('label-rows').children.length;
  $('add-label').disabled = count >= 8 || savingLabels;
  $('label-rows').querySelectorAll('.remove-label').forEach(button => { button.disabled = count <= 1 || savingLabels; });
}

$('edit-labels').addEventListener('click', () => {
  $('label-rows').replaceChildren(); labels.forEach(label => labelRow(label)); showError('', 'labels-error'); $('labels-dialog').showModal();
});
$('add-label').addEventListener('click', () => labelRow().focus());
for (const id of ['close-labels', 'cancel-labels']) $(id).addEventListener('click', () => { if (!savingLabels) $('labels-dialog').close(); });
$('labels-dialog').addEventListener('cancel', event => { if (savingLabels) event.preventDefault(); });
$('labels-form').addEventListener('submit', async event => {
  event.preventDefault(); showError('', 'labels-error');
  const edited = Array.from($('label-rows').children, row => ({
    id: row.dataset.id ? Number(row.dataset.id) : null,
    name: row.querySelector('input').value,
    description: row.querySelector('textarea').value,
  }));
  savingLabels = true;
  $('labels-form').querySelectorAll('input, textarea, button').forEach(control => { control.disabled = true; });
  $('save-labels').textContent = 'Saving and sorting…';
  try {
    labels = await request('/api/labels', {method: 'PUT', body: JSON.stringify({labels: edited})});
    tasks = await request('/api/tasks'); render(); $('labels-dialog').close(); $('sort-status').textContent = 'Labels saved. Unsorted tasks checked against the updated labels.';
  } catch (error) { showError(error.message, 'labels-error'); }
  finally {
    savingLabels = false;
    $('labels-form').querySelectorAll('input, textarea, button').forEach(control => { control.disabled = false; });
    $('save-labels').textContent = 'Save labels'; updateLabelControls();
  }
});

document.addEventListener('click', event => {
  document.querySelectorAll('.task-menu[open]').forEach(menu => { if (!menu.contains(event.target)) menu.open = false; });
});

Promise.all([request('/api/labels'), request('/api/tasks')]).then(([initialLabels, initialTasks]) => {
  labels = initialLabels; tasks = initialTasks; render();
}).catch(error => { showError(error.message); })
  .finally(() => { $('loading').hidden = true; });
