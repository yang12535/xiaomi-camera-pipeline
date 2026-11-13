(function () {
  'use strict';

  var $ = function (selector, root) {
    return (root || document).querySelector(selector);
  };
  var $$ = function (selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  };

  var POLL_MS = 10000;
  var PHASE_LABELS = {
    starting: '启动中',
    merging: '合并中',
    compressing: '压缩中',
    uploading: '上传中',
    backlog: '处理积压',
    waiting: '等待下一轮',
    stopped: '已停止',
    unknown: '状态未知'
  };

  var state = {
    configReady: false,
    machine: { logical_cpus: 0, available_cpus: 0, allowed_cores: [] },
    pinned: [],
    pinnedSet: new Set(),
    overridesFile: null,
    coreListPinned: false,
    selectedCores: new Set(),
    coreTouched: false,
    lastCoresValue: 0,
    baseline: { performance: null, pipeline: null },
    dirty: { performance: false, pipeline: false },
    saving: { performance: false, pipeline: false },
    statusBusy: false,
    statusFailures: 0,
    lastStatusOk: null,
    logsBusy: false,
    lastLogsOk: null,
    recentSig: null,
    runBusy: false,
    pollTimer: null,
    pollBusy: false
  };

  var flashTimers = new WeakMap();

  /* ---------- 通用工具 ---------- */

  function setText(target, text) {
    var el = typeof target === 'string' ? $(target) : target;
    if (!el) return;
    var value = text == null ? '' : String(text);
    if (el.textContent !== value) el.textContent = value;
  }

  function groupOf(el) {
    var form = el && el.closest ? el.closest('[data-group]') : null;
    return form ? form.dataset.group : '';
  }

  function isPinned(key) {
    return state.pinnedSet.has(key);
  }

  function fmtInt(value) {
    var n = Number(value);
    return Number.isFinite(n) ? n.toLocaleString('zh-CN') : '—';
  }

  function toDate(value) {
    if (value instanceof Date) return value;
    if (!value) return null;
    var t = Date.parse(value);
    return Number.isNaN(t) ? null : new Date(t);
  }

  function fmtTime(value) {
    var d = toDate(value);
    if (!d) return value ? String(value) : '—';
    try {
      return new Intl.DateTimeFormat('zh-CN', {
        hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit'
      }).format(d);
    } catch (e) {
      return d.toLocaleTimeString();
    }
  }

  function fmtDateTime(value) {
    var d = toDate(value);
    if (!d) return value ? String(value) : '—';
    try {
      return new Intl.DateTimeFormat('zh-CN', {
        dateStyle: 'short', timeStyle: 'medium'
      }).format(d);
    } catch (e) {
      return d.toLocaleString();
    }
  }

  function fmtRelative(value) {
    var d = toDate(value);
    if (!d) return '';
    var diff = d.getTime() - Date.now();
    var past = diff < 0;
    var minutes = Math.round(Math.abs(diff) / 60000);
    var text;
    if (minutes < 1) text = '不到 1 分钟';
    else if (minutes < 60) text = minutes + ' 分钟';
    else if (minutes < 1440) text = Math.round(minutes / 60) + ' 小时';
    else text = Math.round(minutes / 1440) + ' 天';
    return past ? text + '前' : text + '后';
  }

  function flash(target, text, kind, ms) {
    var el = typeof target === 'string' ? $(target) : target;
    if (!el) return;
    var previous = flashTimers.get(el);
    if (previous) {
      clearTimeout(previous);
      flashTimers.delete(el);
    }
    el.textContent = text || '';
    if (!text) {
      el.removeAttribute('data-kind');
      return;
    }
    el.dataset.kind = kind || 'ok';
    el.setAttribute('role', kind === 'err' ? 'alert' : 'status');
    el.setAttribute('aria-live', kind === 'err' ? 'assertive' : 'polite');
    var timeout = ms == null ? (kind === 'err' ? 9000 : 5000) : ms;
    if (timeout > 0) {
      flashTimers.set(el, setTimeout(function () {
        if (el.textContent === text) {
          el.textContent = '';
          el.removeAttribute('data-kind');
        }
        flashTimers.delete(el);
      }, timeout));
    }
  }

  async function requestJSON(url, options) {
    var opts = options || {};
    var controller = new AbortController();
    var timeout = setTimeout(function () { controller.abort(); }, opts.timeout || 10000);
    var response;
    try {
      response = await fetch(url, {
        method: opts.method || 'GET',
        headers: opts.body
          ? { 'Content-Type': 'application/json', 'Accept': 'application/json' }
          : { 'Accept': 'application/json' },
        body: opts.body ? JSON.stringify(opts.body) : undefined,
        cache: 'no-store',
        credentials: 'same-origin',
        signal: controller.signal
      });
    } catch (e) {
      clearTimeout(timeout);
      throw new Error(e && e.name === 'AbortError' ? '请求超时' : '网络错误');
    }
    clearTimeout(timeout);
    var data = null;
    try {
      data = await response.json();
    } catch (e) {
      data = null;
    }
    if (!response.ok) {
      var err = new Error(data && data.error ? data.error : ('HTTP ' + response.status));
      err.status = response.status;
      err.data = data;
      throw err;
    }
    if (!data) throw new Error('响应不是合法 JSON');
    return data;
  }

  /* ---------- 字段注册表 ---------- */

  function fieldsInGroup(group) {
    return $$('[data-group="' + group + '"] [data-key]');
  }

  function readField(el) {
    var type = el.dataset.type;
    if (type === 'bool') return !!el.checked;
    if (type === 'int') {
      var raw = el.value.trim();
      return raw === '' ? null : Number(raw);
    }
    return el.value.trim();
  }

  function writeField(el, value) {
    if (el.dataset.type === 'bool') {
      el.checked = !!value;
    } else if (value === null || value === undefined) {
      el.value = '';
    } else {
      el.value = String(value);
    }
  }

  function putValue(body, key, value) {
    var parts = key.split('.');
    var section = parts[0];
    var name = parts[1];
    if (!body[section]) body[section] = {};
    body[section][name] = value;
  }

  function collectGroup(group) {
    var body = {};
    var fields = fieldsInGroup(group);
    for (var i = 0; i < fields.length; i++) {
      var el = fields[i];
      var key = el.dataset.key;
      if (key === 'performance.cores' && $('#perf-cores-unlimited').checked) {
        if (!isPinned(key)) putValue(body, key, 0);
        continue;
      }
      if (el.disabled) continue;
      putValue(body, key, readField(el));
    }
    if (group === 'performance' && !isPinned('performance.core_list')) {
      putValue(body, 'performance.core_list', serializeCores(state.selectedCores));
    }
    return body;
  }

  function validateForm(form) {
    var controls = $$('input, select', form);
    for (var i = 0; i < controls.length; i++) {
      var el = controls[i];
      if (el.disabled) continue;
      if (!el.checkValidity()) {
        el.reportValidity();
        return false;
      }
    }
    return true;
  }

  /* ---------- 核心列表 ---------- */

  function parseCoreExpr(expr) {
    var set = new Set();
    String(expr || '').split(',').forEach(function (part) {
      var p = part.trim();
      if (!p) return;
      var m = p.match(/^(\d+)-(\d+)$/);
      if (m) {
        var start = parseInt(m[1], 10);
        var end = parseInt(m[2], 10);
        for (var i = start; i <= end; i++) set.add(i);
      } else if (/^\d+$/.test(p)) {
        set.add(parseInt(p, 10));
      }
    });
    return set;
  }

  function serializeCores(set) {
    var arr = Array.from(set).sort(function (a, b) { return a - b; });
    var parts = [];
    var i = 0;
    while (i < arr.length) {
      var j = i;
      while (j + 1 < arr.length && arr[j + 1] === arr[j] + 1) j++;
      parts.push(i === j ? String(arr[i]) : arr[i] + '-' + arr[j]);
      i = j + 1;
    }
    return parts.join(',');
  }

  function readCoresLimit() {
    if ($('#perf-cores-unlimited').checked) return 0;
    var n = Number($('#perf-cores').value);
    return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
  }

  function coreBudget() {
    var available = state.machine.allowed_cores.length;
    if (state.coreListPinned) return available;
    var limit = readCoresLimit();
    return limit > 0 ? Math.min(limit, available) : available;
  }

  function effectiveCores() {
    if (state.selectedCores.size > 0) return state.selectedCores.size;
    return readCoresLimit();
  }

  function updateCoreInfo() {
    var available = state.machine.allowed_cores.length;
    var parallel = Math.max(1, Number($('#perf-parallel').value) || 1);
    var budget = coreBudget();
    var size = state.selectedCores.size;
    var limit = readCoresLimit();
    var bind = $('#perf-bind').checked;

    setText('#core-count', '已选 ' + size + ' / 上限 ' + budget);
    setText('#core-budget', state.coreListPinned
      ? '（环境变量固定，可用 ' + available + ' 核）'
      : '（本轮上限 ' + budget + ' 核）');
    setText('#core-expr', serializeCores(state.selectedCores) || '（空）');

    var effective = effectiveCores();
    if (effective > 0) {
      var perTask = Math.max(1, Math.floor(effective / parallel));
      setText('#perf-derived', '按当前设置：每任务约 ' + perTask +
        ' 线程（由 ' + (state.selectedCores.size ? 'core_list' : '核心上限') +
        ' ÷ 并行数推导，仅供预览，不会写回配置）。');
    } else {
      setText('#perf-derived', '核心数不限：使用全部可用核心，每任务线程由 compress.threads 决定。');
    }

    if (available) {
      var logical = state.machine.logical_cpus;
      var limited = logical && logical !== available ? '（受容器 cpuset 限制）' : '';
      setText('#perf-machine', '逻辑核心 ' + (logical || '—') + ' · 容器可用 ' + available + ' 核' + limited);
    } else {
      setText('#perf-machine', '未获取到可用核心信息。');
    }

    var note;
    if (state.coreListPinned) {
      note = 'core_list 由环境变量固定：核心网格与核心上限已锁定；并行数与绑核仍可修改。';
      if (size === 0) {
        note += ' 当前 core_list 为空，核心上限仍会影响可用核心范围。';
        if (bind) {
          note += isPinned('performance.bind')
            ? ' 绑核列表为空且 bind 也被环境变量固定，性能配置无法在页面保存；请调整 compose 环境变量。'
            : ' 可关闭“启用 CPU 绑核”后保存，或在 compose 中调整 core_list。';
        }
      }
    } else if (!available) {
      note = '没有可用的核心信息，无法选择核心；仍可保存其他性能项。';
    } else if ($('#perf-bind').checked) {
      note = '绑核已启用：至少选择 1 个核心' +
        (parallel > 1 ? '，建议不少于并行数 ' + parallel : '') +
        '；达到上限后需先取消其他核心。';
    } else {
      note = '未启用绑核：core_list 仍会限制可用核心范围，并参与每任务线程数计算。';
    }

    if (!state.coreListPinned && limit > available && available > 0) {
      note += ' 核心上限 ' + limit + ' 大于容器可用核心数 ' + available +
        (bind ? '；未显式选择核心时，绑核保存会被阻止。' : '，实际最多使用 ' + available + ' 核。');
    }

    var allowedSet = new Set(state.machine.allowed_cores);
    var outOfRange = Array.from(state.selectedCores).filter(function (core) {
      return !allowedSet.has(core);
    });
    if (outOfRange.length) {
      note += ' 配置中有 ' + outOfRange.length + ' 个核心不在当前可用范围（' +
        outOfRange.slice(0, 6).join(', ') + (outOfRange.length > 6 ? '…' : '') +
        '）；如需改变并行数或核心上限，请先点“清空”再重新选择。';
    }
    setText('#core-note', note);
  }

  function renderCoreGrid() {
    var grid = $('#core-grid');
    if (!grid) return;
    var cores = state.machine.allowed_cores;
    var signature = cores.join(',');
    if (grid.dataset.sig !== signature) {
      grid.dataset.sig = signature;
      grid.textContent = '';
      if (!cores.length) {
        var empty = document.createElement('p');
        empty.className = 'empty';
        empty.textContent = '没有可用的核心信息';
        grid.appendChild(empty);
      } else {
        var fragment = document.createDocumentFragment();
        cores.forEach(function (core) {
          var btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'core-btn';
          btn.dataset.core = String(core);
          btn.textContent = String(core);
          btn.setAttribute('aria-pressed', 'false');
          btn.setAttribute('aria-label', '核心 ' + core);
          fragment.appendChild(btn);
        });
        grid.appendChild(fragment);
      }
    }

    var locked = !state.configReady || state.coreListPinned || state.saving.performance;
    $$('.core-btn', grid).forEach(function (btn) {
      var on = state.selectedCores.has(Number(btn.dataset.core));
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      btn.disabled = locked;
    });
    $$('[data-core-action]').forEach(function (btn) {
      btn.disabled = locked || !cores.length;
    });
    updateCoreInfo();
  }

  function setCoreSelection(next) {
    state.selectedCores = next;
    state.coreTouched = true;
    renderCoreGrid();
    updateDirty('performance');
  }

  function toggleCore(core) {
    if (state.selectedCores.has(core)) {
      state.selectedCores.delete(core);
    } else {
      var budget = coreBudget();
      if (budget <= 0) {
        flash('#core-error', '当前没有可选择的可用核心。', 'err', 4500);
        return;
      }
      if (state.selectedCores.size >= budget) {
        flash('#core-error', '最多选择 ' + budget + ' 个核心（当前上限）；请先取消其他核心。', 'err', 4500);
        return;
      }
      state.selectedCores.add(core);
    }
    state.coreTouched = true;
    renderCoreGrid();
    updateDirty('performance');
  }

  /* ---------- 配置回填 / 钉死 ---------- */

  function normalizeMachine(machine) {
    var m = machine || {};
    var allowed = Array.isArray(m.allowed_cores) ? m.allowed_cores.map(Number).filter(Number.isFinite) : [];
    allowed = Array.from(new Set(allowed)).sort(function (a, b) { return a - b; });
    return {
      logical_cpus: Number(m.logical_cpus) || 0,
      available_cpus: Number(m.available_cpus) || allowed.length,
      allowed_cores: allowed
    };
  }

  function applyCoresLimit(value) {
    var n = Number(value);
    if (!Number.isFinite(n) || n < 0) n = 0;
    var unlimited = $('#perf-cores-unlimited');
    var input = $('#perf-cores');
    if (n > 0) {
      state.lastCoresValue = n;
      unlimited.checked = false;
      input.value = String(n);
    } else {
      unlimited.checked = true;
      input.value = '';
    }
  }

  function applyCoreList(expr) {
    state.selectedCores = parseCoreExpr(expr);
    state.coreTouched = false;
    renderCoreGrid();
    updateCoreInfo();
  }

  function applySections(sections) {
    Object.keys(sections || {}).forEach(function (section) {
      var values = sections[section] || {};
      Object.keys(values).forEach(function (key) {
        var el = document.querySelector('[data-key="' + section + '.' + key + '"]');
        if (el) writeField(el, values[key]);
      });
    });
    var perf = sections && sections.performance;
    if (perf) {
      if (Object.prototype.hasOwnProperty.call(perf, 'cores')) applyCoresLimit(perf.cores);
      if (Object.prototype.hasOwnProperty.call(perf, 'core_list')) applyCoreList(perf.core_list);
    }
    updateUploadState();
    updateScheduleHint();
  }

  function applyPinned() {
    state.pinnedSet = new Set(state.pinned);
    state.coreListPinned = state.pinnedSet.has('performance.core_list');

    $$('[data-key]').forEach(function (el) {
      var key = el.dataset.key;
      var pinned = state.pinnedSet.has(key);
      el.dataset.pinned = pinned ? '1' : '0';
      var field = el.closest('.field') || el.closest('fieldset');
      if (!field) return;
      var badge = field.querySelector(':scope > .pin-badge');
      if (pinned && !badge) {
        badge = document.createElement('span');
        badge.className = 'pin-badge';
        badge.textContent = '环境变量固定';
        field.appendChild(badge);
      } else if (!pinned && badge) {
        badge.remove();
      }
    });

    $('#core-pin-note').hidden = !state.coreListPinned;
    refreshDisabledStates();
    renderCoreGrid();
  }

  function refreshDisabledStates() {
    $$('[data-key]').forEach(function (el) {
      var key = el.dataset.key;
      var group = groupOf(el);
      var disabled = !state.configReady || state.pinnedSet.has(key) || state.saving[group];

      if (key === 'performance.cores' && state.coreListPinned) {
        disabled = true;
        el.title = 'core_list 由环境变量固定，核心上限已锁定';
      } else if (key === 'performance.cores'
                 && el.title === 'core_list 由环境变量固定，核心上限已锁定') {
        el.removeAttribute('title');
      }

      if (key === 'performance.cores' && $('#perf-cores-unlimited').checked) disabled = true;
      el.disabled = disabled;
    });

    var unlimited = $('#perf-cores-unlimited');
    unlimited.disabled = !state.configReady || state.pinnedSet.has('performance.cores') || state.coreListPinned;

    var gridLocked = !state.configReady || state.coreListPinned || state.saving.performance;
    $$('.core-btn').forEach(function (btn) { btn.disabled = gridLocked; });
    $$('[data-core-action]').forEach(function (btn) {
      btn.disabled = gridLocked || !state.machine.allowed_cores.length;
    });

    $('#perf-save').disabled = !state.configReady || state.saving.performance;
    $('#pipe-save').disabled = !state.configReady || state.saving.pipeline;
    $('#reset-btn').disabled = !state.configReady || !state.overridesFile || state.saving.performance;
  }

  function updateConfigMeta() {
    if (!state.configReady) {
      setText('#config-source', '配置加载失败，表单暂不可编辑');
      return;
    }
    setText('#config-source', state.overridesFile
      ? '当前配置来源：runtime_overrides.yaml（覆盖 config.yaml；环境变量优先级最高）'
      : '当前配置来源：config.yaml / 环境变量（没有 WebUI 覆盖文件）');
    var reset = $('#reset-btn');
    reset.title = state.overridesFile ? '' : '当前没有 WebUI 覆盖配置，无需恢复';
  }

  /* ---------- 脏状态 ---------- */

  function updateDirty(group) {
    if (!group) return false;
    var badge = group === 'performance' ? $('#perf-dirty') : $('#pipe-dirty');
    if (!state.configReady) {
      badge.hidden = true;
      state.dirty[group] = false;
      return false;
    }
    var dirty = JSON.stringify(collectGroup(group)) !== state.baseline[group];
    badge.hidden = !dirty;
    state.dirty[group] = dirty;
    return dirty;
  }

  function anyDirty() {
    return updateDirty('performance') || updateDirty('pipeline');
  }

  function resetBaseline(group) {
    state.baseline[group] = JSON.stringify(collectGroup(group));
    updateDirty(group);
  }

  function resetAllBaselines() {
    resetBaseline('performance');
    resetBaseline('pipeline');
  }

  /* ---------- 加载配置 ---------- */

  async function loadConfig() {
    state.configReady = false;
    refreshDisabledStates();
    setText('#config-source', '正在加载配置…');
    $('#config-error').hidden = true;
    $('#config-retry').hidden = true;

    try {
      var data = await requestJSON('/api/config', { timeout: 10000 });
      state.machine = normalizeMachine(data.machine);
      state.pinned = Array.isArray(data.pinned) ? data.pinned.slice() : [];
      state.overridesFile = data.overrides_file || null;
      applyPinned();
      applySections(data.sections || {});
      state.configReady = true;
      state.coreTouched = false;
      refreshDisabledStates();
      renderCoreGrid();
      resetAllBaselines();
      updateConfigMeta();
    } catch (e) {
      state.configReady = false;
      refreshDisabledStates();
      setText('#config-source', '配置加载失败，表单暂不可编辑');
      $('#config-error').hidden = false;
      setText('#config-error-text', '配置加载失败：' + e.message + '。请检查服务状态后重试。');
      $('#config-retry').hidden = false;
    }
  }

  /* ---------- 状态渲染 ---------- */

  function setConnection(ok, message) {
    var chip = $('#conn-chip');
    var nextState = ok ? 'online' : 'offline';
    var nextText = ok ? '已连接' : '连接中断';
    if (chip.dataset.state !== nextState) {
      chip.dataset.state = nextState;
      chip.textContent = nextText;
    }

    var banner = $('#offline-banner');
    if (ok) {
      banner.hidden = true;
      return;
    }
    banner.hidden = false;
    var last = state.lastStatusOk
      ? '最后成功 ' + fmtTime(state.lastStatusOk)
      : '尚未成功获取状态';
    setText('#offline-text', '无法获取运行状态（' + message + '）；' + last + '。页面数据可能已陈旧。');
  }

  function renderRuntime(runtime) {
    var chip = $('#phase-chip');
    if (!runtime || runtime.available === false) {
      chip.dataset.phase = 'unknown';
      setText(chip, '状态未知');
      setText('#st-phase', '运行状态暂不可用（运行时未接入）');
      setText('#st-current', '—');
      setText('#st-last', '—');
      setText('#st-next', '—');
      return;
    }

    var phase = PHASE_LABELS[runtime.phase] ? runtime.phase : 'unknown';
    chip.dataset.phase = phase;
    setText(chip, PHASE_LABELS[phase]);
    setText('#st-phase', PHASE_LABELS[phase] + (runtime.running ? ' · 运行中' : ' · 空闲'));
    setText('#st-current', runtime.running && runtime.current_run_started_at
      ? '本轮开始于 ' + fmtDateTime(runtime.current_run_started_at)
      : '当前空闲');

    var last = runtime.last_run;
    setText('#st-last', last
      ? '合并 ' + fmtInt(last.merged) + ' · 压缩 ' + fmtInt(last.compressed) +
        ' · 上传 ' + fmtInt(last.uploaded) +
        (last.finished_at ? '（完成于 ' + fmtDateTime(last.finished_at) + '）' : '')
      : '尚无完成的轮次');

    setText('#st-next', runtime.next_run_at
      ? fmtDateTime(runtime.next_run_at) + '（' + fmtRelative(runtime.next_run_at) + '）'
      : '—');
  }

  function renderRecent(rows) {
    var items = Array.isArray(rows) ? rows : [];
    var signature = items.map(function (row) {
      return [row.path, row.stage, row.timestamp].join('\u0001');
    }).join('\u0002');
    if (signature === state.recentSig) return;
    state.recentSig = signature;

    var tbody = $('#recent-body');
    tbody.textContent = '';
    if (!items.length) {
      var tr = document.createElement('tr');
      var td = document.createElement('td');
      td.colSpan = 3;
      td.className = 'empty';
      td.textContent = '暂无处理记录';
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }

    var fragment = document.createDocumentFragment();
    items.forEach(function (row) {
      var tr = document.createElement('tr');

      var tdPath = document.createElement('td');
      tdPath.className = 'path';
      tdPath.textContent = row.path || '';
      tr.appendChild(tdPath);

      var tdStage = document.createElement('td');
      var stage = document.createElement('span');
      stage.className = 'stage';
      stage.textContent = row.stage || '—';
      tdStage.appendChild(stage);
      tr.appendChild(tdStage);

      var tdTime = document.createElement('td');
      var time = document.createElement('time');
      if (row.timestamp) {
        time.dateTime = row.timestamp;
        time.title = row.timestamp;
        time.textContent = fmtDateTime(row.timestamp);
      } else {
        time.textContent = '—';
      }
      tdTime.appendChild(time);
      tr.appendChild(tdTime);
      fragment.appendChild(tr);
    });
    tbody.appendChild(fragment);
  }

  function renderStatus(data) {
    var counts = data.stage_counts || {};
    setText('#kpi-merge', fmtInt(counts.merge || 0));
    setText('#kpi-compress', fmtInt(counts.compress || 0));
    setText('#kpi-upload', fmtInt(counts.upload || 0));
    setText('#kpi-pending', fmtInt(data.pending_uploads || 0));

    var schedule = data.schedule || {};
    var interval = schedule.interval;
    setText('#schedule-note', interval != null
      ? '空闲轮询间隔 ' + interval + ' 秒' + (schedule.run_once ? ' · 单次运行模式' : ' · 持续运行')
      : '调度信息不可用');

    var perf = data.performance || {};
    var coreText = Number(perf.cores) > 0 ? perf.cores + ' 核' : '不限';
    setText('#status-foot', '并行 ' + (perf.parallel != null ? perf.parallel : '—') +
      ' · 核心上限 ' + coreText +
      ' · core_list ' + (perf.core_list || '自动') +
      ' · 空闲时每 ' + (interval != null ? interval : '—') + ' 秒检查');

    renderRuntime(data.runtime);
    renderRecent(data.recent);

    var time = $('#last-refresh');
    if (data.time) {
      time.dateTime = data.time;
      time.textContent = fmtTime(data.time);
      time.title = data.time;
    }
  }

  async function refreshStatus() {
    if (state.statusBusy) return;
    state.statusBusy = true;
    try {
      var data = await requestJSON('/api/status', { timeout: 8000 });
      renderStatus(data);
      state.statusFailures = 0;
      state.lastStatusOk = new Date();
      setConnection(true);
    } catch (e) {
      state.statusFailures += 1;
      setConnection(false, e.message);
    } finally {
      state.statusBusy = false;
    }
  }

  /* ---------- 日志 ---------- */

  function setLogStatus(text, isError) {
    var el = $('#log-status');
    setText(el, text || '');
    if (isError) {
      el.dataset.kind = 'err';
      el.setAttribute('role', 'alert');
      el.setAttribute('aria-live', 'assertive');
    } else {
      el.removeAttribute('data-kind');
      el.setAttribute('role', 'status');
      el.setAttribute('aria-live', 'polite');
    }
  }

  function showJump() {
    $('#log-jump').hidden = false;
  }

  function hideJump() {
    $('#log-jump').hidden = true;
  }

  function renderLogs(text) {
    var pre = $('#log');
    if (pre.textContent === text) return;
    var atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 48;
    var oldTop = pre.scrollTop;
    pre.textContent = text;
    if ($('#log-follow').checked && atBottom) {
      pre.scrollTop = pre.scrollHeight;
      hideJump();
    } else {
      pre.scrollTop = Math.min(oldTop, Math.max(0, pre.scrollHeight - pre.clientHeight));
      showJump();
    }
  }

  async function refreshLogs(manual) {
    if (state.logsBusy) return;
    if (document.hidden && !manual) return;
    state.logsBusy = true;
    var btn = $('#log-refresh');
    btn.setAttribute('aria-busy', 'true');
    try {
      var lines = $('#log-lines').value;
      var data = await requestJSON('/api/logs?lines=' + encodeURIComponent(lines), { timeout: 8000 });
      var items = Array.isArray(data.lines) ? data.lines : [];
      renderLogs(items.length ? items.join('\n') : '（日志文件不存在或为空）');
      state.lastLogsOk = new Date();
      setLogStatus($('#log-auto').checked ? '' : '自动刷新已暂停（可手动刷新）', false);
    } catch (e) {
      var last = state.lastLogsOk
        ? '显示 ' + fmtTime(state.lastLogsOk) + ' 的内容'
        : '尚无可用内容';
      setLogStatus('日志刷新失败：' + e.message + '（' + last + '）', true);
      if (!state.lastLogsOk) {
        renderLogs('（日志加载失败：' + e.message + '）');
      }
    } finally {
      state.logsBusy = false;
      btn.removeAttribute('aria-busy');
    }
  }

  /* ---------- 轮询 ---------- */

  function schedulePoll(delay) {
    if (state.pollTimer) {
      clearTimeout(state.pollTimer);
      state.pollTimer = null;
    }
    if (document.hidden) return;
    state.pollTimer = setTimeout(pollOnce, delay == null ? POLL_MS : delay);
  }

  function stopPolling() {
    if (state.pollTimer) {
      clearTimeout(state.pollTimer);
      state.pollTimer = null;
    }
  }

  function nextPollDelay() {
    if (!state.statusFailures) return POLL_MS;
    return Math.min(30000, POLL_MS * Math.pow(2, Math.min(state.statusFailures, 2)));
  }

  async function pollOnce() {
    if (document.hidden) {
      stopPolling();
      return;
    }
    if (state.pollBusy) return;
    state.pollBusy = true;
    try {
      await refreshStatus();
      if ($('#log-auto').checked) await refreshLogs(false);
    } finally {
      state.pollBusy = false;
      schedulePoll(nextPollDelay());
    }
  }

  /* ---------- 保存 ---------- */

  function validatePerformance() {
    var available = state.machine.allowed_cores.length;
    var parallel = Number($('#perf-parallel').value);
    var limit = readCoresLimit();
    var bind = $('#perf-bind').checked;
    var size = state.selectedCores.size;

    if (!Number.isFinite(parallel) || parallel < 1 || parallel > 32) {
      flash('#core-error', '并行任务数需在 1-32 之间。', 'err', 0);
      return false;
    }
    if (!state.coreListPinned) {
      var budget = coreBudget();
      if (size > budget) {
        flash('#core-error', '已选 ' + size + ' 个核心，超过上限 ' + budget + ' 个；请点“清空”后重新选择。', 'err', 0);
        return false;
      }
      if (bind && limit > available && size === 0) {
        flash('#core-error', '核心上限 ' + limit + ' 超过当前可用核心数 ' + available +
          '，且尚未选择核心，无法按该上限绑核；请选择核心、调低上限或勾选“不限”。', 'err', 0);
        return false;
      }
      if (bind && size === 0) {
        flash('#core-error', '启用绑核时至少需要选择 1 个核心。', 'err', 0);
        return false;
      }
    } else if (bind && size === 0) {
      flash('#core-error', isPinned('performance.bind')
        ? '启用绑核但 core_list 为空，且 bind 与 core_list 均由环境变量固定，性能配置无法保存；请在 compose 中调整环境变量。'
        : '启用绑核但 core_list 为空且由环境变量固定；请关闭“启用 CPU 绑核”后保存，或在 compose 中调整 core_list。', 'err', 0);
      return false;
    }

    if (bind && size > 0 && size < parallel) {
      flash('#core-error', '已选 ' + size + ' 核少于并行数 ' + parallel + '，部分任务会共享核心（仍可保存）。', 'ok', 5000);
    } else {
      setText('#core-error', '');
    }
    return true;
  }

  async function saveGroup(group) {
    var form = group === 'performance' ? $('#panel-perf') : $('#panel-pipe');
    var btn = group === 'performance' ? $('#perf-save') : $('#pipe-save');
    var msg = group === 'performance' ? $('#perf-msg') : $('#pipe-msg');

    if (!state.configReady || state.saving[group]) return;
    if (!validateForm(form)) {
      flash(msg, '请先修正表单中标红的输入项。', 'err', 7000);
      return;
    }
    if (group === 'performance' && !validatePerformance()) {
      flash(msg, '请先修正性能设置中的问题。', 'err', 0);
      return;
    }

    var body = collectGroup(group);
    if (group === 'performance' && !state.coreTouched && body.performance) {
      delete body.performance.core_list;
    }
    if (!Object.keys(body).length) {
      flash(msg, '所有配置项均由环境变量固定，无可保存项。', 'err', 7000);
      return;
    }

    state.saving[group] = true;
    var label = btn.textContent;
    btn.textContent = '保存中…';
    btn.setAttribute('aria-busy', 'true');
    refreshDisabledStates();
    flash(msg, '', 'ok', 0);

    var succeeded = false;
    try {
      var data = await requestJSON('/api/config', {
        method: 'POST', body: body, timeout: 15000
      });
      if (data.sections) applySections(data.sections);
      if (group === 'performance') state.coreTouched = false;
      succeeded = true;

      if (data.persisted === false) {
        flash(msg, '已生效，但写入覆盖文件失败：' + (data.persist_error || '未知原因') +
          '（重启容器后会丢失）', 'err', 0);
      } else {
        state.overridesFile = state.overridesFile || 'runtime_overrides.yaml';
        updateConfigMeta();
        flash(msg, '已保存并生效', 'ok', 6000);
      }
    } catch (e) {
      var extra = e.status === 409
        ? '（由环境变量固定的键已禁用且不会提交；请移除对应环境变量后重试）'
        : '';
      flash(msg, '保存失败：' + e.message + extra, 'err', 0);
    } finally {
      state.saving[group] = false;
      btn.textContent = label;
      btn.removeAttribute('aria-busy');
      refreshDisabledStates();
    }

    if (succeeded) resetBaseline(group);
  }

  /* ---------- 恢复 / 立即运行 ---------- */

  async function resetConfig() {
    if (!state.configReady || state.saving.performance) return;
    if (!state.overridesFile) {
      flash('#perf-msg', '当前没有 WebUI 覆盖配置，无需恢复。', 'ok', 5000);
      return;
    }
    var dirty = anyDirty();
    var ok = await confirmDialog({
      title: '恢复文件配置',
      body: '将删除 runtime_overrides.yaml，并重新加载 config.yaml 与环境变量中的设置。' +
        (dirty ? ' 当前未保存的修改会丢失。' : ''),
      confirmLabel: '恢复',
      danger: true
    });
    if (!ok) return;

    var btn = $('#reset-btn');
    var label = btn.textContent;
    btn.textContent = '恢复中…';
    btn.disabled = true;
    try {
      await requestJSON('/api/config/reset', { method: 'POST', timeout: 15000 });
      await loadConfig();
      if (state.configReady) {
        flash('#perf-msg', '已恢复文件配置', 'ok', 6000);
      } else {
        flash('#perf-msg', '已删除覆盖文件，但配置重新加载失败，请重试。', 'err', 0);
      }
    } catch (e) {
      flash('#perf-msg', '恢复失败：' + e.message, 'err', 0);
    } finally {
      btn.textContent = label;
      refreshDisabledStates();
    }
  }

  async function runNow() {
    if (state.runBusy) return;
    state.runBusy = true;
    var btn = $('#run-btn');
    btn.disabled = true;
    try {
      var data = await requestJSON('/api/run', { method: 'POST', timeout: 10000 });
      flash('#run-msg', data.ok ? '已触发，正在唤醒处理循环' : '触发失败', data.ok ? 'ok' : 'err', 6000);
      setTimeout(refreshStatus, 1500);
    } catch (e) {
      flash('#run-msg', '触发失败：' + e.message, 'err', 8000);
    } finally {
      setTimeout(function () {
        state.runBusy = false;
        btn.disabled = false;
      }, 3000);
    }
  }

  /* ---------- 确认对话框 ---------- */

  function confirmDialog(options) {
    var opts = options || {};
    var dialog = $('#confirm-dialog');
    if (!dialog || typeof dialog.showModal !== 'function') {
      var text = (opts.title ? opts.title + '\n\n' : '') + (opts.body || '');
      return Promise.resolve(window.confirm(text));
    }

    setText('#confirm-title', opts.title || '请确认');
    setText('#confirm-body', opts.body || '');
    var confirmBtn = $('#confirm-ok');
    confirmBtn.textContent = opts.confirmLabel || '确认';
    confirmBtn.className = opts.danger ? 'btn btn-danger' : 'btn btn-primary';

    var previous = document.activeElement;
    dialog.returnValue = '';
    return new Promise(function (resolve) {
      function onClose() {
        dialog.removeEventListener('close', onClose);
        var accepted = dialog.returnValue === 'confirm';
        if (previous && typeof previous.focus === 'function') previous.focus();
        resolve(accepted);
      }
      dialog.addEventListener('close', onClose);
      dialog.showModal();
    });
  }

  /* ---------- 上传状态 / 调度提示 ---------- */

  function updateUploadState() {
    var enabled = $('#u-enabled').checked;
    var chip = $('#upload-chip');
    chip.textContent = enabled ? '已启用' : '已关闭';
    chip.dataset.state = enabled ? 'on' : 'off';
    $('#upload-note').hidden = enabled;
  }

  function updateScheduleHint() {
    var seconds = Number($('#s-interval').value);
    if (Number.isFinite(seconds) && seconds > 0) {
      var minutes = seconds / 60;
      setText('#schedule-hint', '当前：' + seconds + ' 秒（约 ' +
        (Number.isInteger(minutes) ? minutes : minutes.toFixed(1)) + ' 分钟）');
    } else {
      setText('#schedule-hint', '请输入 60-86400 秒。');
    }
  }

  /* ---------- 标签页 ---------- */

  function setupTabs() {
    var tabs = $$('.tabs [role="tab"]');
    if (!tabs.length) return;

    function activate(tab, focus) {
      tabs.forEach(function (item) {
        var selected = item === tab;
        item.setAttribute('aria-selected', selected ? 'true' : 'false');
        item.tabIndex = selected ? 0 : -1;
        var panel = document.getElementById(item.getAttribute('aria-controls'));
        if (panel) panel.hidden = !selected;
      });
      if (focus) tab.focus();
    }

    tabs.forEach(function (tab, index) {
      tab.addEventListener('click', function () { activate(tab, false); });
      tab.addEventListener('keydown', function (event) {
        var next = null;
        if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
          next = (index + 1) % tabs.length;
        } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
          next = (index - 1 + tabs.length) % tabs.length;
        } else if (event.key === 'Home') {
          next = 0;
        } else if (event.key === 'End') {
          next = tabs.length - 1;
        }
        if (next !== null) {
          event.preventDefault();
          activate(tabs[next], true);
        }
      });
    });
  }

  /* ---------- 事件绑定 ---------- */

  function bindEvents() {
    $('#panel-perf').addEventListener('submit', function (event) {
      event.preventDefault();
      saveGroup('performance');
    });
    $('#panel-pipe').addEventListener('submit', function (event) {
      event.preventDefault();
      saveGroup('pipeline');
    });

    ['performance', 'pipeline'].forEach(function (group) {
      var form = group === 'performance' ? $('#panel-perf') : $('#panel-pipe');
      var onEdit = function (event) {
        var target = event.target;
        if (target.id === 'perf-cores-unlimited') {
          if (!target.checked && !$('#perf-cores').value) {
            var fallback = state.lastCoresValue ||
              Math.min(Math.max(state.machine.allowed_cores.length, 1), 128);
            $('#perf-cores').value = String(fallback);
          }
          refreshDisabledStates();
          updateCoreInfo();
        }
        if (target.id === 'perf-parallel' || target.id === 'perf-cores' || target.id === 'perf-bind') {
          updateCoreInfo();
        }
        if (target.id === 'u-enabled') updateUploadState();
        if (target.id === 's-interval') updateScheduleHint();
        updateDirty(group);
      };
      form.addEventListener('input', onEdit);
      form.addEventListener('change', onEdit);
    });

    $('#core-grid').addEventListener('click', function (event) {
      var btn = event.target.closest('.core-btn');
      if (!btn || btn.disabled) return;
      toggleCore(Number(btn.dataset.core));
    });

    $$('[data-core-action]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (btn.disabled) return;
        var action = btn.dataset.coreAction;
        var cores = state.machine.allowed_cores;
        var budget = coreBudget();
        if (action === 'all') {
          setCoreSelection(new Set(cores.slice(0, Math.max(0, budget))));
        } else if (action === 'none') {
          setCoreSelection(new Set());
        } else if (action === 'invert') {
          var next = new Set();
          cores.forEach(function (core) {
            if (!state.selectedCores.has(core)) next.add(core);
          });
          state.selectedCores.forEach(function (core) {
            if (cores.indexOf(core) === -1) next.add(core);
          });
          if (next.size > budget) {
            flash('#core-error', '反选后为 ' + next.size + ' 个核心，超过上限 ' + budget + '，未执行。', 'err', 5000);
            return;
          }
          setCoreSelection(next);
        }
      });
    });

    $$('input[data-danger]').forEach(function (box) {
      box.addEventListener('change', async function () {
        if (!box.checked) {
          updateDirty(groupOf(box));
          updateUploadState();
          return;
        }
        var ok = await confirmDialog({
          title: box.dataset.dangerTitle || '确认危险操作',
          body: box.dataset.danger || '该操作可能永久删除文件，确定开启？',
          confirmLabel: '确定开启',
          danger: true
        });
        if (!ok) box.checked = false;
        updateDirty(groupOf(box));
        updateUploadState();
      });
    });

    $('#reset-btn').addEventListener('click', resetConfig);
    $('#run-btn').addEventListener('click', runNow);
    $('#retry-btn').addEventListener('click', pollOnce);
    $('#config-retry').addEventListener('click', loadConfig);

    $('#log-refresh').addEventListener('click', function () { refreshLogs(true); });
    $('#log-lines').addEventListener('change', function () { refreshLogs(true); });
    $('#log-auto').addEventListener('change', function () {
      if ($('#log-auto').checked) {
        refreshLogs(true);
      } else {
        setLogStatus('自动刷新已暂停（可手动刷新）', false);
      }
    });
    $('#log-follow').addEventListener('change', function () {
      if ($('#log-follow').checked) {
        var pre = $('#log');
        pre.scrollTop = pre.scrollHeight;
        hideJump();
      }
    });
    $('#log-jump').addEventListener('click', function () {
      var pre = $('#log');
      pre.scrollTop = pre.scrollHeight;
      hideJump();
    });
    $('#log').addEventListener('scroll', function () {
      var pre = $('#log');
      if (pre.scrollHeight - pre.scrollTop - pre.clientHeight < 48) hideJump();
    });

    document.addEventListener('visibilitychange', function () {
      if (document.hidden) {
        stopPolling();
      } else {
        pollOnce();
      }
    });

    window.addEventListener('beforeunload', function (event) {
      if (state.configReady && anyDirty()) {
        event.preventDefault();
        event.returnValue = '';
      }
    });
  }

  /* ---------- 初始化 ---------- */

  function init() {
    setupTabs();
    bindEvents();
    updateUploadState();
    updateScheduleHint();
    renderCoreGrid();
    updateCoreInfo();
    refreshDisabledStates();
    loadConfig();
    refreshStatus();
    refreshLogs(true);
    schedulePoll(POLL_MS);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
