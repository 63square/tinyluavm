# `json-deploy` example

A complete, runnable example of feeding tinyvm an entirely JSON-encodable
input plane: **both** the macro-VM AST **and** the user program are
pre-decoded to JSON before launch, the launcher parses the JSON at
startup, and the micro-VM gets pure-data tables.

Useful when:

* You want a single, well-known serialization format (JSON) for every
  payload tinyvm consumes -- no platform-specific bytecode files, no
  Lua-syntax-only modules, just JSON strings you can store anywhere.
* You want to ship the macro-VM AST and user programs over a wire that
  only carries text (REST APIs, message queues, MessagePack-via-JSON
  gateways, etc.).
* You want the user-facing tooling (compiler + predecoder) to be the
  same regardless of whether you're shipping the macro-VM or user code.


## Layout

```
examples/json-deploy/
├── README.md              you are here
├── build_and_run.py       driver: predecode + JSON-wrap everything, run luau
├── launcher.luau          ★ the launcher: requires the modules and decodes
├── jsondec.luau           ~80-line JSON parser (object/array/string/number)
├── user.luau              a sample user program
└── staged/                ↑ assembled by build_and_run.py, gitignored
    ├── tinyvm.luau            copy of src/tinyvm.luau
    ├── jsondec.luau           copy of ../jsondec.luau
    ├── launcher.luau          copy of ../launcher.luau
    ├── macrovm-ast-json.luau  ModuleScript: returns {<json string>}
    └── user-ast-json.luau     ModuleScript: returns {<json string>}
```

The two `*-json.luau` modules just wrap a JSON string in a 1-element
table (Roblox / standalone `luau` requires `require()` returns to be
tables or functions, not bare strings). The wrappers are the **only**
non-JSON parts of the payload, and they're trivial.


## Run it

```bash
python examples/json-deploy/build_and_run.py
```

Expected output:

```
[json-deploy] predecoded macro-VM -> macrovm-ast.json (23115 bytes)
[json-deploy] predecoded user.luau -> user-ast.json (2119 bytes)
[json-deploy] wrapped JSON payloads as Luau modules
[json-deploy] staged tinyvm.luau (1955 bytes), jsondec.luau, launcher.luau
[json-deploy] invoking luau on staged/launcher.luau
============================================================
== launcher: running user.luau (all data plane is JSON) ==
hello from tinyvm-json-deploy-example v1.0
counter: 1, 2, 3
basket total: 1.85
v = Vec(4,6)
pcall returned ok=false err=user.luau:34: intentional
user.luau done
== launcher: user program finished cleanly ==
============================================================
[json-deploy] done
```


## How it works

### Build pipeline (offline, in Python)

1. `tools/compiler.py` compiles `src/macrovm.luau` to `macrovm.bin`
   (already done by `tools/build.py` -- the driver reuses it).
2. `tools/predecode.py --for-micro --json macrovm.bin macrovm-ast.json`
   reads the macro-VM bytecode, applies all the micro-VM-specific atom
   rewrites (BinOp -> Call(B<n>), Local/Upval unify, If flatten, etc.),
   and emits a JSON file.
3. `tools/compiler.py` compiles `user.luau` to `user.bin`.
4. `tools/predecode.py --json user.bin user-ast.json` reads the user
   bytecode and emits JSON. **No** `--for-micro` here -- the macro-VM
   will consume this AST at runtime, so we keep the macro-VM-friendly
   atom set (no Local/Upval unify, no BinOp rewrite, etc.).

The result is two JSON files, both purely data: arrays, objects,
strings, numbers, `true`, `false`, `null`. No functions, no userdata,
no Lua-specific constructs.

### Runtime pipeline (inside luau)

1. The launcher `require()`s the two JSON modules and gets two strings.
2. It decodes them with `jsondec.luau` (a small JSON parser).
3. It builds the shadow env exposing the op-helper functions
   (`B1`..`B14`, `U1`..`U3`) the predecoder rewrote macro-VM BinOp/UnOp
   atoms into.
4. It calls the micro-VM:

   ```lua
   micro(K, F, shadowEnv, table.pack, table.unpack,
         userAst, userEnv, "user.luau")
   ```

   Note that `userAst` is a **table** here, not a byte string. The
   macro-VM (in `src/macrovm.luau`) detects this with
   `type(b) == "table"` and skips its bytecode reader entirely,
   pulling `K, F` from `userAst[1], userAst[2]`.

If you JSON-stringify the launcher's inputs, you get something like:

```json
[
  [/* K: const pool */],
  [/* F: function records [{np, va, L, b}, ...] */]
]
```

Both files have that shape.


## The user AST is also JSON

The `user.luau` source compiles to ~250 bytes of bytecode; the
predecoder turns that into ~2 KB of JSON. The JSON is bigger than the
raw bytecode (varints are denser than decimal digits), but you can pipe
it through any JSON-handling tool: pretty-print it, grep it, diff two
versions of the same script, transform it with `jq`, etc.

Sample slice of the user AST:

```json
[
  [/* K: */ 2, 1, 0, 12, "print", "fib(", "tostring", ") = ", null, "next"],
  [
    {
      "np": 0, "va": 1, "L": [],
      "b": [50, [[31, [1], [[4, 9]]], ...], [2, 2, 7]]
    },
    {
      "np": 1, "va": 0, "L": [[0, 1]],
      "b": [50, [[32, ...], [37, ...]], [2, 3]]
    }
  ]
]
```

* `K` is the constant pool: numbers, strings, `null`, `true`, `false`.
* `F` is a list of function records: `np` = number of params,
  `va` = vararg flag (0/1), `L` = upvalue source list `[[kind, idx], ...]`
  where `kind` is `0` (parent local) or `1` (parent upvalue), and
  `b` is the body atom tree (a tagged array `[tag, ...payload]`).

See `docs/bytecode-format.md` for the full atom-tag reference.


## Where this fits in the deployment matrix

|                                  | bundle (Option 1)           | split deploy (Option 2)              | json deploy (this)                    |
|----------------------------------|-----------------------------|--------------------------------------|---------------------------------------|
| User-source code that ships      | one file (~25 KB)           | one file (`tinyvm.luau`, 1955 bytes) | one file (`tinyvm.luau`, 1955 bytes)  |
| Macro-VM data format             | embedded Lua                | Lua module returning `{K, F}`        | JSON string                           |
| User program data format         | binary bytecode             | binary bytecode                      | JSON string                           |
| Launcher boilerplate             | none                        | ~75 lines                            | ~80 lines + a JSON parser             |
| Source code can be diffed/jq'd?  | no                          | partially                            | yes -- everything                     |

If you want JSON-style transport for all the data tinyvm consumes, this
example is the recipe. Otherwise the bundle (Option 1) or the split
deploy (Option 2) is more compact.


## Customizing

* **Streaming**: replace the `require()` calls with HTTP/GetAsync calls
  to load the JSON strings from a remote service.
* **Restricting the user env**: replace the `__index = _G` chain with
  a curated table to sandbox.
* **Replacing the JSON parser**: any JSON parser that produces nested
  Lua tables, with string keys for objects and 1-based int keys for
  arrays, mapping `null` to `nil`, works. The `jsondec.luau` bundled
  here is just one possible choice.
