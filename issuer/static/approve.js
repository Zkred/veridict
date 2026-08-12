// Browser-side approval flow.
//
// The reviewer's device key is generated here and stored non-extractable in
// IndexedDB, so it cannot be read out by script and never reaches the issuer.
// The issuer signs a credential around the matching *public* key, the browser
// signs the DeviceAuthentication bytes, and the proof is generated in a worker.
//
// The finished proof is posted back through the issuer rather than straight to
// the backend. That is deliberate: the pseudonym and reputation chips are
// server-computed, and a browser posting directly to the backend could claim any
// pseudonym it wanted.

const DB_NAME = "veridict";
const STORE = "keys";
const KEY_ID = "device";

function idb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function idbGet(db, key) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readonly").objectStore(STORE).get(key);
    tx.onsuccess = () => resolve(tx.result);
    tx.onerror = () => reject(tx.error);
  });
}

function idbPut(db, key, value) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite").objectStore(STORE).put(value, key);
    tx.onsuccess = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

// Returns a persistent P-256 keypair for this browser profile. extractable is
// false, so even same-origin script cannot export the private key; it can only
// ask WebCrypto to sign with it.
async function getDeviceKey() {
  const db = await idb();
  const existing = await idbGet(db, KEY_ID);
  if (existing && existing.privateKey) return existing;

  const pair = await crypto.subtle.generateKey(
    { name: "ECDSA", namedCurve: "P-256" },
    false, // non-extractable private key
    ["sign", "verify"],
  );
  await idbPut(db, KEY_ID, pair);
  return pair;
}

function b64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// base64url (as used by JWK) to a fixed-width hex string.
function b64UrlToHex(b64url) {
  const b64 = b64url.replace(/-/g, "+").replace(/_/g, "/");
  const bytes = b64ToBytes(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

async function devicePublicHex(pair) {
  const jwk = await crypto.subtle.exportKey("jwk", pair.publicKey);
  return { x: b64UrlToHex(jwk.x), y: b64UrlToHex(jwk.y) };
}

export async function runApproval({ prSlug, comment, onProgress }) {
  const step = onProgress || (() => {});

  step("Preparing device key", 4);
  const pair = await getDeviceKey();
  const pub = await devicePublicHex(pair);

  step("Requesting credential", 8);
  const credResp = await fetch("/approve/credential", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pr_slug: prSlug,
      device_pk_x: pub.x,
      device_pk_y: pub.y,
    }),
  });
  const cred = await credResp.json();
  if (!credResp.ok) throw new Error(cred.error || `issuer returned ${credResp.status}`);

  // Sign the DeviceAuthentication bytes. WebCrypto emits raw r||s, which is
  // exactly the form COSE_Sign1 wants, so no DER unwrapping is needed.
  step("Signing credential on device", 12);
  const deviceTbs = b64ToBytes(cred.device_tbs_b64);
  const signature = await crypto.subtle.sign(
    { name: "ECDSA", hash: "SHA-256" },
    pair.privateKey,
    deviceTbs,
  );

  const mdoc = b64ToBytes(cred.mdoc_b64);

  const { proof, ms } = await proveInWorker({
    circuitUrl: cred.circuit_url,
    mdoc,
    signature: new Uint8Array(signature),
    sigOffset: cred.sig_offset,
    pkx: cred.issuer_pkx,
    pky: cred.issuer_pky,
    transcriptHex: cred.transcript_hex,
    claimNs: cred.claim_ns,
    claimId: cred.claim_id,
    claimCborHex: cred.claim_cbor_hex,
    now: cred.now,
    onProgress: step,
  });

  step("Submitting proof", 92);
  const form = new FormData();
  form.append("token", cred.token);
  form.append("comment", comment || "");
  form.append("prover_ms", String(ms));
  form.append("file", new Blob([proof], { type: "application/octet-stream" }), "proof.bin");

  const subResp = await fetch("/approve/submit", { method: "POST", body: form });
  const sub = await subResp.json();
  if (!subResp.ok) throw new Error(sub.error || `submit returned ${subResp.status}`);

  step("Done", 100);
  return sub;
}

function proveInWorker(opts) {
  return new Promise((resolve, reject) => {
    const worker = new Worker("/js/prover-worker.js");
    worker.onerror = (e) => {
      worker.terminate();
      reject(new Error(e.message || "prover worker failed to start"));
    };
    worker.onmessage = (e) => {
      const m = e.data;
      if (m.type === "progress") {
        opts.onProgress(m.step, m.pct);
      } else if (m.type === "done") {
        worker.terminate();
        resolve({ proof: m.proof, ms: m.ms });
      } else if (m.type === "error") {
        worker.terminate();
        reject(new Error(m.message));
      }
    };
    const { onProgress, ...payload } = opts;
    // Transfer the credential buffers rather than copying them.
    worker.postMessage({ type: "prove", ...payload });
  });
}
