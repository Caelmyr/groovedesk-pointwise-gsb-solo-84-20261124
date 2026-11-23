'use strict';

const $ = id => document.getElementById(id);
const state = {config: null, panel: null, draft: null, result: null, archive: null,
  mode: 'surface', tool: null, markStart: null, cursor: null, selection: null, stripUrl: null,
  seamSuggestion: null};
const apiRoot = '/groove';
const fieldNames = ['inner', 'outer', 'phase', 'seam', 'diameter', 'angle', 'span'];
const TAU = 2 * Math.PI;
const SVG = 'http://www.w3.org/2000/svg';
let busy = false;

function element(tag, content, attrs = {}) {
  const node = document.createElement(tag);
  if (content !== null) node.textContent = content;
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

function graphic(tag, attrs) {
  const node = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

function tell(message, error = false) {
  $('status').textContent = message;
  $('status').dataset.error = error;
  if (!state.panel && error) $('empty').querySelector('p').textContent = message;
}

function action(fn) {
  return async event => {
    if (busy) return;
    busy = true;
    try {
      await fn(event);
    } catch (error) {
      tell(error.message || '操作未完成，请重试。', true);
    } finally {
      busy = false;
    }
  };
}

async function api(path, method = 'GET', data, format = 'json') {
  const options = {method};
  if (data instanceof FormData) options.body = data;
  else if (data !== undefined) {
    options.body = JSON.stringify(data);
    options.headers = {'Content-Type': 'application/json'};
  }
  const response = await fetch(apiRoot + path, options);
  if (!response.ok) {
    const details = await response.json().catch(() => ({}));
    throw Error(details.error || '服务未返回检查结果。');
  }
  return response[format]();
}

const panelPath = () => '/panels/' + state.panel.id;
const geometry = () => state.archive ? state.archive.settings : state.draft;
const format = value => value === null || value === undefined ? '—' : value;
const normalAngle = angle => ((angle % 360) + 360) % 360;
const radiusUnit = () => Math.min(state.panel.width - 1, state.panel.height - 1);

function origin(settings) {
  return [settings.center[0] * (state.panel.width - 1), settings.center[1] * (state.panel.height - 1)];
}

function sourcePoint(angle, radius, settings) {
  const [cx, cy] = origin(settings);
  const theta = angle * TAU / 360;
  return [cx + Math.sin(theta) * radius * radiusUnit(), cy - Math.cos(theta) * radius * radiusUnit()];
}

function applyFields() {
  for (const key of fieldNames) {
    const value = $(key).valueAsNumber;
    if (!Number.isFinite(value)) throw Error('请填写各项标定数字。');
    state.draft[key] = value;
  }
}

function showFields() {
  for (const key of fieldNames) $(key).value = Number(state.draft[key].toFixed(6));
}

function framePoint(event, node) {
  const matrix = node.getScreenCTM();
  if (!matrix) return null;
  const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
  return [point.x, point.y];
}

function drawPhoto() {
  const panel = state.panel;
  const settings = geometry();
  const svg = $('photo');
  const [cx, cy] = origin(settings);
  svg.setAttribute('viewBox', `0 0 ${panel.width} ${panel.height}`);
  svg.classList.toggle('choosing', ['center', 'inner', 'outer', 'phase'].includes(state.tool));
  const nodes = [graphic('image', {href: apiRoot + panelPath() + '/image', width: panel.width, height: panel.height})];
  for (const key of ['inner', 'outer']) {
    nodes.push(graphic('circle', {cx, cy, r: settings[key] * radiusUnit(), fill: 'none', stroke: '#7de1b5',
      'stroke-width': 1.15, 'stroke-dasharray': key === 'inner' ? '4 4' : '0', 'vector-effect': 'non-scaling-stroke'}));
  }
  const [x2, y2] = sourcePoint(settings.phase, settings.outer, settings);
  nodes.push(graphic('line', {x1: cx, y1: cy, x2, y2, stroke: '#7de1b5', 'stroke-width': 1.2, 'stroke-dasharray': '7 5',
    'vector-effect': 'non-scaling-stroke'}));
  const seam = normalAngle(settings.seam ?? 0);
  if (seam) {
    const [sx, sy] = sourcePoint(settings.phase + seam, settings.outer, settings);
    nodes.push(graphic('line', {x1: cx, y1: cy, x2: sx, y2: sy, stroke: '#8fb8ff', 'stroke-width': 1.2,
      'stroke-dasharray': '2 4', 'vector-effect': 'non-scaling-stroke'}));
  }
  nodes.push(graphic('circle', {cx, cy, r: Math.max(2, radiusUnit() / 120), fill: 'none', stroke: '#7de1b5',
    'vector-effect': 'non-scaling-stroke'}));
  const selected = (state.archive || state.result)?.rows[state.selection];
  if (selected?.id) {
    const mark = settings.marks.find(item => item.id === selected.id);
    if (mark) {
      const radius = (mark.inner + mark.outer) / 2;
      const [x0, y0] = sourcePoint(mark.start, radius, settings);
      const [x1, y1] = sourcePoint(mark.start + mark.span, radius, settings);
      const arc = radius * radiusUnit();
      nodes.push(graphic('path', {d: `M ${x0} ${y0} A ${arc} ${arc} 0 0 1 ${x1} ${y1}`, fill: 'none',
        stroke: '#ffbd76', 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke'}));
    }
  }
  if (state.cursor) {
    const [sx, sy] = state.cursor;
    const r = Math.max(3, radiusUnit() / 85);
    nodes.push(graphic('path', {d: `M ${sx-r} ${sy} H ${sx+r} M ${sx} ${sy-r} V ${sy+r}`, fill: 'none',
      stroke: '#ffbd76', 'stroke-width': 1.8, 'vector-effect': 'non-scaling-stroke'}));
    const valid = sx >= 0 && sy >= 0 && sx < panel.width && sy < panel.height;
    $('cursor').textContent = valid ? `原片 X ${sx.toFixed(1)} · Y ${sy.toFixed(1)} px` : '这个展开点位于原片外';
  } else $('cursor').textContent = '点选展开图或检查行定位';
  svg.replaceChildren(...nodes);
}

function stripRange() {
  const visible = state.archive || state.result;
  const settings = visible.settings;
  return visible.mode === 'slice' ? [settings.angle, settings.span] : [settings.seam ?? 0, 360];
}

function drawStrip() {
  const result = state.archive || state.result;
  if (!result || !state.stripUrl) return;
  const svg = $('strip');
  const settings = result.settings;
  const nodes = [graphic('image', {href: state.stripUrl, width: 960, height: 160, preserveAspectRatio: 'none'})];
  if (result.mode === 'surface') {
    for (const [index, row] of result.rows.entries()) {
      const mark = settings.marks.find(item => item.id === row.id);
      const clamp = radius => Math.max(0, Math.min(160, 160 * (settings.outer - radius) / (settings.outer - settings.inner)));
      const y = clamp(mark.outer);
      const h = clamp(mark.inner) - y;
      for (const [left, right] of row.segments) {
        if (h <= 0) continue;
        const attrs = {x: left / 360 * 960, y, width: (right - left) / 360 * 960, height: h,
          fill: index === state.selection ? '#ffbd7654' : '#ffbd761c', stroke: '#ffbd76',
          'stroke-width': 1.2, 'vector-effect': 'non-scaling-stroke'};
        const rect = graphic('rect', attrs);
        rect.append(graphic('title', {}));
        rect.firstChild.textContent = row.id;
        nodes.push(rect);
      }
    }
  }
  if (state.markStart) {
    nodes.push(graphic('circle', {cx: state.markStart[0], cy: state.markStart[1], r: 5, fill: '#ffbd76'}));
  }
  const [start, sweep] = stripRange();
  if (state.seamSuggestion) {
    const x = normalAngle(state.seamSuggestion.seam - start) / sweep * 960;
    nodes.push(graphic('line', {x1: x, y1: 0, x2: x, y2: 160, stroke: '#8fb8ff', 'stroke-width': 1.6,
      'stroke-dasharray': '6 4', 'vector-effect': 'non-scaling-stroke'}));
  }
  svg.replaceChildren(...nodes);
  svg.classList.toggle('choosing', state.tool === 'mark');
  $('strip-title').textContent = result.mode === 'slice' ? '角度切片' : '圆周展开';
  $('axis').replaceChildren(...[0, .25, .5, .75, 1].map(part =>
    element('span', `${Number(normalAngle(start + sweep * part).toFixed(1))}°`)));
  const seamNote = result.mode !== 'slice' && start ? `接缝 ${Number(start.toFixed(1))}° · ` : '';
  $('strip-help').textContent = state.tool === 'mark'
    ? (state.markStart ? '点击另一个角完成标记' : '点击标记的第一个角')
    : seamNote + '外圈在上 · 点击回到原片';
}

function focusRow(index) {
  state.selection = index;
  state.cursor = (state.archive || state.result).rows[index].point;
  drawPhoto();
  drawStrip();
  $('result-rows').querySelectorAll('tr').forEach((row, i) => row.classList.toggle('selected', i === index));
}

function drawRows() {
  const report = state.archive || state.result;
  const row = element('tr');
  row.append(...report.columns.map(col => element('th', col.title)));
  if (!state.archive && report.mode === 'surface') row.append(element('th', '标记操作'));
  $('result-header').replaceChildren(row);
  $('result-heading').textContent = report.heading;
  $('no-rows').hidden = !!report.rows.length;
  $('result-rows').replaceChildren(...report.rows.map((item, index) => {
    const row = element('tr', null, {tabindex: 0, 'data-row': index});
    row.append(...report.columns.map(col => element('td', format(item[col.key]))));
    row.onclick = () => focusRow(index);
    row.onkeydown = event => {
      if (event.target === row && ['Enter', ' '].includes(event.key)) {
        event.preventDefault();
        focusRow(index);
      }
    };
    if (!state.archive && report.mode === 'surface') {
      const cell = element('td');
      const remove = element('button', '移除', {'aria-label': '移除 ' + item.id});
      remove.onclick = action(async event => {
        event.stopPropagation();
        applyFields();
        state.draft.marks = state.draft.marks.filter(mark => mark.id !== item.id);
        await inspect();
        tell('已从本次检查移除标记');
      });
      cell.append(remove);
      row.append(cell);
    }
    return row;
  }));
}

function drawMenu(items, nav, empty, create) {
  nav.replaceChildren(...(items.length ? items.map(create) : [element('p', empty)]));
}

async function updateMenu() {
  const list = await api('/panels');
  drawMenu(list, $('library'), '还没有照片', panel => {
    const button = element('button', panel.title);
    if (state.panel?.id === panel.id) button.setAttribute('aria-current', 'true');
    button.onclick = action(() => openPanel(panel.id));
    return button;
  });
  return list;
}

function drawArchive() {
  drawMenu(state.panel.checks, $('archive'), '还没有检查记录', report => {
    const button = element('button');
    const label = element('span', report.heading);
    label.append(element('small', new Date(report.created).toLocaleString(), {class: 'detail'}));
    button.append(label);
    if (state.archive?.id === report.id) button.setAttribute('aria-current', 'true');
    button.onclick = action(() => openArchive(report.id));
    return button;
  });
}

function drawMode() {
  const mode = state.archive?.mode || state.mode;
  $('mode-tag').hidden = false;
  $('mode-tag').textContent = state.archive ? '已保存' : '本次检查';
  $('controls').hidden = !!state.archive;
  $('save').hidden = !!state.archive;
  $('return-live').hidden = !state.archive;
  $('downloads').hidden = !state.archive;
  $('mark-controls').hidden = mode !== 'surface';
  $('slice-controls').hidden = mode !== 'slice';
  $('modes').querySelectorAll('button').forEach(node => node.setAttribute('aria-pressed', node.dataset.mode === mode));
  for (const node of document.querySelectorAll('[data-tool]')) node.setAttribute('aria-pressed', node.dataset.tool === state.tool);
}

async function loadStrip(settings, mode) {
  const blob = await api(panelPath() + '/strip', 'POST', {settings, mode}, 'blob');
  if (state.stripUrl) URL.revokeObjectURL(state.stripUrl);
  state.stripUrl = URL.createObjectURL(blob);
}

async function inspect() {
  const record = await api(panelPath() + '/preview', 'POST', {settings: state.draft, mode: state.mode});
  await loadStrip(record.settings, record.mode);
  state.result = record;
  state.draft = structuredClone(record.settings);
  state.archive = null;
  state.cursor = null;
  state.selection = null;
  state.markStart = null;
  state.tool = null;
  state.seamSuggestion = null;
  $('seam-bar').hidden = true;
  showFields();
  drawMode();
  drawPhoto();
  drawStrip();
  drawRows();
  drawArchive();
}

async function openPanel(id) {
  const record = await api('/panels/' + id);
  state.panel = record;
  state.draft = structuredClone(record.settings);
  state.mode = 'surface';
  state.result = null;
  state.archive = null;
  localStorage.setItem('groovedesk-panel', id);
  $('title').textContent = record.title;
  $('file-info').textContent = `${record.filename} · ${record.width} × ${record.height} px`;
  $('desk').hidden = false;
  $('empty').hidden = true;
  await inspect();
  await updateMenu();
  tell('已打开原片');
}

async function showArchive(record) {
  await loadStrip(record.settings, record.mode);
  state.archive = record;
  state.cursor = null;
  state.selection = null;
  state.tool = null;
  state.markStart = null;
  state.seamSuggestion = null;
  $('seam-bar').hidden = true;
  const root = apiRoot + panelPath() + '/checks/' + record.id;
  $('csv').href = root + '/report.csv';
  $('overlay').href = root + '/overlay.png';
  $('strip-download').href = root + '/strip.png';
  drawMode();
  drawArchive();
  drawPhoto();
  drawStrip();
  drawRows();
}

async function openArchive(id) {
  const record = await api(panelPath() + '/checks/' + id);
  await showArchive(record);
}

function pickTool(tool) {
  state.tool = state.tool === tool ? null : tool;
  state.markStart = null;
  const text = {center: '点选原片上的盘心。', inner: '点选原片上的内圈边缘。',
    outer: '点选原片上的外圈边缘。', phase: '点选原片上用于对照的零位方向。'};
  $('cal-hint').textContent = text[state.tool] || '可在原片点选位置，也可微调数值。';
  drawMode();
  drawPhoto();
  drawStrip();
}

$('photo').onclick = action(async event => {
  if (!state.tool || state.tool === 'mark' || state.archive) return;
  const point = framePoint(event, $('photo'));
  const {width, height} = state.panel;
  if (!point || point[0] < 0 || point[1] < 0 || point[0] >= width || point[1] >= height) return;
  applyFields();
  const [cx, cy] = origin(state.draft);
  const [x, y] = point;
  if (state.tool === 'center') state.draft.center = [Math.min(1, x / (width - 1)), Math.min(1, y / (height - 1))];
  else if (state.tool === 'phase') state.draft.phase = normalAngle(Math.atan2(x - cx, cy - y) * 360 / TAU);
  else state.draft[state.tool] = Math.hypot(x - cx, y - cy) / radiusUnit();
  showFields();
  await inspect();
  $('cal-hint').textContent = '已更新展开，需要时可保留标定。';
});

$('strip').onclick = action(async event => {
  if (!state.result && !state.archive) return;
  const point = framePoint(event, $('strip'));
  const settings = (state.archive || state.result).settings;
  if (!point || point[0] < 0 || point[1] < 0 || point[0] >= 960 || point[1] >= 160) return;
  const angleAt = x => settings.phase + stripRange()[0] + x / 960 * stripRange()[1];
  const radiusAt = y => settings.outer - y / 160 * (settings.outer - settings.inner);
  if (state.tool === 'mark' && !state.archive) {
    if (!state.markStart) {
      state.markStart = point;
      drawStrip();
      return;
    }
    const [a, b] = [angleAt(state.markStart[0]), angleAt(point[0])].sort((a, b) => a - b);
    const [inner, outer] = [radiusAt(state.markStart[1]), radiusAt(point[1])].sort((a, b) => a - b);
    const span = b - a;
    if (span < .1 || span > 180 || outer - inner < .001) {
      state.markStart = null;
      drawStrip();
      throw Error('标记需有可见大小，角宽不可超过半圈。');
    }
    applyFields();
    let number = 1;
    while (state.draft.marks.some(mark => mark.id === `M-${number}`)) number += 1;
    if (state.draft.marks.length >= 64) throw Error('最多保存 64 条标记。');
    state.draft.marks.push({id: `M-${number}`, kind: $('kind').value, start: normalAngle(a), span, inner, outer});
    await inspect();
    tell('已添加标记，保留标定后可继续编辑。');
    return;
  }
  state.selection = null;
  state.cursor = sourcePoint(angleAt(point[0]), radiusAt(point[1]), settings);
  drawPhoto();
  drawStrip();
  $('result-rows').querySelectorAll('tr').forEach(row => row.classList.remove('selected'));
});

$('sample').onclick = action(async () => {
  const panel = await api('/demo', 'POST', {});
  await openPanel(panel.id);
});
$('file').onchange = action(async event => {
  const file = event.target.files[0];
  if (!file) return;
  const data = new FormData();
  data.append('file', file);
  try {
    const panel = await api('/panels', 'POST', data);
    await openPanel(panel.id);
  } finally {
    event.target.value = '';
  }
});
for (const node of document.querySelectorAll('[data-tool]')) node.onclick = action(() => pickTool(node.dataset.tool));
$('add-mark').onclick = action(() => pickTool('mark'));
$('suggest-seam').onclick = action(async () => {
  applyFields();
  const idea = await api(panelPath() + '/seam', 'POST', {settings: state.draft});
  state.seamSuggestion = idea;
  const margins = idea.left === null ? '' : `，两端余量 ${idea.left.toFixed(1)}° / ${idea.right.toFixed(1)}°`;
  $('seam-text').textContent = idea.cut.length
    ? `建议接缝 ${idea.seam.toFixed(1)}°：标记围满一圈，将切断 ${idea.cut.join('、')}${margins}`
    : `建议接缝 ${idea.seam.toFixed(1)}°：不切断任何标记${margins}`;
  $('seam-bar').hidden = false;
  drawStrip();
});
$('seam-apply').onclick = action(async () => {
  if (!state.seamSuggestion) return;
  applyFields();
  state.draft.seam = state.seamSuggestion.seam;
  await inspect();
  tell(`已采用接缝 ${state.draft.seam.toFixed(1)}°，保留标定或保存检查后生效`);
});
$('seam-hide').onclick = action(async () => {
  state.seamSuggestion = null;
  $('seam-bar').hidden = true;
  drawStrip();
});
$('refresh').onclick = action(async () => {
  applyFields();
  await inspect();
  tell('展开已更新');
});
$('retain').onclick = action(async () => {
  applyFields();
  state.panel = await api(panelPath() + '/settings', 'PUT', {settings: state.draft, revision: state.panel.revision});
  state.draft = structuredClone(state.panel.settings);
  await inspect();
  tell('标定和标记已保留');
});
$('save').onclick = action(async () => {
  applyFields();
  const saved = await api(panelPath() + '/checks', 'POST', {
    settings: state.draft, mode: state.mode, revision: state.panel.revision});
  state.panel = saved.panel;
  await showArchive(saved.check);
});
$('return-live').onclick = action(() => inspect());

action(async () => {
  state.config = await api('/config');
  for (const [mode, label] of Object.entries(state.config.modes)) {
    const node = element('button', label, {'data-mode': mode});
    node.onclick = action(async () => {
      applyFields();
      state.mode = mode;
      await inspect();
      tell(label + '已更新');
    });
    $('modes').append(node);
  }
  for (const [kind, label] of Object.entries(state.config.marks)) $('kind').append(element('option', label, {value: kind}));
  drawMenu([], $('archive'), '还没有检查记录');
  const panels = await updateMenu();
  const remembered = localStorage.getItem('groovedesk-panel');
  if (panels.length) await openPanel((panels.find(item => item.id === remembered) || panels[0]).id);
})();
