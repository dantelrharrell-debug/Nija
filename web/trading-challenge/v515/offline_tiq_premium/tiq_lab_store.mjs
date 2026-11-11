// Optional browser-local progress for the Practice Lab (free play only). Pure: the storage object is injected,
// so tests use an in-memory fake. Nothing is written unless the player turns saving on.
// Stored: only the player's answers to the fictional exercises (cleaned by cleanLabResults). No name, email, age,
// payment, account or device data. It is never used to unlock, price or approve anything.
import { cleanLabResults, emptyLab } from "./tiq_lab.mjs";

export const LAB_STORE_KEY = "nija_tiq_lab_v1";
export const LAB_STORE_VERSION = 1;
export const LAB_STORAGE_DISCLOSURE =
  "Saving is optional and off by default. If you turn it on, your answers to these practice exercises are kept only in this browser on this device. " +
  "They can be lost if you clear your browser data, use private browsing, or switch to another browser or device. " +
  "Nothing else is saved: no name, email, age, payment or account details. Saved answers are free practice only and never unlock anything.";

export function createLabStore(storage) {
  const safe = (fn, dflt) => { try { return storage ? fn(storage) : dflt; } catch (e) { return dflt; } };
  return {
    // Returns { enabled, lab }. enabled is true only if a valid saved record exists.
    load() {
      return safe((st) => {
        const raw = st.getItem(LAB_STORE_KEY);
        if (typeof raw !== "string" || raw.length > 50000) return { enabled: false, lab: emptyLab() };
        const d = JSON.parse(raw);
        if (!d || typeof d !== "object" || d.v !== LAB_STORE_VERSION || d.optIn !== true) return { enabled: false, lab: emptyLab() };
        return { enabled: true, lab: cleanLabResults(d.lab) };
      }, { enabled: false, lab: emptyLab() });
    },
    // Returns true if the save worked. Only call after the player turned saving on.
    save(lab) {
      return safe((st) => { st.setItem(LAB_STORE_KEY, JSON.stringify({ v: LAB_STORE_VERSION, optIn: true, lab: cleanLabResults(lab) })); return true; }, false);
    },
    clear() {
      return safe((st) => { st.removeItem(LAB_STORE_KEY); return true; }, false);
    },
  };
}
