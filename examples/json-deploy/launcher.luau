--!nocheck
-- All-JSON-deploy launcher for tinyvm.
--
-- The driver predecodes the macro-VM and the user program together into
-- a single JSON document of shape:
--
--   {"m": [macroK, macroF], "u": [userK, userF]}
--
-- The launcher decodes that one string with a small JSON parser and
-- hands the resulting table to the micro-VM. The caller's env is
-- passed via `getfenv()` -- the macro-VM resolves any global the user
-- program references through the same table.
local micro    = require("./tinyvm")
local decode   = require("./jsondec")

-- The driver wrapped the JSON document in a 1-element table so it could
-- come through `require()` (which rejects modules whose body returns a
-- bare string). Replace this with whatever channel makes sense for you:
-- HttpService:GetAsync, an asset, a string literal pasted at build time.
local inputData = decode(require("./payload-json")[1])

hostInfo = {
    appName    = "tinyvm-json-deploy-example",
    appVersion = "1.0",
}

local ok, err = pcall(micro, inputData, getfenv())
if not ok then
    print("user program raised: " .. tostring(err))
end
