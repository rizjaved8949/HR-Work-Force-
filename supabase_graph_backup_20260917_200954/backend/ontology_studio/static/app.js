const state = { dashboard:null, graph:null, entities:[], datasets:[], coverage:{}, selectedDataset:null };
const $ = (id) => document.getElementById(id);
const api = async (path, options={}) => {
  const token = localStorage.getItem('ontologyStudioAccessToken');
  const headers = {'Content-Type':'application/json', ...(options.headers||{})};
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, {...options, headers});
  if (!response.ok) { const text = await response.text(); throw new Error(`${response.status} ${text}`); }
  return response.json();
};
const esc = (value='') => String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const notify = (message, error=false) => { const n=$('notice'); n.textContent=message; n.classList.remove('hidden'); if(!error) n.style.borderColor='rgba(85,209,135,.25)'; setTimeout(()=>n.classList.add('hidden'),4500); };

const titles = {
  overview:['Overview','Ontology health, graph status and governance at a glance.'],
  graph:['Ontology Graph','Explore entities and semantic relationships without loading every HR record.'],
  entities:['Entities & Properties','Inspect the business vocabulary, properties and semantic status.'],
  mappings:['Source Mappings','Trace current source columns into ontology concepts.'],
  coverage:['AI Service Coverage','Confirm service contracts are backed by explicit semantic mappings.'],
  reviews:['Mapping Reviews','Stage and govern mapping proposals safely.'],
  changes:['Change Requests','Manage draft ontology evolution without silent production mutation.']
};

document.querySelectorAll('.nav-item').forEach(btn => btn.addEventListener('click', () => {
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active')); btn.classList.add('active');
  document.querySelectorAll('.view').forEach(x=>x.classList.remove('active')); $(`view-${btn.dataset.view}`).classList.add('active');
  const [t,s]=titles[btn.dataset.view]; $('page-title').textContent=t; $('page-subtitle').textContent=s;
}));

function metric(label, value, note='') { return `<div class="metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`; }
function renderDashboard(){
  const d=state.dashboard, o=d.ontology, m=d.mapping, g=d.graph;
  $('metrics').innerHTML = [
    metric('Ontology version',o.version,o.status), metric('Entities',o.entity_count,`${o.module_count} modules`),
    metric('Relationships',o.relationship_count,'semantic edges'), metric('Mapped columns',m.source_column_count,`${m.source_dataset_count} datasets`),
    metric('Graph nodes',g.node_count ?? '—',g.available?'live tenant':'unavailable'), metric('Graph relationships',g.relationship_count ?? '—',g.available?'live tenant':'unavailable')
  ].join('');
  $('graph-badge').textContent=g.available?'Connected':'Unavailable'; $('graph-badge').className=`badge ${g.available?'ok':'danger'}`;
  $('graph-health').classList.remove('skeleton'); $('graph-health').innerHTML = g.available
    ? `<div class="health-stats"><div class="stat-line"><span>Nodes</span><strong>${g.node_count}</strong></div><div class="stat-line"><span>Relationships</span><strong>${g.relationship_count}</strong></div></div><p class="ok-text">Neo4j is available for tenant ${esc(d.tenant_id)}.</p>`
    : `<p class="danger-text">${esc(g.error || 'Graph unavailable')}</p>`;
  $('safety-block').innerHTML = `<div class="list-stack"><div class="list-item"><strong>Active ontology mutation</strong><span>${d.safety.active_ontology_mutation_enabled?'Enabled':'Disabled'}</span></div><div class="list-item"><strong>Active mapping mutation</strong><span>${d.safety.active_mapping_mutation_enabled?'Enabled':'Disabled'}</span></div><div class="list-item"><strong>Workflow</strong><span>${esc(d.safety.review_workflow)}</span></div></div><p>${esc(d.safety.note)}</p>`;
  $('semantic-items').innerHTML = d.pending_semantic_items.length ? `<div class="list-stack">${d.pending_semantic_items.map(x=>`<div class="list-item"><strong>${esc(x.concept)}</strong><span>${esc(x.reason)}</span></div>`).join('')}</div>` : '<p class="ok-text">No open semantic items.</p>';
  $('review-summary').innerHTML = `<div class="health-stats"><div class="stat-line"><span>Pending mapping reviews</span><strong>${d.review_counts.mapping_pending}</strong></div><div class="stat-line"><span>Pending change requests</span><strong>${d.review_counts.change_pending}</strong></div></div>`;
  renderCoverage();
}

function renderCoverage(){
  const coverage = state.dashboard?.service_coverage || {};
  $('coverage-list').innerHTML = Object.entries(coverage).map(([name,c])=>{
    const pct = c.coverage_percent ?? (c.covered_fields && c.contract_fields ? 100*c.covered_fields/c.contract_fields : 100);
    const missing = c.missing_paths || c.missing_fields || c.core_unmodeled_columns || [];
    return `<div class="coverage-row"><div><strong>${esc(name)}</strong><br><small class="muted">${missing.length?`${missing.length} attention item(s)`:'covered'}</small></div><div><div class="progress"><span style="width:${Math.max(0,Math.min(100,pct))}%"></span></div></div><strong>${Number(pct).toFixed(0)}%</strong></div>`;
  }).join('');
}

function renderEntities(filter=''){
  const q=filter.toLowerCase();
  const entities=state.entities.filter(e => !q || e.name.toLowerCase().includes(q) || e.module.toLowerCase().includes(q) || e.properties.some(p=>p.name.toLowerCase().includes(q)));
  $('entity-list').innerHTML=entities.map(e=>`<article class="entity-card"><h3>${esc(e.name)}</h3><p>${esc(e.description)}</p><div class="entity-meta"><span class="chip">${esc(e.module)}</span><span class="chip">${e.properties.length} properties</span><span class="chip">${e.relationship_count} relationships</span><span class="chip">${e.mapped_source_column_count} mapped columns</span>${e.pending_property_count?`<span class="chip warn-text">${e.pending_property_count} pending</span>`:''}</div><div class="property-list">${e.properties.map(p=>`<div class="property"><span>${esc(p.name)}${p.semantic_status!=='confirmed'?' ⚠':''}</span><span>${esc(p.data_type)}${p.unit?` · ${esc(p.unit)}`:''}</span></div>`).join('')}</div></article>`).join('');
}

function renderDatasets(filter=''){
  const q=filter.toLowerCase();
  const rows=state.datasets.filter(d=>!q||d.source_file.toLowerCase().includes(q));
  $('dataset-list').innerHTML=rows.map(d=>`<div class="dataset-row ${state.selectedDataset===d.source_file?'active':''}" data-file="${encodeURIComponent(d.source_file)}"><strong>${esc(d.source_file)}</strong><small>${d.column_count} columns · ${d.ontology_path_count} ontology paths${d.attention_count?` · ${d.attention_count} attention`:''}</small></div>`).join('');
  document.querySelectorAll('.dataset-row').forEach(el=>el.addEventListener('click',()=>loadDataset(decodeURIComponent(el.dataset.file))));
}
async function loadDataset(file){
  try { const d=await api(`/ontology-studio/api/datasets/${encodeURIComponent(file)}`); state.selectedDataset=file; renderDatasets($('dataset-search').value); $('dataset-detail').innerHTML=`<div class="panel-head"><div><h2>${esc(d.source_file)}</h2><p>${d.row_count} source rows · ${d.column_count} columns</p></div><span class="badge ${d.attention_columns.length?'warn':'ok'}">${d.attention_columns.length?`${d.attention_columns.length} attention`:'classified'}</span></div><div style="overflow:auto"><table><thead><tr><th>Source column</th><th>Disposition</th><th>Ontology path</th><th>Transform / reason</th></tr></thead><tbody>${d.columns.map(c=>`<tr><td>${esc(c.source_column)}</td><td>${esc(c.disposition)}</td><td><code>${esc(c.ontology_path||'—')}</code></td><td>${esc(c.transform||c.reason||'—')}</td></tr>`).join('')}</tbody></table></div>`; }
  catch(e){ notify(e.message,true); }
}

function renderGraph(){
  const data=state.graph, svg=$('ontology-graph'), W=1100,H=720,cx=W/2,cy=H/2;
  const modules=[...new Set(data.nodes.map(n=>n.module))]; $('graph-module').innerHTML='<option value="">All modules</option>'+modules.map(m=>`<option>${esc(m)}</option>`).join('');
  const pos=new Map(); data.nodes.forEach((n,i)=>{ const a=(Math.PI*2*i/data.nodes.length)-Math.PI/2; const r=250+(i%3)*28; pos.set(n.id,{x:cx+Math.cos(a)*r,y:cy+Math.sin(a)*r}); });
  const edges=data.edges.map(e=>{const a=pos.get(e.source),b=pos.get(e.target);return `<line class="edge" data-source="${esc(e.source)}" data-target="${esc(e.target)}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/>`;}).join('');
  const nodes=data.nodes.map(n=>{const p=pos.get(n.id);return `<g class="graph-node" data-id="${esc(n.id)}" data-module="${esc(n.module)}" transform="translate(${p.x},${p.y})"><circle r="${17+Math.min(8,n.property_count/4)}"></circle><text y="34">${esc(n.label)}</text>${n.pending_property_count?'<text y="-24" class="warn-text">⚠</text>':''}</g>`;}).join('');
  svg.innerHTML=`<g>${edges}</g><g>${nodes}</g>`;
  document.querySelectorAll('.graph-node').forEach(el=>el.addEventListener('click',()=>selectGraphNode(el.dataset.id)));
}
function selectGraphNode(id){
  document.querySelectorAll('.graph-node').forEach(x=>x.classList.toggle('selected',x.dataset.id===id));
  const n=state.entities.find(e=>e.name===id); if(!n)return;
  $('graph-detail').innerHTML=`<h2>${esc(n.name)}</h2><p>${esc(n.description)}</p><div class="entity-meta"><span class="chip">${esc(n.module)}</span><span class="chip">${n.properties.length} properties</span><span class="chip">${n.relationship_count} relationships</span></div><h3>Properties</h3><div class="property-list">${n.properties.map(p=>`<div class="property"><span>${esc(p.name)}</span><span>${esc(p.data_type)}${p.semantic_status!=='confirmed'?' · pending':''}</span></div>`).join('')}</div>`;
}
function filterGraph(){ const q=$('graph-search').value.toLowerCase(),m=$('graph-module').value; document.querySelectorAll('.graph-node').forEach(n=>{const show=(!q||n.dataset.id.toLowerCase().includes(q))&&(!m||n.dataset.module===m);n.classList.toggle('dim',!show)}); document.querySelectorAll('.edge').forEach(e=>{const s=document.querySelector(`.graph-node[data-id="${CSS.escape(e.dataset.source)}"]`),t=document.querySelector(`.graph-node[data-id="${CSS.escape(e.dataset.target)}"]`);e.classList.toggle('dim',s?.classList.contains('dim')||t?.classList.contains('dim'));}); }

async function renderReviews(){
  const items=await api('/ontology-studio/api/mapping-reviews');
  $('mapping-reviews').innerHTML=items.length?items.slice().reverse().map(r=>`<div class="review-card"><div class="row"><h3>${esc(r.source_file)} · ${esc(r.source_column)}</h3><span class="badge ${r.status==='approved'?'ok':r.status==='rejected'?'danger':'warn'}">${esc(r.status)}</span></div><p>${esc(r.reason)}</p><small class="muted">Proposed: ${esc(r.proposed_ontology_path||r.proposed_disposition||'review only')}</small>${r.status==='pending'?`<div class="review-actions"><button class="btn small primary" onclick="decideMapping('${r.id}','approved')">Approve</button><button class="btn small secondary" onclick="decideMapping('${r.id}','rejected')">Reject</button></div>`:''}</div>`).join(''):'<p class="muted">No mapping reviews yet.</p>';
}
async function renderChanges(){
  const items=await api('/ontology-studio/api/change-requests');
  $('change-requests').innerHTML=items.length?items.slice().reverse().map(r=>`<div class="review-card"><div class="row"><h3>${esc(r.title)}</h3><span class="badge ${r.status==='approved'?'ok':r.status==='rejected'?'danger':'warn'}">${esc(r.status)}</span></div><small class="muted">${esc(r.kind)} · ${esc(r.target)}</small><p>${esc(r.description)}</p>${r.status==='pending'?`<div class="review-actions"><button class="btn small primary" onclick="decideChange('${r.id}','approved')">Approve</button><button class="btn small secondary" onclick="decideChange('${r.id}','rejected')">Reject</button></div>`:''}</div>`).join(''):'<p class="muted">No change requests yet.</p>';
}
window.decideMapping=async(id,decision)=>{try{await api(`/ontology-studio/api/mapping-reviews/${id}`,{method:'PATCH',body:JSON.stringify({decision})});await renderReviews();await loadDashboard();notify(`Mapping review ${decision}.`);}catch(e){notify(e.message,true)}};
window.decideChange=async(id,decision)=>{try{await api(`/ontology-studio/api/change-requests/${id}`,{method:'PATCH',body:JSON.stringify({decision})});await renderChanges();await loadDashboard();notify(`Change request ${decision}.`);}catch(e){notify(e.message,true)}};

async function fillReviewSources(){ $('review-source-file').innerHTML=state.datasets.map(d=>`<option value="${esc(d.source_file)}">${esc(d.source_file)}</option>`).join(''); await updateReviewColumns(); }
async function updateReviewColumns(){ const file=$('review-source-file').value;if(!file)return;const d=await api(`/ontology-studio/api/datasets/${encodeURIComponent(file)}`);$('review-source-column').innerHTML=d.columns.map(c=>`<option value="${esc(c.source_column)}">${esc(c.source_column)} · ${esc(c.disposition)}</option>`).join(''); }

$('mapping-review-form').addEventListener('submit',async(e)=>{e.preventDefault();try{await api('/ontology-studio/api/mapping-reviews',{method:'POST',body:JSON.stringify({source_file:$('review-source-file').value,source_column:$('review-source-column').value,proposed_ontology_path:$('review-path').value||null,proposed_disposition:$('review-disposition').value||null,reason:$('review-reason').value})});e.target.reset();await fillReviewSources();await renderReviews();await loadDashboard();notify('Mapping review created.');}catch(err){notify(err.message,true);}});
$('change-form').addEventListener('submit',async(e)=>{e.preventDefault();try{await api('/ontology-studio/api/change-requests',{method:'POST',body:JSON.stringify({kind:$('change-kind').value,target:$('change-target').value,title:$('change-title').value,description:$('change-description').value,proposed_change:{}})});e.target.reset();await renderChanges();await loadDashboard();notify('Ontology change request created.');}catch(err){notify(err.message,true);}});

async function loadDashboard(){ state.dashboard=await api(`/ontology-studio/api/dashboard?tenant_id=${encodeURIComponent($('tenant-id').value)}`); renderDashboard(); }
async function bootstrap(){
  try{
    const [dashboard,graph,entities,datasets]=await Promise.all([api(`/ontology-studio/api/dashboard?tenant_id=${encodeURIComponent($('tenant-id').value)}`),api('/ontology-studio/api/schema-graph'),api('/ontology-studio/api/entities'),api('/ontology-studio/api/datasets')]);
    Object.assign(state,{dashboard,graph,entities,datasets}); renderDashboard(); renderGraph(); renderEntities(); renderDatasets(); await fillReviewSources(); await Promise.all([renderReviews(),renderChanges()]);
  }catch(e){notify(e.message,true);}
}
$('refresh-btn').addEventListener('click',bootstrap); $('entity-search').addEventListener('input',e=>renderEntities(e.target.value)); $('dataset-search').addEventListener('input',e=>renderDatasets(e.target.value)); $('graph-search').addEventListener('input',filterGraph); $('graph-module').addEventListener('change',filterGraph); $('graph-reset').addEventListener('click',()=>{$('graph-search').value='';$('graph-module').value='';filterGraph();}); $('review-source-file').addEventListener('change',updateReviewColumns);
bootstrap();
