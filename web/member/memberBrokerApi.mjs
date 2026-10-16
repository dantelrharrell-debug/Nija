/** Isolated member API transport. Tokens remain in memory and never enter URLs. */
const API = "https://nija-member-broker-api.onrender.com";

async function memberRequest(path, token, payload) {
  if (typeof token !== "string" || !token.trim()) throw new Error("Authentication required");
  const response = await fetch(API + path, {
    method: payload ? "POST" : "GET",
    headers: {
      Authorization: "Bearer " + token,
      ...(payload ? { "Content-Type": "application/json" } : {}),
    },
    ...(payload ? { body: JSON.stringify(payload) } : {}),
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
  });
  if (!response.ok) throw new Error("Member brokerage request unavailable");
  return response.json();
}

export async function brokerReadiness() {
  const response = await fetch(API + "/readyz", {
    cache: "no-store", credentials: "omit", redirect: "error",
  });
  if (!response.ok) throw new Error("Member brokerage unavailable");
  const result = await response.json();
  if (result.status !== "ready") throw new Error("Member brokerage unavailable");
  return {
    intake: result.credential_intake_enabled === true,
    verification: result.verification_enabled === true,
  };
}

export async function storedBrokerConnections(token) {
  const result = await memberRequest("/api/member/brokers", token);
  if (!Array.isArray(result.connections)) throw new Error("Member brokerage unavailable");
  return result.connections.map(row => ({
    broker: row.broker, environment: row.environment,
    credentials_stored: row.credentials_stored === true,
  }));
}

export async function verifyStoredKraken(token, environment) {
  if (environment !== "live") throw new Error("Unsupported verification scope");
  const result = await memberRequest("/api/member/brokers/verify", token, {
    broker: "kraken", environment,
  });
  if (result.broker !== "kraken" || result.environment !== environment
      || result.credentials_stored !== true || result.broker_verified !== true
      || result.membership_access !== true || result.trading_authorized !== false) {
    throw new Error("Broker authentication not confirmed");
  }
  return true;
}
