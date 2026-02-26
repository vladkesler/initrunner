/* InitRunner dashboard — minimal vanilla JS helpers */

/** Auto-scroll an element to the bottom */
function scrollToBottom(el) {
    if (el) el.scrollTop = el.scrollHeight;
}

/** Format a duration in ms to human-readable */
function formatDuration(ms) {
    if (ms < 1000) return ms + "ms";
    return (ms / 1000).toFixed(1) + "s";
}

/** Format a number with commas */
function formatNumber(n) {
    return n.toLocaleString();
}

/** Escape HTML to prevent XSS */
function escapeHtml(text) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
}

/** Get the assistant avatar HTML from the hidden template, if present */
function getAssistantAvatarHtml() {
    var tpl = document.getElementById("assistant-avatar");
    return tpl ? tpl.innerHTML : "";
}

/** Generate a random session ID (16 hex chars) */
function generateSessionId() {
    var arr = new Uint8Array(8);
    crypto.getRandomValues(arr);
    var hex = "";
    for (var i = 0; i < arr.length; i++) {
        hex += arr[i].toString(16).padStart(2, "0");
    }
    return hex;
}

/** Create a chat message bubble element */
function createMessageBubble(content, role) {
    var wrapper = document.createElement("div");
    wrapper.className = "chat " + (role === "user" ? "chat-end" : "chat-start");
    wrapper.setAttribute("data-role", role);
    if (role !== "user") {
        var avatarHtml = getAssistantAvatarHtml();
        if (avatarHtml) {
            var avatarDiv = document.createElement("div");
            avatarDiv.className = "chat-image";
            avatarDiv.innerHTML = avatarHtml;
            wrapper.appendChild(avatarDiv);
        }
    }
    var bubble = document.createElement("div");
    bubble.className = "chat-bubble " + (role === "user" ? "chat-bubble-primary" : "chat-bubble-neutral");
    bubble.textContent = content;
    wrapper.appendChild(bubble);
    return wrapper;
}

/** POST a prompt to a sense endpoint and invoke callback with the JSON result. */
function senseRequest(url, prompt, callback) {
    fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({prompt: prompt})
    })
    .then(function(r) { return r.json(); })
    .then(callback);
}

/** Set up chat streaming via EventSource. Returns an API object. */
function initChatStream(formId, messagesId, streamUrl, options) {
    var form = document.getElementById(formId);
    var messages = document.getElementById(messagesId);
    if (!form || !messages) return { resetSession: function(){}, exportConversation: function(){}, loadSession: function(){}, restoreSession: function(){}, getSessionId: function(){ return ""; } };

    options = options || {};
    var roleId = options.roleId || "";
    var sessionTokenBudget = options.sessionTokenBudget || null;
    var uploadUrl = options.uploadUrl || "";

    // Attachment state
    var pendingAttachmentIds = [];  // IDs from uploaded files
    var pendingAttachmentUrls = []; // URL strings
    var pendingAttachmentNames = []; // display names for chips

    // Session ID management — persist per role in sessionStorage
    var storageKey = "initrunner_session_" + roleId;
    var sessionId = sessionStorage.getItem(storageKey) || generateSessionId();
    sessionStorage.setItem(storageKey, sessionId);

    // Cumulative token tracking
    var cumulativeTokensIn = 0;
    var cumulativeTokensOut = 0;
    var cumulativeTotal = 0;

    function updateStatusBar(stats) {
        if (stats && stats.tokens_in !== undefined) {
            cumulativeTokensIn += stats.tokens_in;
            cumulativeTokensOut += stats.tokens_out;
            cumulativeTotal += stats.total_tokens;
        }

        var elIn = document.getElementById("status-tokens-in");
        var elOut = document.getElementById("status-tokens-out");
        if (elIn) elIn.textContent = formatNumber(cumulativeTokensIn);
        if (elOut) elOut.textContent = formatNumber(cumulativeTokensOut);

        if (sessionTokenBudget) {
            var elUsed = document.getElementById("status-budget-used");
            var elPct = document.getElementById("status-budget-pct");
            var elBudget = document.getElementById("status-budget");
            if (elUsed) elUsed.textContent = formatNumber(cumulativeTotal);
            if (elPct) {
                var pct = Math.round(cumulativeTotal / sessionTokenBudget * 100);
                elPct.textContent = pct;
                if (elBudget) {
                    elBudget.className = pct >= 100 ? "text-error" : pct >= 80 ? "text-warning" : "";
                }
            }
        }
    }

    function renderAttachmentChips() {
        var container = document.getElementById("attachment-chips");
        if (!container) return;
        container.innerHTML = "";
        var hasItems = pendingAttachmentNames.length > 0;
        container.style.display = hasItems ? "flex" : "none";
        pendingAttachmentNames.forEach(function(name, idx) {
            var chip = document.createElement("div");
            chip.className = "badge badge-outline gap-1";
            chip.innerHTML = escapeHtml(name) + ' <button class="btn btn-xs btn-ghost btn-circle">&times;</button>';
            chip.querySelector("button").addEventListener("click", function() {
                pendingAttachmentIds.splice(idx, 1);
                pendingAttachmentUrls.splice(idx, 1);
                pendingAttachmentNames.splice(idx, 1);
                renderAttachmentChips();
            });
            container.appendChild(chip);
        });
    }

    // File upload handler
    var fileInput = document.getElementById("file-upload");
    var attachBtn = document.getElementById("btn-attach-file");
    if (attachBtn && fileInput && uploadUrl) {
        attachBtn.addEventListener("click", function() { fileInput.click(); });
        fileInput.addEventListener("change", function() {
            if (!fileInput.files || !fileInput.files.length) return;
            var formData = new FormData();
            for (var i = 0; i < fileInput.files.length; i++) {
                formData.append("file_" + i, fileInput.files[i]);
            }
            fetch(uploadUrl, { method: "POST", body: formData })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.error) { alert(data.error); return; }
                    var ids = data.attachment_ids || [];
                    for (var j = 0; j < ids.length; j++) {
                        pendingAttachmentIds.push(ids[j]);
                        pendingAttachmentUrls.push(""); // not a URL
                        pendingAttachmentNames.push(fileInput.files[j] ? fileInput.files[j].name : "file");
                    }
                    renderAttachmentChips();
                });
            fileInput.value = "";
        });
    }

    form.addEventListener("submit", function(e) {
        e.preventDefault();
        var input = form.querySelector("textarea, input[name=prompt]");
        var prompt = input.value.trim();
        if (!prompt) return;

        // Append user message
        messages.appendChild(createMessageBubble(prompt, "user"));
        input.value = "";
        scrollToBottom(messages);

        // Create assistant container
        var assistantWrapper = document.createElement("div");
        assistantWrapper.className = "chat chat-start";
        assistantWrapper.setAttribute("data-role", "assistant");
        var avatarHtml = getAssistantAvatarHtml();
        if (avatarHtml) {
            var avatarDiv = document.createElement("div");
            avatarDiv.className = "chat-image";
            avatarDiv.innerHTML = avatarHtml;
            assistantWrapper.appendChild(avatarDiv);
        }
        var assistantBubble = document.createElement("div");
        assistantBubble.className = "chat-bubble chat-bubble-neutral streaming-indicator";
        assistantBubble.textContent = "";
        assistantWrapper.appendChild(assistantBubble);
        messages.appendChild(assistantWrapper);
        scrollToBottom(messages);

        // Disable input while streaming
        input.disabled = true;
        var submitBtn = form.querySelector("button[type=submit]");
        if (submitBtn) submitBtn.disabled = true;

        var url = streamUrl + "?prompt=" + encodeURIComponent(prompt) + "&session_id=" + encodeURIComponent(sessionId);
        // Append attachment params if present
        var aidList = pendingAttachmentIds.filter(function(id) { return id; });
        var aurlList = pendingAttachmentUrls.filter(function(u) { return u; });
        if (aidList.length) url += "&attachment_ids=" + encodeURIComponent(aidList.join(","));
        if (aurlList.length) url += "&attachment_urls=" + encodeURIComponent(aurlList.join(","));
        // Show attachment indicator in user message if present
        if (pendingAttachmentNames.length) {
            var indicator = document.createElement("div");
            indicator.className = "text-xs text-base-content/50 mt-1";
            indicator.textContent = "[" + pendingAttachmentNames.length + " attachment(s)]";
            var lastChat = messages.lastElementChild;
            if (lastChat) lastChat.appendChild(indicator);
        }
        // Clear pending attachments
        pendingAttachmentIds = [];
        pendingAttachmentUrls = [];
        pendingAttachmentNames = [];
        renderAttachmentChips();

        var evtSource = new EventSource(url);

        var thinkingTimer = setTimeout(function() {
            if (!assistantBubble.textContent) {
                assistantBubble.setAttribute("data-thinking", "true");
                assistantBubble.textContent = "Working...";
            }
        }, 3000);

        evtSource.onmessage = function(event) {
            if (assistantBubble.getAttribute("data-thinking")) {
                assistantBubble.textContent = "";
                assistantBubble.removeAttribute("data-thinking");
            }
            clearTimeout(thinkingTimer);
            assistantBubble.textContent += event.data;
            scrollToBottom(messages);
        };

        evtSource.addEventListener("close", function(event) {
            evtSource.close();
            clearTimeout(thinkingTimer);
            assistantBubble.classList.remove("streaming-indicator");
            // Re-enable input
            input.disabled = false;
            if (submitBtn) submitBtn.disabled = false;
            input.focus();
            // Show stats if provided
            try {
                var stats = JSON.parse(event.data);
                if (stats && stats.session_id) {
                    sessionId = stats.session_id;
                    sessionStorage.setItem(storageKey, sessionId);
                }
                if (stats && stats.error) {
                    assistantBubble.textContent = "Error: " + stats.error;
                    assistantBubble.classList.add("chat-bubble-error");
                } else if (stats) {
                    updateStatusBar(stats);
                    if (stats.total_tokens) {
                        var info = document.createElement("div");
                        info.className = "text-xs text-base-content/50 ml-12 mt-1";
                        info.textContent = formatNumber(stats.total_tokens) + " tokens \u00B7 " + formatDuration(stats.duration_ms);
                        messages.appendChild(info);
                        scrollToBottom(messages);
                    }
                }
            } catch (e) {}
        });

        evtSource.addEventListener("error", function(event) {
            evtSource.close();
            clearTimeout(thinkingTimer);
            assistantBubble.classList.remove("streaming-indicator");
            assistantBubble.classList.add("chat-bubble-error");
            if (!assistantBubble.textContent) {
                assistantBubble.textContent = "Error: connection failed";
            }
            input.disabled = false;
            if (submitBtn) submitBtn.disabled = false;
        });
    });

    // API object
    return {
        getSessionId: function() { return sessionId; },

        resetSession: function() {
            sessionId = generateSessionId();
            sessionStorage.setItem(storageKey, sessionId);
            messages.innerHTML = "";
            cumulativeTokensIn = 0;
            cumulativeTokensOut = 0;
            cumulativeTotal = 0;
            updateStatusBar(null);
        },

        loadSession: function(newSessionId, messageList) {
            sessionId = newSessionId;
            sessionStorage.setItem(storageKey, sessionId);
            messages.innerHTML = "";
            cumulativeTokensIn = 0;
            cumulativeTokensOut = 0;
            cumulativeTotal = 0;
            updateStatusBar(null);
            messageList.forEach(function(msg) {
                messages.appendChild(createMessageBubble(msg.content, msg.role));
            });
            scrollToBottom(messages);
        },

        restoreSession: function() {
            if (!sessionId || !roleId) return;
            fetch("/roles/" + roleId + "/chat/sessions/" + sessionId + "/messages")
                .then(function(r) {
                    if (!r.ok) return null;
                    return r.json();
                })
                .then(function(msgs) {
                    if (msgs && msgs.length) {
                        msgs.forEach(function(msg) {
                            messages.appendChild(createMessageBubble(msg.content, msg.role));
                        });
                        scrollToBottom(messages);
                    }
                })
                .catch(function() {}); // silently ignore if no session found
        },

        exportConversation: function(roleName) {
            var chatBubbles = messages.querySelectorAll(".chat");
            if (!chatBubbles.length) return;
            var lines = ["# Chat Export \u2014 " + (roleName || "Agent"), ""];
            chatBubbles.forEach(function(el) {
                var role = el.getAttribute("data-role");
                var bubble = el.querySelector(".chat-bubble");
                if (!bubble) return;
                var content = bubble.textContent || "";
                if (role === "user") {
                    lines.push("**You:** " + content);
                } else {
                    lines.push("**Agent:** " + content);
                }
                lines.push("");
            });
            var md = lines.join("\n");
            var blob = new Blob([md], { type: "text/markdown" });
            var url = URL.createObjectURL(blob);
            var a = document.createElement("a");
            a.href = url;
            a.download = (roleName || "chat") + "-export.md";
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }
    };
}
