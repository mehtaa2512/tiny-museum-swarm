const state = {
  config: null,
  runId: null,
  events: [],
  metrics: null,
  workspace: null,
  agentStatus: {},
  source: null,
};

const glyphs = { scout: '⌕', weaver: '⌘', storysmith: '✎', curator: '♢' };
const eventLabels = {
  run_started: ['Doors open', '✦'], assignment: ['Assignment', '→'], model_call_started: ['Model call', '◌'],
  tool_call: ['AutoGen tool call', '⚙'], tool_result: ['AutoGen tool result', '↳'], model_result: ['Model result', '◆'],
  agent_message: ['Public message', '●'], handoff: ['Handoff', '⇢'], curator_rejection: ['Curator rejection', '×'],
  curator_approval: ['Curator approval', '✓'], budget_warning: ['Budget warning', '!'], human_intervention: ['Human intervention', '◇'],
  curator_revision_requested: ['Curator rewrite', '↻'],
  provider_retry: ['Provider retry', '↻'],
  image_generation_started: ['Creating image', '▧'], image_generated: ['Image ready', '▣'], image_generation_failed: ['Image unavailable', '!'],
  run_completed: ['Exhibition complete', '✦'], run_terminated: ['Run stopped', '■']
};
const eventColors = {
  run_started: '#d9a84e', assignment: '#8d857a', model_call_started: '#8d857a', handoff: '#d9a84e',
  tool_call: '#73a6ff', tool_result: '#8aa4c8', model_result: '#a98cff',
  curator_rejection: '#ff6f91', curator_approval: '#59d7c7', budget_warning: '#ee7d62',
  human_intervention: '#ffb85a', curator_revision_requested: '#ffb85a', provider_retry: '#ffb85a', image_generation_started: '#d9a84e', image_generated: '#59d7c7',
  image_generation_failed: '#ee7d62', run_completed: '#59d7c7', run_terminated: '#ff6f91'
};

document.addEventListener('DOMContentLoaded', init);

async function init() {
  bindUI();
  try {
    state.config = await api('/api/config');
    state.metrics = emptyMetrics();
    renderAgents();
    renderWorkspace();
    renderStats();
    renderConfig();
    updateGlobalMeter();
    positionBudgetTicks();
    checkHealth();
  } catch (error) {
    setRunStatus(`Setup error: ${error.message}`);
  }
}

function bindUI() {
  document.querySelectorAll('.tab').forEach(button => button.addEventListener('click', () => showTab(button.dataset.tab)));
  document.querySelector('#run-form').addEventListener('submit', startRun);
  document.querySelector('#cancel-button').addEventListener('click', cancelRun);
  document.querySelector('#config-form').addEventListener('submit', saveConfig);
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}

async function checkHealth() {
  const element = document.querySelector('#provider-status');
  try {
    const health = await api('/api/health');
    const entries = Object.entries(health.providers);
    const ready = entries.find(([, value]) => value.status === 'ready');
    const unavailable = entries.find(([, value]) => value.status === 'unavailable');
    if (ready) {
      const models = ready[1].models?.length ? ` · ${ready[1].models.length} models` : '';
      element.className = 'provider-status ready';
      element.innerHTML = `<span class="status-dot"></span>${escapeHTML(ready[0])} ready${models}`;
    } else if (unavailable) {
      element.className = 'provider-status unavailable';
      element.innerHTML = '<span class="status-dot"></span>Local model service offline';
    }
  } catch (_) {
    element.className = 'provider-status unavailable';
    element.innerHTML = '<span class="status-dot"></span>Health check unavailable';
  }
}

async function startRun(event) {
  event.preventDefault();
  const topic = document.querySelector('#topic').value.trim();
  if (!topic) return;
  if (state.source) state.source.close();
  state.events = [];
  state.workspace = null;
  state.metrics = emptyMetrics();
  state.agentStatus = {};
  renderTranscript(); renderWorkspace(); renderStats(); renderAgents(); renderExhibition();
  toggleRunning(true);
  setRunStatus('Opening the gallery…');
  try {
    const run = await api('/api/runs', { method: 'POST', body: JSON.stringify({ topic }) });
    state.runId = run.id;
    connectEvents(run.id);
  } catch (error) {
    toggleRunning(false);
    setRunStatus(error.message);
  }
}

function connectEvents(runId) {
  state.source = new EventSource(`/api/runs/${runId}/events`);
  state.source.addEventListener('swarm', message => {
    const event = JSON.parse(message.data);
    state.events.push(event);
    if (event.meta?.metrics) state.metrics = event.meta.metrics;
    if (event.meta?.workspace) state.workspace = event.meta.workspace;
    if (event.meta?.agent_status) state.agentStatus = event.meta.agent_status;
    renderEvent(event); renderAgents(); renderWorkspace(); renderStats(); updateGlobalMeter();
    if (event.type === 'run_completed') {
      setRunStatus('Curator approved · exhibition complete');
      renderExhibition(event.meta.final_exhibition, event.meta.final_visual_plan, event.meta.image_url);
      toggleRunning(false); state.source.close();
      showTab('exhibition');
    } else if (event.type === 'run_terminated') {
      setRunStatus(`Stopped · ${humanize(event.meta.termination_reason || 'guardrail')}`);
      toggleRunning(false); state.source.close();
    } else if (event.agent) {
      setRunStatus(`${agentName(event.agent)} · ${humanize(event.type)}`);
    }
  });
  state.source.onerror = () => {
    if (!document.querySelector('#start-button').disabled) return;
    setRunStatus('Event stream reconnecting…');
  };
}

async function cancelRun() {
  if (!state.runId) return;
  document.querySelector('#cancel-button').disabled = true;
  try { await api(`/api/runs/${state.runId}/cancel`, { method: 'POST', body: '{}' }); }
  catch (error) { setRunStatus(error.message); }
}

function toggleRunning(running) {
  document.querySelector('#start-button').disabled = running;
  document.querySelector('#topic').disabled = running;
  document.querySelector('#cancel-button').classList.toggle('hidden', !running);
  document.querySelector('#cancel-button').disabled = false;
}

function renderAgents() {
  if (!state.config) return;
  const container = document.querySelector('#agent-cards');
  container.replaceChildren(...Object.entries(state.config.agents).map(([id, agent]) => {
    const usage = state.metrics?.per_agent?.[id] || { tokens: 0, budget: agent.token_budget, calls: 0, handoffs: 0 };
    const status = state.agentStatus[id] || 'idle';
    const card = element('article', `agent-card ${status}`);
    card.style.setProperty('--agent', agent.color);
    card.innerHTML = `<div class="agent-head"><span class="agent-glyph">${glyphs[id]}</span><h3>${escapeHTML(agent.display_name)}</h3><span class="agent-status">${escapeHTML(status)}</span></div>
      <div class="agent-model">${escapeHTML(agent.provider)} · ${escapeHTML(agent.model)}</div>
      <div class="agent-numbers"><div><b>${formatNumber(usage.tokens)}</b><span>tokens</span></div><div><b>${usage.calls}</b><span>calls</span></div><div><b>${usage.handoffs}</b><span>handoffs</span></div></div>
      <div class="mini-track"><i style="width:${percent(usage.tokens, usage.budget)}%"></i></div>`;
    return card;
  }));
}

function renderTranscript() {
  const container = document.querySelector('#transcript');
  container.innerHTML = '';
  if (!state.events.length) container.appendChild(emptyState('◌', 'The gallery is quiet', 'Choose an object to watch four agents build an exhibition together.'));
  else state.events.forEach(renderEvent);
  document.querySelector('#event-count').textContent = state.events.length;
}

function renderEvent(event) {
  const container = document.querySelector('#transcript');
  if (container.querySelector('.empty-state')) container.innerHTML = '';
  const [label, icon] = eventLabels[event.type] || [humanize(event.type), '·'];
  const agentColor = event.agent ? state.config.agents[event.agent]?.color : null;
  const card = element('article', 'event');
  card.style.setProperty('--event-color', eventColors[event.type] || agentColor || '#8d857a');
  const message = element('p', 'event-message'); message.textContent = event.public_message;
  const body = element('div', 'event-body');
  const kicker = element('div', 'event-kicker'); kicker.textContent = event.agent ? `${agentName(event.agent)} · ${label}` : label;
  body.append(kicker, message);
  if (event.decision_summary || event.handoff_reason) {
    const decision = element('p', 'event-decision');
    decision.textContent = event.decision_summary || '';
    if (event.handoff_reason) {
      const reason = element('span', 'handoff-reason');
      reason.textContent = `${event.decision_summary ? ' — ' : ''}${event.handoff_reason}`;
      decision.appendChild(reason);
    }
    body.appendChild(decision);
  }
  const meta = element('div', 'event-meta');
  const usage = event.input_tokens || event.output_tokens ? `${formatNumber(event.input_tokens)} in · ${formatNumber(event.output_tokens)} out${event.usage_is_estimated ? ' ~' : ''}` : '';
  meta.textContent = usage || new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const iconElement = element('div', 'event-icon'); iconElement.textContent = icon;
  card.append(iconElement, body, meta);
  container.appendChild(card);
  document.querySelector('#event-count').textContent = state.events.length;
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function renderWorkspace() {
  const workspace = state.workspace || { facts: [], connections: [], narrative: [], concerns: [] };
  const definitions = [['facts', 'Object & evidence'], ['connections', 'Cross-domain links'], ['narrative', 'Exhibition story'], ['concerns', 'Curator concerns']];
  const container = document.querySelector('#workspace');
  container.replaceChildren(...definitions.map(([key, title]) => {
    const card = element('section', 'workspace-card');
    const heading = element('h4'); heading.textContent = title; card.appendChild(heading);
    if (!workspace[key]?.length) { const none = element('p', 'nothing'); none.textContent = 'Nothing placed here yet.'; card.appendChild(none); }
    else { const list = element('ol'); workspace[key].forEach(item => { const li = element('li'); li.textContent = item; list.appendChild(li); }); card.appendChild(list); }
    return card;
  }));
}

function renderExhibition(markdown, visualPlan, imageUrl) {
  const finalText = markdown || state.workspace?.final_exhibition;
  const plan = visualPlan || state.workspace?.final_visual_plan;
  const container = document.querySelector('#exhibition');
  container.innerHTML = '';
  if (!finalText) { container.appendChild(emptyState('◇', 'No exhibition yet', 'Only the Museum Curator can open this final gallery.')); return; }
  if (imageUrl) {
    const figure = element('figure', 'generated-exhibition-visual');
    const image = element('img', 'exhibition-image');
    image.src = imageUrl;
    image.alt = plan?.caption || 'Generated miniature museum exhibition';
    const caption = element('figcaption');
    const heading = element('strong'); heading.textContent = 'Curator’s visual story';
    const story = element('p'); story.textContent = plan?.caption || 'The Curator did not provide a visual story.';
    caption.append(heading, story);
    figure.append(image, caption);
    container.appendChild(figure);
  } else if (plan?.center && Array.isArray(plan.elements)) container.appendChild(renderMiniature(plan));
  finalText.split('\n').forEach(line => {
    if (!line.trim()) return;
    let node;
    if (line.startsWith('# ')) { node = element('h1'); node.textContent = line.slice(2); }
    else if (line.startsWith('## ')) { node = element('h2'); node.textContent = line.slice(3); }
    else if (line.startsWith('### ')) { node = element('h3'); node.textContent = line.slice(4); }
    else { node = element('p'); node.textContent = line.replace(/^\*|\*$/g, ''); }
    container.appendChild(node);
  });
}

function renderMiniature(plan) {
  const figure = element('figure', 'exhibition-miniature');
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 600 330');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', plan.caption || `Visual map of ${plan.center}`);
  const nodes = plan.elements.slice(0, 5).map(value => String(value).slice(0, 38));
  const center = { x: 300, y: 155 };
  const positions = [[110, 75], [490, 75], [90, 245], [510, 245], [300, 285]];
  nodes.forEach((label, index) => {
    const [x, y] = positions[index];
    svg.appendChild(svgNode('line', { x1: center.x, y1: center.y, x2: x, y2: y, class: 'mini-link' }));
    svg.appendChild(svgNode('circle', { cx: x, cy: y, r: 42, class: 'mini-node' }));
    svg.appendChild(svgText(x, y, label, 'mini-label'));
  });
  svg.appendChild(svgNode('circle', { cx: center.x, cy: center.y, r: 62, class: 'mini-center' }));
  svg.appendChild(svgText(center.x, center.y, String(plan.center).slice(0, 34), 'mini-center-label'));
  figure.appendChild(svg);
  if (plan.caption) { const caption = element('figcaption'); caption.textContent = String(plan.caption).slice(0, 180); figure.appendChild(caption); }
  return figure;
}

function svgNode(name, attributes) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', name);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
  return node;
}

function svgText(x, y, value, className) {
  const textNode = svgNode('text', { x, y, class: className, 'text-anchor': 'middle', 'dominant-baseline': 'middle' });
  textNode.textContent = value;
  return textNode;
}

function renderStats() {
  const metrics = state.metrics || emptyMetrics();
  const container = document.querySelector('#statistics');
  const cards = [
    [formatNumber(metrics.total_tokens), `of ${formatNumber(metrics.total_token_budget)} tokens`],
    [metrics.model_calls, `of ${metrics.max_model_calls} model calls`],
    [metrics.handoffs, `of ${metrics.max_handoffs} handoffs`],
    [`$${Number(metrics.estimated_cost_usd || 0).toFixed(4)}`, 'estimated provider cost']
  ];
  container.innerHTML = cards.map(([value, label]) => `<div class="stat-card"><strong>${value}</strong><span>${label}</span></div>`).join('');
  const table = element('table', 'stat-table');
  table.innerHTML = '<thead><tr><th>Agent</th><th>Tokens</th><th>Budget used</th><th>Calls</th><th>Handoffs sent</th></tr></thead>';
  const tbody = element('tbody');
  Object.entries(state.config?.agents || {}).forEach(([id, agent]) => {
    const data = metrics.per_agent?.[id] || { tokens: 0, budget: agent.token_budget, calls: 0, handoffs: 0 };
    const row = element('tr');
    row.innerHTML = `<td>${escapeHTML(agent.display_name)}</td><td>${formatNumber(data.tokens)}</td><td>${percent(data.tokens, data.budget).toFixed(1)}%</td><td>${data.calls}</td><td>${data.handoffs}</td>`;
    tbody.appendChild(row);
  });
  table.appendChild(tbody); container.appendChild(table);
}

function renderConfig() {
  if (!state.config) return;
  const providers = Object.keys(state.config.providers);
  const container = document.querySelector('#config-rows');
  container.replaceChildren(...Object.entries(state.config.agents).map(([id, agent]) => {
    const row = element('div', 'config-row'); row.dataset.agent = id;
    const options = providers.map(provider => `<option value="${escapeHTML(provider)}" ${provider === agent.provider ? 'selected' : ''}>${escapeHTML(provider)}</option>`).join('');
    row.innerHTML = `<div class="config-agent" style="color:${agent.color}">${escapeHTML(agent.display_name)}</div><select name="provider">${options}</select><input name="model" value="${escapeHTML(agent.model)}" aria-label="${escapeHTML(agent.display_name)} model"><div class="config-budget">${formatNumber(agent.token_budget)} tokens</div>`;
    return row;
  }));
}

async function saveConfig(event) {
  event.preventDefault();
  const agents = {};
  document.querySelectorAll('.config-row').forEach(row => {
    agents[row.dataset.agent] = { provider: row.querySelector('[name=provider]').value, model: row.querySelector('[name=model]').value };
  });
  const message = document.querySelector('#config-message');
  try { state.config = await api('/api/config', { method: 'POST', body: JSON.stringify({ agents }) }); message.textContent = 'Saved for the next run.'; renderAgents(); }
  catch (error) { message.textContent = error.message; }
}

function updateGlobalMeter() {
  const metrics = state.metrics || emptyMetrics();
  document.querySelector('#global-usage').textContent = `${formatNumber(metrics.total_tokens)} / ${formatNumber(metrics.total_token_budget)} tokens`;
  document.querySelector('#global-meter-fill').style.width = `${percent(metrics.total_tokens, metrics.total_token_budget)}%`;
}

function emptyMetrics() {
  const limits = state.config?.limits || { total_tokens: 80000, max_model_calls: 10, max_handoffs: 9 };
  return { total_tokens: 0, total_token_budget: limits.total_tokens, model_calls: 0, max_model_calls: limits.max_model_calls, handoffs: 0, max_handoffs: limits.max_handoffs, estimated_cost_usd: 0, per_agent: {} };
}

function positionBudgetTicks() {
  const limits = state.config?.limits;
  if (!limits) return;
  document.querySelector('.warning-tick').style.left = `${limits.warn_at_fraction * 100}%`;
  document.querySelector('.reserve-tick').style.left = `${limits.curator_reserve_starts_at / limits.total_tokens * 100}%`;
}

function showTab(name) {
  document.querySelectorAll('.tab').forEach(tab => tab.classList.toggle('active', tab.dataset.tab === name));
  document.querySelectorAll('.view').forEach(view => view.classList.toggle('active', view.id === `view-${name}`));
}
function setRunStatus(text) { document.querySelector('#run-status').textContent = text; }
function agentName(id) { return state.config?.agents?.[id]?.display_name || humanize(id); }
function humanize(value) { return String(value || '').replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase()); }
function formatNumber(value) { return Number(value || 0).toLocaleString(); }
function percent(value, total) { return Math.min(100, total ? Number(value || 0) / total * 100 : 0); }
function element(tag, className = '') { const node = document.createElement(tag); if (className) node.className = className; return node; }
function emptyState(icon, title, copy) { const box = element('div', 'empty-state'); const mark = element('span'); mark.textContent = icon; const heading = element('h4'); heading.textContent = title; const paragraph = element('p'); paragraph.textContent = copy; box.append(mark, heading, paragraph); return box; }
function escapeHTML(value) { return String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char]); }
