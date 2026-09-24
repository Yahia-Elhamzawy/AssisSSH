/* ==========================================================================
   AI DevOps Studio & Terminal — Next-Gen Client Engine ⚡
   ========================================================================== */

// State
let isConnected = false;
let isRunning = false;
let eventSource = null;
let currentSessionId = "web_default";
let sessionTurnCount = 1;
let isWebSearchActive = true;
let isSudoActive = false;
let executedActionCount = 0;
let commandHistory = [];
let historyIndex = -1;
let terminalFontSize = 13;
let auditLog = [];
let activeDockerContainerForLogs = "";
let currentDisplayPath = "~";
let currentMaxSteps = 20;

// Linux & Docker command autocompletion dictionary
const LINUX_COMMANDS = [
    "docker ps", "docker ps -a", "docker logs", "docker restart", "docker stop", "docker start",
    "docker images", "docker compose up -d", "docker compose down", "docker compose logs", "docker system prune -f",
    "systemctl status", "systemctl restart", "systemctl stop", "systemctl start", "systemctl list-units --failed",
    "journalctl -xe", "journalctl -u", "cat /var/log/syslog | tail -50",
    "df -h", "free -h", "uptime", "top -b -n 1 | head -20", "htop", "uname -a",
    "netstat -tuln", "ss -tuln", "ufw status", "curl -I", "ping -c 4",
    "ls -la", "tail -f", "nano", "vim", "chmod", "chown", "mkdir -p", "grep -rn",
    "apt update", "apt upgrade -y", "apt install -y"
];

// Palette Commands Registry
const PALETTE_COMMANDS = [
    { title: "التيرمينال والكوبيلوت", desc: "فتح واجهة سطر الأوامر ومساعد الذكاء الاصطناعي", icon: "🖥️", action: () => switchView('terminal') },
    { title: "مراقبة السيرفر والدوكر", desc: "عرض استهلاك الموارد وشبكة الحاويات", icon: "📊", action: () => switchView('dashboard') },
    { title: "سجل التدقيق والأوامر", desc: "عرض تاريخ الأوامر المنفذة وحالتها", icon: "📜", action: () => switchView('audit') },
    { title: "الإعدادات وبوت التليجرام", desc: "خيارات الذكاء الاصطناعي وأمان البوت", icon: "⚙️", action: () => switchView('settings') },
    { title: "تبديل البحث في الويب", desc: "تفعيل أو تعطيل البحث الحي على الإنترنت", icon: "🌐", action: () => toggleWebSearch() },
    { title: "سجل الجلسات والمحادثات", desc: "عرض واستعادة المحادثات والجلسات السابقة", icon: "📂", action: () => openSessionsModal() },
    { title: "جلسة جديدة ومسح الذاكرة", desc: "بدء محادثة جديدة وتصفير سياق الجلسة", icon: "🧹", action: () => resetWebSession() },
    { title: "إدارة اتصال السيرفر (SSH)", desc: "فتح نافذة إعدادات الخادم والاتصال", icon: "🔗", action: () => openConnModal() },
    { title: "فحص شامل للسيرفر (Doctor)", desc: "تشغيل الذكاء الاصطناعي لفحص السيرفر", icon: "🩺", action: () => runQuickDiag("قم بعمل فحص شامل للسيرفر ولخص حالته") },
    { title: "فحص حاويات Docker وإصلاحها", desc: "فحص الحاويات وتشغيل المتوقف منها", icon: "🐳", action: () => runQuickDiag("افحص الدوكر وشغل الحاويات المتوقفة") },
    { title: "تنظيف مخلفات Docker Prune", desc: "إزالة الحاويات والصور غير المستخدمة", icon: "🧹", action: () => confirmDockerPrune() },
    { title: "مسح شاشة التيرمينال", desc: "تنظيف مخرجات التيرمينال", icon: "✨", action: () => clearTerminal() },
    { title: "تصدير سجل التيرمينال", desc: "تحميل مخرجات التيرمينال كملف log", icon: "⬇️", action: () => downloadTerminalLog() }
];

/* ==========================================================================
   INITIALIZATION
   ========================================================================== */
document.addEventListener("DOMContentLoaded", () => {
    loadSavedCredentials();
    checkConnectionStatus();
    setupEventListeners();
    initSettings();
    initSessionHistory();
    
    // Restore preferred tab
    const savedTab = localStorage.getItem("devops_active_tab") || "terminal";
    switchView(savedTab, false);

    // Initial terminal greeting
    printTerminalBanner();

    // Start background stats polling
    setInterval(pollHeaderMetrics, 8000);
});

/* ==========================================================================
   VIEW / TAB NAVIGATION
   ========================================================================== */
function switchView(viewName, doRefresh = true) {
    // Nav buttons
    document.querySelectorAll(".nav-tab-btn").forEach(btn => btn.classList.remove("active"));
    const activeBtn = document.getElementById(`tabBtn${capitalize(viewName)}`);
    if (activeBtn) activeBtn.classList.add("active");

    // View panels
    document.querySelectorAll(".view-panel").forEach(panel => panel.classList.remove("active"));
    const activePanel = document.getElementById(`view${capitalize(viewName)}`);
    if (activePanel) activePanel.classList.add("active");

    localStorage.setItem("devops_active_tab", viewName);

    if (viewName === "dashboard" && doRefresh) {
        refreshDashboard(true);
    } else if (viewName === "terminal") {
        focusTerminalInput();
    }
}

function capitalize(s) {
    return s.charAt(0).toUpperCase() + s.slice(1);
}

/* ==========================================================================
   TERMINAL BANNER & CORE RENDERING
   ========================================================================== */
function printTerminalBanner() {
    const termScreen = document.getElementById("termScreen");
    const now = new Date().toUTCString();
    termScreen.innerHTML = `
<div class="motd-banner">
  <div class="motd-title">Welcome to Ubuntu 24.04.1 LTS (GNU/Linux 6.8.0-40-generic x86_64)</div>
  <div class="motd-doc"> * Documentation:  https://help.ubuntu.com</div>
  <div class="motd-doc"> * Management:     https://landscape.canonical.com</div>
  <div class="motd-doc"> * Support:        https://ubuntu.com/pro</div>
  <div class="motd-stats">
  System load:   0.12               Processes:             142
  Usage of /:    18.4% of 38.70GB   Users logged in:       1
  Memory usage:  34%                IP address for eth0:   192.168.1.100</div>
  <div class="motd-footer">
    ⚡ <b>AssisSSH Terminal Core</b> active (Gemini 3.5 Flash-Lite)
    💡 Type any command below (e.g. <code>docker ps</code>, <code>ufw status</code>) or use the AI Copilot on the right.
  </div>
</div>
<div class="term-divider"></div>
`;
}

function appendTerminalCommand(username, hostname, command, isSudo = false, path = null) {
    const termScreen = document.getElementById("termScreen");
    const user = username || (document.getElementById("cliUser") ? document.getElementById("cliUser").textContent : "user");
    const host = hostname || (document.getElementById("cliHost") ? document.getElementById("cliHost").textContent : "server");
    const displayPath = path || currentDisplayPath || "~";
    const symbol = isSudo ? "#" : "$";
    const sudoClass = isSudo ? "sudo" : "";

    const div = document.createElement("div");
    div.className = "term-prompt-line";
    div.innerHTML = `
        <span class="term-prompt-wrapper"><span class="prompt-user">${escapeHtml(user)}</span><span class="prompt-at">@</span><span class="prompt-host">${escapeHtml(host)}</span><span class="prompt-colon">:</span><span class="prompt-path">${escapeHtml(displayPath)}</span><span class="prompt-symbol ${sudoClass}">${symbol}</span></span>
        <span class="term-cmd-text">${escapeHtml(command)}</span>
        <span class="cmd-badge running" id="badge-${Date.now()}">RUNNING</span>
    `;
    termScreen.appendChild(div);
    scrollTerminalToBottom();
}

function appendTerminalOutput(stdout, stderr, exitCode, command = "") {
    const termScreen = document.getElementById("termScreen");

    // Remove running badge from latest prompt line
    const lastBadge = termScreen.querySelector(".cmd-badge.running");
    if (lastBadge) {
        if (exitCode === 0) {
            lastBadge.remove();
        } else {
            lastBadge.className = "cmd-badge error";
            lastBadge.textContent = `EXIT ${exitCode}`;
        }
    }

    if (stdout || stderr) {
        const streamDiv = document.createElement("div");
        streamDiv.className = "term-output-stream";

        if (stdout && stdout.trim()) {
            const preOut = document.createElement("pre");
            preOut.className = "term-stdout";
            preOut.textContent = stdout;
            streamDiv.appendChild(preOut);
        }

        if (stderr && stderr.trim()) {
            const preErr = document.createElement("pre");
            preErr.className = "term-stderr";
            preErr.textContent = stderr;
            streamDiv.appendChild(preErr);
        }

        termScreen.appendChild(streamDiv);
    }

    // Log to Audit system
    if (command) {
        logToAudit(command, isRunning ? "AI Copilot" : "يحيى (يدوي)", exitCode);
    }

    scrollTerminalToBottom();
}

function isArabicText(text) {
    return /[\u0600-\u06FF]/.test(text);
}

function formatBidiText(rawText) {
    if (!rawText) return "";
    let escaped = escapeHtml(rawText);
    
    // 1. Convert backticked code `something` into an isolated LTR code badge
    escaped = escaped.replace(/`([^`]+)`/g, '<code class="term-inline-code" dir="ltr"><bdi>$1</bdi></code>');
    
    // 2. Isolate parenthesized English terms: (something)
    escaped = escaped.replace(/\(([a-zA-Z0-9_\-\.\s]+)\)/g, '(<bdi class="bidi-isolate" dir="ltr">$1</bdi>)');

    // 3. Isolate hyphenated English technical names (e.g. rida-academy, docker-compose)
    escaped = escaped.replace(/(?<![<"\/])\b([a-zA-Z0-9_]+[-.][a-zA-Z0-9_\-\.]+)\b(?![>"])/g, '<bdi class="bidi-isolate" dir="ltr">$1</bdi>');
    
    return escaped;
}

function appendTerminalComment(text) {
    if (!text || !text.trim()) return;
    const termScreen = document.getElementById("termScreen");
    const div = document.createElement("div");
    
    const isAr = isArabicText(text);
    div.className = `term-comment-line ${isAr ? 'rtl-comment' : 'ltr-comment'}`;
    div.setAttribute("dir", isAr ? "rtl" : "ltr");
    
    const formatted = formatBidiText(text);

    div.innerHTML = `
        <span class="term-comment-badge" dir="ltr"># 🤖 [AI]</span>
        <span class="term-comment-text" dir="${isAr ? 'rtl' : 'ltr'}">${formatted}</span>
    `;
    
    termScreen.appendChild(div);
    scrollTerminalToBottom();
}

function scrollTerminalToBottom() {
    const termScreen = document.getElementById("termScreen");
    termScreen.scrollTop = termScreen.scrollHeight;
}

function focusTerminalInput() {
    const input = document.getElementById("termInput");
    if (input) input.focus();
}

/* ==========================================================================
   TERMINAL ACTIONS (TOOLBAR & SHORTCUTS)
   ========================================================================== */
function copyTerminalOutput() {
    const termScreen = document.getElementById("termScreen");
    navigator.clipboard.writeText(termScreen.innerText).then(() => {
        showToast("📋 تم نسخ محتوى التيرمينال بنجاح!", "success");
    }).catch(() => {
        showToast("تعذر النسخ إلى الحافظة", "error");
    });
}

function downloadTerminalLog() {
    const text = document.getElementById("termScreen").innerText;
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `terminal_log_${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}.log`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast("⬇️ تم تصدير ملف سجل التيرمينال بنجاح!", "success");
}

function clearTerminal() {
    const termScreen = document.getElementById("termScreen");
    termScreen.innerHTML = "";
    printTerminalBanner();
    showToast("🧹 تم مسح شاشة التيرمينال");
}

function toggleFullscreen() {
    if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => {});
    } else {
        if (document.exitFullscreen) {
            document.exitFullscreen().catch(() => {});
        }
    }
}

function zoomTerminal(delta) {
    terminalFontSize = Math.max(11, Math.min(20, terminalFontSize + delta));
    document.getElementById("termScreen").style.fontSize = `${terminalFontSize}px`;
    document.getElementById("fontSizeIndicator").textContent = `${terminalFontSize}px`;
}

function toggleCopilotDock() {
    const dock = document.getElementById("copilotDock");
    const btnText = document.getElementById("dockToggleText");
    dock.classList.toggle("collapsed");
    const isCollapsed = dock.classList.contains("collapsed");
    if (btnText) {
        btnText.textContent = isCollapsed ? "◫ إظهار الكوبيلوت" : "◫ إخفاء الكوبيلوت";
    }
}

function toggleSudo() {
    isSudoActive = !isSudoActive;
    const btn = document.getElementById("btnSudoToggle");
    const indicator = document.getElementById("sudoIndicator");
    const cliSymbol = document.getElementById("cliSymbol");

    if (isSudoActive) {
        btn.classList.add("active");
        indicator.textContent = "ON";
        cliSymbol.textContent = "#";
        cliSymbol.className = "prompt-symbol sudo";
        showToast("⚡ تم تفعيل صلاحيات sudo للأمر القادم");
    } else {
        btn.classList.remove("active");
        indicator.textContent = "OFF";
        cliSymbol.textContent = "$";
        cliSymbol.className = "prompt-symbol";
    }
}

/* ==========================================================================
   MANUAL CLI EXECUTION & HISTORY
   ========================================================================== */
function executeManualCommand() {
    const input = document.getElementById("termInput");
    const cmd = input.value.trim();
    if (!cmd) return;

    if (!isConnected) {
        showToast("يرجى الاتصال بالسيرفر أولاً عبر زر 🔗 السيرفر", "error");
        openConnModal();
        return;
    }

    // Add to local history
    commandHistory.push(cmd);
    historyIndex = commandHistory.length;
    input.value = "";

    const isSudo = isSudoActive;
    const user = document.getElementById("cliUser").textContent;
    const host = document.getElementById("cliHost").textContent;

    // Print command prompt
    appendTerminalCommand(user, host, cmd, isSudo, currentDisplayPath);

    document.getElementById("footerDot").className = "status-dot-idle busy";
    document.getElementById("footerStatus").textContent = `ينفذ: ${cmd}...`;

    fetch("/api/exec", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: cmd, sudo: isSudo })
    })
    .then(r => r.json())
    .then(data => {
        document.getElementById("footerDot").className = "status-dot-idle";
        document.getElementById("footerStatus").textContent = "جاهز لاستقبال الأوامر";

        if (data.display_path) {
            currentDisplayPath = data.display_path;
            const cliPath = document.getElementById("cliPath");
            if (cliPath) cliPath.textContent = currentDisplayPath;
            const termHost = document.getElementById("termTitleHost");
            if (termHost) termHost.textContent = `bash — ${data.username || user}@${data.hostname || host}:${currentDisplayPath}`;
        }

        appendTerminalOutput(data.stdout, data.stderr, data.exit_code, cmd);
    })
    .catch(err => {
        document.getElementById("footerDot").className = "status-dot-idle";
        document.getElementById("footerStatus").textContent = "خطأ في الاتصال";
        appendTerminalOutput("", `خطأ في الاتصال: ${err.message}`, 1, cmd);
    });
}

/* ==========================================================================
   AI AGENT EXECUTION & SSE STREAM
   ========================================================================== */
function setGoal(goalText) {
    const input = document.getElementById("goalInput");
    input.value = goalText;
    input.focus();
}

function runQuickDiag(goalText) {
    switchView("terminal");
    setGoal(goalText);
    setTimeout(startAgent, 150);
}

function scrollCopilotToBottom() {
    const feed = document.getElementById("copilotFeed");
    if (feed) feed.scrollTop = feed.scrollHeight;
}

function appendUserChatMessage(text) {
    const stream = document.getElementById("copilotChatStream");
    if (!stream) return;

    const timeStr = new Date().toLocaleTimeString('ar-EG', { hour: '2-digit', minute: '2-digit' });
    const div = document.createElement("div");
    div.className = "chat-msg user-msg";
    div.innerHTML = `
        <div class="chat-msg-header">
            <span class="chat-msg-author">👤 أنت</span>
            <span class="chat-msg-time">${timeStr}</span>
        </div>
        <div class="chat-msg-body">${escapeHtml(text)}</div>
    `;
    stream.appendChild(div);
    scrollCopilotToBottom();
}

function appendAssistantChatMessage(turnId) {
    const stream = document.getElementById("copilotChatStream");
    if (!stream) return;

    const div = document.createElement("div");
    div.className = "chat-msg assistant-msg";
    div.id = `assistantMsg-${turnId}`;
    div.innerHTML = `
        <div class="chat-msg-header">
            <div class="assistant-author-group">
                <span class="assistant-avatar">🤖</span>
                <span class="chat-msg-author">AI DevOps Copilot</span>
            </div>
            <span class="chat-turn-badge">#${turnId}</span>
        </div>

        <!-- Live Process Accordion (Thinking & Command Timeline) -->
        <div class="agent-process-card active" id="processCard-${turnId}">
            <div class="process-header" onclick="toggleProcessDetails(${turnId})">
                <div class="process-header-left">
                    <span class="process-pulse-dot"></span>
                    <span class="process-status-text" id="procStatus-${turnId}">يفكر ويحلل...</span>
                </div>
                <span class="process-toggle-arrow" id="procArrow-${turnId}">▲</span>
            </div>
            <div class="process-details" id="procDetails-${turnId}">
                <div class="process-thought-box" id="procThought-${turnId}">
                    <span class="proc-thought-placeholder">جاري دراسة المشكلة وفحص معطيات السيرفر...</span>
                </div>
                <div class="process-actions-list" id="procActions-${turnId}"></div>
            </div>
        </div>

        <!-- Final Assistant Response (Rendered Markdown) -->
        <div class="chat-msg-body markdown-body" id="agentAnswer-${turnId}" style="display: none;"></div>
    `;
    stream.appendChild(div);
    scrollCopilotToBottom();
}

function startAgent() {
    const goalInput = document.getElementById("goalInput");
    const goal = goalInput.value.trim();
    if (!goal) {
        goalInput.focus();
        return;
    }

    if (!isConnected) {
        showToast("يرجى الاتصال بالسيرفر أولاً عبر زر 🔗 السيرفر", "error");
        openConnModal();
        return;
    }

    // Immediately clear input field and reset height!
    goalInput.value = "";
    goalInput.style.height = "auto";
    goalInput.disabled = true;
    goalInput.placeholder = "جاري التفكير والتنفيذ...";

    isRunning = true;
    executedActionCount = 0;
    const currentTurn = sessionTurnCount;

    // Toggle UI controls
    document.getElementById("startAgentBtn").style.display = "none";
    document.getElementById("stopAgentBtn").style.display = "inline-flex";
    document.getElementById("headerStopBtn").style.display = "inline-flex";

    // Hide welcome starter card
    const welcomeCard = document.getElementById("copilotWelcome");
    if (welcomeCard) welcomeCard.style.display = "none";

    const stepBadge = document.getElementById("stepCounter");
    if (stepBadge) {
        stepBadge.style.display = "inline-block";
        stepBadge.textContent = `الخطوة 1/${currentMaxSteps}`;
    }
    const progTrack = document.getElementById("agentProgressBarTrack");
    if (progTrack) progTrack.style.display = "block";
    const progBar = document.getElementById("progressBar");
    if (progBar) progBar.style.width = "5%";

    // Status state
    const agentPill = document.getElementById("agentStatusPill");
    agentPill.className = "agent-state-pill thinking";
    agentPill.textContent = "يفكر ويحلل...";

    document.getElementById("footerStatus").textContent = "AI Copilot active...";
    document.getElementById("footerDot").className = "status-dot-idle busy";

    // Append user & assistant bubbles
    appendUserChatMessage(goal);
    appendAssistantChatMessage(currentTurn);

    // Terminal notice
    if (currentTurn === 1) {
        appendTerminalComment(`🎯 بدء جلسة جديدة: "${goal}"`);
    } else {
        appendTerminalComment(`💬 متابعة الجلسة (#${currentTurn}): "${goal}"`);
    }

    // Connect SSE
    const encodedGoal = encodeURIComponent(goal);
    const webSearchFlag = isWebSearchActive;
    eventSource = new EventSource(`/api/solve?goal=${encodedGoal}&session_id=${encodeURIComponent(currentSessionId)}&web_search=${webSearchFlag}&max_steps=${currentMaxSteps}`);

    eventSource.addEventListener("status", (e) => {
        const data = JSON.parse(e.data);
        handleAgentStatus(data.message);
    });

    eventSource.addEventListener("thinking", (e) => {
        const data = JSON.parse(e.data);
        handleAgentThinking(data.message, currentTurn);
    });

    eventSource.addEventListener("search", (e) => {
        const data = JSON.parse(e.data);
        handleAgentSearch(data, currentTurn);
    });

    eventSource.addEventListener("command", (e) => {
        const data = JSON.parse(e.data);
        handleAgentCommand(data, currentTurn);
    });

    eventSource.addEventListener("output", (e) => {
        const data = JSON.parse(e.data);
        handleAgentOutput(data, currentTurn);
    });

    eventSource.addEventListener("error", (e) => {
        try {
            const data = JSON.parse(e.data);
            appendTerminalOutput("", data.message, 1);
        } catch {
            appendTerminalOutput("", "حدث انقطاع في الاتصال بالوكيل", 1);
        }
    });

    eventSource.addEventListener("provider_switch", (e) => {
        try {
            const data = JSON.parse(e.data);
            handleProviderSwitch(data);
        } catch (err) {
            console.error("provider_switch parse error:", err);
        }
    });

    eventSource.addEventListener("done", (e) => {
        const data = JSON.parse(e.data);
        handleAgentDone(data.message, currentTurn, data.provider);
    });

    eventSource.addEventListener("end", () => {
        finishAgentSession();
    });

    eventSource.onerror = () => {
        if (isRunning) {
            appendTerminalComment("انقطع الاتصال بالوكيل الذكي.");
            finishAgentSession();
        }
    };
}

function handleAgentStatus(statusText) {
    if (statusText.includes("Step")) {
        const match = statusText.match(/Step (\d+)\/(\d+)/);
        if (match) {
            const current = parseInt(match[1]);
            const total = parseInt(match[2]);
            document.getElementById("stepCounter").textContent = `الخطوة ${current}/${total}`;
            document.getElementById("progressBar").style.width = `${(current / total) * 100}%`;
        }
    }
}

function handleAgentThinking(thoughtText, turnId) {
    const targetTurn = turnId || sessionTurnCount;
    const pill = document.getElementById("agentStatusPill");
    if (pill) {
        pill.className = "agent-state-pill thinking";
        pill.textContent = "يفكر ويحلل...";
    }

    const thoughtBox = document.getElementById(`procThought-${targetTurn}`);
    if (thoughtBox) {
        thoughtBox.textContent = thoughtText;
    }

    const shortThought = thoughtText.split("\n")[0].substring(0, 140);
    appendTerminalComment(shortThought);
    scrollCopilotToBottom();
}

function handleAgentSearch(data, turnId) {
    const targetTurn = turnId || sessionTurnCount;
    const statusText = document.getElementById(`procStatus-${targetTurn}`);
    const actionsList = document.getElementById(`procActions-${targetTurn}`);

    if (data.status === "searching") {
        if (statusText) statusText.textContent = `يبحث عن: ${data.query.substring(0, 22)}...`;
        appendTerminalComment(`🌐 [Web Search] جاري البحث في الإنترنت: "${data.query}"`);
        if (actionsList) {
            const chip = document.createElement("div");
            chip.className = "proc-action-item running";
            chip.id = `searchChip-${targetTurn}`;
            chip.innerHTML = `<span class="action-icon">🌐</span> <code>بحث: "${escapeHtml(data.query)}"</code>`;
            actionsList.appendChild(chip);
        }
    } else if (data.status === "done") {
        const chip = document.getElementById(`searchChip-${targetTurn}`);
        if (chip) {
            chip.className = "proc-action-item success";
            chip.innerHTML = `<span class="action-icon">✓</span> <code>تم العثور على ${data.count} نتائج لـ "${escapeHtml(data.query)}"</code>`;
        }
    } else if (data.status === "empty") {
        const chip = document.getElementById(`searchChip-${targetTurn}`);
        if (chip) {
            chip.className = "proc-action-item";
            chip.innerHTML = `<span class="action-icon">ℹ️</span> <code>لم يتم العثور على نتائج</code>`;
        }
    }
    scrollCopilotToBottom();
}

function handleAgentCommand(data, turnId) {
    const targetTurn = turnId || sessionTurnCount;
    const pill = document.getElementById("agentStatusPill");
    if (pill) {
        pill.className = "agent-state-pill executing";
        pill.textContent = `ينفذ: ${data.command.substring(0, 25)}...`;
    }

    const statusText = document.getElementById(`procStatus-${targetTurn}`);
    if (statusText) statusText.textContent = `ينفذ: ${data.command.substring(0, 30)}...`;

    // Add action to Copilot process card
    const actionsList = document.getElementById(`procActions-${targetTurn}`);
    if (actionsList) {
        const item = document.createElement("div");
        item.className = "proc-action-item running";
        item.id = `procAction-${executedActionCount + 1}`;
        item.innerHTML = `<span class="action-icon">⚡</span> <code>${data.sudo ? 'sudo ' : ''}${escapeHtml(data.command)}</code>`;
        actionsList.appendChild(item);
    }

    // Also send to terminal stream
    appendTerminalCommand(data.username, data.hostname, data.command, data.sudo, data.display_path || currentDisplayPath);

    executedActionCount++;
    const actionCountEl = document.getElementById("actionCount");
    if (actionCountEl) actionCountEl.textContent = executedActionCount.toString();

    scrollCopilotToBottom();
}

function handleAgentOutput(data, turnId) {
    const targetTurn = turnId || sessionTurnCount;
    if (data.display_path) {
        currentDisplayPath = data.display_path;
        const cliPath = document.getElementById("cliPath");
        if (cliPath) cliPath.textContent = currentDisplayPath;
        const termHost = document.getElementById("termTitleHost");
        if (termHost && isConnected) {
            const user = document.getElementById("cliUser").textContent;
            const host = document.getElementById("cliHost").textContent;
            termHost.textContent = `bash — ${data.username || user}@${data.hostname || host}:${currentDisplayPath}`;
        }
    }

    // Update action status in Copilot
    const actionItem = document.getElementById(`procAction-${executedActionCount}`);
    if (actionItem) {
        if (data.exit_code === 0) {
            actionItem.className = "proc-action-item success";
            const icon = actionItem.querySelector(".action-icon");
            if (icon) icon.textContent = "✓";
        } else {
            actionItem.className = "proc-action-item failed";
            const icon = actionItem.querySelector(".action-icon");
            if (icon) icon.textContent = `✕ (${data.exit_code})`;
        }
    }

    // Send output to terminal stream
    appendTerminalOutput(data.stdout, data.stderr, data.exit_code, data.command);
}

function handleAgentDone(doneMsg, turnId, provider) {
    const targetTurn = turnId || sessionTurnCount;
    if (provider) {
        syncProviderBadge(provider);
    }
    const pill = document.getElementById("agentStatusPill");
    if (pill) {
        pill.className = "agent-state-pill completed";
        pill.textContent = "تم إنجاز المهمة!";
    }
    const progBar = document.getElementById("progressBar");
    if (progBar) progBar.style.width = "100%";

    // Mark process card as completed
    const processCard = document.getElementById(`processCard-${targetTurn}`);
    if (processCard) {
        processCard.className = "agent-process-card done";
        const statusText = document.getElementById(`procStatus-${targetTurn}`);
        if (statusText) {
            const countTxt = executedActionCount > 0 ? ` (${executedActionCount} أمر منفّذ)` : "";
            statusText.textContent = `✓ اكتمل التحليل والإنجاز${countTxt}`;
        }
        // Auto-collapse details so the final answer takes spotlight
        const details = document.getElementById(`procDetails-${targetTurn}`);
        const arrow = document.getElementById(`procArrow-${targetTurn}`);
        if (details) details.style.display = "none";
        if (arrow) arrow.textContent = "▼";
    }

    // Render beautiful Markdown in Assistant Chat Bubble
    const answerEl = document.getElementById(`agentAnswer-${targetTurn}`);
    if (answerEl && doneMsg) {
        answerEl.innerHTML = renderMarkdownToHtml(doneMsg);
        answerEl.style.display = "block";
    }

    // Also render report box in terminal
    renderTerminalReportBox(doneMsg);

    sessionTurnCount++;
    const sessionPill = document.getElementById("sessionPill");
    if (sessionPill) sessionPill.textContent = `#${sessionTurnCount}`;

    showToast("🎯 تم إنجاز المهمة بنجاح!", "success");
    scrollCopilotToBottom();
}

function finishAgentSession() {
    isRunning = false;
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }

    document.getElementById("startAgentBtn").style.display = "inline-flex";
    document.getElementById("stopAgentBtn").style.display = "none";
    document.getElementById("headerStopBtn").style.display = "none";

    // Re-enable input box, clear it, set placeholder, and focus!
    const goalInput = document.getElementById("goalInput");
    if (goalInput) {
        goalInput.disabled = false;
        goalInput.value = "";
        goalInput.style.height = "auto";
        goalInput.placeholder = "اكتب ما تريد تنفيذه أو اسأل عن أي مشكلة... (Enter للإرسال)";
        goalInput.focus();
    }

    const footerDot = document.getElementById("footerDot");
    if (footerDot) footerDot.className = "status-dot-idle";
    const footerStatus = document.getElementById("footerStatus");
    if (footerStatus) footerStatus.textContent = "جاهز لاستقبال الأوامر";

    const pill = document.getElementById("agentStatusPill");
    if (pill && !pill.classList.contains("completed")) {
        pill.className = "agent-state-pill idle";
        pill.textContent = "خامل (جاهز)";
    }
}

function stopAgent() {
    if (!isRunning) return;
    fetch("/api/stop", { method: "POST" })
        .then(() => {
            appendTerminalComment("⏹️ تم إيقاف الذكاء الاصطناعي بناءً على طلبك.");
            showToast("⏹️ تم إيقاف المهمة");
            finishAgentSession();
        })
        .catch(() => finishAgentSession());
}

function resetWebSession() {
    fetch("/api/session/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: currentSessionId })
    })
    .then(r => r.json())
    .then(() => {
        sessionTurnCount = 1;
        document.getElementById("sessionPill").textContent = "#1";
        
        // Clear chat stream and restore welcome card
        const chatStream = document.getElementById("copilotChatStream");
        if (chatStream) chatStream.innerHTML = "";
        
        const welcomeCard = document.getElementById("copilotWelcome");
        if (welcomeCard) welcomeCard.style.display = "flex";
        
        const stepBadge = document.getElementById("stepCounter");
        if (stepBadge) stepBadge.style.display = "none";
        const progBar = document.getElementById("progressBar");
        if (progBar) progBar.style.width = "0%";
        
        const goalInput = document.getElementById("goalInput");
        if (goalInput) {
            goalInput.value = "";
            goalInput.disabled = false;
            goalInput.style.height = "auto";
            goalInput.placeholder = "اكتب ما تريد تنفيذه أو اسأل عن أي مشكلة... (Enter للإرسال)";
            goalInput.focus();
        }

        appendTerminalComment("🧹 تم تصفير ذاكرة المحادثة وبدء جلسة جديدة بنجاح.");
        showToast("🧹 تم بدء جلسة جديدة ومسح الذاكرة بنجاح!", "success");
    });
}

function toggleWebSearch() {
    isWebSearchActive = !isWebSearchActive;
    syncWebSearchUI();
}

function toggleWebSearchBadge(checkbox) {
    isWebSearchActive = checkbox.checked;
    syncWebSearchUI();
}

function syncWebSearchUI() {
    const btn = document.getElementById("btnToggleWebSearch");
    const text = document.getElementById("headerWebSearchText");
    const icon = document.getElementById("headerWebSearchIcon");
    const sidebarCheckbox = document.getElementById("enableWebSearch");
    const sidebarTag = document.getElementById("searchStatusTag");

    if (isWebSearchActive) {
        if (btn) btn.className = "hud-btn search-toggle active";
        if (text) text.textContent = "بحث الويب: شغال ✅";
        if (sidebarCheckbox) sidebarCheckbox.checked = true;
        if (sidebarTag) {
            sidebarTag.className = "search-status-tag-mini active";
            sidebarTag.textContent = "مُفعّل";
        }
        showToast("🌐 تم تفعيل البحث في الويب للذكاء الاصطناعي");
    } else {
        if (btn) btn.className = "hud-btn search-toggle disabled";
        if (text) text.textContent = "بحث الويب: معطل ❌";
        if (sidebarCheckbox) sidebarCheckbox.checked = false;
        if (sidebarTag) {
            sidebarTag.className = "search-status-tag-mini";
            sidebarTag.textContent = "مُعطّل";
        }
        showToast("تم تعطيل البحث في الويب");
    }
}

/* ==========================================================================
   SETTINGS & MAX STEPS CONFIGURATION
   ========================================================================== */
function initSettings() {
    // 1. Instant hydration from localStorage
    const saved = localStorage.getItem("devops_max_steps");
    if (saved) {
        currentMaxSteps = Math.max(5, Math.min(parseInt(saved) || 20, 100));
        syncMaxStepsUI();
    }

    // 2. Fetch authoritative configuration from backend
    fetch("/api/settings")
        .then(r => r.json())
        .then(data => {
            if (data && data.max_steps) {
                currentMaxSteps = Math.max(5, Math.min(parseInt(data.max_steps) || 20, 100));
                localStorage.setItem("devops_max_steps", currentMaxSteps);
                syncMaxStepsUI();
            }
        })
        .catch(() => {
            syncMaxStepsUI();
        });
}

function syncMaxStepsUI() {
    const input = document.getElementById("settingMaxSteps");
    if (input) input.value = currentMaxSteps;

    const badge = document.getElementById("settingsStepsBadge");
    if (badge) badge.textContent = `${currentMaxSteps} خطوة`;

    const infoTag = document.getElementById("infoMaxStepsTag");
    if (infoTag) {
        infoTag.textContent = `${currentMaxSteps} خطوة (${currentMaxSteps === 20 ? 'الافتراضي' : 'مخصص'})`;
    }

    // Update preset chips
    document.querySelectorAll(".preset-chip").forEach(chip => {
        const val = parseInt(chip.getAttribute("data-steps"));
        if (val === currentMaxSteps) {
            chip.classList.add("active");
        } else {
            chip.classList.remove("active");
        }
    });
}

function applyPresetSteps(steps) {
    const input = document.getElementById("settingMaxSteps");
    if (input) input.value = steps;
    saveMaxSteps(steps);
}

function saveMaxStepsFromInput() {
    const input = document.getElementById("settingMaxSteps");
    if (!input) return;
    const val = parseInt(input.value);
    if (isNaN(val) || val < 5 || val > 100) {
        showToast("⚠️ يرجى إدخال عدد خطوات بين 5 و 100", "error");
        return;
    }
    saveMaxSteps(val);
}

function saveMaxSteps(val) {
    const clamped = Math.max(5, Math.min(parseInt(val) || 20, 100));
    currentMaxSteps = clamped;
    localStorage.setItem("devops_max_steps", currentMaxSteps);
    syncMaxStepsUI();

    fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ max_steps: currentMaxSteps })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showToast(`✅ تم حفظ وتطبيق الحد الأقصى: ${currentMaxSteps} خطوة لكل مهمة`, "success");
        } else {
            showToast(data.message || "حدث خطأ أثناء حفظ الإعدادات", "error");
        }
    })
    .catch(() => {
        showToast(`✅ تم حفظ ${currentMaxSteps} خطوة محلياً`, "info");
    });
}

/* ==========================================================================
   DOCKER & METRICS DASHBOARD LOGIC
   ========================================================================== */
function refreshDashboard(showNotification = false) {
    if (!isConnected) {
        if (showNotification) showToast("السيرفر غير متصل", "error");
        return;
    }

    pollHeaderMetrics();
    fetchDockerContainers();

    if (showNotification) {
        showToast("🔄 تم تحديث بيانات المراقبة والحاويات بنجاح!", "success");
    }
}

function pollHeaderMetrics() {
    if (!isConnected) return;

    fetch("/api/metrics")
        .then(r => r.json())
        .then(data => {
            if (!data.connected) return;

            // Header mini-gauges
            if (data.ram) {
                document.getElementById("headerRamFill").style.width = `${data.ram.percent}%`;
                document.getElementById("headerRamVal").textContent = `${data.ram.percent}%`;

                // Dashboard RAM card
                document.getElementById("dashRamPercent").textContent = `${data.ram.percent}%`;
                document.getElementById("dashRamBar").style.width = `${data.ram.percent}%`;
                document.getElementById("dashRamDetails").textContent = `${data.ram.used_mb} MB / ${data.ram.total_mb} MB`;
            }

            if (data.disk) {
                document.getElementById("headerDiskFill").style.width = `${data.disk.percent}%`;
                document.getElementById("headerDiskVal").textContent = `${data.disk.percent}%`;

                // Dashboard Disk card
                document.getElementById("dashDiskPercent").textContent = `${data.disk.percent}%`;
                document.getElementById("dashDiskBar").style.width = `${data.disk.percent}%`;
                const usedGb = (data.disk.used_mb / 1024).toFixed(1);
                const totalGb = (data.disk.total_mb / 1024).toFixed(1);
                document.getElementById("dashDiskDetails").textContent = `${usedGb} GB / ${totalGb} GB`;
            }

            if (data.docker_running !== undefined) {
                document.getElementById("headerDockerVal").textContent = data.docker_running.toString();
            }

            if (data.uptime) {
                document.getElementById("dashUptime").textContent = data.uptime;
            }

            if (data.load_avg) {
                document.getElementById("dashLoadAvg").textContent = data.load_avg.join(", ");
            }
        })
        .catch(() => {});
}

function fetchDockerContainers() {
    const grid = document.getElementById("containersGrid");

    fetch("/api/docker/list")
        .then(r => r.json())
        .then(data => {
            if (!data.success || !data.containers || data.containers.length === 0) {
                grid.innerHTML = `
                    <div class="containers-loading-placeholder">
                        <span style="font-size: 32px;">🐳</span>
                        <p>لا توجد حاويات Docker منشأة أو عاملة على هذا السيرفر حالياً.</p>
                    </div>
                `;
                document.getElementById("containerCountBadge").textContent = "0 حاوية";
                document.getElementById("dashDockerCount").textContent = "0";
                document.getElementById("dashDockerRunningSummary").textContent = "0 نشطة";
                return;
            }

            const containers = data.containers;
            document.getElementById("containerCountBadge").textContent = `${containers.length} حاوية`;
            document.getElementById("dashDockerCount").textContent = containers.length.toString();

            const runningCount = containers.filter(c => c.state === "running").length;
            document.getElementById("dashDockerRunningSummary").textContent = `${runningCount} نشطة من ${containers.length}`;

            grid.innerHTML = containers.map(c => {
                const isRunning = c.state === "running";
                const cardClass = isRunning ? "running" : "exited";
                const badgeClass = isRunning ? "running" : "exited";
                const statusText = isRunning ? "🟢 Running" : "🔴 Exited";

                return `
                    <div class="container-card ${cardClass}" data-name="${escapeHtml(c.name.toLowerCase())}" data-image="${escapeHtml(c.image.toLowerCase())}">
                        <div class="cnt-header-row">
                            <span class="cnt-name">🐳 ${escapeHtml(c.name)}</span>
                            <span class="cnt-status-badge ${badgeClass}">${statusText}</span>
                        </div>
                        <div class="cnt-info-row">
                            <span class="cnt-image">📦 ${escapeHtml(c.image)}</span>
                            <span class="cnt-ports">🔌 ${escapeHtml(c.ports || "No exposed ports")}</span>
                            <span>⏱ ${escapeHtml(c.status)}</span>
                        </div>
                        <div class="cnt-actions-row">
                            <button class="cnt-btn restart" onclick="actionRestartContainer('${escapeHtml(c.name)}')">
                                🔄 <span>Restart</span>
                            </button>
                            <button class="cnt-btn logs" onclick="actionViewDockerLogs('${escapeHtml(c.name)}')">
                                📜 <span>Logs</span>
                            </button>
                            <button class="cnt-btn" onclick="actionToggleContainer('${escapeHtml(c.name)}', '${isRunning ? 'stop' : 'start'}')">
                                ${isRunning ? '⏹ Stop' : '▶️ Start'}
                            </button>
                        </div>
                    </div>
                `;
            }).join("");
        })
        .catch(err => {
            grid.innerHTML = `
                <div class="containers-loading-placeholder">
                    <p style="color: var(--rose-light);">فشل جلب بيانات Docker: ${escapeHtml(err.message)}</p>
                </div>
            `;
        });
}

function filterContainers(query) {
    const q = query.toLowerCase().trim();
    document.querySelectorAll(".container-card").forEach(card => {
        const name = card.getAttribute("data-name") || "";
        const image = card.getAttribute("data-image") || "";
        if (!q || name.includes(q) || image.includes(q)) {
            card.style.display = "flex";
        } else {
            card.style.display = "none";
        }
    });
}

function actionRestartContainer(name) {
    showToast(`🔄 جاري إعادة تشغيل الحاوية ${name}...`);
    fetch("/api/docker/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "restart", target: name })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showToast(`✅ تم إعادة تشغيل ${name} بنجاح!`, "success");
            fetchDockerContainers();
        } else {
            showToast(`فشل إعادة التشغيل: ${data.stderr}`, "error");
        }
    });
}

function actionToggleContainer(name, action) {
    showToast(`جاري ${action === 'stop' ? 'إيقاف' : 'تشغيل'} الحاوية ${name}...`);
    fetch("/api/docker/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: action, target: name })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showToast(`تم ${action === 'stop' ? 'إيقاف' : 'تشغيل'} الحاوية ${name}`, "success");
            fetchDockerContainers();
        } else {
            showToast(`فشلت العملية: ${data.stderr}`, "error");
        }
    });
}

function actionViewDockerLogs(name) {
    activeDockerContainerForLogs = name;
    document.getElementById("dockerLogsTitle").textContent = `سجل الحاوية: ${name}`;
    document.getElementById("dockerLogsContent").textContent = "جاري جلب السجلات من السيرفر...";
    document.getElementById("dockerLogsModal").classList.add("show");

    refreshCurrentDockerLogs();
}

function refreshCurrentDockerLogs() {
    if (!activeDockerContainerForLogs) return;
    fetch(`/api/docker/logs?container=${encodeURIComponent(activeDockerContainerForLogs)}`)
        .then(r => r.json())
        .then(data => {
            const pre = document.getElementById("dockerLogsContent");
            pre.textContent = data.logs || "لا توجد سجلات مسجلة.";
            pre.scrollTop = pre.scrollHeight;
        })
        .catch(err => {
            document.getElementById("dockerLogsContent").textContent = `خطأ: ${err.message}`;
        });
}

function copyDockerLogs() {
    const text = document.getElementById("dockerLogsContent").textContent;
    navigator.clipboard.writeText(text).then(() => {
        showToast("📋 تم نسخ لوجات الحاوية!", "success");
    });
}

function closeDockerLogsModal() {
    document.getElementById("dockerLogsModal").classList.remove("show");
    activeDockerContainerForLogs = "";
}

function confirmDockerPrune() {
    if (!confirm("هل أنت متأكد من رغبتك في تشغيل docker system prune لحذف كافة الحاويات والصور غير المستخدمة؟")) {
        return;
    }
    showToast("🧹 جاري تنظيف Docker...");
    fetch("/api/docker/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "prune" })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showToast("✅ تم تنظيف Docker بنجاح!", "success");
            fetchDockerContainers();
            pollHeaderMetrics();
        } else {
            showToast(`خطأ: ${data.stderr}`, "error");
        }
    });
}

/* ==========================================================================
   AUDIT LOG & HISTORY
   ========================================================================== */
function logToAudit(command, user, exitCode) {
    const item = {
        id: auditLog.length + 1,
        command: command,
        user: user,
        exitCode: exitCode,
        time: new Date().toLocaleTimeString("ar-EG")
    };
    auditLog.unshift(item); // prepend
    renderAuditTable();
    document.getElementById("auditCounterBadge").textContent = auditLog.length.toString();
}

function renderAuditTable() {
    const tbody = document.getElementById("auditTableBody");
    if (!tbody) return;

    if (auditLog.length === 0) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="7">لا توجد أوامر مسجلة في السجل بعد.</td></tr>';
        return;
    }

    tbody.innerHTML = auditLog.map(item => `
        <tr>
            <td>${item.id}</td>
            <td><span class="audit-tag-user ${item.user.includes('AI') ? 'ai' : 'manual'}">${item.user}</span></td>
            <td><span class="audit-cmd-code">${escapeHtml(item.command)}</span></td>
            <td>Bash</td>
            <td><span class="audit-exit-code ${item.exitCode === 0 ? 'success' : 'failed'}">${item.exitCode === 0 ? '✓ 0' : '✗ ' + item.exitCode}</span></td>
            <td>${item.time}</td>
            <td><button class="audit-rerun-btn" onclick="rerunAuditCommand('${escapeHtml(item.command)}')">🔄 تشغيل</button></td>
        </tr>
    `).join("");
}

function rerunAuditCommand(cmd) {
    switchView("terminal");
    const input = document.getElementById("termInput");
    input.value = cmd;
    executeManualCommand();
}

function clearAuditLog() {
    auditLog = [];
    renderAuditTable();
    document.getElementById("auditCounterBadge").textContent = "0";
    showToast("🧹 تم مسح سجل التدقيق");
}

function exportAuditLog() {
    const blob = new Blob([JSON.stringify(auditLog, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `audit_log_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast("⬇️ تم تصدير السجل بصيغة JSON");
}

/* ==========================================================================
   COMMAND PALETTE (CTRL + K)
   ========================================================================== */
function openCommandPalette() {
    const modal = document.getElementById("commandPaletteModal");
    const input = document.getElementById("paletteInput");
    modal.classList.add("show");
    input.value = "";
    filterPalette("");
    input.focus();
}

function closeCommandPalette() {
    document.getElementById("commandPaletteModal").classList.remove("show");
}

function filterPalette(query) {
    const list = document.getElementById("paletteResults");
    const q = query.toLowerCase().trim();

    const filtered = PALETTE_COMMANDS.filter(cmd => {
        return !q || cmd.title.toLowerCase().includes(q) || cmd.desc.toLowerCase().includes(q);
    });

    if (filtered.length === 0) {
        list.innerHTML = '<div style="padding: 16px; text-align: center; color: var(--text-muted);">لا توجد نتائج مطابقة</div>';
        return;
    }

    list.innerHTML = filtered.map((cmd, idx) => `
        <div class="palette-item ${idx === 0 ? 'active' : ''}" onclick="executePaletteItem(${idx})">
            <div class="palette-item-left">
                <span style="font-size: 16px;">${cmd.icon}</span>
                <div>
                    <strong style="color: #fff; display: block;">${cmd.title}</strong>
                    <span style="font-size: 11.5px; color: var(--text-muted);">${cmd.desc}</span>
                </div>
            </div>
            <span class="palette-item-shortcut">↵</span>
        </div>
    `).join("");
}

function executePaletteItem(index) {
    const q = document.getElementById("paletteInput").value.toLowerCase().trim();
    const filtered = PALETTE_COMMANDS.filter(cmd => {
        return !q || cmd.title.toLowerCase().includes(q) || cmd.desc.toLowerCase().includes(q);
    });

    if (filtered[index]) {
        closeCommandPalette();
        filtered[index].action();
    }
}

/* ==========================================================================
   SSH CONNECTION MODAL & LOGIC
   ========================================================================== */
function openConnModal() {
    document.getElementById("connModal").classList.add("show");
    document.getElementById("cfgHost").focus();
}

function closeConnModal() {
    document.getElementById("connModal").classList.remove("show");
}

function checkConnectionStatus() {
    fetch("/api/status")
        .then(r => r.json())
        .then(data => {
            updateConnectionUI(data.connected, data.username, data.hostname, data.display_path);
        })
        .catch(() => updateConnectionUI(false));
}

function performConnect() {
    const host = document.getElementById("cfgHost").value.trim();
    const port = parseInt(document.getElementById("cfgPort").value) || 22;
    const user = document.getElementById("cfgUser").value.trim();
    const pass = document.getElementById("cfgPass").value;
    const sudo = document.getElementById("cfgSudo").value;
    const remember = document.getElementById("cfgRemember").checked;

    if (!host || !user || !pass) {
        showToast("يرجى ملء جميع الحقول المطلوبة", "error");
        return;
    }

    const btn = document.getElementById("modalConnectBtn");
    btn.disabled = true;
    btn.innerHTML = "<span>⏳</span> جاري الاتصال...";

    fetch("/api/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            hostname: host,
            port: port,
            username: user,
            password: pass,
            sudo_password: sudo
        })
    })
    .then(r => r.json())
    .then(data => {
        btn.disabled = false;
        btn.innerHTML = "<span>⚡</span> اتصال الآن";

        if (data.success) {
            updateConnectionUI(true, user, host, data.display_path || "~");
            closeConnModal();
            showToast(`🟢 تم الاتصال بالسيرفر ${user}@${host} بنجاح!`, "success");

            if (remember) {
                localStorage.setItem("ssh_host", host);
                localStorage.setItem("ssh_port", port);
                localStorage.setItem("ssh_user", user);
            }

            appendTerminalComment(`تم الاتصال بالسيرفر بنجاح: ${user}@${host}:${port}`);
            refreshDashboard();
        } else {
            showToast(`فشل الاتصال: ${data.message}`, "error");
        }
    })
    .catch(err => {
        btn.disabled = false;
        btn.innerHTML = "<span>⚡</span> اتصال الآن";
        showToast(`خطأ في الخادم: ${err.message}`, "error");
    });
}

function disconnectSSH() {
    if (!isConnected) return;
    if (!confirm("هل تريد بالتأكيد قطع الاتصال بالسيرفر؟")) return;

    fetch("/api/disconnect", { method: "POST" })
        .then(() => {
            updateConnectionUI(false);
            showToast("🔴 تم قطع الاتصال بالسيرفر");
            appendTerminalComment("تم قطع الاتصال بالسيرفر.");
        });
}

function updateConnectionUI(connected, user = "", host = "", displayPath = "~") {
    isConnected = connected;
    currentDisplayPath = displayPath || "~";
    const pill = document.getElementById("connStatusPill");
    const statusText = document.getElementById("connStatusText");
    const termHost = document.getElementById("termTitleHost");
    const cliUser = document.getElementById("cliUser");
    const cliHost = document.getElementById("cliHost");
    const cliPath = document.getElementById("cliPath");
    const startBtn = document.getElementById("startAgentBtn");

    if (connected) {
        pill.className = "conn-pill connected";
        statusText.textContent = `${user}@${host}`;
        termHost.textContent = `bash — ${user}@${host}:${currentDisplayPath}`;
        cliUser.textContent = user;
        cliHost.textContent = host;
        if (cliPath) cliPath.textContent = currentDisplayPath;
        startBtn.disabled = false;
        document.getElementById("serverLatency").textContent = "3ms";
    } else {
        pill.className = "conn-pill disconnected";
        statusText.textContent = "غير متصل بالسيرفر";
        termHost.textContent = "bash — غير متصل";
        cliUser.textContent = "user";
        cliHost.textContent = "server";
        if (cliPath) cliPath.textContent = "~";
        startBtn.disabled = true;
        document.getElementById("serverLatency").textContent = "-- ms";
    }
}

function loadSavedCredentials() {
    const h = localStorage.getItem("ssh_host");
    const p = localStorage.getItem("ssh_port");
    const u = localStorage.getItem("ssh_user");
    if (h) document.getElementById("cfgHost").value = h;
    if (p) document.getElementById("cfgPort").value = p;
    if (u) document.getElementById("cfgUser").value = u;
}

/* ==========================================================================
   REPORT BOX MARKDOWN PARSER
   ========================================================================== */
function renderTerminalReportBox(text) {
    const termScreen = document.getElementById("termScreen");
    const box = document.createElement("div");
    box.className = "term-report-box";

    const parsedHtml = renderMarkdown(text);
    const boxId = `rep-${Date.now()}`;

    box.innerHTML = `
        <div class="report-box-header">
            <div class="report-box-header-title">
                <span>🎯</span>
                <span>تقرير ونتيجة إنجاز المهمة</span>
            </div>
            <div class="report-box-actions">
                <button class="report-copy-btn" onclick="copyReportContent('${boxId}')">📋 نسخ التقرير</button>
            </div>
        </div>
        <div class="report-box-content" id="${boxId}">
            ${parsedHtml}
        </div>
    `;

    termScreen.appendChild(box);
    scrollTerminalToBottom();
}

function renderMarkdownToHtml(markdownText) {
    if (!markdownText) return "";

    let html = "";
    if (typeof marked !== "undefined" && marked.parse) {
        try {
            marked.setOptions({
                gfm: true,
                breaks: true
            });
            html = marked.parse(markdownText);
        } catch (e) {
            console.error("Marked parsing error:", e);
            html = escapeHtml(markdownText).replace(/\n/g, "<br>");
        }
    } else {
        html = escapeHtml(markdownText).replace(/\n/g, "<br>");
    }

    // Enhance HTML: code blocks with language header and copy button, isolate inline code
    const temp = document.createElement("div");
    temp.innerHTML = html;

    temp.querySelectorAll("pre").forEach(pre => {
        const code = pre.querySelector("code");
        const codeText = code ? code.innerText : pre.innerText;
        let lang = "bash";
        if (code && code.className) {
            const m = code.className.match(/language-(\w+)/);
            if (m) lang = m[1];
        }

        const block = document.createElement("div");
        block.className = "chat-code-block";
        block.setAttribute("dir", "ltr");
        block.innerHTML = `
            <div class="chat-code-header">
                <span class="chat-code-lang">${escapeHtml(lang)}</span>
                <button class="chat-code-copy-btn" onclick="copyCodeSnippet(this)" title="نسخ الكود">
                    <span>📋</span> <span>نسخ الكود</span>
                </button>
            </div>
            <pre class="chat-code-pre" dir="ltr"><code>${escapeHtml(codeText)}</code></pre>
        `;
        pre.replaceWith(block);
    });

    temp.querySelectorAll("code").forEach(c => {
        if (!c.closest(".chat-code-block")) {
            c.className = "chat-inline-code";
            c.setAttribute("dir", "ltr");
        }
    });

    return temp.innerHTML;
}

function renderMarkdown(rawText) {
    return renderMarkdownToHtml(rawText);
}

function copyCodeSnippet(btn) {
    const block = btn.closest(".chat-code-block");
    if (!block) return;
    const pre = block.querySelector("pre");
    const code = pre ? pre.innerText : "";
    navigator.clipboard.writeText(code).then(() => {
        const span = btn.querySelector("span:last-child");
        const orig = span ? span.textContent : "";
        if (span) span.textContent = "تم النسخ! ✓";
        btn.classList.add("copied");
        setTimeout(() => {
            if (span) span.textContent = orig;
            btn.classList.remove("copied");
        }, 2000);
    });
}

function toggleProcessDetails(turnId) {
    const details = document.getElementById(`procDetails-${turnId}`);
    const arrow = document.getElementById(`procArrow-${turnId}`);
    if (!details) return;
    const isHidden = details.style.display === "none";
    details.style.display = isHidden ? "flex" : "none";
    if (arrow) arrow.textContent = isHidden ? "▲" : "▼";
}

function copyReportContent(boxId) {
    const el = document.getElementById(boxId);
    if (!el) return;
    navigator.clipboard.writeText(el.innerText).then(() => {
        showToast("📋 تم نسخ التقرير إلى الحافظة!", "success");
    });
}

/* ==========================================================================
   TOAST NOTIFICATION ENGINE
   ========================================================================== */
function showToast(message, type = "info", duration = 3500) {
    const container = document.getElementById("toastContainer");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = `toast-msg ${type}`;
    const icon = type === "success" ? "✅" : (type === "error" ? "❌" : "💡");
    toast.innerHTML = `<span>${icon}</span><span>${escapeHtml(message)}</span>`;

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateX(-30px)";
        toast.style.transition = "all 0.3s ease";
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

/* ==========================================================================
   EVENT LISTENERS SETUP
   ========================================================================== */
function setupEventListeners() {
    const termInput = document.getElementById("termInput");
    const termScreen = document.getElementById("termScreen");

    // Click anywhere in terminal focuses prompt input
    termScreen.addEventListener("click", () => {
        termInput.focus();
    });

    // Keyboard navigation and shortcuts for CLI input
    termInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            executeManualCommand();
        } else if (e.key === "Tab") {
            e.preventDefault();
            handleTabCompletion();
        } else if (e.key === "ArrowUp") {
            e.preventDefault();
            if (historyIndex > 0) {
                historyIndex--;
                termInput.value = commandHistory[historyIndex];
            }
        } else if (e.key === "ArrowDown") {
            e.preventDefault();
            if (historyIndex < commandHistory.length - 1) {
                historyIndex++;
                termInput.value = commandHistory[historyIndex];
            } else {
                historyIndex = commandHistory.length;
                termInput.value = "";
            }
        } else if (e.ctrlKey && e.key.toLowerCase() === "c") {
            e.preventDefault();
            appendTerminalCommand(
                document.getElementById("cliUser").textContent,
                document.getElementById("cliHost").textContent,
                termInput.value + "^C"
            );
            termInput.value = "";
        } else if (e.ctrlKey && e.key.toLowerCase() === "l") {
            e.preventDefault();
            clearTerminal();
        }
    });

    // Global Command Palette Shortcut (Ctrl + K or Cmd + K)
    document.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
            e.preventDefault();
            const modal = document.getElementById("commandPaletteModal");
            if (modal.classList.contains("show")) {
                closeCommandPalette();
            } else {
                openCommandPalette();
            }
        } else if (e.key === "Escape") {
            closeCommandPalette();
            closeConnModal();
            closeDockerLogsModal();
            closeSessionsModal();
        }
    });

    // Enter key to submit goal in Copilot, Shift+Enter for new line
    const goalInput = document.getElementById("goalInput");
    if (goalInput) {
        goalInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (!isRunning) startAgent();
            }
        });
        goalInput.addEventListener("input", () => {
            goalInput.style.height = "auto";
            goalInput.style.height = Math.min(Math.max(goalInput.scrollHeight, 44), 140) + "px";
        });
    }
}

function handleTabCompletion() {
    const input = document.getElementById("termInput");
    const current = input.value.trimStart();
    if (!current) return;

    const matches = LINUX_COMMANDS.filter(cmd => cmd.startsWith(current));
    if (matches.length === 1) {
        input.value = matches[0] + " ";
    } else if (matches.length > 1) {
        // Show matching commands in terminal
        appendTerminalComment(`اقتراحات: ${matches.slice(0, 5).join("  |  ")}`);
    }
}

function escapeHtml(text) {
    if (!text) return "";
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

/* ==========================================================================
   MULTI-PROVIDER & SESSION PERSISTENCE ENGINE ⚡
   ========================================================================== */

let allLoadedSessions = [];

function syncProviderBadge(providerName, modelName = "") {
    const badge = document.getElementById("activeProviderBadge");
    if (!badge) return;

    const p = (providerName || "gemini").toLowerCase();
    badge.classList.remove("groq-active", "openrouter-active");

    if (p === "groq") {
        badge.classList.add("groq-active");
        badge.textContent = `⚡ Groq (${modelName || 'Qwen 3.8'})`;
        badge.title = "المزود النشط: Groq (سريع وبدون قيود)";
    } else if (p === "openrouter" || p === "deepseek") {
        badge.classList.add("openrouter-active");
        badge.textContent = `🌐 DeepSeek/OpenRouter`;
        badge.title = "المزود النشط: OpenRouter / DeepSeek";
    } else {
        badge.textContent = "🟢 Gemini 3.5";
        badge.title = "المزود النشط: Google Gemini 3.5 Flash (الأساسي)";
    }
}

function handleProviderSwitch(data) {
    const toProvider = (data.to || "").toLowerCase();
    syncProviderBadge(toProvider);

    const providerNames = {
        "gemini": "Google Gemini 3.5",
        "groq": "Groq ⚡",
        "openrouter": "OpenRouter / DeepSeek 🌐"
    };
    const providerArabic = providerNames[toProvider] || toProvider;

    const alertMsg = data.message || `⚠️ تم تجاوز كوتة الموديل (429)! تم التحويل تلقائياً وبسلاسة إلى ${providerArabic} لمتابعة المهمة.`;
    showToast(alertMsg, "info", 6500);
    appendTerminalComment(`⚡ [التحويل التلقائي]: تم المتابعة عبر مزود بديل: ${providerArabic}`);
}

function initSessionHistory() {
    const savedSession = localStorage.getItem("devops_current_session");
    if (savedSession) {
        currentSessionId = savedSession;
    }
    loadCurrentSessionHistory(currentSessionId, false);
}

function loadCurrentSessionHistory(sessionId, notify = false) {
    fetch(`/api/session/${encodeURIComponent(sessionId)}`)
        .then(r => r.json())
        .then(data => {
            if (data.success && data.session) {
                currentSessionId = data.session.session_id;
                localStorage.setItem("devops_current_session", currentSessionId);
                restoreSessionChatHistory(data.session);
                if (data.session.active_provider) {
                    syncProviderBadge(data.session.active_provider);
                }
                if (notify) {
                    showToast(`📂 تم فتح الجلسة: ${data.session.title || currentSessionId}`, "success");
                }
            }
        })
        .catch(err => {
            console.warn("Could not load session history:", err);
        });
}

function restoreSessionChatHistory(sessionData) {
    const stream = document.getElementById("copilotChatStream");
    const welcome = document.getElementById("copilotWelcome");
    if (!stream) return;

    stream.innerHTML = "";

    const turns = sessionData.turns || [];
    if (turns.length === 0) {
        if (welcome) welcome.style.display = "flex";
        sessionTurnCount = 1;
        const pill = document.getElementById("sessionPill");
        if (pill) pill.textContent = "#1";
        return;
    }

    if (welcome) welcome.style.display = "none";
    sessionTurnCount = turns.length + 1;
    const sessionPill = document.getElementById("sessionPill");
    if (sessionPill) sessionPill.textContent = `#${sessionTurnCount}`;

    turns.forEach((t) => {
        const turnNum = t.turn || 1;
        const timeStr = t.timestamp ? new Date(t.timestamp).toLocaleTimeString('ar-EG', { hour: '2-digit', minute: '2-digit' }) : "";

        // 1. User Message Bubble
        const userDiv = document.createElement("div");
        userDiv.className = "chat-msg user-msg";
        userDiv.innerHTML = `
            <div class="chat-msg-header">
                <span class="chat-msg-author">👤 أنت</span>
                <span class="chat-msg-time">${timeStr}</span>
            </div>
            <div class="chat-msg-body">${escapeHtml(t.user_prompt || "")}</div>
        `;
        stream.appendChild(userDiv);

        // 2. Assistant Message Bubble
        const asstDiv = document.createElement("div");
        asstDiv.className = "chat-msg assistant-msg";
        asstDiv.id = `assistantMsg-${turnNum}`;

        const actionsHtml = (t.actions || []).map((act) => {
            const isSuccess = !act.result || (!act.result.includes("Error") && !act.result.includes("failed"));
            const cmd = act.args && act.args.command ? act.args.command : (act.tool || "action");
            return `
                <div class="proc-action-item ${isSuccess ? 'success' : 'failed'}">
                    <span class="action-icon">${isSuccess ? '✓' : '✕'}</span>
                    <code>${escapeHtml(cmd)}</code>
                </div>
            `;
        }).join("");

        const thoughtText = (t.thoughts && t.thoughts.length > 0) ? t.thoughts.join("\n") : "تم تحليل وتنفيذ المتطلبات بنجاح.";
        const actionsCount = (t.actions || []).length;
        const countTxt = actionsCount > 0 ? ` (${actionsCount} أمر منفّذ)` : "";

        asstDiv.innerHTML = `
            <div class="chat-msg-header">
                <div class="assistant-author-group">
                    <span class="assistant-avatar">🤖</span>
                    <span class="chat-msg-author">AI DevOps Copilot</span>
                </div>
                <span class="chat-turn-badge">#${turnNum}</span>
            </div>

            <!-- Historical Process Accordion -->
            <div class="agent-process-card done" id="processCard-${turnNum}">
                <div class="process-header" onclick="toggleProcessDetails(${turnNum})">
                    <div class="process-header-left">
                        <span class="process-pulse-dot" style="animation: none; background: var(--emerald);"></span>
                        <span class="process-status-text" id="procStatus-${turnNum}">✓ اكتمل التحليل والإنجاز${countTxt}</span>
                    </div>
                    <span class="process-toggle-arrow" id="procArrow-${turnNum}">▼</span>
                </div>
                <div class="process-details" id="procDetails-${turnNum}" style="display: none;">
                    <div class="process-thought-box" id="procThought-${turnNum}">${escapeHtml(thoughtText)}</div>
                    <div class="process-actions-list" id="procActions-${turnNum}">
                        ${actionsHtml}
                    </div>
                </div>
            </div>

            <!-- Rendered Markdown Response -->
            <div class="chat-msg-body markdown-body" id="agentAnswer-${turnNum}">
                ${renderMarkdownToHtml(t.assistant_response || "")}
            </div>
        `;
        stream.appendChild(asstDiv);
    });

    scrollCopilotToBottom();
}

function openSessionsModal() {
    const modal = document.getElementById("sessionsModal");
    if (modal) modal.classList.add("show");
    const input = document.getElementById("sessionSearchInput");
    if (input) input.value = "";
    fetchSessionsList();
}

function closeSessionsModal() {
    const modal = document.getElementById("sessionsModal");
    if (modal) modal.classList.remove("show");
}

function fetchSessionsList() {
    const container = document.getElementById("sessionsListContainer");
    if (container) {
        container.innerHTML = '<div class="sessions-empty-state">جاري تحميل الجلسات...</div>';
    }

    fetch("/api/sessions")
        .then(r => r.json())
        .then(data => {
            if (data.success && data.sessions) {
                allLoadedSessions = data.sessions;
                renderSessionsList(allLoadedSessions);
            } else {
                if (container) container.innerHTML = '<div class="sessions-empty-state">لا توجد جلسات محفوظة بعد</div>';
            }
        })
        .catch(err => {
            if (container) container.innerHTML = `<div class="sessions-empty-state">خطأ في جلب الجلسات: ${escapeHtml(err.message)}</div>`;
        });
}

function filterSessionsList(query) {
    const q = (query || "").toLowerCase().trim();
    if (!q) {
        renderSessionsList(allLoadedSessions);
        return;
    }
    const filtered = allLoadedSessions.filter(s => {
        const title = (s.title || "").toLowerCase();
        const id = (s.session_id || "").toLowerCase();
        return title.includes(q) || id.includes(q);
    });
    renderSessionsList(filtered);
}

function renderSessionsList(sessions) {
    const container = document.getElementById("sessionsListContainer");
    if (!container) return;

    if (!sessions || sessions.length === 0) {
        container.innerHTML = `
            <div class="sessions-empty-state">
                <span style="font-size: 28px; display: block; margin-bottom: 6px;">📂</span>
                لا توجد جلسات مطابقة.<br>
                <small style="color: var(--text-muted);">انقر على "➕ جلسة جديدة" لبدء محادثة منفصلة.</small>
            </div>
        `;
        return;
    }

    container.innerHTML = sessions.map(s => {
        const isActive = s.session_id === currentSessionId;
        const activeClass = isActive ? "active" : "";
        const activeTag = isActive ? '<span class="session-tag-active">النشطة حالياً</span>' : '';
        const title = escapeHtml(s.title || `جلسة #${s.session_id.split('_').pop()}`);
        const turnsCount = s.turn_count || 0;
        const actionsCount = s.action_count || 0;
        const dateStr = s.updated_at ? new Date(s.updated_at).toLocaleString('ar-EG', {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
        }) : "";

        return `
            <div class="session-item-card ${activeClass}" onclick="switchSession('${escapeHtml(s.session_id)}')">
                <div class="session-card-main">
                    <div class="session-card-title-row">
                        <span style="font-size: 14px;">💬</span>
                        <span class="session-card-title">${title}</span>
                        ${activeTag}
                    </div>
                    <div class="session-card-meta">
                        <span>📊 ${turnsCount} جولة</span>
                        <span>⚡ ${actionsCount} أمر</span>
                        ${dateStr ? `<span>🕒 ${dateStr}</span>` : ''}
                    </div>
                </div>
                <div class="session-actions">
                    <button class="btn-session-action delete" onclick="deleteSessionPrompt('${escapeHtml(s.session_id)}', event)" title="حذف هذه الجلسة">
                        🗑️
                    </button>
                </div>
            </div>
        `;
    }).join("");
}

function switchSession(sessionId) {
    if (isRunning) {
        showToast("لا يمكن تغيير الجلسة أثناء تنفيذ مهمة بواسطة الذكاء الاصطناعي", "error");
        return;
    }

    currentSessionId = sessionId;
    localStorage.setItem("devops_current_session", currentSessionId);
    loadCurrentSessionHistory(sessionId, true);
    closeSessionsModal();
}

function createNewSessionPrompt() {
    if (isRunning) {
        showToast("الوكيل الذكي قيد العمل حالياً، انتظر حتى يكتمل", "error");
        return;
    }

    const title = prompt("أدخل اسماً أو عنواناً للجلسة الجديدة (أو اضغط موافق لتوليده تلقائياً):");
    if (title === null) return;

    fetch("/api/session/new", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title.trim() || undefined })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success && data.session) {
            currentSessionId = data.session.session_id;
            localStorage.setItem("devops_current_session", currentSessionId);
            restoreSessionChatHistory(data.session);
            closeSessionsModal();
            showToast("✨ تم إنشاء جلسة جديدة وحفظها بنجاح!", "success");
            appendTerminalComment(`✨ تم فتح جلسة عمل جديدة (#${currentSessionId})`);
        } else {
            showToast("تعذر إنشاء الجلسة", "error");
        }
    })
    .catch(err => {
        showToast(`خطأ: ${err.message}`, "error");
    });
}

function deleteSessionPrompt(sessionId, event) {
    if (event) event.stopPropagation();

    if (isRunning && sessionId === currentSessionId) {
        showToast("لا يمكن حذف الجلسة النشطة أثناء قيد التشغيل", "error");
        return;
    }

    if (!confirm("هل أنت متأكد من رغبتك في حذف هذه الجلسة وسجل محادثاتها نهائياً من السيرفر؟")) {
        return;
    }

    fetch(`/api/session/${encodeURIComponent(sessionId)}`, {
        method: "DELETE"
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            showToast("🗑️ تم حذف الجلسة بنجاح", "success");
            if (sessionId === currentSessionId) {
                currentSessionId = "web_default";
                localStorage.setItem("devops_current_session", "web_default");
                loadCurrentSessionHistory("web_default", false);
            }
            fetchSessionsList();
        } else {
            showToast("تعذر حذف الجلسة", "error");
        }
    })
    .catch(err => {
        showToast(`خطأ: ${err.message}`, "error");
    });
}
