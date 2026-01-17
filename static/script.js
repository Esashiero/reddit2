// --- STATE MANAGEMENT ---
let currentCuration = {
    description: "",
    constraints: [],
    variations: [],
    results: [],
    stats: { fetched: 0, analyzed: 0, approved: 0 }
};

let tournamentData = {};
let userFavorites = {};

document.addEventListener('DOMContentLoaded', () => {
    loadSubreddits();
    loadHistory();
    loadUserFavorites();
});

// --- API WRAPPERS ---
async function api(endpoint, method = 'GET', body = null) {
    const options = {
        method,
        headers: { 'Content-Type': 'application/json' }
    };
    if (body) options.body = JSON.stringify(body);
    const res = await fetch(endpoint, options);
    return res.json();
}

// --- INITIALIZATION ---
async function loadSubreddits() {
    const subs = await api('/api/subreddits');
    document.getElementById('subs-input').value = subs.join(', ');
}

async function loadUserFavorites() {
    userFavorites = await api('/api/favorites');
}

async function initCuration() {
    const desc = document.getElementById('description-input').value;
    if (!desc) return alert("Please enter a description");

    const btn = document.getElementById('init-btn');
    const originalContent = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Generating...';

    try {
        const data = await api('/api/curate/init', 'POST', { description: desc });

        currentCuration.description = desc;
        currentCuration.constraints = data.core_constraints;
        currentCuration.variations = data.variations;

        renderSetup(data);
        document.getElementById('curation-setup').style.display = 'block';
        document.getElementById('curation-setup').scrollIntoView({ behavior: 'smooth' });
    } catch (e) {
        alert("Error initializing curation: " + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalContent;
    }
}

function renderSetup(data) {
    // Render Constraints
    const cList = document.getElementById('constraints-list');
    cList.innerHTML = data.core_constraints.map(c => `
        <div class="constraint-tag">
            <span class="constraint-theme">${c.theme}</span>
            <span class="constraint-desc">${c.terms.slice(0, 3).join(', ')}...</span>
        </div>
    `).join('');

    // Render Variations Preview
    const vPreview = document.getElementById('variations-preview');
    vPreview.innerHTML = data.variations.map(v => `
        <div class="variant-card">
            <div class="variant-type">${v.type}</div>
            <div class="variant-query">${v.query}</div>
            <div style="font-size:0.75rem; color:#64748b; margin-top:4px;">${v.reasoning}</div>
        </div>
    `).join('');
}

// --- PIPELINE EXECUTION ---
function startPipeline() {
    const desc = currentCuration.description;
    const subs = document.getElementById('subs-input').value;

    // UI Reset
    document.getElementById('pipeline-status').style.display = 'block';
    document.getElementById('tournament-view').style.display = 'none';
    document.getElementById('results-view').style.display = 'none';
    document.getElementById('logs-container').innerHTML = '';
    document.getElementById('tournament-results').innerHTML = '';
    document.getElementById('posts-container').innerHTML = '';

    // Reset Stats
    updateStats({ fetched: 0, analyzed: 0, approved: 0 });
    tournamentData = {};

    const params = new URLSearchParams({
        keywords: currentCuration.variations[0].query, // Default
        criteria: desc,
        subreddits: subs,
        tournament: 'true',
        exhaustive: 'false',
        target_posts: '10'
    });

    const eventSource = new EventSource(`/stream?${params.toString()}`);

    eventSource.onmessage = (e) => {
        const data = e.data;

        if (data.startsWith('<<<TOURNAMENT_START>>>')) {
            document.getElementById('tournament-view').style.display = 'block';
            const variations = JSON.parse(data.replace('<<<TOURNAMENT_START>>>', ''));
            renderTournamentBase(variations);
        }
        else if (data.startsWith('<<<TOURNAMENT_RESULT>>>')) {
            const result = JSON.parse(data.replace('<<<TOURNAMENT_RESULT>>>', ''));
            updateTournamentResult(result);
        }
        else if (data.startsWith('<<<SEARCH_PASS>>>')) {
            const info = JSON.parse(data.replace('<<<SEARCH_PASS>>>', ''));
            showSearchPass(info);
        }
        else if (data.startsWith('<<<POST_SCORED>>>')) {
            const post = JSON.parse(data.replace('<<<POST_SCORED>>>', ''));
            // Optionally add to a live feed
            log(`⭐ [${post.score.toFixed(1)}] r/${post.sub}: ${post.title.substring(0, 50)}...`, "success");
        }
        else if (data.startsWith('<<<SEARCH_STATS>>>')) {
            const stats = JSON.parse(data.replace('<<<SEARCH_STATS>>>', ''));
            updateStats({
                fetched: stats.fetched,
                analyzed: stats.analyzed,
                approved: stats.scores.high
            });
        }
        else if (data.startsWith('<<<APPROVED_POSTS>>>')) {
            const posts = JSON.parse(data.replace('<<<APPROVED_POSTS>>>', ''));
            finalizeResults(posts);
            eventSource.close();
            loadHistory();
        }
        else {
            log(data);
        }
    };

    eventSource.onerror = () => {
        log("❌ Connection Closed", "warning");
        eventSource.close();
    };
}

// --- UI COMPONENTS ---

function renderTournamentBase(variations) {
    const container = document.getElementById('tournament-results');
    container.innerHTML = variations.map(v => `
        <div class="variant-card" id="v-${v.type}">
            <div class="variant-header">
                <div class="variant-type">${v.type}</div>
                <div class="stat-val" id="score-${v.type}">--</div>
            </div>
            <div class="variant-query">${v.query}</div>
            <div class="variant-stats">
                <div class="stat-item">
                    <span class="stat-val" id="hq-${v.type}">0</span>
                    <span class="stat-label">Matches</span>
                </div>
                <div class="stat-item">
                    <span class="stat-val" id="avg-${v.type}">0</span>
                    <span class="stat-label">Avg Score</span>
                </div>
            </div>
            <div class="progress-bar-bg"><div class="progress-bar-fill" id="pb-${v.type}"></div></div>
        </div>
    `).join('');
}

function updateTournamentResult(res) {
    const card = document.getElementById(`v-${res.type}`);
    if (!card) return;

    document.getElementById(`score-${res.type}`).innerText = res.v_score.toFixed(1);
    document.getElementById(`hq-${res.type}`).innerText = res.high_quality;
    document.getElementById(`avg-${res.type}`).innerText = res.avg_score.toFixed(1);

    const pb = document.getElementById(`pb-${res.type}`);
    pb.style.width = '100%';
    pb.style.background = '#10b981';

    tournamentData[res.type] = res;

    // Check if winner
    const all = Object.values(tournamentData);
    if (all.length === 5) {
        const winner = all.sort((a,b) => b.v_score - a.v_score)[0];
        document.getElementById(`v-${winner.type}`).classList.add('winner');
        log(`🏆 Winner: ${winner.type} variant`, "success");
    }
}

function showSearchPass(info) {
    const el = document.getElementById('pass-info');
    el.style.display = 'block';
    document.getElementById('current-query').innerText = info.query;
    document.getElementById('current-sort').innerText = info.sort.toUpperCase();
    document.getElementById('current-limit').innerText = `limit: ${info.limit}/sub`;
}

function updateStats(stats) {
    document.getElementById('stat-fetched').innerText = stats.fetched;
    document.getElementById('stat-analyzed').innerText = stats.analyzed;
    document.getElementById('stat-approved').innerText = stats.approved;

    if (stats.approved >= 10) {
        document.getElementById('stat-approved').style.color = '#10b981';
    }
}

function finalizeResults(posts) {
    currentCuration.results = posts;
    document.getElementById('results-view').style.display = 'block';
    document.getElementById('results-view').scrollIntoView({ behavior: 'smooth' });

    const container = document.getElementById('posts-container');
    container.innerHTML = posts.map((p, i) => renderPostCard(p, i)).join('');

    document.getElementById('results-meta').innerText = `${posts.length} high-quality matches found`;
}

function renderPostCard(p, index) {
    const score = (typeof p.score === 'number') ? p.score.toFixed(1) : "N/A";
    const isFavorited = !!userFavorites[p.id];

    // Simple keyword highlighting based on description/query
    let highlightedTitle = escapeHtml(p.title);
    let highlightedContent = escapeHtml(p.content || "");

    const terms = currentCuration.description.split(' ').filter(t => t.length > 3);
    terms.forEach(term => {
        const regex = new RegExp(`(${term})`, 'gi');
        highlightedTitle = highlightedTitle.replace(regex, '<mark>$1</mark>');
        highlightedContent = highlightedContent.replace(regex, '<mark>$1</mark>');
    });

    return `
        <div class="post-card">
            <div class="post-header">
                <span class="post-sub">r/${p.sub}</span>
                <div style="display:flex; align-items:center; gap:12px;">
                    <button class="btn btn-outline" style="padding:4px 8px;" onclick="toggleFavorite('${p.id}', ${index})">
                        <i class="fa-${isFavorited ? 'solid' : 'regular'} fa-star" style="color:${isFavorited ? '#f59e0b' : 'inherit'}"></i>
                    </button>
                    <span class="post-score">${score}</span>
                </div>
            </div>
            <h3 class="post-title"><a href="${p.url}" target="_blank">${highlightedTitle}</a></h3>
            <div class="post-content" id="content-${p.id}">${highlightedContent}</div>
            <button class="btn btn-outline" style="margin-top:8px; font-size:0.75rem;" onclick="toggleExpand('${p.id}')">Toggle Expand</button>
            <div style="margin-top:12px; display:flex; gap:8px; flex-wrap:wrap;">
                ${(p.tags || []).map(t => `<span class="tag-pill">${t}</span>`).join('')}
            </div>
        </div>
    `;
}

async function toggleFavorite(postId, index) {
    const post = currentCuration.results[index];
    if (userFavorites[postId]) {
        await api(`/api/favorites/${postId}`, 'DELETE');
        delete userFavorites[postId];
    } else {
        await api('/api/favorites', 'POST', post);
        userFavorites[postId] = post;
    }
    // Re-render specifically this card or all
    finalizeResults(currentCuration.results);
}

function toggleExpand(id) {
    document.getElementById(`content-${id}`).classList.toggle('expanded');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function log(msg, type = "info") {
    const container = document.getElementById('logs-container');
    const div = document.createElement('div');
    div.className = `log-entry ${type}`;
    div.innerText = `[${new Date().toLocaleTimeString()}] ${msg}`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

// --- HISTORY & NAVIGATION ---
function toggleHistory() {
    const panel = document.getElementById('side-panel');
    const overlay = document.getElementById('overlay');
    panel.classList.toggle('open');
    overlay.classList.toggle('show');
}

async function loadHistory() {
    const data = await api('/api/results');
    const container = document.getElementById('history-container');

    if (data.length === 0) {
        container.innerHTML = '<div style="text-align:center; color:#64748b; margin-top:20px;">No history found</div>';
        return;
    }

    container.innerHTML = data.map(item => {
        const date = new Date(item.timestamp * 1000).toLocaleString();
        return `
            <div class="history-item" onclick="loadSavedResult('${item.id}')">
                <div class="history-date">${date}</div>
                <div class="history-query">${item.criteria || item.query}</div>
                <div class="history-stats">
                    <span><i class="fa-solid fa-file-lines"></i> ${item.count} posts</span>
                </div>
            </div>
        `;
    }).join('');
}

async function loadSavedResult(id) {
    toggleHistory();
    const data = await api(`/api/results/${id}`);

    currentCuration.description = data.criteria || data.query;
    currentCuration.results = data.results;

    document.getElementById('curation-setup').style.display = 'none';
    document.getElementById('pipeline-status').style.display = 'none';

    finalizeResults(data.results);
    document.getElementById('results-title').innerText = "History Result";
}
