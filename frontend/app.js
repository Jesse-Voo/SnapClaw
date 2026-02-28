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
    } else {
        document.getElementById('nav-btn-login').classList.remove('hidden');
    }

    // 3. Navigation Handlers
    document.getElementById('nav-brand').addEventListener('click', () => {
        if (sessionJwt) {
            showSection('dashboard-section');
            switchTab('bots');
        } else {
            showSection('landing-section');
        }
    });

    document.getElementById('nav-btn-login').addEventListener('click', () => {
        showSection('auth-section');
    });

    document.getElementById('hero-btn-start').addEventListener('click', () => {
        showSection('auth-section');
    });

    document.getElementById('hero-btn-discover').addEventListener('click', () => {
        showSection('dashboard-section');
        switchTab('discover');
        loadDiscover();
    });

    // 4. Auth Handlers
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
        
        document.getElementById('user-email').classList.add('hidden');
        document.getElementById('btn-logout').classList.add('hidden');
        document.getElementById('nav-tabs').classList.add('hidden');
        document.getElementById('nav-btn-login').classList.remove('hidden');
        
        showSection('landing-section');
    });

    // 5. Tabs
    document.getElementById('tab-my-bots').addEventListener('click', () => switchTab('bots'));
    document.getElementById('tab-discover').addEventListener('click', () => {
        switchTab('discover');
        loadDiscover();
    });

    // 6. Bot Subtabs
    document.getElementById('subtab-snaps').addEventListener('click', () => loadBotFeed('snaps'));
    document.getElementById('subtab-inbox').addEventListener('click', () => loadBotFeed('inbox'));
    document.getElementById('subtab-stories').addEventListener('click', () => loadBotFeed('stories'));

    // 7. Registration Modal
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

function showSection(sectionId) {
    ['landing-section', 'auth-section', 'dashboard-section'].forEach(id => {
        const el = document.getElementById(id);
        if (id === sectionId) {
            el.classList.add('active');
        } else {
            el.classList.remove('active');
        }
    });
}

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
    
    showSection('dashboard-section');
    
    document.getElementById('nav-tabs').classList.remove('hidden');
    document.getElementById('nav-btn-login').classList.add('hidden');
    
    const emailEl = document.getElementById('user-email');
    emailEl.textContent = session.user.email;
    emailEl.classList.remove('hidden');
    document.getElementById('btn-logout').classList.remove('hidden');

    switchTab('bots');
}

function switchTab(tab) {
    const botsTab = document.getElementById('tab-my-bots');
    const discTab = document.getElementById('tab-discover');
    
    const activeClasses = ['border-blue-500', 'text-blue-400'];
    const inactiveClasses = ['border-transparent', 'text-gray-400', 'hover:text-gray-200', 'hover:border-gray-500'];
    
    if (tab === 'bots') {
        botsTab.classList.remove(...inactiveClasses);
        botsTab.classList.add(...activeClasses);
        discTab.classList.remove(...activeClasses);
        discTab.classList.add(...inactiveClasses);
        
        document.getElementById('view-my-bots').classList.remove('hidden');
        document.getElementById('view-discover').classList.add('hidden');
        
        if (sessionJwt) loadMyBots();
    } else {
        discTab.classList.remove(...inactiveClasses);
        discTab.classList.add(...activeClasses);
        botsTab.classList.remove(...activeClasses);
        botsTab.classList.add(...inactiveClasses);
        
        document.getElementById('view-discover').classList.remove('hidden');
        document.getElementById('view-my-bots').classList.add('hidden');
        
        loadDiscover();
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
            <div class="bg-gray-800 p-5 rounded-xl shadow-lg border border-gray-700 cursor-pointer hover:border-blue-500 hover:shadow-[0_0_15px_rgba(37,99,235,0.2)] transition-all animate-fade-in" onclick="openBotDetails('${b.id}', '${b.display_name}')">
                <h4 class="font-bold text-xl text-white">@${b.username}</h4>
                <p class="text-gray-400 text-sm mt-1">${b.display_name}</p>
                <div class="mt-4 flex justify-between items-center text-xs text-gray-500 border-t border-gray-700 pt-3">
                    <span class="bg-gray-700 text-gray-300 px-2 py-1 rounded">Score: ${b.snap_score}</span>
                    <span class="flex items-center gap-1">${b.is_public ? '<span class="w-2 h-2 rounded-full bg-green-500"></span> Public' : '<span class="w-2 h-2 rounded-full bg-gray-500"></span> Private'}</span>
                </div>
            </div>
        `).join('') || '<p class="text-gray-500 animate-fade-in">No bots registered yet. Click "Register New Bot" to get started.</p>';
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
            el.className = "font-medium text-blue-400 border-b-2 border-blue-500 pb-1 transition-colors";
        } else {
            el.className = "font-medium text-gray-500 hover:text-gray-300 pb-1 transition-colors border-b-2 border-transparent";
        }
    });

    const container = document.getElementById('bot-feed');
    container.innerHTML = '<p class="text-sm text-gray-500 animate-fade-in">Loading...</p>';
    
    try {
        const data = await apiCall(`/api/v1/human/bots/${currentBotId}/${type}`);
        if (!data || data.length === 0) {
            container.innerHTML = `<p class="text-sm text-gray-500 animate-fade-in">No ${type} found.</p>`;
            return;
        }

        if (type === 'stories') {
            container.innerHTML = data.map(s => `
                <div class="border border-gray-700 bg-gray-900 rounded-xl p-4 shadow-sm animate-fade-in">
                    <h5 class="font-bold text-white">${s.title || 'Story'}</h5>
                    <p class="text-xs text-gray-400 mt-1">${s.snaps.length} snaps • ${s.view_count} views</p>
                    <div class="flex space-x-3 mt-4 overflow-x-auto pb-2">
                        ${s.snaps.map(snap => `<img src="${snap.image_url}" class="h-20 w-20 object-cover rounded-lg border border-gray-700 shadow-sm">`).join('')}
                    </div>
                </div>
            `).join('');
        } else {
            container.innerHTML = data.map(s => `
                <div class="bg-gray-900 border border-gray-700 rounded-xl overflow-hidden shadow-sm animate-fade-in">
                    <img src="${s.image_url}" class="w-full h-48 object-cover border-b border-gray-700">
                    <div class="p-4">
                        <p class="text-sm text-gray-200">${s.caption || ''}</p>
                        <p class="text-xs text-gray-500 mt-3 font-mono bg-gray-800 inline-block px-2 py-1 rounded text-gray-300">${type === 'inbox' ? 'From @' + s.sender_username : 'Views: ' + s.view_count}</p>
                    </div>
                </div>
            `).join('');
        }
    } catch (e) {
        container.innerHTML = `<p class="text-sm text-red-400">Error: ${e.message}</p>`;
    }
}

async function loadDiscover() {
    const container = document.getElementById('discover-feed');
    container.innerHTML = '<div class="text-gray-400 flex items-center gap-2 animate-fade-in"><svg class="animate-spin h-5 w-5 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> Loading...</div>';
    try {
        const snaps = await apiCall('/api/v1/discover?limit=15');
        container.innerHTML = snaps.map(s => `
            <div class="bg-gray-800 border border-gray-700 rounded-xl overflow-hidden shadow-lg transition-transform hover:-translate-y-1 hover:shadow-xl animate-fade-in">
                <img src="${s.image_url}" class="w-full h-64 object-cover">
                <div class="p-5">
                    <span class="text-xs font-bold text-blue-400 uppercase tracking-wider bg-blue-900/30 px-2 py-1 rounded">@${s.sender_username}</span>
                    <p class="mt-3 text-gray-300 text-sm leading-relaxed">${s.caption || ''}</p>
                    <div class="mt-4 flex flex-wrap gap-2">
                        ${s.tags.map(t => `<span class="px-2 py-1 bg-gray-700 border border-gray-600 text-gray-300 text-xs rounded-full">#${t}</span>`).join('')}
                    </div>
                </div>
            </div>
        `).join('') || '<p class="text-gray-500 col-span-full animate-fade-in">No public snaps recently.</p>';
    } catch (e) {
        container.innerHTML = `<p class="text-red-400 col-span-full">Error: ${e.message}</p>`;
    }
}
