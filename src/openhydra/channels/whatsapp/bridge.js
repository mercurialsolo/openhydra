#!/usr/bin/env node
/**
 * Baileys WhatsApp Web bridge — JSON-L over stdin/stdout.
 *
 * Reads from stdin:  {"type":"send","to":"+1234","text":"hello"}
 * Writes to stdout:  {"type":"message","from":"+1234","text":"hi"}
 *                    {"type":"qr","data":"..."}
 *                    {"type":"connected"}
 *                    {"type":"disconnected","reason":"..."}
 *
 * Auth state persisted to BAILEYS_AUTH_DIR (default: ./whatsapp_auth)
 */

const readline = require('readline');

let makeWASocket, useMultiFileAuthState, DisconnectReason;

try {
    const baileys = require('@whiskeysockets/baileys');
    makeWASocket = baileys.default || baileys.makeWASocket;
    useMultiFileAuthState = baileys.useMultiFileAuthState;
    DisconnectReason = baileys.DisconnectReason;
} catch (e) {
    console.error(JSON.stringify({
        type: 'error',
        message: 'Missing @whiskeysockets/baileys. Run: npm install @whiskeysockets/baileys'
    }));
    process.exit(1);
}

const authDir = process.env.BAILEYS_AUTH_DIR || './whatsapp_auth';
const reconnectDelayMs = parseInt(process.env.BAILEYS_RECONNECT_DELAY_MS || '2000', 10);
const maxReconnectDelayMs = parseInt(
    process.env.BAILEYS_MAX_RECONNECT_DELAY_MS || '30000',
    10
);
const silentLogger = {
    level: 'silent',
    child() { return this; },
    trace() {},
    debug() {},
    info() {},
    warn() {},
    error() {},
    fatal() {},
};

let sock = null;
let reconnectTimer = null;
let shuttingDown = false;
let connecting = false;
let saveCredsFn = null;
let authState = null;
let reconnectAttempt = 0;

function emit(obj) {
    process.stdout.write(JSON.stringify(obj) + '\n');
}

function clearReconnectTimer() {
    if (!reconnectTimer) return;
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
}

function disconnectCode(statusCode) {
    if (typeof statusCode === 'number') return statusCode;
    const parsed = Number(statusCode);
    return Number.isFinite(parsed) ? parsed : null;
}

function shouldReconnectForStatus(statusCode) {
    if (statusCode === null) {
        return true;
    }
    // These generally need manual intervention (re-auth or removing duplicate clients).
    const nonRecoverable = new Set([
        DisconnectReason.loggedOut,
        DisconnectReason.badSession,
        DisconnectReason.connectionReplaced,
        DisconnectReason.multideviceMismatch,
        DisconnectReason.forbidden,
    ]);
    return !nonRecoverable.has(statusCode);
}

function scheduleReconnect(statusCode) {
    if (shuttingDown || reconnectTimer || connecting) return;
    reconnectAttempt += 1;
    const delay = Math.min(
        reconnectDelayMs * Math.max(1, reconnectAttempt),
        maxReconnectDelayMs
    );
    emit({ type: 'reconnecting', attempt: reconnectAttempt, delayMs: delay, statusCode });
    reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        void startSocket();
    }, delay);
}

async function ensureAuthState() {
    if (authState && saveCredsFn) {
        return;
    }
    const auth = await useMultiFileAuthState(authDir);
    authState = auth.state;
    saveCredsFn = auth.saveCreds;
}

async function startSocket() {
    if (shuttingDown || connecting) {
        return;
    }
    connecting = true;

    try {
        await ensureAuthState();
        if (sock) {
            try {
                sock.ev.removeAllListeners('connection.update');
                sock.ev.removeAllListeners('messages.upsert');
                sock.ev.removeAllListeners('creds.update');
                sock.end?.(new Error('restarting socket'));
            } catch (_) {
                // Best effort cleanup before creating the next socket.
            } finally {
                sock = null;
            }
        }

        sock = makeWASocket({
            auth: authState,
            printQRInTerminal: false,
            logger: silentLogger,
        });

        sock.ev.on('creds.update', saveCredsFn);

        sock.ev.on('connection.update', (update) => {
            const { connection, lastDisconnect, qr } = update;

            if (qr) {
                emit({ type: 'qr', data: qr });
            }

            if (connection === 'open') {
                clearReconnectTimer();
                reconnectAttempt = 0;
                emit({ type: 'connected' });
            }

            if (connection === 'close') {
                const statusCode = disconnectCode(lastDisconnect?.error?.output?.statusCode);
                const shouldReconnect = shouldReconnectForStatus(statusCode);
                const disconnectReason =
                    statusCode !== null ? DisconnectReason[statusCode] : undefined;
                emit({
                    type: 'disconnected',
                    reason: lastDisconnect?.error?.message || 'unknown',
                    statusCode,
                    disconnectReason,
                    shouldReconnect,
                });

                sock = null;
                if (!shouldReconnect) {
                    // Credentials are invalid/logged out. Let OpenHydra restart explicitly.
                    process.exit(0);
                    return;
                }
                scheduleReconnect(statusCode);
            }
        });

        sock.ev.on('messages.upsert', ({ messages, type }) => {
            if (type !== 'notify') return;
            for (const msg of messages) {
                if (!msg.message || msg.key.fromMe) continue;
                const text =
                    msg.message.conversation ||
                    msg.message.extendedTextMessage?.text ||
                    '';
                if (!text) continue;
                const from = msg.key.remoteJid?.replace('@s.whatsapp.net', '') || '';
                if (from) {
                    emit({ type: 'message', from, text });
                }
            }
        });
    } catch (err) {
        emit({ type: 'error', message: err?.message || String(err) });
        scheduleReconnect(null);
    } finally {
        connecting = false;
    }
}

async function main() {
    await startSocket();

    // Read commands from stdin
    const rl = readline.createInterface({ input: process.stdin });
    rl.on('line', async (line) => {
        try {
            const cmd = JSON.parse(line);
            if (cmd.type === 'send' && cmd.to && cmd.text) {
                if (!sock) {
                    emit({ type: 'error', message: 'Bridge not connected yet' });
                    return;
                }
                const jid = cmd.to.replace(/^\+/, '') + '@s.whatsapp.net';
                await sock.sendMessage(jid, { text: cmd.text });
            }
        } catch (e) {
            emit({ type: 'error', message: e?.message || String(e) });
            // Ignore invalid JSON
        }
    });

    const shutdown = () => {
        shuttingDown = true;
        clearReconnectTimer();
        rl.close();
    };
    process.on('SIGINT', shutdown);
    process.on('SIGTERM', shutdown);
}

main().catch((err) => {
    emit({ type: 'error', message: err.message });
    process.exit(1);
});
