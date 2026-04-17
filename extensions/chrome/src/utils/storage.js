import {
  DEFAULT_VIRCHOW_DOMAIN,
  CHROME_SPECIFIC_STORAGE_KEYS,
} from "./constants.js";

export async function getVirchowDomain() {
  const result = await chrome.storage.local.get({
    [CHROME_SPECIFIC_STORAGE_KEYS.VIRCHOW_DOMAIN]: DEFAULT_VIRCHOW_DOMAIN,
  });
  return result[CHROME_SPECIFIC_STORAGE_KEYS.VIRCHOW_DOMAIN];
}

export function setVirchowDomain(domain, callback) {
  chrome.storage.local.set(
    { [CHROME_SPECIFIC_STORAGE_KEYS.VIRCHOW_DOMAIN]: domain },
    callback,
  );
}

export function getVirchowDomainSync() {
  return new Promise((resolve) => {
    getVirchowDomain(resolve);
  });
}
