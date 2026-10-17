// Shop product-data check: pure logic, no network.
// Input: array of Shopify products (as in /products.json). Output: findings.
'use strict';

const EXAMPLES = 5;

function isGiftOrDigital(p, v) {
  const t = `${p.title} ${p.product_type || ''} ${v.title || ''}`.toLowerCase();
  return /gift ?card|e-?gift|voucher|digital|download|subscription|donation/.test(t) &&
    !/gift ?set|gift ?box|gift ?pack|hamper/.test(t);
}

function shippable(p, v) {
  if (v.requires_shipping === false) return false;
  if (Number(v.price) === 0) return false;
  return !isGiftOrDigital(p, v);
}

function label(p, v) {
  const vt = (v.title || '').trim();
  return vt && vt !== 'Default Title' ? `${p.title} – ${vt}` : p.title;
}

// Pull a pack/case quantity out of a variant or product title, e.g. "12 Pack",
// "Case of 24", "24 x 330ml", "Raspberry Lemonade / 48", "6-pack".
function packSize(text, allowBare) {
  const s = String(text || '').toLowerCase();
  let m = s.match(/(\d{1,3})\s*[- ]?\s*(?:pack|pk|cans?|bottles?|count|ct)\b/) ||
    s.match(/case of\s*(\d{1,3})/) ||
    s.match(/(\d{1,3})\s*[x×]\s*\d/) ||
    (allowBare === false ? null : s.match(/(?:^|\/\s*)(\d{1,3})\s*$/));
  if (!m) return null;
  const n = Number(m[1]);
  return n >= 2 && n <= 500 ? n : null;
}

function stripPack(text) {
  return String(text || '').toLowerCase()
    .replace(/(\d{1,3})\s*[- ]?\s*(?:pack|pk|cans?|bottles?|count|ct)\b/g, '')
    .replace(/case of\s*\d{1,3}/g, '')
    .replace(/\d{1,3}\s*[x×]\s*\d+\s*\w*/g, '')
    .replace(/(?:^|\/\s*)\d{1,3}\s*$/g, '')
    .replace(/[^a-z]+/g, ' ').trim();
}

function normTitle(t) { return String(t || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim(); }

function check(products) {
  const rows = [];
  for (const p of products || []) {
    for (const v of p.variants || []) rows.push({ p, v });
  }
  const ship = rows.filter(r => shippable(r.p, r.v));

  // 1. Shippable items with no weight
  const zero = ship.filter(r => !Number(r.v.grams));

  // 2. Different pack sizes recorded at the same weight (same product family)
  const fam = new Map();
  for (const r of ship) {
    // A bare number ("24", "Red / 12") only counts as a pack size when the product
    // is clearly sold in packs; otherwise it is usually a clothing or shoe size.
    const packish = /pack|case|cans?\b|bottles?|box|multi|bundle|crate|tray|sachets?/i.test(`${r.p.title} ${r.p.product_type || ''}`);
    const size = packSize(r.v.title, packish) || packSize(r.p.title, packish);
    const g = Number(r.v.grams);
    if (!size || !g) continue;
    // family = same product + flavour (variant title without the pack size),
    // or across products: product title without the pack size
    const key = r.p.handle + '|' + stripPack(r.v.title);
    const key2 = 'T|' + stripPack(r.p.title) + '|' + stripPack(r.v.title);
    for (const k of [key, key2]) {
      if (!fam.has(k)) fam.set(k, []);
      fam.get(k).push({ r, size, g });
    }
  }
  const packSame = [];
  const seenFam = new Set();
  for (const [, items] of fam) {
    const sizes = new Set(items.map(i => i.size));
    if (sizes.size < 2) continue;
    const bySize = new Map();
    items.forEach(i => { if (!bySize.has(i.size)) bySize.set(i.size, i); });
    const uniq = [...bySize.values()].sort((a, b) => a.size - b.size);
    const weights = new Set(uniq.map(i => i.g));
    if (weights.size !== 1) continue;
    const first = uniq[0].r;
    const core = stripPack(first.v.title === 'Default Title' ? '' : first.v.title) || stripPack(first.p.title);
    const sig = core + '|' + uniq.map(i => i.size).join(',') + '|' + uniq[0].g;
    if (seenFam.has(sig)) continue;
    seenFam.add(sig);
    packSame.push({
      name: uniq[0].r.p.title + (stripPack(uniq[0].r.v.title) ? ` – ${uniq[0].r.v.title.replace(/\s*\/?\s*\d{1,3}\s*$/, '').trim()}` : ''),
      sizes: uniq.map(i => i.size),
      grams: uniq[0].g,
    });
  }

  // 3. Shippable items with no product code (SKU)
  const noSku = ship.filter(r => !String(r.v.sku || '').trim());

  // 4. Same product code on more than one listing
  const bySku = new Map();
  for (const r of rows) {
    const s = String(r.v.sku || '').trim();
    if (!s) continue;
    if (!bySku.has(s)) bySku.set(s, []);
    bySku.get(s).push(r);
  }
  const dupSku = [];
  for (const [sku, rs] of bySku) {
    const handles = new Set(rs.map(r => r.p.handle));
    if (handles.size > 1) dupSku.push({ sku, items: rs.map(r => label(r.p, r.v)) });
  }

  // 5. Products with the same title on different listings
  const byTitle = new Map();
  for (const p of products || []) {
    const k = normTitle(p.title);
    if (!k) continue;
    if (!byTitle.has(k)) byTitle.set(k, new Set());
    byTitle.get(k).add(p.handle);
  }
  const dupTitle = [...byTitle].filter(([, h]) => h.size > 1)
    .map(([k, h]) => ({ title: (products.find(p => normTitle(p.title) === k) || {}).title, listings: h.size }));

  return {
    products: (products || []).length,
    variants: rows.length,
    shippable: ship.length,
    checks: {
      zeroWeight: { count: zero.length, examples: zero.slice(0, EXAMPLES).map(r => label(r.p, r.v)) },
      packSameWeight: { count: packSame.length, examples: packSame.slice(0, EXAMPLES) },
      missingSku: { count: noSku.length, examples: noSku.slice(0, EXAMPLES).map(r => label(r.p, r.v)) },
      sharedSku: { count: dupSku.length, examples: dupSku.slice(0, EXAMPLES) },
      duplicateTitles: { count: dupTitle.length, examples: dupTitle.slice(0, EXAMPLES) },
    },
  };
}

// Normalise whatever a visitor types into a bare hostname, or null if unsafe.
function normaliseShop(input) {
  let s = String(input || '').trim().toLowerCase();
  if (!s || s.length > 253) return null;
  s = s.replace(/^[a-z]+:\/\//, '').split(/[/?#]/)[0].replace(/:\d+$/, '').replace(/\.$/, '');
  if (s.includes('@')) return null;
  if (!/^[a-z0-9.-]+$/.test(s)) return null;
  if (/^\d+(\.\d+){3}$/.test(s)) return null; // IP address
  if (s === 'localhost' || s.endsWith('.localhost') || s.endsWith('.local') || s.endsWith('.internal')) return null;
  const parts = s.split('.');
  if (parts.length < 2 || parts.some(x => !x || x.length > 63 || x.startsWith('-') || x.endsWith('-'))) return null;
  if (!/^[a-z]{2,}$/.test(parts[parts.length - 1])) return null;
  return s;
}

module.exports = { check, normaliseShop, packSize, stripPack };
