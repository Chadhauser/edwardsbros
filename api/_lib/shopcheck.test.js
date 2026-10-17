'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { check, normaliseShop, packSize } = require('./shopcheck');

const v = (title, sku, grams, extra = {}) => ({ title, sku, grams, price: '10.00', requires_shipping: true, ...extra });
const p = (title, handle, variants, extra = {}) => ({ title, handle, variants, product_type: '', ...extra });

// Mirrors Collider's real feed as read in Chrome on 15 Oct 2026
const collider = [
  p('Welcome Pack', 'intro-pack', [v('Lager + IPA', 'D2C-BEV-UN-MIXED-CAN-12', 0), v('Session IPA', 'D2C-BEV-UN-PALE-CAN-12', 0), v('Lager', 'D2C-BEV-UN-LAGER-CAN-12', 0)]),
  p('Bestseller Pack', 'bestseller-pack', [v('Default Title', 'D2C-BEV-UN-BESTSELLER-CAN-24', 0)]),
  p('Lager + IPA', 'unwind-mixed-1', [v('12 Pack', 'D2C-BEV-UN-MIXED-CAN-12', 4500), v('24 Pack', 'D2C-BEV-UN-MIXED-CAN-24', 9000), v('48 Pack', 'D2C-BEV-UN-MIXED-CAN-48', 18000)]),
  p('Collider Gift Card', 'gift-card', [v('£30.00', null, 0, { requires_shipping: false }), v('£50.00', null, 0, { requires_shipping: false })]),
];

test('1. Collider: 4 zero-weight packs, gift cards excluded', () => {
  const r = check(collider);
  assert.equal(r.checks.zeroWeight.count, 4);
  assert.ok(!r.checks.zeroWeight.examples.some(e => /Gift Card/.test(e)));
});
test('2. Collider: correct pack weights (4500/9000/18000) are NOT flagged', () => {
  assert.equal(check(collider).checks.packSameWeight.count, 0);
});
test('3. Collider: code D2C-BEV-UN-MIXED-CAN-12 on two listings is flagged', () => {
  const r = check(collider);
  assert.equal(r.checks.sharedSku.count, 1);
  assert.equal(r.checks.sharedSku.examples[0].sku, 'D2C-BEV-UN-MIXED-CAN-12');
});
test('4. Gift cards without SKU are not counted as missing codes', () => {
  assert.equal(check(collider).checks.missingSku.count, 0);
});

// Mirrors Sneak: one product, flavour/size options, all sizes 6500g; Variety Pack varies
const sneak = [
  p('Sneak Energy Cans 500ml', 'sneak-energy-500ml-cans', [
    ...['Purple Storm', 'Cherry Limeade', 'Raspberry Lemonade', 'Mango Meltdown', 'Sherbet Burst']
      .flatMap(f => [12, 24, 48].map(n => v(`${f} / ${n}`, `${f}-${n}`, 6500))),
    v('Variety Pack / 12', 'VP12', 6500), v('Variety Pack / 24', 'VP24', 13000),
  ]),
  p('Street Fighter T-Shirt', 'sf-tee', [v('S', 'SF-S', 0), v('M', 'SF-M', 0)]),
  p('Transformers Starter Pack', 'tf-starter', [v('Default Title', '', 120)]),
];
test('5. Sneak: exactly 5 flavours with 12/24/48 at the same weight; Variety Pack not flagged', () => {
  const r = check(sneak);
  assert.equal(r.checks.packSameWeight.count, 5);
  assert.ok(r.checks.packSameWeight.examples.every(e => e.grams === 6500 && e.sizes.join() === '12,24,48'));
  assert.ok(!r.checks.packSameWeight.examples.some(e => /Variety/.test(e.name)));
});
test('6. Sneak: T-shirts at 0g counted; starter pack with no code counted', () => {
  const r = check(sneak);
  assert.equal(r.checks.zeroWeight.count, 2);
  assert.equal(r.checks.missingSku.count, 1);
});

// Mirrors Moth: same product listed twice, 8/12/24 all 1524g
const moth = [
  p('Twilight Pack', 'twilight-pack', [v('8', 'MC-8', 1524), v('12', 'MC-12', 1524), v('24', 'MC-24', 1524)]),
  p('Twilight Pack', 'twilight-pack-2', [v('8', 'MC-8', 1524), v('12', 'MC-12', 1524), v('24', 'MC-24', 1524)]),
];
test('7. Moth: same-weight packs reported once, not twice; duplicate title and codes flagged', () => {
  const r = check(moth);
  assert.equal(r.checks.packSameWeight.count, 1);
  assert.equal(r.checks.duplicateTitles.count, 1);
  assert.equal(r.checks.sharedSku.count, 3);
});

// Separate products per pack size (Sneak's "RASPBERRY LEMONADE - 12 PACK" listings)
const separate = [
  p('RASPBERRY LEMONADE - 12 PACK', 'rl-12', [v('Raspberry Lemonade / 12', 'A', 6500)]),
  p('RASPBERRY LEMONADE 24 PACK', 'rl-24', [v('Raspberry Lemonade / 24', 'B', 6500)]),
  p('RASPBERRY LEMONADE 48 PACK', 'rl-48', [v('Raspberry Lemonade / 48', 'C', 6500)]),
];
test('8. Pack sizes split across separate listings are still caught', () => {
  assert.equal(check(separate).checks.packSameWeight.count, 1);
});

test('9. Gift SETS are physical and are checked (not excluded like gift cards)', () => {
  const r = check([p('Wildflowers - Gift Set', 'wf', [v('Default Title', '8623', 0)])]);
  assert.equal(r.checks.zeroWeight.count, 1);
});
test('10. Free (£0) items are ignored', () => {
  const r = check([p('Bundle Discounts Applied', 'b', [v('Default Title', '', 0, { price: '0.00' })])]);
  assert.equal(r.checks.zeroWeight.count, 0);
  assert.equal(r.checks.missingSku.count, 0);
});
test('11. Clean shop returns all zeros', () => {
  const r = check([p('Lager', 'l', [v('12 Pack', 'L12', 4500), v('24 Pack', 'L24', 9000)])]);
  assert.deepEqual(Object.values(r.checks).map(c => c.count), [0, 0, 0, 0, 0]);
});
test('12. Empty / missing input does not crash', () => {
  assert.equal(check([]).products, 0);
  assert.equal(check(undefined).products, 0);
});

test('13. packSize reads common formats', () => {
  assert.equal(packSize('12 Pack'), 12);
  assert.equal(packSize('Case of 24'), 24);
  assert.equal(packSize('24 x 330ml cans'), 24);
  assert.equal(packSize('Raspberry Lemonade / 48'), 48);
  assert.equal(packSize('6-pack'), 6);
  assert.equal(packSize('1065g'), null);
  assert.equal(packSize('Default Title'), null);
});

test('14. Shop address normalisation', () => {
  assert.equal(normaliseShop('https://www.drinkcollider.com/collections/all?x=1'), 'www.drinkcollider.com');
  assert.equal(normaliseShop('drinkcollider.com'), 'drinkcollider.com');
  assert.equal(normaliseShop('  Feistydrinks.com/  '), 'feistydrinks.com');
  assert.equal(normaliseShop('shop.example.co.uk:443/x'), 'shop.example.co.uk');
});
test('15. Unsafe or junk addresses are refused', () => {
  for (const bad of ['localhost', 'http://127.0.0.1', '10.0.0.1', '169.254.169.254', 'foo', 'a@b.com',
    'evil.local', 'x.internal', 'http://[::1]/', '', 'a..b.com', '-a.com', 'a'.repeat(300) + '.com', 'exa mple.com']) {
    assert.equal(normaliseShop(bad), null, bad);
  }
});

test('16. Same flavour listed both ways (one product with options + separate listings) is reported once', () => {
  const r = check([...sneak, ...separate]);
  assert.equal(r.checks.packSameWeight.count, 5);
});

test('17. Clothing sizes are not mistaken for pack sizes', () => {
  const r = check([
    p('Leopard Jaspre Skirt', 'skirt', [6, 8, 10, 12, 14].map(n => v(String(n), 'SK' + n, 325))),
    p('Tilly Dress', 'dress', [v('Black / 12', 'D12', 400), v('Black / 14', 'D14', 400)]),
  ]);
  assert.equal(r.checks.packSameWeight.count, 0);
});
test('18. A bare number still counts when the product is sold in packs', () => {
  const r = check([p('Twilight Pack', 'tp', [v('8', 'a', 1524), v('24', 'b', 1524)])]);
  assert.equal(r.checks.packSameWeight.count, 1);
});

test('19. Colour names like "Bottle Green" do not make clothing look like packs', () => {
  const r = check([p('Bottle Green Studded Vegan Leather Trousers', 'tr', [6, 8, 10, 12].map(n => v(String(n), 'T' + n, 600)))]);
  assert.equal(r.checks.packSameWeight.count, 0);
});
test('20. A product with a Size option is never treated as packs', () => {
  const r = check([p('Party Pack Dress', 'pd', [v('Red / 12', 'a', 400), v('Red / 14', 'b', 400)], { options: [{ name: 'Colour' }, { name: 'Size' }] })]);
  assert.equal(r.checks.packSameWeight.count, 0);
});
test('21. Display names are tidy', () => {
  const r1 = check(separate).checks.packSameWeight.examples[0].name;
  assert.equal(r1, 'Raspberry Lemonade');
  const r2 = check([p('Feisty Protein Soda', 'f', [v('Mixed / 6-pack', 'a', 4500), v('Mixed / 12-pack', 'b', 4500)])]).checks.packSameWeight.examples[0].name;
  assert.equal(r2, 'Feisty Protein Soda – Mixed');
  const r3 = check(moth).checks.packSameWeight.examples[0].name;
  assert.equal(r3, 'Twilight Pack');
});

test('22. Measurements in cm are not pack sizes; "24 x 330ml" still is', () => {
  const r = check([p('Satara Oval Jute Basket', 'b', [v('18x25cm', 'a', 18500), v('22x30cm', 'b', 18500)]),
                   p('Outlet - Hemsby 160 x 230cm Garden Rug', 'r', [v('160 x 230cm', 'c', 15000), v('200 x 290cm', 'd', 15000)])]);
  assert.equal(r.checks.packSameWeight.count, 0);
  assert.equal(packSize('24 x 330ml cans'), 24);
  assert.equal(packSize('12 x 250ml'), 12);
  assert.equal(packSize('160 x 230cm'), null);
});
