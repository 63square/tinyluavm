# Limitations

`tinyvm` runs user Luau bytecode through a layered interpreter. Most of
Luau works. These specific things don't, or work with caveats.

## Things that **do** work

* All literal types: nil, true, false, integer, double, string,
  raw byte strings.
* Tables: array part, hash part, mixed; `setmetatable`/`getmetatable`;
  all standard metamethods (`__index`, `__newindex`, `__add`,
  `__sub`, `__mul`, `__div`, `__mod`, `__pow`, `__unm`, `__concat`,
  `__len`, `__eq`, `__lt`, `__le`, `__tostring`, `__call`, `__iter`,
  `__namecall`).
* Functions: closures, multi-return, varargs, methods, recursion.
* Control flow: `if`/`elseif`/`else`, `if`-expressions, `while`,
  `repeat`/`until`, numeric `for` (with all Luau corner cases:
  zero step, NaN step, NaN bounds), generic `for` (with `__iter`
  and table-as-iterable fallback), `break`, `continue`.
* Operators: all 14 binary, all 3 unary, compound assignment
  (`+=`, `-=`, `*=`, `/=`, `//=`, `%=`, `^=`, `..=`).
* Error handling: `pcall`, `xpcall`, `error`, `assert`.
* Coroutines: full support via the host's `coroutine` library.
* Type annotations: parsed and discarded by the compiler. The bytecode
  contains no runtime type information.
* String interpolation: `` `foo {bar}` `` compiles to a concat chain.
* `::` cast operator: parsed and discarded.

All of the above are handled by the **macro-VM** when interpreting
user code. The micro-VM itself has a much smaller atom set — see
`docs/bytecode-format.md` — but that's invisible at the user-Luau
level because the macro-VM bridges it.

## Build-time and integration constraints

### The micro-VM cannot run standalone

`src/tinyvm.luau` requires:

* `K` — the constant pool from the predecoded macro-VM AST.
* `F` — the function-builder array, also from the predecoded AST.
* `E` — an env that exposes the macro-VM's globals (`string`, `table`,
  `error`, `setmetatable`, ...) **plus** the op helpers `B1`..`B14`
  and `U1`..`U3`.
* `tp`, `tu` — `table.pack` and `table.unpack`.
* Trailing `...` — forwarded to the macro-VM's main closure.

If you just `require("./tinyvm")` and call it with raw user bytecode,
nothing happens; the call site has to be wired up to the predecoded
artifacts. Use `build/tinyvm-bundled.luau` unless you're doing a
custom integration. See `examples/USAGE.md`.

### The op-helper env

The predecoder rewrites every BinOp/UnOp atom in the macro-VM into a
Call atom that looks up `B1`..`B14` / `U1`..`U3` in the env. If your
env doesn't expose them, the macro-VM will fail to run (you'll see
errors like `attempt to call a nil value` while it's setting up
constants). The bundle's `_E(u)` helper builds a shadow env exposing
them on top of your user env.

If you supply your own env wrapping, replicate this:

```lua
local _E = setmetatable({
  B1 = function(a, b) return a + b end,
  B2 = function(a, b) return a - b end,
  -- ...
  B14 = function(a, b) return a >= b end,
  U1 = function(a) return -a end,
  U2 = function(a) return not a end,
  U3 = function(a) return #a end,
}, {__index = your_user_env})
```


## Things that **don't** work

### `loadstring` / `load`

These are unavailable on the Roblox client and not used by the
interpreter. If user code calls `loadstring`, it fails (the macro-VM
doesn't synthesize one). If you control the environment table, you
can supply a `loadstring` shim that delegates to the host on
platforms where it's available.

### `setfenv` / `getfenv`

The macro-VM uses a single shared environment table (the one you pass
in). `setfenv` / `getfenv` as Luau used to expose them aren't
implemented per-closure. Luau itself removed these from the language
in newer versions, so this is mostly a non-issue, but some legacy
conformance tests assume them.

### Deep tail recursion

Each interpreted function call adds at least one host Lua stack frame.
Programs that depend on 10 000+ deep tail recursion (common in Lua
test suites) will overflow the host's stack much sooner than native
Lua would. Make tests less recursive or use iteration instead.

### `math.tau`

Only present in Roblox Luau, not in upstream `luau` standalone. Use
`2 * math.pi` for portability.

### Native source-line errors

When user code does `error("oops")`, the macro-VM prepends
`chunkname:line:` as Lua does. When the *host* runtime raises an
error (e.g., calling a `nil`), the prefix is added by our call-site
wrapper. Both produce reasonable diagnostics. Programs that pattern-
match exact error text against the *native* Luau VM's wording may
behave slightly differently. The conformance tests that pass include
the ones that check fragments like `: attempt to call`,
`: assertion failed!`, `'for' initial value`, `attempt to iterate
over a`.

### Sort with mutating comparators

`table.sort(t, cmp)` where `cmp` mutates `t` during sort: the
behavior depends on the host's sort implementation. The
conformance test exercising this fails because the host's sort
doesn't trip the same internal assert that the upstream Luau VM's
sort does. This isn't a language-semantic issue.

### Exact `pairs` traversal order

The hash bucket layout of tables created by interpreted code goes
through the host's table allocator. Tables created by both the
macro-VM and user code may have a slightly different bucket layout
than tables created directly in Luau source, so `for k in pairs(t)`
order can differ. Tests that depend on exact order fail.

### Performance

Tree-walking interpretation is ~50–200× slower than native. Each
arithmetic op in user code involves an `OP_BINOP` atom in the user
bytecode, which the macro-VM has to dispatch, which itself involves
multiple atoms in the macro-VM's own AST, which the micro-VM
dispatches. Two levels of tree walking. Don't use this for hot
inner loops.

Note: the predecoder's BinOp → Call rewrite turns every macro-VM
arithmetic into an env lookup + function call. This is a small
performance hit on top of tree-walking; it was a deliberate trade
to remove the BinOp/UnOp handlers from the micro-VM source.

### Return values from the outer call

The micro-VM's outermost invocation does **not** return the user
program's return values. That is, if your user program ends with
`return 42`, the bundle's `play(...)` call returns nothing
(implicit `nil`). This is a deliberate byte-saving choice in the
current build. Inner function returns still work normally — closures
in user code see each other's return values, `pcall` sees errors and
returns, etc. Only the outermost-of-outermost return is dropped.
