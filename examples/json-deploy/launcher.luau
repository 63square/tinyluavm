--!nocheck
-- All-JSON-deploy launcher for tinyvm.
--
-- The driver predecodes the macro-VM and the user program together into
-- a single JSON document of shape:
--
--   {"m": [macroK, macroF], "u": [userK, userF]}
--
-- The launcher decodes that one string with a small JSON parser and hands
-- the resulting table to the micro-VM as its `inputData` argument.
--
-- Everything tinyvm consumes from us is plain Lua data: numbers, strings,
-- booleans, nil, tables. No userdata, no opaque blobs.
local micro    = require("./tinyvm")
local decode   = require("./jsondec")

-- The driver wrapped the JSON document in a 1-element table so it could
-- come through `require()` (which rejects modules whose body returns a
-- bare string). Replace this with whatever channel makes sense for you:
-- HttpService:GetAsync, an asset, a string literal pasted at build time.
local inputData = decode(require("./payload-json")[1])

-- The env the user program sees as `_G`. A writable shadow of `_G` is
-- usually fine; restrict or extend as needed. The micro-VM handles
-- BinOp/UnOp natively, so no shadow env is needed -- the macro-VM
-- resolves its own globals through this same table.
local userEnv = setmetatable({}, {__index = _G})
userEnv._G = userEnv
userEnv.hostInfo = {
    appName    = "tinyvm-json-deploy-example",
    appVersion = "1.0",
}

-- micro(inputData, userEnv, label)
--   inputData - {m = macro-VM AST, u = user-program AST}
--   userEnv   - what user code sees as its _G
--   label     - chunk name shown in diagnostic messages
print("== launcher: running user.luau (all data plane is JSON) ==")
local ok, err = pcall(micro, inputData, userEnv, "user.luau")
if not ok then
    print("== launcher: user program raised an error ==")
    print(tostring(err))
else
    print("== launcher: user program finished cleanly ==")
end
