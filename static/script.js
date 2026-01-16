// GLOBAL STATE
let activeSubreddits = [];

document.addEventListener('DOMContentLoaded', async () => {
    await fetchAndRenderSubreddits();
    addNewGroup();
    fetchSavedQueries();
    fetchHistory();
    toggleTimeFilter();
    updateExplainer();

    // Listeners
    const deepScan = document.getElementById('deep_scan');
    if (deepScan) {
        deepScan.addEventListener('change', function() {
            const manualInput = document.getElementById('scan_limit');
            manualInput.disabled = this.checked;
            manualInput.style.opacity = this.checked ? "0.5" : "1";
            updateExplainer();
        });
    }

    const rawInput = document.getElementById('raw-query-input');
    if (rawInput) {
        rawInput.addEventListener('input', syncRawToBuilder);
    }
});

// --- AI QUERY GENERATOR ---
async function generateAIQuery() {
    const inputField = document.getElementById('ai-gen-input');
    const desc = inputField.value;
    // Find the button next to the input
    const btn = inputField.nextElementSibling; 
    
    if(!desc.trim()) return alert("Please describe what you want first.");
    
    // UI Loading State
    const originalText = btn.innerText;
    btn.disabled = true;
    btn.innerText = "Generating...";
    
    try {
        const res = await fetch('/api/generate_query', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                description: desc,
                provider: document.getElementById('provider').value
            })
        });
        
        const data = await res.json();
        
        if (data.query) {
            // Set the raw input
            document.getElementById('raw-query-input').value = data.query;
            // Update the visual builder
            syncRawToBuilder();
        } else {
            alert("AI Error: " + (data.error || "Unknown error"));
        }
    } catch(e) {
        console.error(e);
        alert("Network Error: Check console logs.");
    }
    
    // Reset UI
    btn.disabled = false;
    btn.innerText = originalText;
}

// --- SYNC LOGIC: RAW <-> BUILDER ---

// 1. Raw Text -> Visual Builder
function syncRawToBuilder() {
    const raw = document.getElementById('raw-query-input').value;
    const container = document.getElementById('builder-container');
    container.innerHTML = ''; // Clear visual builder

    // Parse logic: Match (groups)
    const parenRegex = /\(([^)]+)\)/g;
    let match;
    let found = false;

    while ((match = parenRegex.exec(raw)) !== null) {
        found = true;
        // Split by OR, remove quotes if present
        const groupTerms = match[1].split(/ OR |\|/i).map(s => s.trim().replace(/"/g, '')).filter(s => s);
        
        if (groupTerms.length > 0) {
            // Add group without triggering sync back (prevent loop)
            const groupDiv = addNewGroup(false); 
            const termContainer = groupDiv.querySelector('.terms-container');
            termContainer.innerHTML = ''; 
            groupTerms.forEach(term => addTermToContainer(termContainer, term, false));
        }
    }
    
    // If empty/invalid, reset to one empty group
    if (!found && raw.trim() === '') {
        addNewGroup(false);
    }
    
    updatePreviewOnly(); 
}

// 2. Visual Builder -> Raw Text
function syncBuilderToRaw() {
    const groups = document.querySelectorAll('.query-group');
    let blocks = [];
    
    groups.forEach(group => {
        const inputs = group.querySelectorAll('input');
        let terms = [];
        inputs.forEach(inp => {
            const val = inp.value.trim();
            if (val) terms.push(val);
        });
        
        if (terms.length > 0) {
            // Join terms with OR, wrap in quotes for safety
            const quotedTerms = terms.map(t => `"${t}"`);
            blocks.push(`(${quotedTerms.join(" OR ")})`);
        }
    });

    // Join groups with AND
    const rawString = blocks.join(" AND ");
    document.getElementById('raw-query-input').value = rawString;
    updatePreviewOnly();
}

// --- BUILDER FUNCTIONS ---

function addNewGroup(triggerSync = true) {
    const container = document.getElementById('builder-container');
    const groupDiv = document.createElement('div');
    groupDiv.className = 'query-group';
    groupDiv.innerHTML = `
        <div class="group-header">
            <span>MUST MATCH (AND)</span>
            <button class="btn-icon" onclick="removeGroup(this)" title="Remove Group">&times;</button>
        </div>
        <div class="terms-container"></div>
        <button class="btn-add-term" onclick="addTerm(this)">+ Add "OR" Term</button>
    `;
    container.appendChild(groupDiv);
    
    // Add default empty input
    if (triggerSync) {
        addTermToContainer(groupDiv.querySelector('.terms-container'), "", true);
    }
    return groupDiv;
}

function addTerm(btn) {
    addTermToContainer(btn.previousElementSibling, "", true);
}

function addTermToContainer(container, value="", triggerSync=true) {
    const row = document.createElement('div');
    row.className = 'term-row';
    row.innerHTML = `
        <input type="text" placeholder="keyword..." value="${value}" oninput="syncBuilderToRaw()">
        <button class="btn-icon" onclick="removeTerm(this)">&times;</button>
    `;
    container.appendChild(row);
    
    // Only focus if adding manually
    if(!value && triggerSync) row.querySelector('input').focus();
    
    if(triggerSync) syncBuilderToRaw();
}

function removeTerm(btn) {
    btn.parentElement.remove();
    syncBuilderToRaw();
}

function removeGroup(btn) {
    btn.closest('.query-group').remove();
    syncBuilderToRaw();
}

// --- DATA EXTRACTION ---
function getBuilderData() {
    const groups = document.querySelectorAll('.query-group');
    let logicalGroups = [];
    groups.forEach(group => {
        const inputs = group.querySelectorAll('input');
        let terms = [];
        inputs.forEach(inp => { if (inp.value.trim()) terms.push(inp.value.trim()); });
        if (terms.length > 0) logicalGroups.push(terms);
    });
    return logicalGroups;
}

function updatePreviewOnly() {
    const groups = getBuilderData();
    const previewBox = document.getElementById('combo-preview');
    if (groups.length === 0) { previewBox.innerHTML = "Add terms..."; return; }
    
    const combinations = cartesian(groups);
    let html = "";
    const displayLimit = 20;
    
    combinations.slice(0, displayLimit).forEach(combo => {
        const line = Array.isArray(combo) ? combo.join(" + ") : combo;
        html += `<div class="preview-item">🔎 ${line}</div>`;
    });
    
    if (combinations.length > displayLimit) {
        html += `<div class="preview-item" style="color:#888">...and ${combinations.length - displayLimit} more combinations</div>`;
    }
    previewBox.innerHTML = html;
}

function cartesian(args) {
    if (args.length === 0) return [];
    const r = [], max = args.length-1;
    function helper(arr, i) {
        for (let j=0, l=args[i].length; j<l; j++) {
            const a = arr.slice(0); a.push(args[i][j]);
            if (i==max) r.push(a); else helper(a, i+1);
        }
    }
    helper([], 0);
    return r;
}

// --- SUBREDDIT MANAGER ---
async function fetchAndRenderSubreddits() {
    try {
        const res = await fetch('/api/subreddits');
        const data = await res.json();
        activeSubreddits = data;
        renderSubreddits();
    } catch (e) { console.error(e); }
}

async function syncSubreddits() {
    await fetch('/api/subreddits', { 
        method: 'POST', 
        headers: {'Content-Type': 'application/json'}, 
        body: JSON.stringify(activeSubreddits)
    });
}

function renderSubreddits() {
    const container = document.getElementById('sub-list-container');
    container.innerHTML = '';
    activeSubreddits.forEach(sub => {
        const tag = document.createElement('span');
        tag.className = 'sub-tag';
        tag.innerHTML = `r/${sub} <span class="remove-sub" onclick="removeSub('${sub}')">&times;</span>`;
        container.appendChild(tag);
    });
    updateExplainer();
}

async function addSubreddit() {
    const input = document.getElementById('new-sub-input');
    let val = input.value.trim().replace(/^r\//, '');
    if (val && !activeSubreddits.includes(val)) {
        activeSubreddits.push(val);
        renderSubreddits();
        input.value = '';
        await syncSubreddits();
    }
}

function handleSubInputKey(event) { if (event.key === 'Enter') addSubreddit(); }

async function removeSub(sub) {
    activeSubreddits = activeSubreddits.filter(s => s !== sub);
    renderSubreddits();
    await syncSubreddits();
}

// --- SETTINGS UI ---
function updateExplainer() {
    const box = document.getElementById('logic-explainer');
    if (!box) return;
    
    const target = document.getElementById('target_posts').value;
    const isDeep = document.getElementById('deep_scan').checked;
    const limit = document.getElementById('scan_limit').value;
    const subs = activeSubreddits.length;
    const chunk = document.getElementById('ai_chunk').value;

    let text = "";
    if (isDeep) {
        text = `Script will scan the <strong>combined stream of ${subs} subreddits</strong> (Server-Side). It stops as soon as it finds <strong>${target} candidates</strong>.`;
    } else {
        text = `Script will scan the <strong>newest ${limit} posts</strong> across all ${subs} subreddits simultaneously.`;
    }
    text += `<br><br>Then, the LLM will analyze these <strong>${target} candidates</strong> in groups of <strong>${chunk}</strong>.`;
    box.innerHTML = text;
}

function toggleTimeFilter() {
    const sortVal = document.getElementById('sort_by').value;
    const timeSelect = document.getElementById('time_filter');
    const timeContainer = document.getElementById('time_filter_container');
    
    if (sortVal === 'top' || sortVal === 'relevance') {
        timeSelect.disabled = false;
        timeContainer.style.opacity = "1";
    } else {
        timeSelect.disabled = true;
        timeContainer.style.opacity = "0.5";
    }
}

// --- SAVE / LOAD ---
async function saveCurrentQuery() {
    const name = document.getElementById('save-name').value.trim();
    if (!name) return alert("Please enter a name.");
    
    const payload = {
        groups: getBuilderData(),
        criteria: document.getElementById('criteria').value,
        target_posts: document.getElementById('target_posts').value,
        deep_scan: document.getElementById('deep_scan').checked,
        ai_chunk: document.getElementById('ai_chunk').value,
        scan_limit: document.getElementById('scan_limit').value,
        provider: document.getElementById('provider').value,
        subreddits: activeSubreddits,
        sort: document.getElementById('sort_by').value,
        time: document.getElementById('time_filter').value,
        post_type: document.getElementById('post_type').value
    };

    await fetch('/api/queries', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ name, payload })
    });
    
    document.getElementById('save-name').value = "";
    fetchSavedQueries();
    alert("Saved!");
}

async function fetchSavedQueries() {
    const res = await fetch('/api/queries');
    const data = await res.json();
    const select = document.getElementById('saved-list');
    select.innerHTML = '<option value="">-- Select a Preset --</option>';
    for (const [name, payload] of Object.entries(data)) {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        opt.dataset.payload = JSON.stringify(payload);
        select.appendChild(opt);
    }
}

async function deleteSelectedQuery() {
    const select = document.getElementById('saved-list');
    const name = select.value;
    if(!name) return;
    if(confirm("Delete " + name + "?")) {
        await fetch('/api/queries/' + encodeURIComponent(name), { method: 'DELETE' });
        fetchSavedQueries();
    }
}

function loadSelectedQuery() {
    const select = document.getElementById('saved-list');
    const selectedOpt = select.options[select.selectedIndex];
    if (!selectedOpt.value) return;

    const payload = JSON.parse(selectedOpt.dataset.payload);
    
    // Rebuild visual from data
    document.getElementById('builder-container').innerHTML = '';
    payload.groups.forEach(groupTerms => {
        const groupDiv = addNewGroup(false);
        const container = groupDiv.querySelector('.terms-container');
        container.innerHTML = ''; 
        groupTerms.forEach(term => addTermToContainer(container, term, false));
    });
    
    // Sync to Raw
    syncBuilderToRaw();

    document.getElementById('criteria').value = payload.criteria || "";
    document.getElementById('target_posts').value = payload.target_posts || 20;
    document.getElementById('ai_chunk').value = payload.ai_chunk || 5;
    document.getElementById('scan_limit').value = payload.scan_limit || 100;
    document.getElementById('provider').value = payload.provider || "mistral";
    
    if(payload.sort) document.getElementById('sort_by').value = payload.sort;
    if(payload.time) document.getElementById('time_filter').value = payload.time;
    if(payload.post_type) document.getElementById('post_type').value = payload.post_type;
    toggleTimeFilter();

    const deepBox = document.getElementById('deep_scan');
    deepBox.checked = payload.deep_scan || false;
    
    if (payload.subreddits) {
        activeSubreddits = payload.subreddits;
        renderSubreddits();
        syncSubreddits();
    }
    updateExplainer();
}

// --- HISTORY PANEL ---
function toggleHistoryPanel() {
    const panel = document.getElementById('side-panel');
    const overlay = document.getElementById('panel-overlay');
    panel.classList.toggle('open');
    overlay.classList.toggle('show');
}

async function fetchHistory() {
    const container = document.getElementById('history-list');
    container.innerHTML = '<p style="color:#666; text-align:center;">Loading...</p>';
    try {
        const res = await fetch('/api/blacklist');
        const data = await res.json();
        const items = Object.values(data).reverse();
        
        if (items.length === 0) {
            container.innerHTML = '<p style="color:#666; text-align:center;">No history found.</p>';
            return;
        }
        
        container.innerHTML = '';
        items.forEach(item => {
            const div = document.createElement('div');
            div.className = 'history-card';
            let criteriaShort = item.criteria || "None";
            if (criteriaShort.length > 50) criteriaShort = criteriaShort.substring(0, 50) + "...";
            
            div.innerHTML = `
                <h4><a href="${item.url}" target="_blank">${item.title}</a></h4>
                <span class="meta-tag">🔎 Query: ${item.keywords}</span>
                <span class="meta-tag">🤖 Criteria: ${criteriaShort}</span>
                <div style="margin-top:5px; font-size:0.8em; color:#666;">ID: ${item.id}</div>
            `;
            container.appendChild(div);
        });
    } catch (e) {
        container.innerHTML = '<p style="color:red; text-align:center;">Error loading history.</p>';
    }
}

async function clearHistory() {
    if(!confirm("Clear all history?")) return;
    await fetch('/api/blacklist/clear', { method: 'POST' });
    fetchHistory();
}

// --- EXECUTION ---
function startScan() {
    const logs = document.getElementById('logs');
    const results = document.getElementById('results');
    const btn = document.querySelector('#mode-curator .scan-btn');
    const keywordString = document.getElementById('raw-query-input').value;

    if (!keywordString) return alert("Add keywords first!");

    logs.innerHTML = "🚀 Initializing...";
    results.innerHTML = "";
    btn.disabled = true;

    const params = new URLSearchParams({
        keywords: keywordString,
        criteria: document.getElementById('criteria').value,
        provider: document.getElementById('provider').value,
        target_posts: document.getElementById('target_posts').value,
        deep_scan: document.getElementById('deep_scan').checked,
        ai_chunk: document.getElementById('ai_chunk').value,
        scan_limit: document.getElementById('scan_limit').value,
        subreddits: activeSubreddits.join(','),
        debug: document.getElementById('debug_mode').checked,
        sort: document.getElementById('sort_by').value,
        time: document.getElementById('time_filter').value,
        post_type: document.getElementById('post_type').value
    });

    const eventSource = new EventSource("/stream?" + params.toString());

    eventSource.onmessage = function(e) {
        if (e.data.startsWith("<<<HTML_RESULT>>>")) {
            const htmlContent = e.data.replace("<<<HTML_RESULT>>>", "").replaceAll("||NEWLINE||", "\n");
            results.innerHTML = htmlContent;
            eventSource.close();
            btn.disabled = false;
            logs.innerHTML += "\n✅ Process Complete.";
            logs.scrollTop = logs.scrollHeight;
            fetchHistory();
        } else if (e.data.startsWith("<<<APPROVED_POSTS>>>")) {
            // Handle new approved posts format with scores
            try {
                const approvedData = JSON.parse(e.data.replace("<<<APPROVED_POSTS>>>", ""));
                renderApprovedPosts(approvedData);
            } catch (err) {
                console.error("Error parsing approved posts:", err);
            }
        } else {
            logs.innerHTML += "\n" + e.data;
            logs.scrollTop = logs.scrollHeight;
        }
    };

    eventSource.onerror = function() {
        eventSource.close();
        btn.disabled = false;
        logs.innerHTML += "\n❌ Connection Closed.";
    };
}

// Mode 2
function startDiscovery() {
    const logs = document.getElementById('logs');
    const resultsBox = document.getElementById('discovery-results');
    const btn = document.querySelector('#mode-discovery .scan-btn');
    const keywordString = document.getElementById('raw-query-input').value;

    if (!keywordString) return alert("Add keywords first!");

    logs.innerHTML = "🌍 Starting Global Discovery...";
    resultsBox.innerHTML = "";
    btn.disabled = true;

    const params = new URLSearchParams({
        keywords: keywordString,
        limit: document.getElementById('disc_limit').value,
        criteria: document.getElementById('disc_criteria').value,
        provider: document.getElementById('provider').value
    });

    const eventSource = new EventSource("/stream_discovery?" + params.toString());

    eventSource.onmessage = function(e) {
        if (e.data.startsWith("<<<JSON_CARD>>>")) {
            const sub = JSON.parse(e.data.replace("<<<JSON_CARD>>>", ""));
            renderDiscoveryCard(sub);
        } else if (e.data.includes("<<<DONE>>>")) {
            eventSource.close();
            btn.disabled = false;
            logs.innerHTML += "\n✅ Discovery Complete.";
        } else {
            logs.innerHTML += "\n" + e.data;
            logs.scrollTop = logs.scrollHeight;
        }
    };

    eventSource.onerror = function() {
        eventSource.close();
        btn.disabled = false;
        logs.innerHTML += "\n❌ Connection Closed.";
    };
}

function renderDiscoveryCard(sub) {
    const box = document.getElementById('discovery-results');
    const div = document.createElement('div');
    div.className = 'sub-card';
    const safeDesc = sub.description ? sub.description.substring(0, 150) + "..." : "No description.";
    div.innerHTML = `
        <h4>r/${sub.name}</h4>
        <span class="stats">Matches found: ${sub.hits}</span>
        <p>${safeDesc}</p>
        <button class="btn-add-sub" onclick="addDiscoverySub('${sub.name}', this)">+ Add to List</button>
    `;
    box.appendChild(div);
}

async function addDiscoverySub(name, btn) {
    if (!activeSubreddits.includes(name)) {
        activeSubreddits.push(name);
        renderSubreddits();
        await syncSubreddits();
        btn.innerHTML = "✅ Added";
        btn.style.background = "#2b7bd6";
        btn.disabled = true;
    } else {
        alert("Already in your list!");
    }
}

// Global variable to store approved posts for export
let approvedPostsData = [];

function renderApprovedPosts(posts) {
    approvedPostsData = posts;  // Store for export
    const box = document.getElementById('results');
    if (!box) return;
    
    let html = '<div class="results-header">';
    html += '<h3>✅ Approved Posts (' + posts.length + ')</h3>';
    html += '<button class="btn-export" onclick="exportResults()" style="background:#10b981;margin-left:10px;">📥 Export Results</button>';
    html += '</div>';
    html += '<div class="approved-posts">';
    
    posts.forEach(post => {
        const score = post.score || 0;
        const scoreClass = score >= 80 ? 'score-high' : (score >= 60 ? 'score-medium' : 'score-low');
        // Truncate content for preview
        const contentPreview = post.content ? 
            '<div class="approved-content">' + escapeHtml(post.content.substring(0, 300)) + (post.content.length > 300 ? '...' : '') + '</div>' : 
            '';
        html += `
            <div class="approved-card">
                <div class="approved-header">
                    <span class="sub-tag">r/${post.sub}</span>
                    <span class="score-tag ${scoreClass}">Score: ${score}</span>
                </div>
                <h4><a href="${post.url}" target="_blank">${escapeHtml(post.title)}</a></h4>
                ${contentPreview}
                <div class="approved-meta">ID: ${post.id}</div>
            </div>
        `;
    });
    html += '</div>';
    
    box.innerHTML = html;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function exportResults() {
    if (!approvedPostsData || approvedPostsData.length === 0) {
        alert('No results to export!');
        return;
    }
    
    // Create formatted export
    const timestamp = new Date().toISOString().split('T')[0];
    let exportText = `Reddit Curator Results - ${timestamp}\n`;
    exportText += '=====================================\n\n';
    
    approvedPostsData.forEach((post, index) => {
        exportText += `${index + 1}. [${post.sub}] Score: ${post.score}\n`;
        exportText += `   Title: ${post.title}\n`;
        exportText += `   URL: ${post.url}\n`;
        exportText += `   ID: ${post.id}\n`;
        exportText += '\n-------------------------------------\n\n';
    });
    
    // Create and download file
    const blob = new Blob([exportText], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `reddit-curator-results-${timestamp}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}
