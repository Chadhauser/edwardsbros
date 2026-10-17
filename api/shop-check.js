// GET /api/shop-check?shop=example.com
// Reads a Shopify shop's public product feed and returns plain-English findings.
// Nothing is stored. Only the public /products.json feed is read.
'use strict';
const { check, normaliseShop } = require('./_lib/shopcheck');

const PAGES = 4;          // up to 1,000 products
const TIMEOUT_MS = 7000;

async function getPage(host, page) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`https://${host}/products.json?limit=250&page=${page}`, {
      signal: ctrl.signal,
      redirect: 'follow',
      headers: { 'User-Agent': 'EdwardsBros-ShopCheck/1.0 (+https://www.edwardsbros.co.uk/data.html)', Accept: 'application/json' },
    });
    if (!res.ok) return { error: `status ${res.status}` };
    const text = await res.text();
    if (text.length > 15_000_000) return { error: 'too large' };
    let json;
    try { json = JSON.parse(text); } catch { return { error: 'not json' }; }
    if (!json || !Array.isArray(json.products)) return { error: 'no products' };
    return { products: json.products };
  } catch (e) {
    return { error: e.name === 'AbortError' ? 'timeout' : 'unreachable' };
  } finally {
    clearTimeout(t);
  }
}

module.exports = async (req, res) => {
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  const host = normaliseShop(req.query && req.query.shop);
  if (!host) {
    res.statusCode = 400;
    return res.end(JSON.stringify({ ok: false, message: "That doesn't look like a shop web address. Try something like yourshop.co.uk." }));
  }

  const pages = await Promise.all(Array.from({ length: PAGES }, (_, i) => getPage(host, i + 1)));
  if (pages[0].error) {
    console.log(JSON.stringify({ shopCheck: host, result: 'no-feed', reason: pages[0].error }));
    res.statusCode = 200;
    return res.end(JSON.stringify({
      ok: false, host,
      message: "We couldn't read a public product list for that shop. The instant check works on Shopify shops. For any other system, send us an export and we'll check it free.",
    }));
  }
  const products = [];
  const seen = new Set();
  for (const pg of pages) {
    if (!pg.products) break;
    for (const p of pg.products) if (!seen.has(p.id)) { seen.add(p.id); products.push(p); }
    if (pg.products.length < 250) break;
  }
  const result = check(products);
  result.truncated = products.length >= PAGES * 250;
  console.log(JSON.stringify({ shopCheck: host, result: 'ok', products: result.products,
    found: Object.fromEntries(Object.entries(result.checks).map(([k, v]) => [k, v.count])) }));
  res.setHeader('Cache-Control', 'public, s-maxage=3600');
  res.statusCode = 200;
  return res.end(JSON.stringify({ ok: true, host, ...result }));
};
