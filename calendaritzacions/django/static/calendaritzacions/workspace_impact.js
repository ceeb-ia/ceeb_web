(function(){
  var rows = Array.from(document.querySelectorAll('.workspace-impact-row'));
  if (!rows.length) return;

  var controls = {
    text: document.getElementById('workspaceImpactFilterText'),
    modality: document.getElementById('workspaceImpactFilterModality'),
    league: document.getElementById('workspaceImpactFilterLeague'),
    category: document.getElementById('workspaceImpactFilterCategory'),
    entity: document.getElementById('workspaceImpactFilterEntity'),
    type: document.getElementById('workspaceImpactFilterType'),
    round: document.getElementById('workspaceImpactFilterRound'),
    level: document.getElementById('workspaceImpactFilterLevel')
  };
  var resetButton = document.getElementById('workspaceImpactFiltersReset');
  var summary = document.getElementById('workspaceImpactFiltersSummary');
  var resultSummary = document.getElementById('workspaceImpactFiltersResultSummary');
  var emptyState = document.getElementById('workspaceImpactFiltersEmptyState');
  var filtersToggle = document.getElementById('workspaceImpactFiltersToggle');
  var filtersCollapse = document.getElementById('workspaceImpactFiltersCollapse');
  var chartNodes = Array.from(document.querySelectorAll('[data-impact-chart]'));
  var kpiRoot = document.getElementById('workspaceImpactKpis');
  var totalTeams = parseInt((kpiRoot && kpiRoot.dataset.totalTeams) || '0', 10) || 0;
  var totalMatches = parseInt((kpiRoot && kpiRoot.dataset.totalMatches) || '0', 10) || 0;
  var totalLinkages = parseInt((kpiRoot && kpiRoot.dataset.totalLinkages) || '0', 10) || 0;

  function normalize(value){
    return String(value || '').trim().toLocaleLowerCase();
  }

  function hasToken(value, token){
    if (!token) return true;
    return normalize(value).split(/\s+/).indexOf(normalize(token)) !== -1;
  }

  function uniqueCount(values){
    var seen = {};
    values.forEach(function(value){
      var key = String(value || '').trim();
      if (key) seen[key] = true;
    });
    return Object.keys(seen).length;
  }

  function activeFilterCount(){
    return Object.keys(controls).map(function(key){
      return controls[key] ? controls[key].value : '';
    }).filter(function(value){ return normalize(value) !== ''; }).length;
  }

  function rowMatches(row){
    var textQ = normalize(controls.text ? controls.text.value : '');
    return (!textQ || normalize(row.dataset.text).indexOf(textQ) !== -1)
      && hasToken(row.dataset.modality, controls.modality ? controls.modality.value : '')
      && hasToken(row.dataset.league, controls.league ? controls.league.value : '')
      && hasToken(row.dataset.category, controls.category ? controls.category.value : '')
      && hasToken(row.dataset.entity, controls.entity ? controls.entity.value : '')
      && hasToken(row.dataset.level, controls.level ? controls.level.value : '')
      && hasToken(row.dataset.rounds, controls.round ? controls.round.value : '')
      && (!controls.type || !controls.type.value || normalize(row.dataset.type) === normalize(controls.type.value));
  }

  function setKpi(key, value){
    var node = document.querySelector('[data-impact-kpi="' + key + '"] .workspace-kpi-value');
    if (node) node.textContent = String(value);
  }

  function setKpiSubtitle(key, value){
    var node = document.querySelector('[data-impact-kpi="' + key + '"] .workspace-kpi-sub');
    if (node) node.textContent = String(value);
  }

  function formatDecimal(value){
    var numeric = Number(value || 0);
    if (!isFinite(numeric)) return '0';
    if (Math.abs(numeric - Math.round(numeric)) < 0.05) return String(Math.round(numeric));
    return numeric.toFixed(1);
  }

  function rowNumber(row, key){
    var parsed = Number(row.dataset[key] || '0');
    return isNaN(parsed) ? 0 : parsed;
  }

  function resourceExcessCount(visibleRows){
    var byIncident = {};
    visibleRows.forEach(function(row){
      if (normalize(row.dataset.type) !== 'resource_excess') return;
      var incidentId = String(row.dataset.incidentId || '').trim();
      if (!incidentId) return;
      byIncident[incidentId] = Math.max(byIncident[incidentId] || 0, rowNumber(row, 'excess'));
    });
    return Object.keys(byIncident).reduce(function(total, key){
      return total + byIncident[key];
    }, 0);
  }

  function updateKpis(visibleRows){
    var roundValues = [];
    visibleRows.forEach(function(row){
      normalize(row.dataset.rounds).split(/\s+/).forEach(function(token){
        if (token) roundValues.push(token);
      });
    });
    var affectedTeams = uniqueCount(visibleRows.map(function(row){ return row.dataset.teamId; }));
    var affectedIncidents = uniqueCount(visibleRows.map(function(row){ return row.dataset.incidentId; }));
    var affectedMatches = resourceExcessCount(visibleRows);
    var affectedLinkages = uniqueCount(visibleRows.filter(function(row){
      return normalize(row.dataset.type) === 'linkage_violation';
    }).map(function(row){ return row.dataset.linkageGroup; }));
    var entityConflictTeams = uniqueCount(visibleRows.filter(function(row){
      return normalize(row.dataset.type) === 'assignment_conflict';
    }).map(function(row){ return row.dataset.teamId; }));
    var severityTotal = visibleRows.reduce(function(total, row){ return total + rowNumber(row, 'severity'); }, 0);
    var excessTotal = visibleRows.reduce(function(total, row){ return total + rowNumber(row, 'excess'); }, 0);
    var impactScoreTotal = visibleRows.reduce(function(total, row){ return total + rowNumber(row, 'impactScore'); }, 0);
    setKpi('affected_incidents', affectedIncidents);
    setKpi('affected_entities', uniqueCount(visibleRows.map(function(row){ return row.dataset.entityLabel; })));
    setKpi('affected_rounds', uniqueCount(roundValues));
    setKpi('severity_total', formatDecimal(severityTotal));
    setKpi('excess_per_team', formatDecimal(affectedTeams ? excessTotal / affectedTeams : 0));
    setKpi('avg_severity_per_team', formatDecimal(affectedTeams ? severityTotal / affectedTeams : 0));
    setKpi('avg_severity_per_incident', formatDecimal(affectedIncidents ? severityTotal / affectedIncidents : 0));
    setKpi('avg_impact_score', formatDecimal(visibleRows.length ? impactScoreTotal / visibleRows.length : 0));
    setKpi('affected_team_ratio', formatDecimal(totalTeams ? (affectedTeams / totalTeams) * 100 : 0) + '%');
    setKpiSubtitle('affected_team_ratio', affectedTeams + ' de ' + totalTeams + ' equips');
    setKpi('entity_conflict_team_ratio', formatDecimal(totalTeams ? (entityConflictTeams / totalTeams) * 100 : 0) + '%');
    setKpiSubtitle('entity_conflict_team_ratio', entityConflictTeams + ' de ' + totalTeams + ' equips');
    setKpi('affected_linkage_ratio', formatDecimal(totalLinkages ? (affectedLinkages / totalLinkages) * 100 : 0) + '%');
    setKpiSubtitle('affected_linkage_ratio', affectedLinkages + ' de ' + totalLinkages + ' linkages');
    setKpi('affected_match_ratio', formatDecimal(totalMatches ? (affectedMatches / totalMatches) * 100 : 0) + '%');
    setKpiSubtitle('affected_match_ratio', affectedMatches + ' de ' + totalMatches + ' partits');
  }

  function addBucket(buckets, key, label, row){
    if (!key) return;
    if (!buckets[key]) {
      buckets[key] = {label: label || key, rows: 0, teams: {}, impactScoreTotal: 0, severityTotal: 0};
    }
    buckets[key].rows += 1;
    buckets[key].impactScoreTotal += rowNumber(row, 'impactScore');
    buckets[key].severityTotal += rowNumber(row, 'severity');
    if (row.dataset.teamId) buckets[key].teams[row.dataset.teamId] = true;
  }

  function chartBuckets(visibleRows, kind){
    var buckets = {};
    visibleRows.forEach(function(row){
      if (kind === 'modality' || kind === 'modality_severity') {
        addBucket(buckets, row.dataset.modalityLabel || 'Sense modalitat', row.dataset.modalityLabel || 'Sense modalitat', row);
      } else if (kind === 'entity' || kind === 'entity_severity') {
        addBucket(buckets, row.dataset.entityLabel || 'Sense entitat', row.dataset.entityLabel || 'Sense entitat', row);
      } else if (kind === 'type' || kind === 'type_severity') {
        addBucket(buckets, row.dataset.type || 'other', row.dataset.typeLabel || row.dataset.type || 'Altres', row);
      } else if (kind === 'round' || kind === 'round_severity') {
        var tokens = normalize(row.dataset.rounds).split(/\s+/);
        var labels = String(row.dataset.roundLabels || '').split(/\s*,\s*/);
        tokens.forEach(function(token, index){
          if (token) addBucket(buckets, token, labels[index] || token, row);
        });
      }
    });
    return Object.keys(buckets).map(function(key){
      var bucket = buckets[key];
      var isSeverity = kind.indexOf('_severity') !== -1;
      var teamCount = Object.keys(bucket.teams).length;
      var value = isSeverity ? (bucket.rows ? bucket.impactScoreTotal / bucket.rows : 0) : (kind === 'type' ? bucket.rows : teamCount);
      return {
        key: key,
        label: bucket.label,
        value: value,
        valueText: isSeverity ? formatDecimal(value) + '/10' : String(value)
      };
    }).filter(function(row){ return row.value > 0; }).sort(function(a, b){
      return b.value - a.value || a.label.localeCompare(b.label);
    }).slice(0, 10);
  }

  function escapeHtml(value){
    return String(value || '').replace(/[&<>"']/g, function(char){
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'}[char];
    });
  }

  function renderChart(node, rowsForChart){
    if (!rowsForChart.length) {
      node.innerHTML = '<div class="text-muted small">No hi ha dades per representar.</div>';
      return;
    }
    var maxValue = rowsForChart.reduce(function(max, row){ return Math.max(max, row.value); }, 1);
    node.innerHTML = rowsForChart.map(function(row){
      var pct = Math.max(4, Math.round((row.value / maxValue) * 100));
      return '' +
        '<div class="audit-bar-row workspace-impact-bar-row">' +
          '<div class="audit-bar-label" title="' + escapeHtml(row.label) + '">' + escapeHtml(row.label) + '</div>' +
          '<div class="audit-bar-track"><div class="audit-bar-fill" style="width: ' + pct + '%;"></div></div>' +
          '<div class="audit-bar-value">' + escapeHtml(row.valueText || row.value) + '</div>' +
        '</div>';
    }).join('');
  }

  function updateCharts(visibleRows){
    chartNodes.forEach(function(node){
      renderChart(node, chartBuckets(visibleRows, node.getAttribute('data-impact-chart')));
    });
  }

  function applyImpactFilters(){
    var visibleRows = [];
    rows.forEach(function(row){
      var ok = rowMatches(row);
      row.style.display = ok ? '' : 'none';
      if (ok) visibleRows.push(row);
    });

    var active = activeFilterCount();
    if (summary) {
      summary.textContent = active ? active + ' filtre' + (active === 1 ? '' : 's') + ' actiu' + (active === 1 ? '' : 's') + '.' : 'Sense filtres actius.';
    }
    if (resultSummary) {
      resultSummary.textContent = 'Mostrant ' + visibleRows.length + ' de ' + rows.length + ' files d\'impacte.';
    }
    if (emptyState) {
      emptyState.classList.toggle('d-none', visibleRows.length !== 0 || rows.length === 0);
    }
    updateKpis(visibleRows);
    updateCharts(visibleRows);
  }

  function resetImpactFilters(){
    Object.keys(controls).forEach(function(key){
      if (controls[key]) controls[key].value = '';
    });
    applyImpactFilters();
  }

  function updateFilterToggleLabel(){
    if (!filtersToggle || !filtersCollapse) return;
    filtersToggle.textContent = filtersCollapse.classList.contains('show') ? 'Amagar filtres' : 'Mostrar filtres';
  }

  Object.keys(controls).forEach(function(key){
    var control = controls[key];
    if (!control) return;
    control.addEventListener('input', applyImpactFilters);
    control.addEventListener('change', applyImpactFilters);
  });
  if (resetButton) resetButton.addEventListener('click', resetImpactFilters);
  if (filtersCollapse) {
    filtersCollapse.addEventListener('shown.bs.collapse', updateFilterToggleLabel);
    filtersCollapse.addEventListener('hidden.bs.collapse', updateFilterToggleLabel);
  }

  applyImpactFilters();
  updateFilterToggleLabel();
})();
