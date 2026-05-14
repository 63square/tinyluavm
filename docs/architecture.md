# Architecture

`tinyvm` is a Luau interpreter implemented as **two stacked interpreters**
plus a **build-time atom-rewriting predecoder** that does heavy lifting
the micro-VM would otherwise have to do at runtime.

1. The **micro-VM** (`src/tinyvm.luau`, 1955 bytes) is a stripped tree-
   walker that interprets a pre-decoded atom tree.
2. The **macro-VM** (`src/macrovm.luau`, 6.9 KB) is a full-featured
   Luau interpreter — compiled offline and pre-decoded — that the
   micro-VM *executes*.
3. The **predecoder** (`tools/predecode.py`) rewrites the macro-VM's
   atom tree at build time: folding constants, replacing arithmetic
   opcodes with calls to env-supplied helpers, unifying opcodes, and
   converting function records to a JSON-friendly shape. This is what
   lets the micro-VM be so small while keeping every input to it pure
   data.

A user program goes through this pipeline at run time:

```
                  ┌──────────────────────────────────────────────────┐
                  │ user.luau                                        │
                  │   compiled offline → user.bin (or user-ast.json) │
                  │                                                  │
                  │   bundle.play(user, env, label, ...) →           │
                  │                                                  │
   src/tinyvm.luau (the micro-VM, 1.9 KB) ── interprets ── macro-VM AST
                  │                                                  │
                  │   macro-VM ── interprets ── user code            │
                  │                                                  │
                  │   user program executes                          │
                  └──────────────────────────────────────────────────┘
```

The macro-VM AST is **not bytecode** at micro-VM run time; it's already
a tree of Lua tables produced at build time. The micro-VM never decodes
varints or reads byte streams. It just walks atoms.

Likewise, the macro-VM can be fed either bytecode bytes **or** a
pre-decoded user AST as a table — `type(b)=="table"` skips the macro-VM's
own bytecode reader and treats `b[1]`, `b[2]` as `K`, `F` directly.


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
function(K, F, E, tp, tu, ...)
```

where:

| param | what it is                                                   |
|-------|--------------------------------------------------------------|
| `K`   | array of constants (numbers, strings, booleans, nil)         |
| `F`   | array of function records `{np, va, L, b}`                   |
| `E`   | env table (caller-provided; macro-VM globals look here)      |
| `tp`  | `table.pack`                                                 |
| `tu`  | `table.unpack`                                               |
| `...` | passed through to the macro-VM main closure                  |

`K` and `F` are pure data — no function literals, no userdata. Every
nested value is a number, string, boolean, nil, or table. This means
the entire `[K, F]` payload is JSON-encodable: pre-decode the
macro-VM with `tools/predecode.py --json` and load the JSON at
runtime with any JSON parser.

The `E`, `tp`, `tu` parameters are host-side wiring (the env exposes
op-helper functions `B1`..`B14` / `U1`..`U3`; `tp`/`tu` are stdlib
pack/unpack), not part of any serialized payload.


## Where the byte savings come from

| Reduction                                            | mechanism                                                                                                                          | ~bytes |
|------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|--------|
| Bytecode reader                                      | predecode emits Lua tables directly                                                                                                | ~1450  |
| Nil/True/False atoms (tags 1, 2, 3)                  | folded into Const atoms (tag 4)                                                                                                    |   ~85  |
| BinOp/UnOp atoms (tags 14, 15)                       | rewritten into Call atoms targeting `B1`..`B14` and `U1`..`U3` in the env                                                          |  ~620  |
| Vararg expression atom (tag 5) in `z`                | macro-VM only uses Vararg in tail-call position; `P` handles it                                                                    |   ~28  |
| Local + Upval atoms (tags 6, 7)                      | unified into tag 6 with `"S"`/`"U"` storage marker; single handler                                                                 |   ~22  |
| Generic-for `__iter` fallback in micro-VM            | force_gfor3 rewrites `for k,v in t do` into `for k,v in next, t, nil do`                                                           |   ~52  |
| NumericFor step support                              | dropped — verified macro-VM never emits step                                                                                       |   ~80  |
| Multi-target Assign for non-Local kinds              | rewrites single-target Assign by kind (Local/Upval → t==20, Global → t==22, Index → t==23); multi-target only sees Local           |  ~120  |
| `if`/`elseif`/`else` IIFE in t==32                   | flattened to a single (cond, block) pair list                                                                                      |   ~40  |
| Generic-for 2-slot flatten                           | inlines the slot pair directly in the atom                                                                                         |   ~12  |
| Top-level return value (caller-side void)            | dropped: `Q(1)()(...)` instead of `return Q(1)()...`                                                                               |    ~7  |
| `tp`/`tu` constants                                  | passed in as micro-VM parameters; `M` function doubles as the break sentinel                                                       |   ~50  |
| Various local-variable hoisting and code rearranging | shared `v`, `x`, `r` locals; `M(A[n], fr)` always uses P; etc.                                                                     |  ~200  |
| **Total approx.**                                    |                                                                                                                                    | **~2750** |

(Baseline 4708 → current 1955 = 2753 actual.)


## What the micro-VM contains

In source order, the top-level function `function(K, F, E, tp, tu, ...)`:

* `local z, P, J, Q` — forward declarations for the four mutually
  recursive functions.
* **`M(A, fr)`** — evaluates an atom list and returns `(packArray,
  count)`. The last element is always routed through `P` so multi-return
  values expand naturally. Used by Table construction, Call args,
  multi-target Assign, multi-source LocalDecl, GenericFor sources, and
  Return.
* **`z(n, fr)`** — single-value expression evaluator. Handles tags
  4, 6, 8, 9, 10, 12, 13, 16, 17. `local t, k, m = n[1], n[2], n[3]`
  at the start aliases the three most commonly used atom positions.
* **`P(n, fr)`** — call/multret evaluator. Returns a pack table
  (`{n=N, [1]=..., [2]=..., ...}`). Handles tags 10 (Call) and 5
  (Vararg); everything else falls through to `tp(z(n,fr))`.
* **`J(bl, fr)`** — block executor. Walks `bl[2]` (the statement list)
  and dispatches by tag. Local-hoisted `v, x, r` are reused across
  iterations to avoid per-iter `local` allocations.
* **`Q(ix, pa)`** — closure constructor. Reads `F[ix]`, builds the
  upvalue list `lr` from `pa` (the parent frame), and returns the
  inner closure that pushes a new frame and calls `J(Y.b, fr)`.
* **`Q(1)()(...)`** — entry point. The macro-VM's main chunk is `F[1]`.
  `Q(1)` builds the main-chunk closure (no parent frame); `()` invokes
  it (no args — the main chunk takes none); `(...)` calls the
  user-facing closure it returns with the caller's args.

That's the whole micro-VM.


## What the predecoder does

`tools/predecode.py` reads a `.bin` (compiled with the offline
compiler) into a Python AST, applies optional rewrites, and emits
either:

* a Luau module `return {K, F}` (the default), or
* a pure JSON document `[K, F]` (with `--json`).

The rewrites are gated on the `--for-micro` flag, which is only safe
when the consumer is the micro-VM (not the macro-VM at runtime). For
user programs, `--for-micro` is omitted so the macro-VM sees its
native atom set.

### Rewrites applied with `--for-micro`

1. **Fold Nil/True/False**: `[1]` (Nil), `[2]` (True), `[3]` (False)
   become `[4, idx]` where `K[idx]` holds the corresponding value.
2. **BinOp/UnOp to Call**: `[14, opCode, a, b]` (BinOp) becomes
   `[10, [8, B_idx], [a, b], 1]` (a Call atom calling the global
   `B<opCode>` with two args, multret-1). Similarly for `[15]` (UnOp).
   Adds 17 string constants to K: `"B1"`..`"B14"`, `"U1"`..`"U3"`.
3. **Local/Upval unify**: `[6, slot]` (Local) becomes `[6, "S", slot]`;
   `[7, slot]` (Upval) becomes `[6, "U", slot]`. The micro-VM's `z`
   handler dispatches via `fr[k][m][1]` (a single lookup regardless
   of storage kind).
4. **GenericFor 3-source + 2-slot flatten**: `[36, slots, [src], body]`
   (1-source GenericFor) becomes `[36, slots, [Global("next"), src,
   Const(nil)], body]`. All 2-slot variants are flattened to
   `[36, s1, s2, sources, body]`.
5. **NumericFor step drop**: `[35, slot, from, to, None, body]` becomes
   `[35, slot, from, to, body]` (no step slot).
6. **If flatten**: `[32, c0, t0, elseifs, else]` becomes
   `[32, [[c0, t0]] ++ elseifs, else]`. The main cond becomes the first
   `(cond, block)` pair in a uniform list.
7. **Single-target Assign split**: Single-target `[30, [target], [value]]`
   becomes one of:
   * `[20, "S", slot, value]` — local assign
   * `[20, "U", slot, value]` — upvalue assign
   * `[22, name_idx, value]` — global assign
   * `[23, tableAtom, keyAtom, value]` — indexed assign

   Multi-target `[30, [targets...], [values...]]` is only kept when
   all targets are local; the targets list is flattened to slot
   integers.

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

JSON form:

```json
[
  ["string", "byte", "table", ..., true, false],
  [{"np": 0, "va": 1, "L": [], "b": [50, [...], [...]]}, ...]
]
```


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
* **No bytecode reader.** Earlier revisions had a varint/atom reader
  taking ~1.1 KB. The predecoder emits Lua tables directly, so the
  micro-VM never does I/O on a byte stream.
* **`tp` / `tu` from the caller, not stdlib.** They're parameters of
  the micro-VM (`function(K, F, E, tp, tu, ...)`). The bundle defines
  `local tp, tu = table.pack, table.unpack` once at the top.
* **User code as pre-decoded AST.** The macro-VM accepts either a
  byte string or a pre-decoded `{K, F}` table as its first argument.
  When given a table, it skips its bytecode reader and uses
  `b[1]`, `b[2]` directly. This means user programs can also be
  shipped in JSON (or any data-serialization) form, not just as
  binary bytecode.
