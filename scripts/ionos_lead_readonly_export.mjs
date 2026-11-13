#!/usr/bin/env node
/*
 * Owner-operated, read-only IONOS PocketBase lead export.
 * Does not install hooks, request source credentials, submit leads, or change production.
 * This is a stable logical record export, NOT a transactional database backup.
 * Requires an explicitly authorized PocketBase read token in the local process
 * environment, and a separate RSA recipient certificate/public key. Plaintext
 * records are kept only in process memory; only authenticated ciphertext is saved.
 */
import fs from 'node:fs';
import crypto from 'node:crypto';
import { pathToFileURL } from 'node:url';

export const REQUIRED_COLLECTIONS = Object.freeze([
  'nija_lead_events', 'nija_lead_delivery', 'nija_lead_dispatch', 'nija_consent_events',
]);
const COLLECTION_RE = /^[A-Za-z][A-Za-z0-9_]{1,63}$/;
const MAX_ROWS = 100000;
const MAX_PAGES = 1000;
const MAX_TOTAL_BYTES = 45 * 1024 * 1024;

function jsonStable(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(jsonStable).join(',')}]`;
  return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${jsonStable(value[k])}`).join(',')}}`;
}
const sha = value => crypto.createHash('sha256').update(value).digest('hex');

function originFor(baseUrl) {
  const u = new URL(baseUrl);
  if (u.protocol !== 'https:' || u.hostname !== 'nijaaitrading.com' || u.port || u.username || u.password || u.search || u.hash || u.pathname.replace(/\/$/, '') !== '/.sfs-be') {
    throw Error('Origin must be the canonical HTTPS IONOS PocketBase base URL');
  }
  return u.origin + '/.sfs-be';
}
function validCollections(additional = []) {
  const names = [...REQUIRED_COLLECTIONS, ...additional];
  if (names.some(n => !COLLECTION_RE.test(n) || n === 'nija_settings')) throw Error('Collection not allowlisted for protected lead export');
  return [...new Set(names)];
}

async function authorizedJson(url, token, fetchImpl) {
  const res = await fetchImpl(url, {
    method: 'GET',
    headers: { Authorization: token, Accept: 'application/json' },
    redirect: 'manual',
    cache: 'no-store',
    signal: AbortSignal.timeout(15000),
  });
  if (!res || res.status !== 200 || !String(res.headers?.get?.('content-type') || '').toLowerCase().includes('application/json')) {
    throw Error('Authorized API read unavailable (no data counts inferred)');
  }
  const data = await res.json();
  if (!data || typeof data !== 'object') throw Error('Malformed authorized API read');
  return data;
}

async function readCollection(base, name, token, fetchImpl) {
  // Collection schema is mandatory: without it, an export is not independently restorable.
  const schema = await authorizedJson(`${base}/api/collections/${name}`, token, fetchImpl);
  if (schema.name !== name || !(Array.isArray(schema.fields) || Array.isArray(schema.schema))) throw Error('Incomplete collection schema');
  let total = null, pages = null;
  const rows = [], seen = new Set();
  for (let page = 1; page <= MAX_PAGES; page++) {
    const u = new URL(`${base}/api/collections/${name}/records`);
    u.searchParams.set('page', String(page));
    u.searchParams.set('perPage', '200');
    u.searchParams.set('sort', 'id');
    const list = await authorizedJson(u.toString(), token, fetchImpl);
    if (!Array.isArray(list.items) || !Number.isSafeInteger(list.totalItems) || !Number.isSafeInteger(list.totalPages) ||
        list.totalItems < 0 || list.totalItems > MAX_ROWS || list.totalPages < 0 ||
        list.page !== page || list.totalPages > MAX_PAGES) {
      throw Error('Incomplete or malformed collection page');
    }
    if (total === null) { total = list.totalItems; pages = list.totalPages; }
    if (total !== list.totalItems || pages !== list.totalPages) throw Error('Collection changed while paging');
    for (const item of list.items) {
      if (!item || typeof item !== 'object' || typeof item.id !== 'string' || !item.id || seen.has(item.id)) {
        throw Error('Missing or duplicate source record ID');
      }
      seen.add(item.id);
      rows.push(item);
    }
    if (rows.length > total) throw Error('Collection page overreported rows');
    if (page >= pages) {
      if (rows.length !== total) throw Error('Collection page omitted rows');
      break;
    }
    if (page === MAX_PAGES) throw Error('Collection page limit reached');
  }
  return { collection: name, schema, total, records: rows, digest: sha(jsonStable({schema, rows})) };
}

export async function collectSnapshot({baseUrl, token, additional = [], fetchImpl = fetch}) {
  if (typeof token !== 'string' || token.trim().length < 20) throw Error('Authorized read token unavailable');
  const base = originFor(baseUrl);
  const collections = validCollections(additional);
  const startedAt = new Date().toISOString();
  const first = {};
  for (const name of collections) first[name] = await readCollection(base, name, token, fetchImpl);
  // A second full read detects many concurrent inserts/updates/deletes; it cannot
  // establish an atomic transaction or a live backup/restore guarantee.
  for (const name of collections) {
    const second = await readCollection(base, name, token, fetchImpl);
    if (first[name].digest !== second.digest || first[name].total !== second.total) {
      throw Error('Collection drift across repeated read passes');
    }
  }
  const finishedAt = new Date().toISOString();
  const snapshot = {
    format: 'nija-ionos-lead-logical-export-v1',
    transactional_backup: false,
    completeness: 'TWO_STABLE_READ_PASSES_ONLY',
    base, started_at: startedAt, finished_at: finishedAt,
    collections: first,
  };
  const plaintext = Buffer.from(jsonStable(snapshot));
  if (plaintext.length > MAX_TOTAL_BYTES) throw Error('Export exceeds bounded in-memory size');
  return {snapshot, plaintext};
}

function publicKeyFromPem(pem) {
  const value = String(pem);
  if (value.includes('PRIVATE KEY')) throw Error('Export recipient must not be a private key');
  const key = value.includes('BEGIN CERTIFICATE')
    ? new crypto.X509Certificate(value).publicKey
    : crypto.createPublicKey(value);
  if (key.asymmetricKeyType !== 'rsa') throw Error('Recipient RSA certificate/public key required');
  return key;
}

export function encryptSnapshot(plaintext, recipientPublicPem) {
  const key = publicKeyFromPem(recipientPublicPem);
  const aes = crypto.randomBytes(32), nonce = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', aes, nonce);
  const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  const tag = cipher.getAuthTag();
  const wrapped = crypto.publicEncrypt({key, padding:crypto.constants.RSA_PKCS1_OAEP_PADDING, oaepHash:'sha256'}, aes);
  aes.fill(0);
  return {
    format:'nija-ionos-encrypted-export-v1',
    algorithm:'AES-256-GCM+RSA-OAEP-SHA256',
    data_sha256:sha(plaintext),
    wrapped_key:wrapped.toString('base64'),
    nonce:nonce.toString('base64'),
    tag:tag.toString('base64'),
    ciphertext:ciphertext.toString('base64'),
  };
}

export function verifyEncryptedExport(exportJson, privatePem) {
  if (!exportJson || exportJson.format !== 'nija-ionos-encrypted-export-v1' || exportJson.algorithm !== 'AES-256-GCM+RSA-OAEP-SHA256') {
    throw Error('Unknown export format');
  }
  const key = crypto.privateDecrypt({key:privatePem, padding:crypto.constants.RSA_PKCS1_OAEP_PADDING, oaepHash:'sha256'}, Buffer.from(exportJson.wrapped_key,'base64'));
  const dec = crypto.createDecipheriv('aes-256-gcm',key, Buffer.from(exportJson.nonce,'base64'));
  dec.setAuthTag(Buffer.from(exportJson.tag,'base64'));
  const plaintext = Buffer.concat([dec.update(Buffer.from(exportJson.ciphertext,'base64')), dec.final()]);
  key.fill(0);
  if (sha(plaintext) !== exportJson.data_sha256) throw Error('Plaintext digest mismatch');
  const snapshot = JSON.parse(plaintext.toString('utf8'));
  if (snapshot.format !== 'nija-ionos-lead-logical-export-v1' || snapshot.transactional_backup !== false || snapshot.completeness !== 'TWO_STABLE_READ_PASSES_ONLY') throw Error('Unrecognized snapshot manifest');
  if (!snapshot.collections || !REQUIRED_COLLECTIONS.every(n => snapshot.collections[n])) throw Error('Required collection missing');
  let counts = {};
  for (const [name, v] of Object.entries(snapshot.collections)) {
    if (!COLLECTION_RE.test(name) || !Array.isArray(v.records) || !v.schema || v.schema.name !== name || v.total !== v.records.length ||
       v.digest !== sha(jsonStable({schema:v.schema, rows:v.records})) || new Set(v.records.map(r=>r.id)).size !== v.total) throw Error('Snapshot mismatch');
    counts[name] = v.total;
  }
  return {verified:true, record_counts:counts, atomic_backup:false, schema_included:true};
}

export async function run(argv=process.argv.slice(2)) {
  if (!(argv.length === 4 || (argv.length === 6 && argv[4] === '--extra-collections')) || argv[0] !== '--certificate' || argv[2] !== '--output') {
    throw Error('Usage: node ionos_lead_readonly_export.mjs --certificate RECIPIENT_RSA_CERT.pem --output ENCRYPTED_EXPORT.json [--extra-collections older_collection,another_collection]');
  }
  const token = process.env.NIJA_IONOS_PB_READ_TOKEN;
  const cert = fs.readFileSync(argv[1], 'utf8');
  const additional = argv.length === 6 ? argv[5].split(',').map(s=>s.trim()) : [];
  const {snapshot, plaintext} = await collectSnapshot({baseUrl:'https://nijaaitrading.com/.sfs-be',token,additional});
  const encrypted = encryptSnapshot(plaintext,cert);
  fs.writeFileSync(argv[3],JSON.stringify(encrypted)+'\n',{flag:'wx',mode:0o600});
  plaintext.fill(0);
  console.log(JSON.stringify({status:'ENCRYPTED_LOGICAL_EXPORT_WRITTEN_NOT_RESTORATION_CERTIFIED',counts:Object.fromEntries(Object.entries(snapshot.collections).map(([n,v])=>[n,v.total])),output:argv[3]}));
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  run().catch(err=>{console.error('IONOS export blocked:',err.message);process.exitCode=1;});
}