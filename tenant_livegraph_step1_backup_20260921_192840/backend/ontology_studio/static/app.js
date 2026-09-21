const state = {
  tenants:[],
  dashboard:null,
  graph:null,
  liveGraph:null,
  graphMode:localStorage.getItem('ontologyGraphMode') || 'live',
  entities:[],
  datasets:[],
  reviewOptions:null,
  selectedDataset:null,
  selectedLiveNode:null,
  zoom:{scale:1,x:0,y:0},
};
const $ = (id) => document.getElementById(id);
const API_BASE = String(window.HR_API_BASE || '').replace(/\/$/, '');
const api = async (path, options={}) => {
  const token = localStorage.getItem('ontologyStudioAccessToken');
  const headers = {'Content-Type':'application/json', ...(options.headers||{})};
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${API_BASE}${path}`, {...options, headers});
  if (!response.ok) { const text = await response.text(); throw new Error(`${response.status} ${text}`); }
  return response.json();
};
const esc = (value='') => String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const notify = (message, error=false) => {
  const n=$('notice'); n.textContent=message; n.classList.remove('hidden');
  n.style.borderColor=error?'rgba(239,111,122,.35)':'rgba(85,209,135,.25)';
  setTimeout(()=>n.classList.add('hidden'),4500);
};

const titles = {
  overview:['Overview','Ontology health, live graph status and governance at a glance.'],
  graph:['Ontology Graph','Switch between the ontology schema and actual tenant data stored in kg_nodes / kg_relationships.'],
  entities:['Entities & Properties','Inspect the business vocabulary, properties and semantic status.'],
  mappings:['Source Mappings','Trace current source columns into ontology concepts.'],
  coverage:['AI Service Coverage','Confirm service contracts are backed by explicit semantic mappings.'],
  reviews:['Mapping Reviews','Choose ontology paths and dispositions from controlled selectors, then stage the review safely.'],
  changes:['Change Requests','Manage draft ontology evolution without silent production mutation.']
};

document.querySelectorAll('.nav-item').forEach(btn => btn.addEventListener('click', () => {
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active')); btn.classList.add('active');
  document.querySelectorAll('.view').forEach(x=>x.classList.remove('active')); $(`view-${btn.dataset.view}`).classList.add('active');
  const [t,s]=titles[btn.dataset.view]; $('page-title').textContent=t; $('page-subtitle').textContent=s;
  if (btn.dataset.view==='graph' && state.graphMode==='live' && state.dashboard) loadLiveGraph();
}));

function metric(label, value, note='') { return `<div class="metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`; }
function renderDashboard(){
  const d=state.dashboard, o=d.ontology, m=d.mapping, g=d.graph;
  $('metrics').innerHTML = [
    metric('Ontology version',o.version,o.status), metric('Entities',o.entity_count,`${o.module_count} modules`),
    metric('Relationships',o.relationship_count,'semantic edge types'), metric('Mapped columns',m.source_column_count,`${m.source_dataset_count} datasets`),
    metric('Live graph nodes',g.node_count ?? '—',g.available?d.tenant_id:'unavailable'), metric('Live graph relationships',g.relationship_count ?? '—',g.available?d.tenant_id:'unavailable')
  ].join('');
  $('graph-badge').textContent=g.available?'Connected':'Unavailable'; $('graph-badge').className=`badge ${g.available?'ok':'danger'}`;
  $('graph-health').classList.remove('skeleton'); $('graph-health').innerHTML = g.available
    ? `<div class="health-stats"><div class="stat-line"><span>Nodes</span><strong>${g.node_count}</strong></div><div class="stat-line"><span>Relationships</span><strong>${g.relationship_count}</strong></div></div><p class="ok-text">${esc(g.repository || 'Graph repository')} (${esc(g.backend || 'configured backend')}) is reading tenant ${esc(d.tenant_id)}.</p><button class="btn small primary" id="open-live-graph">Open live tenant graph</button>`
    : `<p class="danger-text">${esc(g.error || 'Graph unavailable')}</p>`;
  $('open-live-graph')?.addEventListener('click',()=>{ document.querySelector('[data-view="graph"]').click(); setGraphMode('live'); });
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

function edgeFamily(edge){
  const rel=String(edge.relation||edge.relation_type||'').toUpperCase();
  if (/(PERFORMANCE|SKILL|LEARNING|SUCCESSION|ENGAGEMENT|COMPENSATION|ATTENDANCE|EXPERIENCE|CAREER)/.test(rel)) return 'talent';
  if (/(BUDGET|HEADCOUNT|VACANCY|DEMAND|DECISION|SCENARIO|RISK|EXCEPTION|RECOMMENDATION)/.test(rel)) return 'planning';
  return 'structure';
}
function familyLabel(family){ return family==='talent'?'People / talent / performance':family==='planning'?'Planning / governance / risk':'Organization / structure / reporting'; }

function graphDefs(){
  return `<defs>
    <marker id="arrow-structure" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#52d6ff"/></marker>
    <marker id="arrow-talent" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#a78bfa"/></marker>
    <marker id="arrow-planning" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#f6c85f"/></marker>
  </defs>`;
}
function graphLegend(){ return `<g class="graph-legend" transform="translate(26,26)"><rect width="255" height="92" rx="12"></rect><text x="14" y="20" class="legend-title">Relationship colours</text><line x1="14" y1="38" x2="50" y2="38" class="edge edge-structure"></line><text x="60" y="42">Organization / structure</text><line x1="14" y1="58" x2="50" y2="58" class="edge edge-talent"></line><text x="60" y="62">People / talent / performance</text><line x1="14" y1="78" x2="50" y2="78" class="edge edge-planning"></line><text x="60" y="82">Planning / governance / risk</text></g>`; }

function resetZoom(){ state.zoom={scale:1,x:0,y:0}; applyZoom(); }
function applyZoom(){ const g=$('graph-viewport'); if(g) g.setAttribute('transform',`translate(${state.zoom.x} ${state.zoom.y}) scale(${state.zoom.scale})`); $('zoom-label').textContent=`${Math.round(state.zoom.scale*100)}%`; }
function zoomBy(factor){ state.zoom.scale=Math.max(.35,Math.min(3.5,state.zoom.scale*factor)); applyZoom(); }
function enablePanZoom(){
  const svg=$('ontology-graph'); if(svg.dataset.panReady==='1') return; svg.dataset.panReady='1';
  svg.addEventListener('wheel',e=>{ e.preventDefault(); zoomBy(e.deltaY<0?1.12:.89); },{passive:false});
  let dragging=false,last=null;
  svg.addEventListener('pointerdown',e=>{ if(e.target.closest('.graph-node,.edge-group')) return; dragging=true; last={x:e.clientX,y:e.clientY}; svg.setPointerCapture(e.pointerId); });
  svg.addEventListener('pointermove',e=>{ if(!dragging||!last)return; const r=svg.getBoundingClientRect(); state.zoom.x+=(e.clientX-last.x)*(1100/r.width); state.zoom.y+=(e.clientY-last.y)*(720/r.height); last={x:e.clientX,y:e.clientY}; applyZoom(); });
  svg.addEventListener('pointerup',()=>{dragging=false;last=null;}); svg.addEventListener('pointercancel',()=>{dragging=false;last=null;});
}

function renderSchemaGraph(){
  const data=state.graph, svg=$('ontology-graph'), W=1100,H=720,cx=W/2,cy=H/2;
  const modules=[...new Set(data.nodes.map(n=>n.module))];
  $('graph-module-label').textContent='Module';
  $('graph-module').innerHTML='<option value="">All modules</option>'+modules.map(m=>`<option>${esc(m)}</option>`).join('');
  $('graph-search').placeholder='Filter ontology entity…';
  $('graph-live-summary').innerHTML=`<span class="chip">Schema</span><span class="muted">${data.node_count} entity types · ${data.edge_count} relationship schemas</span>`;
  const groups=new Map(); data.nodes.forEach(n=>{if(!groups.has(n.module))groups.set(n.module,[]);groups.get(n.module).push(n)});
  const flat=[]; [...groups.entries()].sort(([a],[b])=>a.localeCompare(b)).forEach(([,items])=>items.sort((a,b)=>a.id.localeCompare(b.id)).forEach(x=>flat.push(x)));
  const pos=new Map(); flat.forEach((n,i)=>{const a=(Math.PI*2*i/flat.length)-Math.PI/2;const ring=i%2===0?245:305;pos.set(n.id,{x:cx+Math.cos(a)*ring,y:cy+Math.sin(a)*ring})});
  const edges=data.edges.map((e,i)=>{const a=pos.get(e.source),b=pos.get(e.target);if(!a||!b)return'';const dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1,nx=-dy/len,ny=dx/len,bend=((i%5)-2)*9,mx=(a.x+b.x)/2+nx*bend,my=(a.y+b.y)/2+ny*bend,f=edgeFamily(e),path=`M ${a.x} ${a.y} Q ${mx} ${my} ${b.x} ${b.y}`;return `<g class="edge-group" data-source="${esc(e.source)}" data-target="${esc(e.target)}" data-relation="${esc(e.relation)}" data-family="${f}"><path id="edge-${i}" class="edge edge-${f}" d="${path}" marker-end="url(#arrow-${f})"><title>${esc(e.source)} — ${esc(e.relation)} → ${esc(e.target)}</title></path><text class="edge-label edge-label-${f}"><textPath href="#edge-${i}" startOffset="50%" text-anchor="middle">${esc(e.relation)}</textPath></text></g>`}).join('');
  const nodes=data.nodes.map(n=>{const p=pos.get(n.id);return `<g class="graph-node schema-node" data-id="${esc(n.id)}" data-module="${esc(n.module)}" transform="translate(${p.x},${p.y})"><circle r="${17+Math.min(8,n.property_count/4)}"></circle><text y="34">${esc(n.label)}</text>${n.pending_property_count?'<text y="-24" class="warn-text">⚠</text>':''}</g>`}).join('');
  svg.innerHTML=`${graphDefs()}<g id="graph-viewport"><g class="all-edges">${edges}</g><g>${nodes}</g>${graphLegend()}</g>`;
  document.querySelectorAll('.schema-node').forEach(el=>el.addEventListener('click',()=>selectSchemaNode(el.dataset.id)));
  document.querySelectorAll('.edge-group').forEach(el=>el.addEventListener('click',()=>selectSchemaEdge(el)));
  resetZoom(); enablePanZoom(); filterSchemaGraph();
}
function selectSchemaEdge(el){
  const source=el.dataset.source,target=el.dataset.target,relation=el.dataset.relation,family=el.dataset.family;
  document.querySelectorAll('.edge-group').forEach(x=>x.classList.toggle('selected-edge',x===el));
  document.querySelectorAll('.graph-node').forEach(x=>x.classList.toggle('connected',x.dataset.id===source||x.dataset.id===target));
  $('graph-detail').innerHTML=`<div class="detail-kicker">SCHEMA RELATIONSHIP</div><h2>${esc(relation)}</h2><p><span class="relationship-dot dot-${family}"></span>${esc(familyLabel(family))}</p><div class="relation-card"><strong>${esc(source)}</strong><span>→ ${esc(relation)} →</span><strong>${esc(target)}</strong></div><p class="muted">This is an ontology relationship type, not an individual HR record.</p>`;
}
function selectSchemaNode(id){
  document.querySelectorAll('.graph-node').forEach(x=>{x.classList.toggle('selected',x.dataset.id===id);x.classList.remove('connected')});
  document.querySelectorAll('.edge-group').forEach(x=>x.classList.remove('selected-edge','connected-edge'));
  const relations=(state.graph?.edges||[]).filter(e=>e.source===id||e.target===id),connected=new Set(); relations.forEach(e=>connected.add(e.source===id?e.target:e.source));
  document.querySelectorAll('.graph-node').forEach(x=>x.classList.toggle('connected',connected.has(x.dataset.id))); document.querySelectorAll('.edge-group').forEach(x=>x.classList.toggle('connected-edge',x.dataset.source===id||x.dataset.target===id));
  const n=state.entities.find(e=>e.name===id); if(!n)return;
  const relHtml=relations.length?relations.map(e=>{const out=e.source===id,f=edgeFamily(e),other=out?e.target:e.source;return `<div class="relation-item"><span class="relationship-dot dot-${f}"></span><div><strong>${esc(e.relation)}</strong><small>${out?'outbound →':'← inbound'} ${esc(other)}</small></div></div>`}).join(''):'<p class="muted">No ontology relationships.</p>';
  $('graph-detail').innerHTML=`<div class="detail-kicker">ONTOLOGY ENTITY TYPE</div><h2>${esc(n.name)}</h2><p>${esc(n.description)}</p><div class="entity-meta"><span class="chip">${esc(n.module)}</span><span class="chip">${n.properties.length} properties</span><span class="chip">${relations.length} relationships</span></div><h3>Relationships</h3><div class="relationship-list">${relHtml}</div><h3>Properties</h3><div class="property-list">${n.properties.map(p=>`<div class="property"><span>${esc(p.name)}</span><span>${esc(p.data_type)}${p.semantic_status!=='confirmed'?' · pending':''}</span></div>`).join('')}</div>`;
}
function filterSchemaGraph(){
  if(state.graphMode!=='schema')return; const q=$('graph-search').value.toLowerCase(),m=$('graph-module').value;
  document.querySelectorAll('.graph-node').forEach(n=>{const show=(!q||n.dataset.id.toLowerCase().includes(q))&&(!m||n.dataset.module===m);n.classList.toggle('dim',!show)});
  document.querySelectorAll('.edge-group').forEach(e=>{const s=document.querySelector(`.graph-node[data-id="${CSS.escape(e.dataset.source)}"]`),t=document.querySelector(`.graph-node[data-id="${CSS.escape(e.dataset.target)}"]`);e.classList.toggle('dim',s?.classList.contains('dim')||t?.classList.contains('dim'))});
}

function liveLayout(data){
  const W=1100,H=720,cx=W/2,cy=H/2,pos=new Map(); const center=data.nodes.find(n=>n.center);
  if(center){ pos.set(center.graph_id,{x:cx,y:cy}); const others=data.nodes.filter(n=>!n.center); others.forEach((n,i)=>{const ring=i<18?205:i<48?285:335;const count=i<18?Math.min(18,others.length):i<48?Math.min(30,Math.max(1,others.length-18)):Math.max(1,others.length-48);const offset=i<18?i:i<48?i-18:i-48;const a=(Math.PI*2*offset/count)-Math.PI/2;pos.set(n.graph_id,{x:cx+Math.cos(a)*ring,y:cy+Math.sin(a)*ring})}); return pos; }
  const groups=new Map(); data.nodes.forEach(n=>{if(!groups.has(n.entity_type))groups.set(n.entity_type,[]);groups.get(n.entity_type).push(n)}); const flat=[]; [...groups].sort(([a],[b])=>a.localeCompare(b)).forEach(([,items])=>items.forEach(x=>flat.push(x)));
  flat.forEach((n,i)=>{const a=(Math.PI*2*i/Math.max(1,flat.length))-Math.PI/2;const ring=i%3===0?205:i%3===1?270:325;pos.set(n.graph_id,{x:cx+Math.cos(a)*ring,y:cy+Math.sin(a)*ring})}); return pos;
}
function renderLiveGraph(){
  const data=state.liveGraph,svg=$('ontology-graph'); if(!data)return;
  $('graph-module-label').textContent='Entity type'; const current=$('graph-module').value;
  const types=(data.entity_types?.length?data.entity_types:[...new Set(data.nodes.map(n=>n.entity_type))]).sort(); $('graph-module').innerHTML='<option value="">All entity types</option>'+types.map(t=>`<option value="${esc(t)}">${esc(t)}</option>`).join(''); if(types.includes(current))$('graph-module').value=current;
  $('graph-search').placeholder='Search graph id / node properties…';
  $('graph-live-summary').innerHTML=`<span class="chip live-chip">LIVE TENANT DATA</span><strong>${esc(data.tenant_id)}</strong><span class="muted">${data.node_count_total ?? '?'} total nodes · ${data.relationship_count_total ?? '?'} total relationships · showing ${data.displayed_node_count ?? data.nodes.length} nodes</span>`;
  const pos=liveLayout(data), nodeIds=new Set(data.nodes.map(n=>n.graph_id));
  const edges=(data.edges||[]).filter(e=>nodeIds.has(e.source_graph_id)&&nodeIds.has(e.target_graph_id)).map((e,i)=>{const a=pos.get(e.source_graph_id),b=pos.get(e.target_graph_id);if(!a||!b)return'';const f=edgeFamily(e),dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1,nx=-dy/len,ny=dx/len,bend=((i%5)-2)*7,mx=(a.x+b.x)/2+nx*bend,my=(a.y+b.y)/2+ny*bend,path=`M ${a.x} ${a.y} Q ${mx} ${my} ${b.x} ${b.y}`;return `<g class="edge-group live-edge" data-source="${esc(e.source_graph_id)}" data-target="${esc(e.target_graph_id)}" data-relation="${esc(e.relation_type)}" data-family="${f}"><path id="live-edge-${i}" class="edge edge-${f}" d="${path}" marker-end="url(#arrow-${f})"><title>${esc(e.source_entity_type)} — ${esc(e.relation_type)} → ${esc(e.target_entity_type)}</title></path><text class="edge-label edge-label-${f}"><textPath href="#live-edge-${i}" startOffset="50%" text-anchor="middle">${esc(e.relation_type)}</textPath></text></g>`}).join('');
  const nodes=data.nodes.map(n=>{const p=pos.get(n.graph_id);if(!p)return'';const center=n.center?' center-node':'';return `<g class="graph-node live-node${center}" data-id="${esc(n.graph_id)}" data-type="${esc(n.entity_type)}" transform="translate(${p.x},${p.y})"><circle r="${n.center?29:20}"></circle><text class="node-type-label" y="${n.center?-38:-29}">${esc(n.entity_type)}</text><text y="${n.center?45:36}">${esc(String(n.label||n.graph_id).slice(0,28))}</text><title>${esc(n.entity_type)} · ${esc(n.label)} · ${esc(n.graph_id)}</title></g>`}).join('');
  svg.innerHTML=`${graphDefs()}<g id="graph-viewport"><g class="all-edges">${edges}</g><g>${nodes}</g>${graphLegend()}</g>`;
  document.querySelectorAll('.live-node').forEach(el=>el.addEventListener('click',()=>loadLiveNode(el.dataset.id)));
  document.querySelectorAll('.live-edge').forEach(el=>el.addEventListener('click',()=>selectLiveEdge(el)));
  resetZoom(); enablePanZoom();
  if(data.node_detail) renderLiveNodeDetail(data);
  else $('graph-detail').innerHTML=`<div class="detail-kicker">LIVE GRAPH</div><h2>Actual tenant nodes</h2><p>${esc(data.note||'Click a node to load its 1-hop neighbourhood, properties and provenance.')}</p><div class="live-help"><strong>How to inspect</strong><span>1. Click any node</span><span>2. Its inbound/outbound relationships load</span><span>3. Click a neighbour to continue walking the graph</span><span>4. Mouse wheel or +/- buttons zoom; drag empty space to pan</span></div>`;
}
function selectLiveEdge(el){ const source=el.dataset.source,target=el.dataset.target,relation=el.dataset.relation,f=el.dataset.family; document.querySelectorAll('.edge-group').forEach(x=>x.classList.toggle('selected-edge',x===el)); document.querySelectorAll('.graph-node').forEach(x=>x.classList.toggle('connected',x.dataset.id===source||x.dataset.id===target)); $('graph-detail').innerHTML=`<div class="detail-kicker">LIVE RELATIONSHIP</div><h2>${esc(relation)}</h2><div class="relation-card"><button class="node-link" data-node-id="${esc(source)}">${esc(source)}</button><span>→ ${esc(relation)} →</span><button class="node-link" data-node-id="${esc(target)}">${esc(target)}</button></div>`; bindNodeLinks(); }
async function loadLiveNode(graphId){
  const tenant=$('tenant-id').value.trim(); if(!tenant)return notify('Enter a tenant ID first.',true); $('graph-detail').innerHTML='<div class="loading-block">Loading node relationships…</div>';
  try{ const data=await api(`/ontology-studio/api/live-graph/nodes/${encodeURIComponent(graphId)}?tenant_id=${encodeURIComponent(tenant)}&limit=120`); state.liveGraph=data; state.selectedLiveNode=graphId; renderLiveGraph(); }
  catch(e){notify(e.message,true);}
}
function renderLiveNodeDetail(data){
  const n=data.node_detail, edges=data.edges||[], nodeMap=new Map((data.nodes||[]).map(x=>[x.graph_id,x]));
  const relHtml=edges.length?edges.map(e=>{const out=e.source_graph_id===n.graph_id,otherId=out?e.target_graph_id:e.source_graph_id,other=nodeMap.get(otherId),f=edgeFamily(e);return `<div class="relation-item live-relation-item"><span class="relationship-dot dot-${f}"></span><div><strong>${esc(e.relation_type)}</strong><small>${out?'outbound →':'← inbound'} ${esc(other?.entity_type||'Node')}</small><button class="node-link compact" data-node-id="${esc(otherId)}">${esc(other?.label||otherId)}</button></div></div>`}).join(''):'<p class="muted">No relationships found for this node.</p>';
  const props=Object.entries(n.properties||{}); const prov=n.provenance||[];
  $('graph-detail').innerHTML=`<div class="detail-kicker">LIVE NODE · ${esc(data.tenant_id)}</div><h2>${esc(n.label)}</h2><div class="entity-meta"><span class="chip live-chip">${esc(n.entity_type)}</span><span class="chip">${data.outgoing_count} outgoing</span><span class="chip">${data.incoming_count} incoming</span><span class="chip">${data.neighbor_count} neighbours</span></div><div class="graph-id-box"><small>graph_id</small><code>${esc(n.graph_id)}</code></div><h3>Properties</h3><div class="property-list live-properties">${props.length?props.map(([k,v])=>`<div class="property"><span>${esc(k)}</span><span>${esc(typeof v==='object'?JSON.stringify(v):v)}</span></div>`).join(''):'<p class="muted">No properties.</p>'}</div><h3>Relationships / next nodes</h3><div class="relationship-list live-rel-list">${relHtml}</div><h3>Provenance</h3><div class="provenance-list">${prov.length?prov.map(p=>`<div class="provenance-item"><strong>${esc(p.source_system||'source')}</strong><span>${esc(p.source_object||'')}</span><code>${esc(p.source_record_key||'')}</code></div>`).join(''):'<p class="muted">No provenance metadata.</p>'}</div>`;
  bindNodeLinks();
}
function bindNodeLinks(){ document.querySelectorAll('.node-link[data-node-id]').forEach(btn=>btn.addEventListener('click',()=>loadLiveNode(btn.dataset.nodeId))); }
async function loadLiveGraph(){
  const tenant=$('tenant-id').value.trim(); if(!tenant)return notify('Enter a tenant ID first.',true);
  const q=$('graph-search').value.trim(), type=$('graph-module').value; $('graph-live-summary').innerHTML='<span class="muted">Loading live tenant graph…</span>';
  try{ const params=new URLSearchParams({tenant_id:tenant,limit:'160'}); if(q)params.set('search',q); if(type)params.set('entity_type',type); const data=await api(`/ontology-studio/api/live-graph?${params.toString()}`); state.liveGraph=data; state.selectedLiveNode=null; renderLiveGraph(); }
  catch(e){notify(e.message,true);$('graph-live-summary').innerHTML=`<span class="danger-text">${esc(e.message)}</span>`;}
}
function setGraphMode(mode){ state.graphMode=mode; localStorage.setItem('ontologyGraphMode',mode); document.querySelectorAll('.graph-mode-btn').forEach(b=>b.classList.toggle('active',b.dataset.mode===mode)); $('graph-load-live').classList.toggle('hidden',mode!=='live'); $('graph-module').value=''; $('graph-search').value=''; if(mode==='live')loadLiveGraph();else renderSchemaGraph(); }

async function renderReviews(){ const items=await api('/ontology-studio/api/mapping-reviews'); $('mapping-reviews').innerHTML=items.length?items.slice().reverse().map(r=>`<div class="review-card"><div class="row"><h3>${esc(r.source_file)} · ${esc(r.source_column)}</h3><span class="badge ${r.status==='approved'?'ok':r.status==='rejected'?'danger':'warn'}">${esc(r.status)}</span></div><p>${esc(r.reason)}</p><small class="muted">Ontology path: ${esc(r.proposed_ontology_path||'—')}<br>Disposition: ${esc(r.proposed_disposition||'—')}</small>${r.status==='pending'?`<div class="review-actions"><button class="btn small primary" onclick="decideMapping('${r.id}','approved')">Approve</button><button class="btn small secondary" onclick="decideMapping('${r.id}','rejected')">Reject</button></div>`:''}</div>`).join(''):'<p class="muted">No mapping reviews yet.</p>'; }
async function renderChanges(){ const items=await api('/ontology-studio/api/change-requests'); $('change-requests').innerHTML=items.length?items.slice().reverse().map(r=>`<div class="review-card"><div class="row"><h3>${esc(r.title)}</h3><span class="badge ${r.status==='approved'?'ok':r.status==='rejected'?'danger':'warn'}">${esc(r.status)}</span></div><small class="muted">${esc(r.kind)} · ${esc(r.target)}</small><p>${esc(r.description)}</p>${r.status==='pending'?`<div class="review-actions"><button class="btn small primary" onclick="decideChange('${r.id}','approved')">Approve</button><button class="btn small secondary" onclick="decideChange('${r.id}','rejected')">Reject</button></div>`:''}</div>`).join(''):'<p class="muted">No change requests yet.</p>'; }
window.decideMapping=async(id,decision)=>{try{await api(`/ontology-studio/api/mapping-reviews/${id}`,{method:'PATCH',body:JSON.stringify({decision})});await renderReviews();await loadDashboard();notify(`Mapping review ${decision}.`)}catch(e){notify(e.message,true)}};
window.decideChange=async(id,decision)=>{try{await api(`/ontology-studio/api/change-requests/${id}`,{method:'PATCH',body:JSON.stringify({decision})});await renderChanges();await loadDashboard();notify(`Change request ${decision}.`)}catch(e){notify(e.message,true)}};

async function fillReviewOptions(){
  const options=state.reviewOptions || await api('/ontology-studio/api/mapping-review-options'); state.reviewOptions=options;
  $('review-path').innerHTML='<option value="">— Keep / choose no ontology property —</option>'+options.ontology_paths.map(p=>`<option value="${esc(p.value)}">${esc(p.value)} · ${esc(p.data_type)}${p.semantic_status!=='confirmed'?` · ${esc(p.semantic_status)}`:''}</option>`).join('');
  $('review-disposition').innerHTML='<option value="">— Select disposition —</option>'+options.dispositions.map(d=>`<option value="${esc(d)}">${esc(d)}</option>`).join('');
}
async function fillReviewSources(){ $('review-source-file').innerHTML=state.datasets.map(d=>`<option value="${esc(d.source_file)}">${esc(d.source_file)}</option>`).join(''); await updateReviewColumns(); }
async function updateReviewColumns(){ const file=$('review-source-file').value;if(!file)return;const d=await api(`/ontology-studio/api/datasets/${encodeURIComponent(file)}`);$('review-source-column').innerHTML=d.columns.map(c=>`<option value="${esc(c.source_column)}" data-path="${esc(c.ontology_path||'')}" data-disposition="${esc(c.disposition||'')}">${esc(c.source_column)} · ${esc(c.disposition)}</option>`).join(''); syncReviewDefaults(); }
function syncReviewDefaults(){ const opt=$('review-source-column').selectedOptions[0];if(!opt)return; const p=opt.dataset.path||'',d=opt.dataset.disposition||''; if([...$('review-path').options].some(x=>x.value===p))$('review-path').value=p; if([...$('review-disposition').options].some(x=>x.value===d))$('review-disposition').value=d; }

$('mapping-review-form').addEventListener('submit',async(e)=>{e.preventDefault();try{await api('/ontology-studio/api/mapping-reviews',{method:'POST',body:JSON.stringify({source_file:$('review-source-file').value,source_column:$('review-source-column').value,proposed_ontology_path:$('review-path').value||null,proposed_disposition:$('review-disposition').value||null,reason:$('review-reason').value})});e.target.reset();await fillReviewOptions();await fillReviewSources();await renderReviews();await loadDashboard();notify('Mapping review created.')}catch(err){notify(err.message,true)}});
$('change-form').addEventListener('submit',async(e)=>{e.preventDefault();try{await api('/ontology-studio/api/change-requests',{method:'POST',body:JSON.stringify({kind:$('change-kind').value,target:$('change-target').value,title:$('change-title').value,description:$('change-description').value,proposed_change:{}})});e.target.reset();await renderChanges();await loadDashboard();notify('Ontology change request created.')}catch(err){notify(err.message,true)}});

function tenantLabel(item){
  const name=item?.name ? ` · ${item.name}` : '';
  const status=item?.status ? ` · ${item.status}` : '';
  return `${item.tenant_id}${name}${status}`;
}
function syncTenantLinks(){
  const tenant=$('tenant-id').value.trim();
  const link=$('onboarding-link');
  if(link) link.href=`/organization-onboarding?tenant_id=${encodeURIComponent(tenant)}`;
}
function fillTenantSelector(payload, requestedTenant=''){
  const tenants=Array.isArray(payload?.tenants)?payload.tenants:[];
  state.tenants=tenants;
  const select=$('tenant-id');
  const remembered=localStorage.getItem('ontologyStudioTenant')||'';
  const preferred=requestedTenant||remembered||payload?.selected_tenant_id||'ORGANIZATION-001';
  if(tenants.length){
    select.innerHTML=tenants.map(item=>`<option value="${esc(item.tenant_id)}">${esc(tenantLabel(item))}</option>`).join('');
    select.value=tenants.some(item=>item.tenant_id===preferred)?preferred:tenants[0].tenant_id;
  }else{
    select.innerHTML=`<option value="${esc(preferred)}">${esc(preferred)}</option>`;
    select.value=preferred;
  }
  localStorage.setItem('ontologyStudioTenant',select.value);
  syncTenantLinks();
}
async function switchTenant(){
  const tenant=$('tenant-id').value.trim();
  if(!tenant)return;
  localStorage.setItem('ontologyStudioTenant',tenant);
  const url=new URL(location.href); url.searchParams.set('tenant_id',tenant); history.replaceState({},'',url);
  syncTenantLinks();
  await loadDashboard();
  if(state.graphMode==='live') await loadLiveGraph(); else renderSchemaGraph();
  notify(`Switched to ${tenant}.`);
}
async function loadDashboard(){ state.dashboard=await api(`/ontology-studio/api/dashboard?tenant_id=${encodeURIComponent($('tenant-id').value)}`); renderDashboard(); }
async function bootstrap(){
  try{
    const params=new URLSearchParams(location.search); const requestedTenant=params.get('tenant_id')||params.get('tenant')||'';
    const tenantPayload=await api('/tenant-management/api/tenants');
    fillTenantSelector(tenantPayload,requestedTenant);
    const [dashboard,graph,entities,datasets,reviewOptions]=await Promise.all([api(`/ontology-studio/api/dashboard?tenant_id=${encodeURIComponent($('tenant-id').value)}`),api('/ontology-studio/api/schema-graph'),api('/ontology-studio/api/entities'),api('/ontology-studio/api/datasets'),api('/ontology-studio/api/mapping-review-options')]);
    Object.assign(state,{dashboard,graph,entities,datasets,reviewOptions}); renderDashboard(); renderEntities(); renderDatasets(); await fillReviewOptions(); await fillReviewSources(); await Promise.all([renderReviews(),renderChanges()]); setGraphMode(state.graphMode==='schema'?'schema':'live');
  }catch(e){notify(e.message,true)}
}
$('refresh-btn').addEventListener('click',async()=>{await loadDashboard();if(state.graphMode==='live')await loadLiveGraph();else renderSchemaGraph()});
$('tenant-id').addEventListener('change',switchTenant);
$('entity-search').addEventListener('input',e=>renderEntities(e.target.value)); $('dataset-search').addEventListener('input',e=>renderDatasets(e.target.value));
$('graph-search').addEventListener('input',()=>{if(state.graphMode==='schema')filterSchemaGraph()}); $('graph-search').addEventListener('keydown',e=>{if(e.key==='Enter'&&state.graphMode==='live')loadLiveGraph()});
$('graph-module').addEventListener('change',()=>{if(state.graphMode==='schema')filterSchemaGraph();else loadLiveGraph()});
$('graph-reset').addEventListener('click',()=>{$('graph-search').value='';$('graph-module').value='';state.selectedLiveNode=null;if(state.graphMode==='live')loadLiveGraph();else{filterSchemaGraph();resetZoom()}});
$('graph-load-live').addEventListener('click',loadLiveGraph); $('zoom-in').addEventListener('click',()=>zoomBy(1.2)); $('zoom-out').addEventListener('click',()=>zoomBy(.83)); $('zoom-fit').addEventListener('click',resetZoom);
document.querySelectorAll('.graph-mode-btn').forEach(btn=>btn.addEventListener('click',()=>setGraphMode(btn.dataset.mode))); $('review-source-file').addEventListener('change',updateReviewColumns); $('review-source-column').addEventListener('change',syncReviewDefaults);
bootstrap();
