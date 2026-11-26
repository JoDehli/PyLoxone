# Loxone Miniserver – Connection Flow (Connect)

Source: [Communicating with the Miniserver](https://www.loxone.com/wp-content/uploads/datasheets/CommunicatingWithMiniserver.pdf) (Loxone) and `pyloxone_api` (`src/pyloxone_api/connection.py` im Paket-Repo).

## Quick overview

1. **HTTP bootstrap (`open()`)**: check reachability, load the structure file + public key, RSA-encrypt the AES session key, open the WebSocket.
2. **WebSocket authentication (`start_listening()` / `_websocket_event()`)**: key exchange → `getkey2` → token auth or token acquisition → enable updates.
3. **Operation**: receive loop, keepalive (30 s), token refresh, encrypted/secured commands.
4. **Supervision (`run()`)**: reconnect/backoff, escalation on auth errors.

## Phase 0 – Preparation (constructor)

- Parse host/port/scheme, normalize the URL.
- Generate the AES-256-CBC key (`_aes_key`, 32 bytes) and IV (`_iv`, 16 bytes) per instance.
- Take over an existing token cache if present.
- Create the message queue, salt state and visual-hash state.

## Phase 1 – HTTP bootstrap (`open()`)

With bounded exponential backoff (`_get_with_retry`, 5 attempts):

1. `GET /jdev/cfg/apiKey` → version, SNR, `local`.
   - If `local == false`, adjust the URL via Cloud-DNS redirect (`_apply_url`).
2. `GET /data/LoxAPP3.json` → structure file into `structure_file`.
3. `GET /jdev/sys/getPublicKey` → certificate → RSA public key.
4. Build the session key: encrypt the payload `"{aes_key_hex}:{iv_hex}"` with RSA PKCS#1 v1.5, Base64 → `_session_key`.
5. Generate the salt (`_generate_salt`).

## Phase 2 – Open WebSocket

- URL `ws(s)://{host}/ws/rfc6455` (`build_loxone_url`), subprotocol `remotecontrol`.
- `ping_interval=None` (the Loxone keepalive is the liveness channel).

## Phase 3 – Authentication

1. Immediately after connect: `jdev/sys/keyexchange/{session_key}`.
2. Response `keyexchange` → sends `jdev/sys/getkey2/{encoded_username}`.
3. From the response: `key`, `salt`, `hashAlg`.

Branching:

- **Token still valid** (> 100 s remaining lifetime): hash over the token → `authwithtoken/{token_hash}/{user}`.
- **Token missing/expired**: password hash → `jdev/sys/gettoken/{hash}/...` (or `getjwt` from FW 10.2). The response provides `token`, `validUntil`, `key`.

Completion: `_authenticated_event.set()`, token-change callback, `jdev/sps/enablebinstatusupdate`.

## Phase 4 – Operation

- **Receive loop**: parses the binary Loxone protocol (8-byte header + body, chunking/estimated length), dispatches to `_websocket_event()` and the HA callback.
- **Keepalive**: every 30 s (`KEEP_ALIVE_PERIOD`) `keepalive`; watchdog after 90 s without an incoming frame.
- **Token refresh**: after auth, wait ~50 % of the remaining lifetime, then `async_refresh_token`; escalate after 10 failed attempts.
- **Reconnect task**: on a reconnect event, `LoxoneTokenError` is raised.
- **Secured commands**: stash in `_secured_queue`, `jdev/sys/getvisusalt/{user}`, then send the HMAC command.

## Phase 5 – Supervision (`run()`)

- Loop over `open()`/`start_listening()`.
- Retryable errors → `close()`, backoff ±20 % jitter, retry.
- Auth errors → pass on to the integration (delete token / reload).
- `close()` sets the shutdown event and terminates.

## Flow diagram

```mermaid
sequenceDiagram
    autonumber
    participant HA as Home Assistant / Coordinator
    participant C as LoxoneConnection
    participant HTTP as Miniserver (HTTP)
    participant WS as Miniserver (WebSocket)

    HA->>C: run() / start_listening()

    note over C,HTTP: Phase 1 – HTTP bootstrap (open())
    C->>HTTP: GET /jdev/cfg/apiKey
    HTTP-->>C: version, snr, local
    opt not local
        C->>C: adjust URL via Cloud-DNS redirect
    end
    C->>HTTP: GET /data/LoxAPP3.json
    HTTP-->>C: structure file
    C->>HTTP: GET /jdev/sys/getPublicKey
    HTTP-->>C: certificate → RSA public key
    C->>C: encrypt AES key:iv with RSA
    C->>C: generate salt

    note over C,WS: Phase 2 – WebSocket
    C->>WS: ws(s)://host/ws/rfc6455 (remotecontrol)
    WS-->>C: connection open

    note over C,WS: Phase 3 – Auth
    C->>WS: jdev/sys/keyexchange/{session_key}
    WS-->>C: keyexchange
    C->>WS: jdev/sys/getkey2/{user}
    WS-->>C: key, salt, hashAlg

    alt token still valid (>100s)
        C->>WS: authwithtoken/{token_hash}/{user}
    else re-authenticate
        C->>C: build password hash
        C->>WS: jdev/sys/gettoken/{hash}/... (or getjwt)
        WS-->>C: token, validUntil, key
    end
    C->>WS: jdev/sps/enablebinstatusupdate
    C->>C: set _authenticated_event

    note over C,WS: Phase 4 – Operation
    par receive loop
        WS-->>C: status/text messages
    and keepalive (30s)
        C->>WS: keepalive
    and token refresh
        C->>WS: refreshjwt (after ~50% lifetime)
    end

    note over HA,C: On drop: run() → close() → backoff → retry
```

## Error codes (from the docs)

- `401` / `4003`: unauthorized / too many failed attempts (close 4003).
- `420`: not authenticated within the first seconds.
- `400`: another command before auth.
- Further CloudDNS codes see the docs (403, 405, 409, 412, 418, 481–483).
