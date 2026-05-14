# Bytecode format

There are two stages of "format" in `tinyvm`:

1. The **wire format** that `tools/compiler.py` emits — a compact
   binary file with varints and packed doubles. This is what user
   programs are compiled to, and it's what the macro-VM reads at run
   time when interpreting user code.
2. The **runtime atom shape** the micro-VM actually walks — a tree of
   Lua tables produced by `tools/predecode.py` from the wire format.
   The predecoder applies several rewrites on top of the wire format.
   The micro-VM never sees the wire format directly anymore; only the
   macro-VM does.

The rest of this document covers both.


## Wire format (what the compiler emits)

All integers are LEB128 unsigned varints unless stated.
Signed integers are zig-zag encoded varints.
Doubles are 8 bytes little-endian (`string.pack("<d", x)`).
Strings are `varint(length)` followed by raw bytes.

### Top-level layout

```
  varint nk                       constant count
  nk × (u8 kind, payload)         the constant pool
  varint nf                       function count
  nf  × function record           the function pool
```

The "main chunk" is `F[1]`. Execution begins there.

### Constant kinds

| kind | meaning           | payload                       |
|------|-------------------|-------------------------------|
| 0    | nil               | (none)                        |
| 1    | false             | (none)                        |
| 2    | true              | (none)                        |
| 3    | int               | zig-zag varint                |
| 4    | double            | 8 raw bytes, little-endian    |
| 5    | string            | varint length + raw bytes     |

### Function record

```
  u8     numparams
  u8     isvararg              (0 or 1)
  varint numupvalues
  numupvalues × (
      u8     fromKind          (0 = parent local, 1 = parent upvalue)
      varint index             (1-based)
  )
  atom   body                  always a Block atom (tag 50)
```

### Atom tags emitted by the compiler

Each atom is `u8 tag` followed by tag-specific payload.

#### Expression tags

| tag | name        | payload                                  |
|-----|-------------|------------------------------------------|
| 1   | Nil         | (none)                                   |
| 2   | True        | (none)                                   |
| 3   | False       | (none)                                   |
| 4   | Const       | varint ki                                |
| 5   | Vararg      | (none) — must be inside a vararg fn      |
| 6   | Local       | varint slot                              |
| 7   | Upval       | varint idx                               |
| 8   | Global      | varint ki — `env[K[ki]]`                 |
| 9   | Index       | atom obj, atom key                       |
| 10  | Call        | atom fn, atom-list args, u8 multret      |
| 11  | MethodCall  | atom obj, varint nameKi, atom-list args, u8 multret  |
| 12  | Closure     | varint funcIdx                           |
| 13  | Table       | varint narr, varint nhash, narr × atom, nhash × (atom key, atom val) |
| 14  | BinOp       | u8 op, atom a, atom b                    |
| 15  | UnOp        | u8 op, atom a                            |
| 16  | And         | atom a, atom b                           |
| 17  | Or          | atom a, atom b                           |
| 18  | IfExpr      | atom cond, atom thenVal, atom elseVal    |
| 19  | Paren       | atom inner — forces single value         |

#### Statement tags

| tag | name        | payload                                  |
|-----|-------------|------------------------------------------|
| 30  | Assign      | atom-list targets, atom-list values      |
| 31  | LocalDecl   | varint-list slots, atom-list values      |
| 32  | If          | atom cond, atom thenBlock, atom-pair-list elseifs, u8 hasElse, [atom elseBlock] |
| 33  | While       | atom cond, atom body                     |
| 34  | Repeat      | atom body, atom cond                     |
| 35  | NumFor      | varint slot, atom start, atom stop, u8 hasStep, [atom step], atom body |
| 36  | GenFor      | varint-list slots, atom-list sources, atom body |
| 37  | Return      | atom-list values                         |
| 38  | Break       | (none)                                   |
| 39  | Continue    | (none)                                   |
| 40  | Do          | atom body                                |
| 41  | ExprStmt    | atom                                     |

#### Block tag

| tag | name  | payload                                       |
|-----|-------|-----------------------------------------------|
| 50  | Block | varint nstmts, nstmts × (varint line, atom stmt) |

### Operator codes

#### Binary (u8)

| code | op  | code | op  |
|------|-----|------|-----|
| 1    | +   | 8    | ..  |
| 2    | -   | 9    | ==  |
| 3    | *   | 10   | ~=  |
| 4    | /   | 11   | <   |
| 5    | //  | 12   | <=  |
| 6    | %   | 13   | >   |
| 7    | ^   | 14   | >=  |

#### Unary (u8)

| code | op    |
|------|-------|
| 1    | -     |
| 2    | not   |
| 3    | #     |

Logical `and` / `or` are tags 16 / 17, not BinOp codes, so the runtime
can short-circuit.

### Multi-return semantics

Atoms with tags 5, 10, and 11 can produce more than one value. The
runtime expands them only when they're at the tail position of a
value list (last arg in a call, last entry in a table constructor's
array section, last value in a return / multi-assign / local-decl).

For Call / MethodCall, the trailing `multret` u8 controls whether the
result is kept multi (1) or truncated to one value (0). The compiler
sets `multret = 0` for parenthesized calls and `multret = 1` everywhere
else; the runtime then truncates further in single-value contexts.


## Predecoder rewrites

The macro-VM source `src/macrovm.luau` is compiled to wire format
(`build/macrovm.bin`), then `tools/predecode.py` converts it into a
Luau module (or a JSON document, with `--json`) of shape `[K, F]`.

The predecoder has a single switch, `--for-micro`, that controls
whether the **micro-VM-only atom rewrites** are applied. When omitted,
only the wire-format → AST conversion happens; the output is consumable
by the macro-VM at runtime (this is how user programs are pre-decoded).
When set, the micro-VM-specific rewrites listed below are applied; the
output is consumable only by the micro-VM.

`tools/build.py` invokes the predecoder with `--for-micro` on
`build/macrovm.bin` to produce `build/macrovm-ast.luau`.

### Function record shape

Each function record is converted to a JSON-friendly object:

```json
{"np": <int>, "va": <int>, "L": [[<kind>, <idx>], ...], "b": <atom>}
```

* `np` — number of declared parameters.
* `va` — vararg flag (0 or 1).
* `L` — upvalue source list. With `--for-micro`, the `kind` element is
  `"S"` (parent local stack) or `"U"` (parent upvalues), matching the
  unified Local/Upval atom. Without `--for-micro`, it's the raw integer
  kind that `src/macrovm.luau` consumes: `0` (parent local) or `1`
  (parent upvalue).
* `b` — body atom (always a Block atom, tag 50).

### Rewrites that are always on

Even without `--for-micro`, the predecoder converts the wire format
into the JSON-friendly object/array form described above. It does
**not** modify atom contents.

### Rewrites added by `--for-micro`

These are the byte-saving rewrites that target the micro-VM's reduced
atom set. They are *not* safe for the macro-VM (the macro-VM's source
doesn't have handlers for the new atom shapes), so they're only
applied when predecoding the macro-VM itself for direct consumption
by the micro-VM.

#### Nil/True/False → Const

The atoms `[1]` (Nil), `[2]` (True), `[3]` (False) become `[4, idx]`
where `K[idx]` holds `nil` / `true` / `false`. The predecoder appends
those three values to K.

#### BinOp/UnOp → Call

Each `[14, opCode, a, b]` becomes `[10, [8, B_idx], [a, b], 1]`,
a Call atom whose function is the global `B<opCode>` (one of
`B1`..`B14`) applied to `(a, b)` with multret 1. Similarly
`[15, opCode, a]` becomes a Call of `U<opCode>` (`U1`..`U3`) on `(a)`.

The predecoder appends 17 string constants to K: `"B1"`..`"B14"`,
`"U1"`..`"U3"`. The caller-provided env must expose those names as
functions; both example launchers
([split-deploy](../examples/split-deploy/launcher.luau) and
[json-deploy](../examples/json-deploy/launcher.luau)) build a shadow
env that does this and falls through to the user env via `__index`.

#### Local/Upval unify

Local atoms `[6, slot]` become `[6, "S", slot]`; Upval atoms
`[7, slot]` become `[6, "U", slot]`. The shared handler is:

```lua
elseif t == 6 then return fr[k][m][1]
```

where `k` is the storage marker (`"S"` or `"U"`) and `m` is the slot
index. `fr.S` and `fr.U` are the per-frame local-stack and upvalue
tables respectively, so `fr["S"]` and `fr["U"]` resolve correctly.

#### GenericFor 3-source + 2-slot flatten

Atom `[36, slots, [singleSrc], body]` becomes
`[36, slots, [Global("next"), singleSrc, Const(nil)], body]`. This
removes the need for the micro-VM to special-case `for k,v in tbl do`
(where `tbl` is iterated via the `__iter` metamethod or fallback
`next` semantics).

Additionally, if `slots` has exactly 2 entries (the common case for
`for k, v in ...`), they're hoisted into the atom directly:
`[36, s1, s2, sources, body]` (5 elements instead of 4 with a
sublist).

This rewrite is **not** safe for user code: user programs commonly do
`for k, v in pairs(t) do` where `pairs(t)` is a single Call atom that
already returns 3 values via multret. Wrapping it as
`[Global("next"), call, nil]` would treat only the first return of
the call (the actual iterator function) as the iterator state and
break iteration. The macro-VM's native generic-for handler expands
multret correctly.

#### NumericFor step drop

`[35, slot, from, to, None, body]` (NumericFor without step) becomes
`[35, slot, from, to, body]` (no step slot). All NumericFors in the
macro-VM source use step = 1.

The micro-VM's handler is simply `for j = z(h, fr), z(u, fr) do ...`
— no step variable, no NaN guard, no direction selection.

#### If flatten

`[32, c0, t0, elseifs, else]` becomes
`[32, [[c0, t0]] ++ elseifs, else]`. The main cond/then are folded
into the first entry of a uniform `(cond, block)` pair list:

```lua
elseif t == 32 then
  local bk = h                            -- start with else block
  for _, e in p do                        -- p = pair list
    if z(e[1], fr) then bk = e[2]; break end
  end
  r = bk and J(bk, fr)
  if r then return r end
end
```

Layout: `it[2]` = pair list, `it[3]` = else block.

#### Assign by target kind

Single-target `[30, [target], [value]]` becomes:

| target shape       | output                              |
|--------------------|-------------------------------------|
| `[6, "S", slot]`   | `[20, "S", slot, value]`            |
| `[6, "U", slot]`   | `[20, "U", slot, value]`            |
| `[8, name_idx]`    | `[22, name_idx, value]`             |
| `[9, table, key]`  | `[23, table, key, value]`           |

Multi-target Assign (only used in 1 place in the macro-VM, and only
with all-local targets) becomes `[30, [slot1, slot2, ...], values]`
— the targets list is flattened from atoms to slot ints.


## Combined input payload (`--user`)

`tools/predecode.py` can predecode both the macro-VM and a user
program in a single invocation and emit them as one payload. This is
the shape the micro-VM consumes via its `inputData` parameter.

```bash
python tools/predecode.py build/macrovm.bin payload.luau --for-micro \
    --user myscript.bin
```

Output (Luau form):

```lua
--!nocheck
return {m = {<macroK>, <macroF>}, u = {<userK>, <userF>}}
```

Output (JSON form, with additional `--json`):

```json
{
  "m": [<macroK>, <macroF>],
  "u": [<userK>, <userF>]
}
```

The single-letter keys `m` (macro) and `u` (user) match the micro-VM's
accesses (`D.m` and `D.u`).

The macro-VM half always carries the micro-VM-specific rewrites
(implied by `--for-micro` applying to the first input). The user half
never carries them — the macro-VM consumes it at runtime, so its atoms
stay in the form the macro-VM source recognizes (raw int upvalue
kinds, unflattened If/NumericFor/GenericFor, native BinOp/UnOp atoms).

When `--user` is omitted, output is just the macro-VM's `[K, F]` (or
`{K, F}` in Luau form). When `--for-micro` is omitted entirely (with
no `--user`), the predecoder emits a user-program-shaped AST for direct
macro-VM consumption.


## Atoms the micro-VM handles

After all rewrites, the micro-VM dispatches on this reduced atom set:

### In `z` (expression evaluator)

| tag | meaning                                  | handler                                |
|-----|------------------------------------------|----------------------------------------|
| 4   | Const                                    | `return K[k]`                          |
| 6   | Local *or* Upval (with storage marker)   | `return fr[k][m][1]`                   |
| 8   | Global                                   | `return E[K[k]]`                       |
| 9   | Index                                    | `return z(k, fr)[z(m, fr)]`            |
| 10  | Call (single-value context)              | `return P(n, fr)[1]`                   |
| 12  | Closure                                  | `return Q(k, fr)`                      |
| 13  | Table constructor                        | array via `M`, then hash entries       |
| 16  | And                                      | `return z(k,fr) and z(m,fr)`           |
| 17  | Or                                       | `return z(k,fr) or z(m,fr)`            |

### In `P` (multret-aware call evaluator)

| tag | meaning            | handler                                  |
|-----|--------------------|------------------------------------------|
| 10  | Call               | `tp(fn(tu(args, 1, count)))`             |
| 5   | Vararg             | `return fr.V`                            |
| else                                    | `return tp(z(n, fr))`               |

### In `J` (statement executor)

| tag | meaning                          | notes                                                |
|-----|----------------------------------|------------------------------------------------------|
| 20  | Local/Upval Assign               | `fr[p][h][1] = z(u, fr)` — `p` is `"S"` or `"U"`     |
| 22  | Global Assign                    | `E[K[p]] = z(h, fr)`                                 |
| 23  | Index Assign                     | `z(p, fr)[z(h, fr)] = z(u, fr)`                      |
| 30  | Multi-target Local Assign        | iterate slot ints, `fr.S[s][1] = v[j]`               |
| 31  | LocalDecl                        | iterate slot ints, `fr.S[s] = {v[j]}` (fresh box)    |
| 32  | If (flattened pair list)         | first matching cond wins; else block as fallback     |
| 33  | While                            | standard; break propagates the `M` sentinel          |
| 35  | NumericFor (no step)             | `for j = z(h, fr), z(u, fr) do ... end`              |
| 36  | GenericFor (2-slot, 3-source)    | `for k, vv in v[1], v[2], v[3] do ... end`           |
| 37  | Return                           | pack via `M`, set `.n`, return                       |
| 38  | Break                            | `return M` (the M function used as sentinel)         |
| 41  | ExprStmt                         | `z(p, fr)` (discard result)                          |
| 50  | Block                            | not in J's switch; it's the outer iteration target   |

The following compiler-emitted tags are **never seen by the micro-VM**
because the macro-VM never emits them in its own source: 11
(MethodCall), 18 (IfExpr), 19 (Paren), 34 (Repeat), 39 (Continue), 40
(Do). User code using these features works fine because the macro-VM
implements them when interpreting user bytecode.


## Scoping

* Slots are per-function, 1-based, never reused. Every `local`
  declaration in source allocates a fresh slot. This makes closures
  that capture a loop-iteration variable see *that iteration's* boxed
  cell, matching Luau's `local`-per-iteration semantics.
* Upvalues are resolved at compile time. Each function record's `L`
  field describes how the closure should capture its upvalues from the
  enclosing frame: a list of `[storage_marker, slot_index]` pairs.
  At closure-build time, `Q(ix, pa)` iterates `L` and reads each
  source from the parent frame.
* Free identifiers compile to `Global` atoms (tag 8); they read/write
  the caller-provided environment table by name. Writes go through
  the micro-VM's `t == 22` handler.


## JSON form

`tools/predecode.py --json` emits a pure JSON document instead of a
Luau module. The top-level shape depends on whether `--user` is given:

Without `--user` (just the macro-VM, or just a user program):

```json
[
  [<K entries>],
  [<F entries>]
]
```

With `--user` (the combined payload the micro-VM consumes as
`inputData`):

```json
{
  "m": [<macroK>, <macroF>],
  "u": [<userK>,  <userF>]
}
```

Mappings:

| Python (predecoder) | JSON              | Luau (after decode) |
|---------------------|-------------------|---------------------|
| `None`              | `null`            | `nil`               |
| `True` / `False`    | `true` / `false`  | `true` / `false`    |
| `int`               | integer number    | `number`            |
| `float`             | number            | `number`            |
| `str`               | string            | `string`            |
| `list`              | array             | array-indexed table |
| `dict`              | object            | string-keyed table  |

Function records use object form with `np`, `va`, `L`, `b` keys.
Atom trees use array form with the tag as the first element.

Any standard JSON decoder that maps `null → nil` and represents
arrays as 1-indexed Lua tables (which is the conventional behavior
of every Roblox-compatible JSON library, plus the small parser
shipped in `examples/json-deploy/jsondec.luau`) will produce a
structure the micro-VM consumes directly.

Note: nested `null` values inside JSON arrays correspond to `nil`
holes in Lua tables. The micro-VM always indexes these tables by
explicit integer position (it never uses `#` or `ipairs` over a
holed array), so the holes are inert.
