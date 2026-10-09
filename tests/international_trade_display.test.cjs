const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function app() {
    function element() {
        return {children: [], textContent: '', appendChild(child) {this.children.push(child);},
            replaceChildren() {this.children = [];}, addEventListener() {}};
    }
    const container = element();
    const context = vm.createContext({window: {location: {origin: 'https://example.invalid'}},
        document: {addEventListener() {}, getElementById() {return container;}, createElement: element},
        Intl, URLSearchParams, console, setInterval() {}, localStorage: {removeItem() {}}});
    vm.runInContext(fs.readFileSync('frontend/static/js/app.js', 'utf8'), context);
    vm.runInContext("authToken = 'fixture-user';", context);
    return {context, container};
}
function texts(element) {
    return [element.textContent, ...element.children.flatMap(texts)].join('\n');
}

test('renders untrusted exchange identifiers as text and preserves local/UTC time and currency', async () => {
    const {context, container} = app();
    context.apiRequest = async path => {
        assert.match(path, /^\/api\/trading\/history\?/);
        assert.match(path, /timezone=/);
        return {timezone: 'Asia/Tokyo', trades: [{symbol: '<img src=x onerror=alert(1)>', broker: 'okx',
            direction: 'short', quantity: 1, entry_price: 10, exit_price: 9, price_currency: 'EUR',
            net_profit: 0.5, exit_time_local: '2026-07-01T22:00:00+09:00',
            exit_time_utc: '2026-07-01T13:00:00+00:00', close_order_ids: ['<script>bad</script>']}],
            excluded_unverified_rows: 0, has_more: false};
    };
    await context.loadTradeHistory();
    assert.match(texts(container), /<img src=x onerror=alert\(1\)>/);
    assert.match(texts(container), /EUR/);
    assert.match(texts(container), /unit unverified/);
    assert.match(texts(container), /\+09:00/);
    assert.match(texts(container), /UTC 2026/);
    // Fake DOM deliberately has no HTML parser; exchange strings are text nodes.
    assert.equal(container.children[1].children[0].children.length, 0);
});

test('failed requests clear stale trades and show unavailable instead of an empty history', async () => {
    const {context, container} = app();
    container.children.push({textContent: 'old user trade', children: []});
    context.apiRequest = async () => {throw new Error('unavailable');};
    await context.loadTradeHistory();
    assert.doesNotMatch(texts(container), /old user trade/);
    assert.match(texts(container), /history unavailable/);
});

test('a response from a previous signed-in user cannot populate the new user display', async () => {
    const {context, container} = app();
    let complete;
    context.apiRequest = () => new Promise(resolve => {complete = resolve;});
    const pending = context.loadTradeHistory();
    vm.runInContext("authToken = 'different-user';", context);
    complete({timezone: 'UTC', trades: []});
    await pending;
    assert.equal(container.children.length, 0);
});
