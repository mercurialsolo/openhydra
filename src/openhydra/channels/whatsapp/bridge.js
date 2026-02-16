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

function emit(obj) {
    process.stdout.write(JSON.stringify(obj) + '\n');
}

async function main() {
    const { state, saveCreds } = await useMultiFileAuthState(authDir);

    const sock = makeWASocket({
        auth: state,
        printQRInTerminal: false,
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            emit({ type: 'qr', data: qr });
        }

        if (connection === 'open') {
            emit({ type: 'connected' });
        }

        if (connection === 'close') {
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
            emit({
                type: 'disconnected',
                reason: lastDisconnect?.error?.message || 'unknown',
                shouldReconnect,
            });
            if (!shouldReconnect) {
                process.exit(0);
            }
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

    // Read commands from stdin
    const rl = readline.createInterface({ input: process.stdin });
    rl.on('line', async (line) => {
        try {
            const cmd = JSON.parse(line);
            if (cmd.type === 'send' && cmd.to && cmd.text) {
                const jid = cmd.to.replace(/^\+/, '') + '@s.whatsapp.net';
                await sock.sendMessage(jid, { text: cmd.text });
            }
        } catch (e) {
            // Ignore invalid JSON
        }
    });
}

main().catch((err) => {
    emit({ type: 'error', message: err.message });
    process.exit(1);
});
