const state={bootstrap:null,items:[],currentId:null,detail:null,tab:'overview',trajectory:null};
const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=n=>new Intl.NumberFormat('zh-CN').format(n||0);
async function api(url,opts={}){const r=await fetch(url,opts);const j=await r.json();if(!r.ok)throw new Error(j.error||r.statusText);return j}
function toast(msg,error=false){const el=$('#toast');el.textContent=msg;el.className='toast show'+(error?' error':'');setTimeout(()=>el.className='toast',2600)}
function badge(text,type=''){return `<span class="badge ${type}">${esc(text)}</span>`}
function renderDashboard(){const b=state.bootstrap,s=b.summary.replay||{},a=b.summary.alignment||{},pct=b.total?Math.round(b.annotated_samples/b.total*100):0;$('#dashboard').innerHTML=[
 ['标注进度',`${b.annotated_samples}/${b.total}`,`${pct}% · ${b.annotation_records} 份记录`],
 ['Checkpoint',fmt(s.result_count),`${fmt(s.instance_count)} 条轨迹`],
 ['可比较转移',fmt(s.transition_count),'官方 F2P/P2P 对照'],
 ['Outcome-neutral',fmt((s.transition_labels||{})['Outcome-neutral Revision']),s.transition_count?`${((s.transition_labels['Outcome-neutral Revision']||0)/s.transition_count*100).toFixed(1)}%`:'' ],
 ['Productive',fmt((s.transition_labels||{})['Productive Revision']),'unresolved → resolved'],
 ['对齐 Episode',fmt(a.episode_count),`${fmt(a.comparable_episode_count)} 个可比较`]
 ].map(x=>`<div class="metric"><div class="label">${x[0]}</div><div class="value">${x[1]}</div><div class="sub">${x[2]}</div>${x[0]=='标注进度'?`<div class="progress"><span style="width:${pct}%"></span></div>`:''}</div>`).join('')}
async function loadItems(){const p=new URLSearchParams({q:$('#search').value,model:$('#modelFilter').value,outcome:$('#outcomeFilter').value,status:$('#statusFilter').value,replay:$('#replayFilter').value});const d=await api('/api/items?'+p);state.items=d.items;$('#listMeta').textContent=`显示 ${d.count} / ${state.bootstrap.total} 条 · 按优先级排序`;renderList()}
function renderList(){const el=$('#itemList');el.innerHTML=state.items.map(r=>`<div class="item-card ${r.annotation_id===state.currentId?'active':''}" data-id="${r.annotation_id}"><span class="item-status ${r.is_annotated?'done':''}"></span><div class="item-title">${esc(r.instance_id)}</div><div class="item-sub">${badge(r.model_label,'info')} ${badge(r.task_outcome,r.task_outcome==='resolved'?'success':'danger')} ${r.has_replay?badge('replay','warn'):''} ${r.false_accept?badge('false accept','danger'):''}${r.false_reject?badge('false reject','warn'):''}</div><div class="item-sub"><span>${esc(r.sampling_stratum)}</span><span>优先级 ${r.priority_score}</span>${r.annotators.length?`<span>✎ ${esc(r.annotators.join(', '))}</span>`:''}</div></div>`).join('')||'<div class="loading">没有匹配的样本</div>';el.querySelectorAll('.item-card').forEach(x=>x.onclick=()=>selectItem(x.dataset.id))}
async function selectItem(id){state.currentId=id;state.trajectory=null;renderList();$('#emptyState').classList.add('hidden');$('#detail').classList.remove('hidden');$('#tabContent').innerHTML='<div class="loading">正在加载…</div>';state.detail=await api('/api/items/'+id);renderHeader();renderTab()}
function renderHeader(){const s=state.detail.sample,r=state.detail.replay_instance;$('#detailHeader').innerHTML=`<div><div class="eyebrow" style="color:#8c6a2f">${esc(s.annotation_id)} · ${esc(s.repo)}</div><h2>${esc(s.instance_id)}</h2><div class="meta">${esc(s.difficulty)} · ${esc(s.sampling_stratum)} · 原始轨迹 ${state.detail.run_dir?'可用':'不可用'}</div></div><div>${badge(s.model_label,'info')} ${badge(s.task_outcome,s.official_resolved?'success':'danger')} ${badge(s.integrity_status,s.integrity_status==='valid'?'success':'warn')} ${r?badge(r.replay_group,'warn'):''}</div>`}
function kv(obj,keys){return `<dl class="kv">${keys.map(([k,l])=>`<dt>${esc(l)}</dt><dd>${obj?.[k]===undefined||obj?.[k]===null?'—':esc(typeof obj[k]==='object'?JSON.stringify(obj[k]):obj[k])}</dd>`).join('')}</dl>`}
function renderTab(){document.querySelectorAll('#tabs button').forEach(b=>b.classList.toggle('active',b.dataset.tab===state.tab));const f={overview:renderOverview,trajectory:renderTrajectory,replay:renderReplay,files:renderFiles,annotation:renderAnnotation};f[state.tab]()}
function renderOverview(){const d=state.detail,s=d.sample,c=d.canonical||{},labels=d.automatic_labels||[],revs=d.revisions||[],fbs=d.feedback||[],ts=d.tool_statistics||{};$('#tabContent').innerHTML=`
<div class="grid-2"><div class="panel"><h3>任务与结果</h3>${kv(s,[['task_outcome','官方结果'],['agent_task_status','Agent 自评'],['false_accept','False Accept'],['false_reject','False Reject'],['integrity_status','完整性'],['tool_calls','整条轨迹工具调用'],['unique_states','代码状态'],['revision_episode_count','Feedback Episodes']])}<div class="section-note" style="margin-top:10px">“整条轨迹工具调用”包含所有 Worker 和 Evaluator、所有轮次。</div></div>
<div class="panel"><h3>官方评测与溯源</h3>${kv(c,[['experiment_id','实验'],['manifest_status','Manifest'],['f2p_success','F2P 通过'],['f2p_failure','F2P 失败'],['p2p_success','P2P 通过'],['p2p_failure','P2P 失败'],['termination_reason','终止原因'],['outcome_source','结果来源']])}</div></div>
<div class="panel"><h3>工具调用分轮统计 <span class="badge info">原始轨迹重算</span></h3><div class="section-note">总数 = 每轮 Worker + Evaluator。Revision 摘要会同时显示反馈后下一轮的 Worker 与 Evaluator。</div>${ts.available?`<div class="callout ${ts.matches_sample_total?'success':'warn'}"><b>合计 ${ts.total}</b> = Worker ${ts.worker_total} + Evaluator ${ts.evaluator_total}${ts.other_total?` + Other ${ts.other_total}`:''}；与样本总数 ${ts.expected_total} ${ts.matches_sample_total?'一致':'不一致，请复核'}</div><div class="table-wrap"><table><thead><tr><th>轮次</th><th>阶段</th><th>Worker</th><th>Evaluator</th><th>本轮合计</th><th>工具类型</th></tr></thead><tbody>${ts.rounds.map(x=>`<tr><td>Round ${x.round_id}</td><td>${esc(x.phase)}</td><td>${x.worker}</td><td>${x.evaluator}</td><td><b>${x.total}</b></td><td>${esc(Object.entries(x.tool_names).map(([k,v])=>`${k} ${v}`).join(' · '))}</td></tr>`).join('')}</tbody></table></div>`:'<div class="callout warn">原始轨迹不可用，无法重算分轮工具统计。</div>'}</div>
<div class="panel"><h3>自动分析 <span class="badge warn">仅作辅助</span></h3><div class="section-note">这些标签由规则/日志抽取生成，不是人工 gold label。</div>${labels.length?`<div class="table-wrap"><table><thead><tr><th>Episode</th><th>自动标签</th><th>理由</th><th>需人工</th><th>需 Replay</th></tr></thead><tbody>${labels.map(x=>`<tr><td>${esc(x.episode_id)}</td><td>${badge(x.automatic_label,'info')}</td><td>${esc((x.label_reasons||[]).join(', '))}</td><td>${x.requires_manual_review?'是':'否'}</td><td>${x.requires_checkpoint_replay?'是':'否'}</td></tr>`).join('')}</tbody></table></div>`:'<div class="muted small">无自动标签</div>'}</div>
<div class="grid-2"><div class="panel"><h3>Feedback 摘要</h3>${fbs.length?fbs.map(x=>`<div class="callout ${x.status==='accept'?'success':x.status==='protocol_failure'?'warn':''}"><b>Round ${x.round_id} · ${esc(x.status)}</b><br>${esc(x.assessment||x.next_worker_prompt||'无文本')}</div>`).join(''):'<div class="muted small">无反馈记录</div>'}</div><div class="panel"><h3>Revision 摘要（Worker + Evaluator）</h3><div class="section-note">feedback-N 对应完整的下一轮 Round N+1：先由 Worker 修订，再由 Evaluator 检查。工具合计包含二者。</div>${revs.length?revs.map(x=>{if(!x.worker_revision)return `<div class="callout warn"><b>${esc(x.episode_id)}</b> · ${esc(x.automatic_label)}<br>最后反馈后没有下一轮 Worker/Evaluator，故无后续修订。</div>`;const rr=(ts.rounds||[]).find(r=>r.round_id===x.worker_revision.round_id)||{};return `<div class="callout"><b>${esc(x.episode_id)}</b> · ${esc(x.automatic_label)}<br><b>对应 Round ${x.worker_revision.round_id}</b>：Worker 工具 ${x.worker_revision.tool_count} + Evaluator 工具 ${rr.evaluator??'—'} = 本轮合计 ${rr.total??'—'}<br>Worker 状态变化 ${x.worker_revision.state_change_count??'—'} · Worker 测试调用 ${x.worker_revision.test_call_count}</div>`}).join(''):'<div class="muted small">无 revision episode</div>'}</div></div>`}
function trajCode(value, cls = '') {
  const text = typeof value === 'string' ? value : JSON.stringify(value ?? null, null, 2);
  return `<pre class="traj-code ${cls}">${esc(text)}</pre>`;
}

function trajTag(label, value, kind = '') {
  if (value === undefined || value === null || value === '') return '';
  return `<span class="traj-tag ${kind}"><span>${esc(label)}</span><b>${esc(value)}</b></span>`;
}

function trajRecordHeader(record, title, kind = '') {
  const stepId = record.step_id ?? record.message?.step_id;
  return `<div class="traj-record-head">
    <div class="traj-record-title">
      ${badge(title, kind)}
      ${trajTag('record_type', record.record_type)}
      ${record.display_type && record.display_type !== record.record_type ? trajTag('type', record.display_type, 'accent') : ''}
    </div>
    <div class="traj-record-ids">
      ${trajTag('line', record.line_no)}
      ${trajTag('index', record.index)}
      ${trajTag('step_id', stepId)}
      ${(record.step_ids || []).length ? trajTag('step_ids', record.step_ids.join(',')) : ''}
    </div>
  </div>`;
}

function renderTrajectoryBlock(block) {
  const type = block?.type || 'unknown';
  const common = `${trajTag('type', type, 'accent')} ${trajTag('step_id', block?.step_id)}`;
  if (type === 'thinking') {
    return `<details class="traj-block thinking"><summary>${common}<span>思考过程</span></summary>${trajCode(block.thinking, 'markdown')}</details>`;
  }
  if (type === 'text') {
    return `<div class="traj-block text"><div class="traj-block-label">${common}</div>${trajCode(block.text, 'markdown')}</div>`;
  }
  if (type === 'tool_use') {
    return `<div class="traj-block tool-use">
      <div class="traj-block-label">${common} ${trajTag('tool', block.name, 'tool')} ${trajTag('id', block.id, 'id')}</div>
      <div class="traj-caption">工具输入</div>${trajCode(block.input)}
    </div>`;
  }
  if (type === 'tool_result') {
    const status = block.is_error === true ? '失败' : block.is_error === false ? '成功' : '未知';
    return `<div class="traj-block tool-result ${block.is_error ? 'failed' : 'success'}">
      <div class="traj-block-label">${common} ${trajTag('tool_use_id', block.tool_use_id, 'id')} ${trajTag('status', status, block.is_error ? 'danger' : 'success')}</div>
      <div class="traj-caption">工具结果</div>${trajCode(block.content)}
    </div>`;
  }
  return `<div class="traj-block"><div class="traj-block-label">${common}</div>${trajCode(block)}</div>`;
}

function renderTrajectoryRecord(record) {
  if (record.record_type === 'message') {
    const message = record.message || {};
    const type = message.type || 'message';
    let body = '';
    if (type === 'AgentPrompt' || type === 'WorkerPrompt') {
      body = `<div class="traj-caption">本轮提示词</div>${trajCode(message.prompt, 'markdown')}`;
    } else if (type === 'AssistantMessage' || type === 'UserMessage') {
      body = `<div class="traj-meta-line">
        ${trajTag('model', message.model)}
        ${trajTag('session_id', message.session_id, 'id')}
        ${trajTag('message_id', message.message_id, 'id')}
        ${trajTag('uuid', message.uuid, 'id')}
        ${trajTag('parent_tool_use_id', message.parent_tool_use_id, 'id')}
      </div>${(message.content || []).map(renderTrajectoryBlock).join('')}`;
      if (message.tool_use_result) {
        body += `<details class="traj-raw"><summary>原始 tool_use_result</summary>${trajCode(message.tool_use_result)}</details>`;
      }
    } else if (type === 'ResultMessage') {
      const status = message.is_error ? '失败' : (message.subtype || '完成');
      body = `<div class="traj-meta-line">
        ${trajTag('status', status, message.is_error ? 'danger' : 'success')}
        ${trajTag('num_turns', message.num_turns)}
        ${trajTag('duration_ms', message.duration_ms)}
        ${trajTag('session_id', message.session_id, 'id')}
        ${trajTag('stop_reason', message.stop_reason)}
      </div>`;
      if (message.result) body += `<div class="traj-caption">最终结果</div>${trajCode(message.result, 'markdown')}`;
      if (message.errors?.length) body += `<div class="traj-caption danger-text">错误</div>${trajCode(message.errors)}`;
      body += `<details class="traj-raw"><summary>Usage / Model Usage</summary>${trajCode({usage: message.usage, model_usage: message.model_usage})}</details>`;
    } else {
      body = trajCode(message);
    }
    const kind = type === 'ResultMessage' ? (message.is_error ? 'danger' : 'success') : 'info';
    return `<article class="traj-record message-record type-${esc(type.toLowerCase())}">
      ${trajRecordHeader(record, type, kind)}
      <div class="traj-record-body">${body}</div>
    </article>`;
  }

  if (record.record_type === 'tool_execution') {
    const changes = record.code_changes || {};
    const files = (changes.changed_files || []).map(item => `${item.status || ''} ${item.path || ''}`.trim()).join('\n');
    const response = record.error || record.tool_response;
    return `<article class="traj-record tool-execution-record ${record.outcome === 'failure' ? 'failed' : ''}">
      ${trajRecordHeader(record, 'ToolExecution', record.outcome === 'failure' ? 'danger' : 'success')}
      <div class="traj-record-body">
        <div class="traj-meta-line">
          ${trajTag('tool', record.tool_name, 'tool')}
          ${trajTag('outcome', record.outcome, record.outcome === 'failure' ? 'danger' : 'success')}
          ${trajTag('tool_use_id', record.tool_use_id, 'id')}
          ${trajTag('duration_ms', record.duration_ms == null ? '' : Number(record.duration_ms).toFixed(1))}
        </div>
        <div class="traj-caption">工具输入</div>${trajCode(record.tool_input)}
        ${response ? `<div class="traj-caption ${record.error ? 'danger-text' : ''}">${record.error ? '错误' : '执行结果'}</div>${trajCode(response)}` : ''}
        ${files ? `<details class="traj-raw"><summary>代码变化 · ${changes.changed_files.length} 个文件</summary>${trajCode(files)}${changes.patch_preview ? trajCode(changes.patch_preview) : ''}</details>` : ''}
      </div>
    </article>`;
  }

  if (record.record_type === 'runtime_event') {
    return `<article class="traj-record runtime-record">
      ${trajRecordHeader(record, 'RuntimeEvent', 'warn')}
      <div class="traj-record-body"><div class="traj-meta-line">${trajTag('event', record.event, 'warn')} ${trajTag('tool', record.tool_name, 'tool')}</div>${record.reason ? trajCode(record.reason) : trajCode(record)}</div>
    </article>`;
  }

  if (record.record_type === 'evaluation') {
    const tests = record.tests || {};
    return `<article class="traj-record evaluation-record">
      ${trajRecordHeader(record, 'SWE-bench Evaluation', record.resolved ? 'success' : 'danger')}
      <div class="traj-record-body">
        <div class="traj-meta-line">${trajTag('resolved', record.resolved, record.resolved ? 'success' : 'danger')} ${trajTag('passed', tests.passed)} ${trajTag('failed', tests.failed)} ${trajTag('evaluation_run_id', record.evaluation_run_id, 'id')}</div>
        <div class="grid-2"><div><div class="traj-caption">FAIL_TO_PASS</div>${trajCode(tests.FAIL_TO_PASS || {})}</div><div><div class="traj-caption">PASS_TO_PASS</div>${trajCode(tests.PASS_TO_PASS || {})}</div></div>
      </div>
    </article>`;
  }

  if (record.display_type === 'termination') {
    return `<article class="traj-record termination-record">${trajRecordHeader(record, 'Termination', 'warn')}<div class="traj-record-body">${trajCode({termination: record.termination, error: record.error})}</div></article>`;
  }
  return `<article class="traj-record">${trajRecordHeader(record, record.display_type || record.record_type)}<div class="traj-record-body">${trajCode(record)}</div></article>`;
}

function trajectoryGroup(records, agent, roundId) {
  const title = agent === 'WorkerAgent' ? 'Worker' : 'Evaluator';
  return `<details class="traj-agent-group ${agent === 'WorkerAgent' ? 'worker' : 'evaluator'}" open>
    <summary><span class="agent-name">${title}</span>${trajTag('agent', agent)}${trajTag('round_id', roundId)}<span class="group-count">${records.length} 条记录</span></summary>
    <div class="traj-records">${records.map(renderTrajectoryRecord).join('')}</div>
  </details>`;
}

const trajectoryVerdictHelp = {
  'Healthy Success': '官方成功，过程直接、诊断清楚、验证充分。',
  'Costly Success': '官方成功，但有较多无效调用、反复修改或额外成本。',
  'Recovered Success': '前期出错，后来通过反馈或自我纠错恢复成功。',
  'False Accept': 'Agent/Evaluator 声称成功，但官方结果失败。',
  'False Reject': 'Agent/Evaluator 声称失败或 impossible，但官方结果成功。',
  'Looping Failure': '最终失败，主要表现为重复命令、错误或无进展尝试。',
  'Destructive Drift Candidate': '疑似后期修改破坏了较好状态，但证据尚不足以确认。',
  'Verification Failure': '主要因验证不足、错误或误读而失败。',
  'Protocol Failure': '主要因结构化输出、Schema、API或轮次协议问题失败。',
  'Environment Failure': '主要因依赖、解释器、构建、网络、容器或权限问题失败。',
  'Non-addressable Failure': '主要问题不属于当前Agent/Harness可合理解决范围。',
  'Provenance Invalid': '轨迹归属、实例身份或数据来源不可信。',
  'Other': '不属于现有标签；请在备注中解释。',
  'Uncertain': '现有证据不足，无法可靠选择其他标签。'
};

function toolSummaryCard(tool, index) {
  const outcomeKind = tool.outcome === 'success' ? 'success' : tool.outcome === 'failure' ? 'danger' : 'warn';
  return `<div class="tool-summary-card ${tool.outcome === 'failure' ? 'failed' : ''}">
    <div class="tool-summary-head">
      <span class="tool-number">${index + 1}</span>
      ${badge(tool.tool_name, 'info')}
      ${badge(tool.outcome, outcomeKind)}
      ${tool.code_changed ? badge('代码有变化', 'warn') : badge('无代码变化')}
      <span class="tool-step">step ${esc(tool.step_id ?? '—')}</span>
    </div>
    <div class="tool-summary-row"><b>做什么：</b>${esc(tool.purpose)}</div>
    <div class="tool-summary-row"><b>返回：</b>${esc(tool.result_summary || '无详细返回')}</div>
    <div class="tool-summary-row effect"><b>效果：</b>${esc(tool.effect_summary)}</div>
    ${tool.changed_files?.length ? `<div class="changed-file-list"><b>涉及文件：</b>${tool.changed_files.map(esc).join('、')}</div>` : ''}
    <details class="tool-id-details"><summary>调用ID和耗时</summary>${trajTag('tool_use_id', tool.tool_use_id, 'id')} ${trajTag('duration_ms', tool.duration_ms == null ? '—' : Number(tool.duration_ms).toFixed(1))}</details>
  </div>`;
}

function thoughtSummary(thoughts, title) {
  if (!thoughts?.length) return `<div class="empty-mini">没有记录${title}思考内容。</div>`;
  return thoughts.map((item, index) => `<div class="thought-direct"><div class="thought-label">${title}思考 ${index + 1} · step ${esc(item.step_id ?? '—')}</div><div class="thought-text">${esc(item.text)}</div></div>`).join('');
}

function resultSummary(results) {
  if (!results?.length) return '<div class="empty-mini">没有独立的最终结果消息。</div>';
  return results.map(item => `<div class="agent-result-summary">${badge(item.status, item.status?.includes('error') ? 'danger' : 'info')} ${trajTag('turns', item.num_turns)}<div>${esc(item.result || (item.errors || []).join('；') || '没有结果文本')}</div></div>`).join('');
}

function agentRoundSummary(agent, label, kind) {
  return `<section class="agent-summary ${kind}">
    <div class="agent-summary-head"><h4>${label}</h4><span>工具 ${agent.tool_count} · 成功 ${agent.successful_tools} · 失败 ${agent.failed_tools} · 改代码 ${agent.code_change_tools}</span></div>
    <div class="summary-subtitle">思考过程（直接显示）</div>
    <div class="thinking-list">${thoughtSummary(agent.thoughts, label)}</div>
    ${agent.texts?.length ? `<div class="summary-subtitle">文字输出</div>${agent.texts.map(x => `<div class="thought-direct text-output"><div class="thought-label">step ${esc(x.step_id ?? '—')}</div><div class="thought-text">${esc(x.text)}</div></div>`).join('')}` : ''}
    <div class="summary-subtitle">工具调用逐项概括</div>
    <div class="tool-summary-list">${agent.tools?.length ? agent.tools.map(toolSummaryCard).join('') : '<div class="empty-mini">本轮没有工具调用。</div>'}</div>
    <div class="summary-subtitle">Agent 本轮结束状态</div>${resultSummary(agent.results)}
  </section>`;
}

function roundSummaryCard(round) {
  const utility = round.utility || {};
  const utilityKind = utility.label === 'Productive Revision' ? 'success' : utility.label === 'Partial Regression' ? 'danger' : utility.label === 'Outcome-neutral Revision' ? 'warn' : 'info';
  const feedback = round.feedback;
  return `<section class="round-summary-card">
    <div class="round-summary-head">
      <div><h3>Round ${round.round_id}</h3><span>${esc(round.phase)}</span></div>
      ${badge(utility.label || '无效果证据', utilityKind)}
    </div>
    <div class="utility-summary"><b>本轮是否有效：</b>${esc(utility.summary || '没有可用效果判断')}</div>
    <div class="agent-summary-grid">
      ${agentRoundSummary(round.worker, 'Worker', 'worker')}
      ${agentRoundSummary(round.evaluator, 'Evaluator', 'evaluator')}
    </div>
    ${feedback ? `<div class="feedback-summary"><b>本轮反馈：</b>${badge(feedback.status, feedback.status === 'protocol_failure' ? 'danger' : 'info')}<span>${esc(feedback.assessment || feedback.next_worker_prompt || (feedback.protocol_valid === false ? 'Evaluator没有返回有效结构化反馈。' : '无反馈文本'))}</span></div>` : ''}
  </section>`;
}

async function renderTrajectory() {
  const element = $('#tabContent');
  if (!state.trajectory) {
    element.innerHTML = '<div class="loading">正在生成逐轮轨迹摘要…</div>';
    state.trajectory = await api(`/api/items/${state.currentId}/trajectory`);
  }
  const trajectory = state.trajectory;
  if (!trajectory.available) {
    element.innerHTML = '<div class="callout warn">原始 trajectory.jsonl 不可用。自动分析、官方结果和 Replay 数据仍可查看。</div>';
    return;
  }
  const records = trajectory.records || [];
  const rounds = trajectory.round_summary || [];
  const rawRoundIds = [...new Set(records.filter(item => Number.isInteger(item.round_id)).map(item => item.round_id))].sort((a, b) => a - b);
  const systemRecords = records.filter(item => !Number.isInteger(item.round_id));
  const rawRounds = rawRoundIds.map(round => {
    const worker = records.filter(item => item.round_id === round && item.agent === 'WorkerAgent');
    const evaluator = records.filter(item => item.round_id === round && item.agent === 'EvaluatorAgent');
    return `<section class="traj-round"><div class="traj-round-head"><h3>Round ${round}</h3><span>${round === 1 ? '初始解题与评估' : `第 ${round - 1} 次反馈后的修订与评估`}</span></div><div class="traj-agent-columns">${trajectoryGroup(worker, 'WorkerAgent', round)}${trajectoryGroup(evaluator, 'EvaluatorAgent', round)}</div></section>`;
  }).join('');
  const systemHtml = systemRecords.length ? `<section class="traj-round system"><div class="traj-round-head"><h3>系统与官方评测</h3></div><div class="traj-records">${systemRecords.map(renderTrajectoryRecord).join('')}</div></section>` : '';
  element.innerHTML = `<div class="panel"><h3>问题描述</h3><div class="problem">${esc(trajectory.problem_statement || '未提取')}</div></div>
    <div class="panel trajectory-toolbar"><div><h3>逐轮行为摘要</h3><div class="section-note">先看这里即可快速了解Agent做了什么、工具返回了什么、是否改代码以及官方Replay是否显示有效。</div></div><div>${badge(`${rounds.length} 轮`, 'info')} ${badge(`${state.detail.sample.tool_calls} 次工具`, 'warn')}</div></div>
    <div class="round-summary-list">${rounds.map(roundSummaryCard).join('')}</div>
    <details class="raw-trajectory-details"><summary>展开完整原始结构化轨迹（${records.length}条记录）</summary><div class="trajectory-rounds">${rawRounds}${systemHtml}</div></details>`;
}


function renderReplay(){const d=state.detail,r=d.replay_instance,ts=d.replay_transitions||[],as=d.replay_alignments||[];if(!r){$('#tabContent').innerHTML='<div class="callout warn">这条样本没有进入 36 条 checkpoint replay 分层实验。可参考自动标签和官方最终评测，但不能对中间状态做官方因果判断。</div>';return}const counts={};ts.forEach(x=>counts[x.label]=(counts[x.label]||0)+1);$('#tabContent').innerHTML=`<div class="grid-3">${Object.entries(counts).map(([k,v])=>`<div class="metric"><div class="label">${esc(k)}</div><div class="value">${v}</div></div>`).join('')}</div><div class="panel"><h3>实例 Replay 概览</h3>${kv(r,[['replay_group','分组'],['checkpoint_count','Checkpoint 数'],['complete_replay','完整重放'],['resolved_checkpoint_count','Resolved checkpoint'],['best_checkpoint_id','最佳 checkpoint'],['best_is_final','最佳是否最终'],['source_replay_outcome_mismatch','源结果不一致']])}</div><div class="panel"><h3>相邻状态转移</h3><div class="table-wrap"><table><thead><tr><th>From</th><th>To</th><th>Round</th><th>F2P</th><th>P2P failure</th><th>标签</th></tr></thead><tbody>${ts.map(x=>`<tr><td>${esc(x.from_checkpoint_id)}</td><td>${esc(x.to_checkpoint_id)}</td><td>${x.from_round} → ${x.to_round}</td><td>${x.from_f2p_success} → ${x.to_f2p_success}</td><td>${x.from_p2p_failure} → ${x.to_p2p_failure}</td><td>${badge(x.label,x.label.includes('Productive')?'success':x.label.includes('Regression')?'danger':'info')}</td></tr>`).join('')}</tbody></table></div></div><div class="panel"><h3>Feedback–Replay 对齐</h3>${as.length?`<div class="table-wrap"><table><thead><tr><th>Episode</th><th>自动标签</th><th>对齐状态</th><th>Replay 结论</th><th>状态变化</th></tr></thead><tbody>${as.map(x=>`<tr><td>${esc(x.episode_id)}</td><td>${esc(x.automatic_label)}</td><td>${esc(x.alignment_status)}</td><td>${badge(x.replay_label,'warn')}</td><td>${x.worker_state_change_count}</td></tr>`).join('')}</tbody></table></div>`:'无对齐 episode'}</div>`}
function renderFiles(){const d=state.detail,files=d.files||{};$('#tabContent').innerHTML=`<div class="panel"><h3>原始文件</h3><div class="callout ${d.run_dir?'success':'warn'}">${d.run_dir?`已自动定位：${esc(d.run_dir)}`:`未找到旧路径：${esc(d.run_dir_original)}`}</div><div class="file-buttons">${Object.entries(files).filter(([k,v])=>k!=='trajectory'&&v.exists).map(([k,v])=>`<button class="btn ghost file-btn" data-kind="${k}">${esc(k)} · ${(v.size/1024).toFixed(1)} KB</button>`).join('')}</div><div id="fileView" class="code-view">点击文件查看内容。</div></div>`;document.querySelectorAll('.file-btn').forEach(b=>b.onclick=async()=>{const v=$('#fileView');v.textContent='加载中…';try{const d=await api(`/api/items/${state.currentId}/file/${b.dataset.kind}`);v.textContent=`# ${d.path}${d.truncated?'\n# [仅显示前 2MB]':''}\n\n${d.content}`}catch(e){v.textContent=e.message}})}
function options(field,value){return `<option value="">请选择…</option>${(state.bootstrap.enums[field]||[]).map(x=>`<option value="${esc(x)}" ${x===value?'selected':''}>${esc(x)}</option>`).join('')}`}
function renderAnnotation() {
  const detail = state.detail;
  const annotator = $('#globalAnnotator').value.trim();
  const existing = detail.reviews.find(item => item.annotator === annotator) || detail.reviews[0] || {};
  const suggestion = detail.primary_suggestion || {value: 'Uncertain', confidence: 0, reason: '没有机器建议', source: 'none'};
  const confidence = Math.round(Number(suggestion.confidence || 0) * 100);
  const optionsHtml = options('trajectory_verdict', existing.trajectory_verdict || suggestion.value);
  $('#tabContent').innerHTML = `<div class="simple-review-layout">
    <section class="panel simple-review-main">
      <div class="simple-mode-badge">简化复核模式 · 只需核对1个标签</div>
      <h3>这条轨迹整体属于哪一类？</h3>
      <div class="machine-primary-suggestion">
        <div class="machine-suggestion-title">机器建议 ${badge(`${confidence}%`, confidence >= 85 ? 'success' : confidence >= 65 ? 'info' : 'warn')}</div>
        <div class="machine-suggestion-value">${esc(suggestion.value)}</div>
        <div class="machine-suggestion-help">${esc(trajectoryVerdictHelp[suggestion.value] || '')}</div>
        <div class="machine-suggestion-reason"><b>为什么：</b>${esc(suggestion.reason)}</div>
        <div class="machine-suggestion-source"><b>依据：</b>${esc(suggestion.source)}</div>
      </div>
      <form id="simpleReviewForm">
        <div class="field"><label>标注员 *</label><input name="annotator" value="${esc(annotator || existing.annotator || '')}" required></div>
        <div class="field verdict-field"><label>最终轨迹标签 *</label><select name="trajectory_verdict" required>${optionsHtml}</select><div id="verdictHelp" class="verdict-help"></div></div>
        <div class="field"><label>备注（可选）</label><textarea name="notes" placeholder="如果你不同意机器建议，简单写明原因即可。">${esc(existing.notes || '')}</textarea></div>
        <div id="formError" class="error-text"></div>
        <div class="simple-review-actions"><button type="button" id="acceptSuggestion" class="btn secondary">确认机器建议</button><button class="btn primary" type="submit">保存最终标签</button></div>
      </form>
    </section>
    <aside>
      <div class="panel"><h3>怎么判断</h3><p class="small">1. 先看“轨迹”页的逐轮摘要。</p><p class="small">2. 重点看官方结果、本轮效果和Evaluator反馈。</p><p class="small">3. 同意机器建议就直接确认；不同意就在下拉框改选。</p></div>
      <div class="panel"><h3>标签解释</h3><div class="verdict-reference">${Object.entries(trajectoryVerdictHelp).map(([key, value]) => `<div><b>${esc(key)}</b><span>${esc(value)}</span></div>`).join('')}</div></div>
      <div class="panel"><h3>已有复核</h3>${detail.reviews.length ? detail.reviews.map(item => `<div class="callout"><b>${esc(item.annotator)}</b><br>${esc(item.trajectory_verdict)}${item.accepted_suggestion ? ' · 接受机器建议' : ' · 人工改选'}</div>`).join('') : '<div class="muted small">暂无人工复核</div>'}</div>
    </aside>
  </div>`;
  const select = $('#simpleReviewForm [name="trajectory_verdict"]');
  const help = $('#verdictHelp');
  const updateHelp = () => help.textContent = trajectoryVerdictHelp[select.value] || '';
  select.onchange = updateHelp;
  updateHelp();
  $('#acceptSuggestion').onclick = () => { select.value = suggestion.value; updateHelp(); toast(`已选择机器建议：${suggestion.value}`); };
  $('#simpleReviewForm').onsubmit = saveSimpleReview;
}

async function saveSimpleReview(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = {annotator: form.get('annotator'), trajectory_verdict: form.get('trajectory_verdict'), notes: form.get('notes') || ''};
  try {
    await api(`/api/reviews/${state.currentId}`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    $('#globalAnnotator').value = payload.annotator;
    localStorage.setItem('annotator', payload.annotator);
    toast('最终标签已保存');
    state.bootstrap = await api('/api/bootstrap');
    renderDashboard();
    await loadItems();
    state.detail = await api('/api/items/' + state.currentId);
    renderAnnotation();
  } catch (error) {
    $('#formError').textContent = error.message;
    toast('保存失败', true);
  }
}

async function init(){try{state.bootstrap=await api('/api/bootstrap');$('#globalAnnotator').value=localStorage.getItem('annotator')||'';renderDashboard();await loadItems()}catch(e){toast(e.message,true)}}
document.querySelectorAll('#tabs button').forEach(b=>b.onclick=()=>{state.tab=b.dataset.tab;renderTab()});['#modelFilter','#outcomeFilter','#statusFilter','#replayFilter'].forEach(s=>$(s).onchange=loadItems);let timer;$('#search').oninput=()=>{clearTimeout(timer);timer=setTimeout(loadItems,180)};$('#exportBtn').onclick=()=>location.href='/api/export';$('#globalAnnotator').onchange=e=>{localStorage.setItem('annotator',e.target.value);if(state.tab==='annotation'&&state.detail)renderAnnotation()};init();
