// The entry point of strand.mjs, never deployed: the Worker of index.js, and one way to end a request while the store
// loads. A request with the header x-fshy-strand starts the load of the store and answers 202 before the load settles,
// so its context ends during the load. The Workers runtime then drops the continuations of that request, as it does
// for a request whose client goes away (worker/db.js, at the top).
//
//   x-fshy-strand: keep    the load gets the ctx of the request, so ctx.waitUntil() keeps it
//   x-fshy-strand: drop    the load gets no ctx, as when the runtime cancels the request and its waitUntil() work too
//   x-fshy-strand: reset   the open store is closed, so the next request loads it again

import wasmModule from 'sql.js/dist/sql-wasm-browser.wasm';
import worker from '../index.js';
import { discard, getStore } from '../db.js';

export default {
  async fetch(request, env, ctx) {
    const mode = request.headers.get('x-fshy-strand');
    if (!mode) return worker.fetch(request, env, ctx);
    if (mode === 'reset') {
      const { store } = await getStore(env, wasmModule, ctx);
      discard(store);
      return new Response(null, { status: 204 });
    }
    // not awaited on purpose: the request answers while the load runs
    getStore(env, wasmModule, mode === 'keep' ? ctx : undefined).catch(() => {});
    return new Response(null, { status: 202 });
  },
};
