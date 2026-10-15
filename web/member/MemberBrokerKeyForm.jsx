import React, { useEffect, useState } from "react";

/** NIJA member brokerage credential intake. Mount inside the authenticated dashboard.
 *  Never persist, echo, or log credentials. Broker verification and live trading are separate.
 */
const API = "https://nija-member-broker-api.onrender.com";
export default function MemberBrokerKeyForm({ pb }) {
  const [ready, setReady] = useState(false);
  const [checking, setChecking] = useState(true);
  const [broker, setBroker] = useState("kraken");
  const [environment, setEnvironment] = useState("paper");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    let active = true;
    const check = async () => {
      try {
        const response = await fetch(API + "/readyz", { cache: "no-store" });
        if (active) setReady(response.ok);
      } catch {
        if (active) setReady(false);
      } finally {
        if (active) setChecking(false);
      }
    };
    check();
    return () => { active = false; };
  }, []);
  async function submit(event) {
    event.preventDefault();
    const token = pb?.authStore?.token;
    if (!ready || !token || busy || !apiKey.trim() || !apiSecret.trim()) return;
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(API + "/api/member/brokers/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
        body: JSON.stringify({
          broker, environment,
          credentials: { api_key: apiKey.trim(), api_secret: apiSecret.trim() }
        }),
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Unable to save credentials securely. Please contact NIJA support.");
      const result = await response.json();
      if (result.credentials_stored !== true) throw new Error("Credential storage could not be confirmed.");
      setApiKey("");
      setApiSecret("");
      setMessage("Credentials securely stored. Brokerage verification and trading authorization are still pending.");
    } catch {
      setMessage("Secure connection could not be completed. No brokerage access has been confirmed.");
    } finally {
      setBusy(false);
    }
  }
  const canUse = ready && Boolean(pb?.authStore?.token);
  return <section aria-label="Brokerage API key setup">
    <h2>Connect your brokerage</h2>
    <p>NIJA never needs withdrawal permission. Do not share your keys by email or chat.</p>
    {!canUse ? <p role="status">{checking ? "Checking secure setup availability…" :
      "Secure brokerage setup temporarily unavailable. Please try again later."}</p> :
    <form onSubmit={submit} autoComplete="off">
      <label>Brokerage <select value={broker} onChange={e => setBroker(e.target.value)}>
        <option value="kraken">Kraken</option><option value="alpaca">Alpaca</option>
      </select></label>
      <label>Environment <select value={environment} onChange={e => setEnvironment(e.target.value)}>
        <option value="paper">Paper</option><option value="live">Live (storage only; trading disabled)</option>
      </select></label>
      <label>API key <input value={apiKey} onChange={e => setApiKey(e.target.value)} required autoComplete="off" /></label>
      <label>API secret <input type="password" value={apiSecret} onChange={e => setApiSecret(e.target.value)} required autoComplete="new-password" /></label>
      <button type="submit" disabled={busy}>{busy ? "Saving…" : "Save credentials securely"}</button>
    </form>}
    {message && <p role="status">{message}</p>}
  </section>;
}
