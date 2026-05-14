# Architecture

`tinyvm` is a Luau interpreter implemented as **two stacked interpreters**
plus a **build-time atom-rewriting predecoder** that does heavy lifting
the micro-VM would otherwise have to do at runtime.

1. The **micro-VM** (`src/tinyvm.luau`, 2485 bytes) is a stripped tree-
   walker that interprets a pre-decoded atom tree.
2. The **macro-VM** (`src/macrovm.luau`, 4.7 KB) is a full-featured
   Luau interpreter — compiled offline and pre-decoded — that the
   micro-VM *executes*.
3. The **predecoder** (`tools/predecode.py`) rewrites the macro-VM's
   atom tree at build time: folding constants, unifying opcodes, and
   converting function records to a JSON-friendly shape. The same tool
   also predecodes user programs into the same data shape.

A user program goes through this pipeline at run time:

```
                  ┌──────────────────────────────────────────────────┐
                  │ user.luau                                        │
                  │   compiled offline   → user.bin                  │
                  │   predecoded offline → user AST                  │
                  │                                                  │
                  │   inputData = {m = macroAst, u = userAst}        │
                  │                                                  │
                  │   micro(inputData, userEnv)                      │
                  │                                                  │
   src/tinyvm.luau (the micro-VM, 2.5 KB) ── interprets ── macroAst
                  │                                                  │
                  │   macro-VM ── interprets ── userAst              │
                  │                                                  │
                  │   user program executes                          │
                  └──────────────────────────────────────────────────┘
```

The macro-VM AST is **not bytecode** at micro-VM run time; it's already
a tree of Lua tables produced at build time. The micro-VM never decodes
varints or reads byte streams. It just walks atoms. The macro-VM at
runtime likewise consumes a pre-decoded user AST, not bytes — it no
longer has its own bytecode reader.


## Why three pieces?

A self-contained Luau interpreter has to handle a lot of user-facing
behavior: error messages with `chunk:line:` prefixes, `__call`/`__namecall`
metamethod dispatch on non-function call targets, `__iter` generalized
iteration, conformance-exact diagnostic text, multi-target assignment
with pre-evaluation semantics, the full numeric/generic-for protocols,
and so on. Those features collectively cost several KB of code.

The macro-VM still has to implement all of them, because *user code*
expects them. But the micro-VM only has to run the macro-VM, which is a
well-behaved Luau program we wrote ourselves. We know exactly which
atoms the macro-VM ever emits, and the predecoder can rewrite them
into a smaller equivalent set before the micro-VM ever sees them.


## All inputs to the micro-VM are pure data

The micro-VM's signature is:

```lua
function(inputData, userEnv?)
```

| param       | what it is                                                     |
|-------------|----------------------------------------------------------------|
| `inputData` | `{m = macroAst, u = userAst}` where each is `{K, F}`           |
| `userEnv`   | env table the macro-VM uses for its own globals AND what user  |
|             | code sees as its globals. Defaults to `getfenv(2)` (the        |
|             | caller's environment) if omitted.                              |

`inputData` is pure data — no function literals, no userdata. Every
nested value is a number, string, boolean, nil, or table. This means
the whole payload is JSON-encodable; pre-decode both the macro-VM and
your user code with `tools/predecode.py --for-micro --json --user
<user.bin>` and load the JSON at runtime with any JSON parser.

`userEnv` is runtime wiring, not part of any serialized payload. The
micro-VM uses it for both the macro-VM's own global lookups (`string`,
`table`, `error`, ...) and the user program's global lookups — they
share the same table. When omitted the micro-VM picks up the caller's
environment automatically via `getfenv(2)`, so the typical idiom is
just `micro(inputData)` or `micro(inputData, getfenv())`.

`table.pack` and `table.unpack` are looked up internally by the
micro-VM.

There is no chunk-name / label argument. Errors raised by user code
through `error("msg")` propagate out as just `"msg"` — no source
prefix. If you need diagnostic context, attach it to the message
yourself before raising.


## Where the byte savings come from

| Reduction                                            | mechanism                                                                                                                          | ~bytes |
|------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|--------|
| Bytecode reader                                      | predecode emits Lua tables directly                                                                                                | ~1450  |
| Nil/True/False atoms (tags 1, 2, 3)                  | folded into Const atoms (tag 4)                                                                                                    |   ~85  |
| Vararg expression atom (tag 5) in `z`                | macro-VM only uses Vararg in tail-call position; `P` handles it                                                                    |   ~28  |
| Local + Upval atoms (tags 6, 7)                      | unified into tag 6 with `"S"`/`"U"` storage marker; single handler                                                                 |   ~22  |
| Generic-for `__iter` fallback in micro-VM            | force_gfor3 rewrites `for k,v in t do` into `for k,v in next, t, nil do`                                                           |   ~52  |
| NumericFor step support                              | dropped — verified macro-VM never emits step                                                                                       |   ~80  |
| Multi-target Assign for non-Local kinds              | rewrites single-target Assign by kind (Local/Upval → t==20, Global → t==22, Index → t==23); multi-target only sees Local           |  ~120  |
| `if`/`elseif`/`else` IIFE in t==32                   | flattened to a single (cond, block) pair list                                                                                      |   ~40  |
| Generic-for 2-slot flatten                           | inlines the slot pair directly in the atom                                                                                         |   ~12  |
| Top-level return value (caller-side void)            | dropped: `Q(1)()(...)` instead of `return Q(1)()...`                                                                               |    ~7  |
| `M` doubles as the break sentinel                    | no separate `local H = {}` allocation                                                                                              |    ~8  |
| Various local-variable hoisting and code rearranging | shared `v`, `x`, `r` locals; `M(A[n], fr)` always uses P; etc.                                                                     |  ~200  |
| **Total approx.**                                    |                                                                                                                                    | **~2100** |

(Baseline 4708 → current 2485 = 2223 actual.)

Note: the BinOp/UnOp atom rewrite (tags 14, 15) that earlier versions
shipped was removed when the API switched to a single-table `userEnv`
argument. The micro-VM now handles those atoms natively, costing ~530
bytes vs the rewrite approach. The trade is a simpler caller API: no
need to build a shadow env exposing op helpers.


## What the micro-VM contains

In source order, the top-level function `function(D, uE)`:

* `uE = uE or getfenv(2)` — default to the caller's environment if no
  env was passed. `micro(data)` works; `micro(data, getfenv())` is the
  same call written explicitly.
* `local tp, tu = table.pack, table.unpack` — `tp`/`tu` are defined
  inside the micro-VM rather than passed in.
* `local K, F = table.unpack(D.m, 1, 2)` — extract the macro-VM AST.
* `local z, P, J, Q` — forward declarations for the four mutually
  recursive functions.
* **`M(A, fr)`** — evaluates an atom list and returns `(packArray,
  count)`. The last element is always routed through `P` so multi-return
  values expand naturally. Used by Table construction, Call args,
  multi-target Assign, multi-source LocalDecl, GenericFor sources, and
  Return.
* **`z(n, fr)`** — single-value expression evaluator. Handles tags
  4, 6, 8, 9, 10, 12, 13, 14, 15, 16, 17. `local t, k, m = n[1], n[2],
  n[3]` at the start aliases the three most commonly used atom
  positions.
* **`P(n, fr)`** — call/multret evaluator. Returns a pack table
  (`{n=N, [1]=..., [2]=..., ...}`). Handles tags 10 (Call) and 5
  (Vararg); everything else falls through to `tp(z(n,fr))`.
* **`J(bl, fr)`** — block executor. Walks `bl[2]` (the statement list)
  and dispatches by tag. Local-hoisted `v, x, r` are reused across
  iterations to avoid per-iter `local` allocations.
* **`Q(ix, pa)`** — closure constructor. Reads `F[ix]`, builds the
  upvalue list `lr` from `pa` (the parent frame), and returns the
  inner closure that pushes a new frame and calls `J(Y.b, fr)`.
* **`Q(1)()(D.u, uE)`** — entry point. The macro-VM's main chunk is
  `F[1]`. `Q(1)` builds the main-chunk closure (no parent frame);
  `()` invokes it (no args — the main chunk takes none);
  `(D.u, uE)` is the user AST + env tuple passed to the user-facing
  closure the main chunk returns.

That's the whole micro-VM.


## What the predecoder does

`tools/predecode.py` reads a `.bin` (compiled with the offline
compiler) into a Python AST, applies optional rewrites, and emits
either:

* a Luau module `return {K, F}` (the default), or
* a pure JSON document `[K, F]` (with `--json`), or
* a combined payload `{m=[K,F], u=[K,F]}` / `{"m":[...],"u":[...]}`
  (with `--user <user.bin>`, optionally with `--json`).

The rewrites are gated on the `--for-micro` flag, which is only safe
when the consumer is the micro-VM (not the macro-VM at runtime). For
user programs, `--for-micro` is omitted so the macro-VM sees its
native atom set.

`tools/build.py` invokes the predecoder with `--for-micro` on
`build/macrovm.bin` to produce `build/macrovm-ast.luau`.

### Rewrites applied with `--for-micro`

1. **Fold Nil/True/False**: `[1]` (Nil), `[2]` (True), `[3]` (False)
   become `[4, idx]` where `K[idx]` holds the corresponding value.
2. **Local/Upval unify**: `[6, slot]` (Local) becomes `[6, "S", slot]`;
   `[7, slot]` (Upval) becomes `[6, "U", slot]`. The micro-VM's `z`
   handler dispatches via `fr[k][m][1]` (a single lookup regardless
   of storage kind).
3. **GenericFor 3-source + 2-slot flatten**: `[36, slots, [src], body]`
   (1-source GenericFor) becomes `[36, slots, [Global("next"), src,
   Const(nil)], body]`. All 2-slot variants are flattened to
   `[36, s1, s2, sources, body]`.
4. **NumericFor step drop**: `[35, slot, from, to, None, body]` becomes
   `[35, slot, from, to, body]` (no step slot).
5. **If flatten**: `[32, c0, t0, elseifs, else]` becomes
   `[32, [[c0, t0]] ++ elseifs, else]`. The main cond becomes the first
   `(cond, block)` pair in a uniform list.
6. **Single-target Assign split**: Single-target `[30, [target], [value]]`
   becomes one of:
   * `[20, "S", slot, value]` — local assign
   * `[20, "U", slot, value]` — upvalue assign
   * `[22, name_idx, value]` — global assign
   * `[23, tableAtom, keyAtom, value]` — indexed assign

   Multi-target `[30, [targets...], [values...]]` is only kept when
   all targets are local; the targets list is flattened to slot
   integers.

BinOp/UnOp atoms (tags 14, 15) are deliberately **not** rewritten;
the micro-VM handles them natively. Keeping the BinOp/UnOp handlers in
the micro-VM means the caller's `userEnv` doesn't need to expose any
helper functions — it's just a plain table.

### Function record shape

Whether or not `--for-micro` is set, each function record is converted
to a JSON-friendly object:

```json
{"np": <int>, "va": <int>, "L": [[<kind>, <idx>], ...], "b": <atom>}
```

With `--for-micro`, the `L` entries use string storage markers
`"S"`/`"U"` (matching the unified Local/Upval atom). Without
`--for-micro`, they use raw int kinds (`0` = parent local, `1` =
parent upvalue) — the form the macro-VM's source consumes natively.

### Output shape

Single-input form (no `--user`):

```lua
--!nocheck
return {
  {"string", "byte", "table", ..., true, false},   -- K
  {                                                -- F
    {np=0, va=1, L={}, b={50, {...}, {...}}},
    ...
  }
}
```

JSON form: `[K, F]`.

Combined form (with `--user`):

```lua
--!nocheck
return {m = {<macroK>, <macroF>}, u = {<userK>, <userF>}}
```

JSON form: `{"m": [<macroK>, <macroF>], "u": [<userK>, <userF>]}`. The
single-letter keys `m` and `u` match the micro-VM's accesses (`D.m` /
`D.u`).


## Sentinels and signalling

The micro-VM uses a single sentinel — the `M` function itself —
for the **break** signal returned from `J`. When `J` encounters a
Break statement (`t == 38`), it `return M`. The enclosing loop
handler checks `x == M` and breaks. Using the local `M` function as
the sentinel avoids needing a separate `local H = {}` allocation
and saves a few bytes.

The `r` return-pack from `J` is otherwise a table (the multret pack
from a Return statement). Loops and Ifs forward non-nil non-`M`
values upward via `return x`.


## Implementation notes

* **Boxed locals.** Each local slot is a one-element table `{value}`.
  Closures capture the box, so writes via upvalue are visible. This is
  the standard upvalue trick used by every tree-walking Lua interpreter.
* **Hoisted scratch.** `local v, x, r` are declared once at the top of
  `J`'s outer loop, not per iteration. Branches reuse them. `v` is
  used both for the assign value pack (t==30/31) and as the selected
  If branch (t==32) — there's no overlap because the variable is
  dead at the end of every handler.
* **Storage-marker reads.** `fr[p][h][1] = z(u, fr)` (t==20) selects
  the storage table by the marker `p` (the string `"S"` or `"U"`),
  the slot by `h`, and the boxed value by `[1]`. The marker is a
  string from K.
* **`Q(ix, pa)` is a small function.** It reads `F[ix]` (a pure-data
  record), builds the upvalue array `lr` by indexing into `pa` with
  the storage marker, and returns the bound closure. No function
  literals in `F`; everything is reconstructed from data.
* **No bytecode reader anywhere.** Earlier revisions had a varint/atom
  reader in both the micro-VM (taking ~1.1 KB) and the macro-VM
  (taking another ~1.5 KB). The predecoder produces both ASTs as
  data, so neither needs a reader.
* **`tp` / `tu` are internal.** The micro-VM aliases them from the
  stdlib at startup with `local tp, tu = table.pack, table.unpack`.
* **`inputData` carries everything data-side.** The single `inputData`
  table the caller passes contains both the macro-VM AST (`D.m`) and
  the user program AST (`D.u`). The micro-VM extracts macro K/F at
  startup and forwards user AST to the macro-VM main closure.
* **`userEnv` is a plain table.** The caller passes one ordinary
  table. No shadow-env construction, no op-helper wiring. The
  macro-VM's own globals (string, table, error, ...) resolve through
  the same `userEnv` via `__index = _G`.
