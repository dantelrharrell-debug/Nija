import React, { useEffect, useState } from "react";
import { brokerReadiness, storedBrokerConnections, verifyStoredKraken } from "./memberBrokerApi.mjs";

/** NIJA member brokerage credential intake. Mount inside the authenticated dashboard.
 *  Never persist, echo, or log credentials. Broker verification and live trading are separate.
 */
const API = "https://nija-member-broker-api.onrender.com";
export default function MemberBrokerKeyForm({ pb }) {
  const [ready, setReady] = useState(false);
  const [verificationReady, setVerificationReady] = useState(false);
  const [connections, setConnections] = useState([]);
  const [sessionToken, setSessionToken] = useState(pb?.authStore?.token || "");
  const [checking, setChecking] = useState(true);
  const [broker, setBroker] = useState("kraken");
  const [environment, setEnvironment] = useState("live");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    let active = true;
    setReady(false);
    setVerificationReady(false);
    setConnections([]);
    setMessage("");
    setApiKey("");
    setApiSecret("");
    setPassphrase("");
    setChecking(true);
    const check = async () => {
      try {
        const capabilities = await brokerReadiness();
        const rows = await storedBrokerConnections(sessionToken);
        if (active) {
          setReady(capabilities.intake);
          setVerificationReady(capabilities.verification);
          setConnections(rows);
        }
      } catch {
        if (active) setReady(false);
      } finally {
        if (active) setChecking(false);
      }
    };
    check();
    return () => { active = false; };
  }, [sessionToken]);
  useEffect(() => {
    setSessionToken(pb?.authStore?.token || "");
    return pb?.authStore?.onChange?.(token => setSessionToken(token || ""));
  }, [pb]);
  async function verify() {
    const token = pb?.authStore?.token;
    if (!verificationReady || !token || token !== sessionToken || busy) return;
    setBusy(true);
    setMessage("");
    try {
      await verifyStoredKraken(token, "live");
      if (pb?.authStore?.token === token) {
        setMessage("Kraken authentication verified now. Membership access, stored credentials, and trading authorization are separate. Trading remains disabled.");
      }
    } catch {
      if (pb?.authStore?.token === token) {
        setMessage("Kraken verification unavailable or denied. No trading authorization was granted.");
      }
    } finally {
      setBusy(false);
    }
  }
  async function submit(event) {
    event.preventDefault();
    const token = pb?.authStore?.token;
    if (!ready || !token || token !== sessionToken || busy || !apiKey.trim() || !apiSecret.trim()) return;
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(API + "/api/member/brokers/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
        body: JSON.stringify({
          broker, environment,
          credentials: broker === "okx" ? { api_key: apiKey.trim(), api_secret: apiSecret.trim(), passphrase: passphrase.trim() } : { api_key: apiKey.trim(), api_secret: apiSecret.trim() }
        }),
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
      });
      if (!response.ok) throw new Error("Unable to save credentials securely. Please contact NIJA support.");
      const result = await response.json();
      if (result.credentials_stored !== true) throw new Error("Credential storage could not be confirmed.");
      setApiKey("");
      setApiSecret("");
      setPassphrase("");
      const rows = await storedBrokerConnections(token);
      if (pb?.authStore?.token === token) {
        setConnections(rows);
        setMessage("Credentials securely stored. Brokerage verification and trading authorization are still pending.");
      }
    } catch {
      if (pb?.authStore?.token === token) {
        setMessage("Secure connection could not be completed. No brokerage access has been confirmed.");
      }
    } finally {
      setApiKey("");
      setApiSecret("");
      setPassphrase("");
      setBusy(false);
    }
  }
  const authenticated = Boolean(sessionToken) && sessionToken === pb?.authStore?.token;
  const canUse = ready && authenticated;
  const storedKraken = connections.some(row => row.broker === "kraken"
    && row.environment === "live" && row.credentials_stored);
  return <section aria-label="Brokerage API key setup">
    <h2>Connect your brokerage</h2>
    <p>NIJA never needs withdrawal permission. Do not share your keys by email or chat.</p>
    {authenticated && verificationReady && storedKraken && <div>
      <p>Kraken credentials stored. Authentication is checked only when you verify; this does not enable trading.</p>
      <button type="button" disabled={busy} onClick={verify}>
        {busy ? "Working…" : "Verify stored Kraken credentials"}
      </button>
    </div>}
    {!canUse ? <p role="status">{checking ? "Checking secure setup availability…" :
      "Secure brokerage setup temporarily unavailable. Please try again later."}</p> :
    <form onSubmit={submit} autoComplete="off"><fieldset disabled={busy}>
      <label>Brokerage <select value={broker} onChange={e => { setBroker(e.target.value); setEnvironment("live"); setApiKey(""); setApiSecret(""); setPassphrase(""); setMessage(""); }}>
        <option value="kraken">Kraken</option><option value="alpaca">Alpaca</option><option value="coinbase">Coinbase Advanced Trade</option><option value="okx">OKX</option>
      </select></label>
      <label>Environment <select value={environment} onChange={e => setEnvironment(e.target.value)}>
        {broker === "alpaca" && <option value="paper">Paper</option>}<option value="live">Live (storage only; trading disabled)</option>
      </select></label>
      <label>{broker === "coinbase" ? "CDP API key name" : "API key"} <input value={apiKey} onChange={e => setApiKey(e.target.value)} required autoComplete="off" /></label>
      <label>{broker === "coinbase" ? "CDP private key (PEM)" : "API secret"} <input type="password" value={apiSecret} onChange={e => setApiSecret(e.target.value)} required autoComplete="new-password" /></label>
      {broker === "okx" && <label>OKX API passphrase <input type="password" value={passphrase} onChange={e => setPassphrase(e.target.value)} required autoComplete="new-password" /></label>}
      <button type="submit" disabled={busy || (broker === "okx" && !passphrase.trim())}>{busy ? "Saving…" : "Save credentials securely"}</button>
    </fieldset></form>}
    {message && <p role="status">{message}</p>}
  </section>;
}
