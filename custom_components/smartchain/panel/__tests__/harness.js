/**
 * Shared jsdom scaffolding for the panel tests.
 *
 * Deliberately tiny. The panel talks to Home Assistant through exactly one
 * door — `hass.connection.sendMessagePromise({type, ...payload})` — so a fake
 * `hass` is a recorder plus a table of canned answers, and nothing here needs
 * to know a single command name.
 *
 * NOT a test file: the runner only collects `*.test.js`, so this is imported,
 * never executed on its own.
 */

/**
 * A fake `hass` whose websocket answers come from `handlers`.
 *
 * @param {Record<string, unknown|((msg: object) => unknown)>} handlers
 *   keyed by message `type`. A function is called with the whole message and
 *   may throw to simulate a backend error; anything else is returned as-is.
 * @returns {{hass: object, sent: object[], calls: (type: string) => object[]}}
 */
export function fakeHass(handlers = {}) {
  const sent = [];
  const hass = {
    states: {},
    entities: {},
    connection: {
      async sendMessagePromise(msg) {
        sent.push(msg);
        if (!(msg.type in handlers)) {
          throw new Error(`unexpected websocket command: ${msg.type}`);
        }
        const answer = handlers[msg.type];
        return typeof answer === "function" ? answer(msg) : answer;
      },
    },
  };
  return {
    hass,
    sent,
    calls: (type) => sent.filter((msg) => msg.type === type),
  };
}

/**
 * Let every already-scheduled promise chain finish.
 *
 * The panel's loads are `async` methods started from a property setter, so
 * there is no handle to await. Yielding to the macrotask queue a few times
 * drains them without any test needing to know how many `await`s deep a load
 * happens to be.
 */
export async function flush(times = 5) {
  for (let i = 0; i < times; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

/** Mount an element by tag name, run its connectedCallback, return it. */
export function mount(tagName) {
  const el = document.createElement(tagName);
  document.body.appendChild(el);
  return el;
}
