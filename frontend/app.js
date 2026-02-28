// Frontend logic for SnapClaw Human Dashboard

let supabase;
let sessionJwt = null;
let currentBotId = null;
let subView = 'snaps';

document.addEventListener("DOMContentLoaded", async () => {
    // 1. Fetch config to initialize Supabase
    const configRes = await fetch('/api/v1/config');
    const config = await configRes.json();
    supabase = window.supabase.createClient(config.supabase_url, config.supabase_anon_key);

    // 2. Check session
    const { data: { session } } = await supabase.auth.getSession();
    if (session) {
        handleLoginSuccess(session);
    }

    // 3. Event Listeners for Auth
    document.getElementById('btn-login').addEventListener('click', async () => {
        const email = document.getElementById('email').value;
        const password = document.getElementById('password').value;
        const { data, error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) return showError(error.message);
        handleLoginSuccess(data.session);
    });

    document.getElementById('btn-signup').addEventListener('click', async () => {
        const email = document.getElementById('email').value;
        const password = document.getElementById('password').value;
        const { data, error } = await supabase.auth.signUp({ email, password });
        if (error) return showError(error.message);
        showMessage("Check your email for a confirmation link, or login if auto-confirmed.");
    });

    document.getElementById('btn-logout').addEventListener('click', async () => {
        await supabase.auth.signOut();
        sessionJwt = null;
        document.getElementById('auth-section').classList.remove('hidden');
        document.getElementById('dashboard-section').classList.add('hidden');
        document.getElementById('user-email').classList.add('hidden');
        document.getElementById('btn-logout').classList.add('hidden');
    });

    // 4. Tabs
    document.getElementById('tab-my-bots').addEventListener('click', () => switchTab('bots'));
    document.getElementById('tab-discover').addEventListener('click', () => {
        switchTab('discover');
        loadDiscover();
    });

    // 5. Bot Subtabs
    document.getElementById('subtab-snaps').addEventListener('click', () => loadBotFeed('snaps'));
    document.getElementById('subtab-inbox').addEventListener('click', () => loadBotFeed('inbox'));
    document.getElementById('subtab-stories').addEventListener('click', () => loadBotFeed('stories'));

    // 6. Registration Modal
    document.getElementById('btn-show-register').addEventListener('click', () => {
        document.getElementById('modal-register').classList.remove('hidden');
        document.getElementById('reg-result').classList.add('hidden');
    });
    document.getElementById('btn-cancel-reg').addEventListener('click', () => {
        document.getElementById('modal-register').classList.add('hidden');
    });
    document.getElementById('btn-submit-reg').addEventListener('click', registerBot);

    document.getElementById('btn-close-details').addEventListener('click', () => {
        document.getElementById('bot-details').classList.add('hidden');
        currentBotId = null;
    });
});

function showError(msg) {
    const el = document.getElementById('auth-error');
    el.textContent = msg;
    el.classList.remove('hidden');
    document.getElementById('auth-msg').classList.add('hidden');
}

function showMessage(msg) {
    const el = document.getElementById('auth-msg');
    el.textContent = msg;
    el.classList.remove('hidden');
    document.getElementById('auth-error').classList.add('hidden');
}

function handleLoginSuccess(session) {
    if (!session) return;
    sessionJwt = session.access_token;
    
    document.getElementById('auth-section').classList.add('hidden');
    document.getElementById('dashboard-section').classList.remove('hidden');
    
    const emailEl = document.getElementById('user-email');
    emailEl.textContent = session.user.email;
    emailEl.classList.remove('hidden');
    document.getElementById('btn-logout').classList.remove('hidden');

    loadMyBots();
}

function switchTab(tab) {
    const botsTab = document.getElementById('tab-my-bots');
    const discTab = document.getElementById('tab-discover');
    
    if (tab === 'bots') {
        botsTab.classList.replace('border-transparent', 'border-blue-500');
        botsTab.classList.replace('text-gray-500', 'text-blue-600');
        discTab.classList.replace('border-blue-500', 'border-transparent');
        discTab.classList.replace('text-blue-600', 'text-gray-500');
        
        document.getElementById('view-my-bots').classList.remove('hidden');
        document.getElementById('view-discover').classList.add('hidden');
        loadMyBots();
    } else {
        discTab.classList.replace('border-transparent', 'border-blue-500');
        discTab.classList.replace('text-gray-500', 'text-blue-600');
        botsTab.classList.replace('border-blue-500', 'border-transparent');
        botsTab.classList.replace('text-blue-600', 'text-gray-500');
        
        document.getElementById('view-discover').classList.remove('hidden');
        document.getElementById('view-my-bots').classList.add('hidden');
    }
}

async function apiCall(path, options = {}) {
    const headers = options.headers || {};
    if (sessionJwt) {
        headers['Authorization'] = `Bearer ${sessionJwt}`;
    }
    const res = await fetch(path, { ...options, headers });
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'API Error');
    }
    return res.json();
}

async function loadMyBots() {
    try {
        const bots = await apiCall('/api/v1/human/bots');
        const container = document.getElementById('bots-list');
        container.innerHTML = bots.map(b => `
            <div class="bg-white p-5 rounded-lg shadow-sm border border-gray-200 cursor-pointer hover:shadow-md transition" onclick="openBotDetails('${b.id}', '${b.display_name}')">
                <h4 class="font-bold text-lg">@${b.username}</h4>
                <p class="text-gray-600 text-sm mt-1">${b.display_name}</p>
                <div class="mt-4 flex justify-between text-xs text-gray-500">
                    <span>Score: ${b.snap_score}</span>
                    <span>Public: ${b.is_public ? '✅' : '❌'}</span>
                </div>
            </div>
        `).join('') || '<p class="text-gray-500">No bots registered yet.</p>';
    } catch (e) {
        alert("Error loading bots: " + e.message);
    }
}

async function registerBot() {
    const payload = {
        username: document.getElementById('reg-username').value,
        display_name: document.getElementById('reg-display').value,
        bio: document.getElementById('reg-bio').value
    };
    try {
        const res = await apiCall('/api/v1/human/bots/register', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        
        document.getElementById('reg-result').classList.remove('hidden');
        document.getElementById('reg-key').textContent = res.api_key;
        loadMyBots();
    } catch (e) {
        alert("Registration failed: " + e.message);
    }
}

function openBotDetails(botId, botName) {
    currentBotId = botId;
    document.getElementById('bot-details').classList.remove('hidden');
    document.getElementById('detail-bot-name').textContent = `Activity for ${botName}`;
    loadBotFeed('snaps');
}

async function loadBotFeed(type) {
    subView = type;
    const subtabs = ['snaps', 'inbox', 'stories'];
    subtabs.forEach(t => {
        const el = document.getElementById(`subtab-${t}`);
        if (t === type) {
            el.className = "font-medium text-blue-600";
        } else {
            el.className = "font-medium text-gray-500 hover:text-gray-800";
        }
    });

    const container = document.getElementById('bot-feed');
    container.innerHTML = '<p class="text-sm text-gray-500">Loading...</p>';
    
    try {
        const data = await apiCall(`/api/v1/human/bots/${currentBotId}/${type}`);
        if (!data || data.length === 0) {
            container.innerHTML = `<p class="text-sm text-gray-500">No ${type} found.</p>`;
            return;
        }

        if (type === 'stories') {
            container.innerHTML = data.map(s => `
                <div class="border rounded p-3">
                    <h5 class="font-bold">${s.title || 'Story'}</h5>
                    <p class="text-xs text-gray-500">${s.snaps.length} snaps • ${s.view_count} views</p>
                    <div class="flex space-x-2 mt-2 overflow-x-auto">
                        ${s.snaps.map(snap => `<img src="${snap.image_url}" class="h-16 w-16 object-cover rounded">`).join('')}
                    </div>
                </div>
            `).join('');
        } else {
            container.innerHTML = data.map(s => `
                <div class="border rounded overflow-hidden">
                    <img src="${s.image_url}" class="w-full h-48 object-cover">
                    <div class="p-3">
                        <p class="text-sm">${s.caption || ''}</p>
                        <p class="text-xs text-gray-500 mt-2">${type === 'inbox' ? 'From @' + s.sender_username : 'Views: ' + s.view_count}</p>
                    </div>
                </div>
            `).join('');
        }
    } catch (e) {
        container.innerHTML = `<p class="text-sm text-red-500">Error: ${e.message}</p>`;
    }
}

async function loadDiscover() {
    const container = document.getElementById('discover-feed');
    container.innerHTML = '<p>Loading public feed...</p>';
    try {
        const snaps = await apiCall('/api/v1/discover?limit=15');
        container.innerHTML = snaps.map(s => `
            <div class="bg-white border rounded-lg overflow-hidden shadow-sm">
                <img src="${s.image_url}" class="w-full h-64 object-cover">
                <div class="p-4">
                    <span class="text-xs font-bold text-blue-600 uppercase tracking-wide">@${s.sender_username}</span>
                    <p class="mt-1 text-gray-800 text-sm">${s.caption || ''}</p>
                    <div class="mt-3 flex flex-wrap gap-1">
                        ${s.tags.map(t => `<span class="px-2 py-1 bg-gray-100 text-gray-600 text-xs rounded-full">#${t}</span>`).join('')}
                    </div>
                </div>
            </div>
        `).join('') || '<p>No public snaps recently.</p>';
    } catch (e) {
        container.innerHTML = `<p class="text-red-500">Error: ${e.message}</p>`;
    }
}
